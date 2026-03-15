#!/usr/bin/env python3
"""
DDNS Daemon - 跨平台 Cloudflare DDNS 守护程序
支持 IPv4/IPv6 双栈，自动重试，日志记录
"""

import json
import logging
import os
import platform
import re
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

# 配置文件路径
SCRIPT_DIR = Path(__file__).parent.resolve()
CONFIG_FILE = SCRIPT_DIR / "config.json"
LOG_FILE = SCRIPT_DIR / "ddns.log"
CACHE_FILE = SCRIPT_DIR / ".ip_cache.json"

# Cloudflare API
CF_API_BASE = "https://api.cloudflare.com/client/v4"

# 日志配置
def setup_logging():
    """配置日志系统"""
    logging.basicConfig(
        level=logging.INFO,
        format='[%(asctime)s] [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.FileHandler(LOG_FILE, encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger(__name__)

logger = setup_logging()


class Config:
    """配置管理"""

    def __init__(self):
        self.cloudflare_api_token = ""
        self.cloudflare_zone_id = ""
        self.domains = []
        self.ip_version = "both"
        self.check_interval = 120
        self.retry_interval = 30
        self.max_retries = 3
        self.interface = "auto"
        self.load()

    def load(self):
        """加载配置文件"""
        if not CONFIG_FILE.exists():
            logger.error(f"配置文件不存在: {CONFIG_FILE}")
            self.create_template()
            raise FileNotFoundError(f"已创建配置模板: {CONFIG_FILE}，请填写后重试")

        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)

            cf = data.get('cloudflare', {})
            self.cloudflare_api_token = cf.get('api_token', '')
            self.cloudflare_zone_id = cf.get('zone_id', '')
            self.domains = data.get('domains', [])
            self.ip_version = data.get('ip_version', 'both')
            self.check_interval = data.get('check_interval', 120)
            self.retry_interval = data.get('retry_interval', 30)
            self.max_retries = data.get('max_retries', 3)
            self.interface = data.get('interface', 'auto')

            if not self.cloudflare_api_token:
                raise ValueError("cloudflare.api_token 不能为空")
            if not self.cloudflare_zone_id:
                raise ValueError("cloudflare.zone_id 不能为空")
            if not self.domains:
                raise ValueError("domains 不能为空")

            logger.info(f"配置加载成功: {len(self.domains)} 个域名")

        except json.JSONDecodeError as e:
            logger.error(f"配置文件格式错误: {e}")
            raise

    def create_template(self):
        """创建配置模板"""
        template = {
            "cloudflare": {
                "api_token": "your_cloudflare_api_token",
                "zone_id": "your_zone_id"
            },
            "domains": [
                {
                    "name": "example.com",
                    "type": "A",
                    "ttl": 300,
                    "proxied": False
                },
                {
                    "name": "ipv6.example.com",
                    "type": "AAAA",
                    "ttl": 300,
                    "proxied": False
                }
            ],
            "ip_version": "both",
            "check_interval": 120,
            "retry_interval": 30,
            "max_retries": 3,
            "interface": "auto"
        }
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(template, f, indent=2, ensure_ascii=False)


class IPCache:
    """IP 缓存管理"""

    def __init__(self):
        self.cache = {}
        self.load()

    def load(self):
        """加载缓存"""
        if CACHE_FILE.exists():
            try:
                with open(CACHE_FILE, 'r') as f:
                    self.cache = json.load(f)
            except:
                self.cache = {}

    def save(self):
        """保存缓存"""
        with open(CACHE_FILE, 'w') as f:
            json.dump(self.cache, f)

    def get(self, domain: str) -> Optional[str]:
        """获取缓存的 IP"""
        return self.cache.get(domain)

    def set(self, domain: str, ip: str):
        """设置缓存"""
        self.cache[domain] = ip
        self.save()


class IPDetector:
    """IP 地址检测"""

    # IPv4 私有地址段 (CIDR)
    IPV4_PRIVATE = [
        (0x0A000000, 0xFF000000),  # 10.0.0.0/8
        (0xAC100000, 0xFFF00000), # 172.16.0.0/12
        (0xC0A80000, 0xFFFF0000), # 192.168.0.0/16
        (0x64400000, 0xFFC00000), # 100.64.0.0/10 (CGNAT)
        (0x7F000000, 0xFF000000), # 127.0.0.0/8 (Loopback)
        (0xA9FE0000, 0xFFFF0000), # 169.254.0.0/16 (Link-local)
    ]

    @staticmethod
    def ip_to_int(ip: str) -> int:
        """将 IP 地址转换为整数"""
        parts = ip.split('.')
        return (int(parts[0]) << 24) + (int(parts[1]) << 16) + (int(parts[2]) << 8) + int(parts[3])

    @staticmethod
    def is_public_ipv4(ip: str) -> bool:
        """检查是否为公网 IPv4"""
        try:
            ip_int = IPDetector.ip_to_int(ip)
            for network, mask in IPDetector.IPV4_PRIVATE:
                if (ip_int & mask) == network:
                    return False
            return True
        except:
            return False

    @staticmethod
    def is_public_ipv6(ip: str) -> bool:
        """检查是否为公网 IPv6"""
        try:
            # 扩展为完整格式
            parts = ip.split(':')
            # 处理 :: 缩写
            if '::' in ip:
                empty_idx = parts.index('')
                missing = 8 - len([p for p in parts if p])
                parts = parts[:empty_idx] + ['0'] * missing + parts[empty_idx + 1:]

            # 检查是否为全球单播地址 (2000::/3)
            first_part = int(parts[0], 16)
            prefix = first_part >> 13  # 取前3位

            # 2000::/3 = 001 开头，即 0x2000-0x3FFF
            if prefix != 1:  # 不是全球单播
                return False

            return True
        except:
            return False

    @staticmethod
    def get_interface_ips(interface: str = "auto") -> Tuple[Optional[str], Optional[str]]:
        """获取指定网卡的 IPv4 和 IPv6 地址"""
        system = platform.system()
        ipv4 = None
        ipv6 = None

        if system == "Windows":
            ipv4, ipv6 = IPDetector._get_windows_ips(interface)
        else:
            ipv4, ipv6 = IPDetector._get_linux_ips(interface)

        return ipv4, ipv6

    @staticmethod
    def _get_windows_ips(interface: str) -> Tuple[Optional[str], Optional[str]]:
        """Windows 系统获取网卡 IP"""
        ipv4 = None
        ipv6 = None

        try:
            # 使用 PowerShell 获取 IP
            result = subprocess.run(
                ['powershell', '-Command',
                 'Get-NetIPAddress | Where-Object { $_.AddressState -eq "Preferred" } | '
                 'Select-Object InterfaceAlias, IPAddress, AddressFamily | ConvertTo-Json'],
                capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW
            )

            if result.returncode == 0:
                data = json.loads(result.stdout) if result.stdout.strip() else []
                if not isinstance(data, list):
                    data = [data]

                iface_name = None
                for item in data:
                    iface = item.get('InterfaceAlias', '')
                    ip = item.get('IPAddress', '')
                    family = item.get('AddressFamily', '')

                    # 自动选择第一个有公网 IP 的网卡
                    if interface == "auto":
                        if family == 'IPv4' and IPDetector.is_public_ipv4(ip):
                            if iface_name is None or iface == iface_name:
                                ipv4 = ip
                                iface_name = iface
                        elif family == 'IPv6' and IPDetector.is_public_ipv6(ip):
                            if iface_name is None or iface == iface_name:
                                ipv6 = ip
                                iface_name = iface
                    else:
                        if iface == interface:
                            if family == 'IPv4' and IPDetector.is_public_ipv4(ip):
                                ipv4 = ip
                            elif family == 'IPv6' and IPDetector.is_public_ipv6(ip):
                                ipv6 = ip

        except Exception as e:
            logger.error(f"获取 Windows 网卡 IP 失败: {e}")

        return ipv4, ipv6

    @staticmethod
    def _get_linux_ips(interface: str) -> Tuple[Optional[str], Optional[str]]:
        """Linux 系统获取网卡 IP"""
        ipv4 = None
        ipv6 = None

        try:
            # 使用 ip addr 命令
            result = subprocess.run(
                ['ip', '-j', 'addr', 'show'],
                capture_output=True, text=True
            )

            if result.returncode == 0:
                data = json.loads(result.stdout)
                iface_name = None

                for iface in data:
                    name = iface.get('ifname', '')
                    if name == 'lo':
                        continue

                    for addr_info in iface.get('addr_info', []):
                        ip = addr_info.get('local', '')
                        family = addr_info.get('family', '')

                        # 自动选择第一个有公网 IP 的网卡
                        if interface == "auto":
                            if family == 'inet' and IPDetector.is_public_ipv4(ip):
                                if iface_name is None or name == iface_name:
                                    ipv4 = ip
                                    iface_name = name
                            elif family == 'inet6' and IPDetector.is_public_ipv6(ip):
                                if iface_name is None or name == iface_name:
                                    ipv6 = ip
                                    iface_name = name
                        elif name == interface:
                            if family == 'inet' and IPDetector.is_public_ipv4(ip):
                                ipv4 = ip
                            elif family == 'inet6' and IPDetector.is_public_ipv6(ip):
                                ipv6 = ip

        except Exception as e:
            logger.error(f"获取 Linux 网卡 IP 失败: {e}")

        return ipv4, ipv6


class CloudflareAPI:
    """Cloudflare API 客户端"""

    def __init__(self, api_token: str, zone_id: str):
        self.api_token = api_token
        self.zone_id = zone_id
        self.record_ids = {}  # 缓存记录 ID

    def _request(self, method: str, path: str, data: dict = None) -> dict:
        """发送 API 请求"""
        url = f"{CF_API_BASE}{path}"
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json"
        }

        body = json.dumps(data).encode('utf-8') if data else None
        req = Request(url, data=body, headers=headers, method=method)

        try:
            with urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode('utf-8'))
                if not result.get('success'):
                    errors = result.get('errors', [])
                    raise Exception(f"API 错误: {errors}")
                return result.get('result', {})
        except HTTPError as e:
            error_body = e.read().decode('utf-8')
            raise Exception(f"HTTP {e.code}: {error_body}")
        except URLError as e:
            raise Exception(f"网络错误: {e.reason}")

    def get_record_id(self, name: str, record_type: str) -> Optional[str]:
        """获取 DNS 记录 ID"""
        if f"{name}_{record_type}" in self.record_ids:
            return self.record_ids[f"{name}_{record_type}"]

        try:
            result = self._request('GET', f"/zones/{self.zone_id}/dns_records?type={record_type}&name={name}")
            if result:
                records = result if isinstance(result, list) else [result]
                for record in records:
                    if record.get('name') == name:
                        record_id = record.get('id')
                        self.record_ids[f"{name}_{record_type}"] = record_id
                        return record_id
        except Exception as e:
            logger.error(f"查询 DNS 记录失败: {e}")

        return None

    def update_record(self, name: str, record_type: str, ip: str, ttl: int = 300, proxied: bool = False) -> bool:
        """更新 DNS 记录"""
        record_id = self.get_record_id(name, record_type)

        if not record_id:
            # 创建新记录
            logger.info(f"创建 DNS 记录: {name} ({record_type})")
            try:
                data = {
                    "type": record_type,
                    "name": name,
                    "content": ip,
                    "ttl": ttl,
                    "proxied": proxied
                }
                result = self._request('POST', f"/zones/{self.zone_id}/dns_records", data)
                if result:
                    self.record_ids[f"{name}_{record_type}"] = result.get('id')
                    logger.info(f"DNS 记录创建成功: {name} -> {ip}")
                    return True
            except Exception as e:
                logger.error(f"创建 DNS 记录失败: {e}")
                return False
        else:
            # 更新现有记录
            try:
                data = {
                    "type": record_type,
                    "name": name,
                    "content": ip,
                    "ttl": ttl,
                    "proxied": proxied
                }
                self._request('PUT', f"/zones/{self.zone_id}/dns_records/{record_id}", data)
                logger.info(f"DNS 更新成功: {name} -> {ip}")
                return True
            except Exception as e:
                logger.error(f"更新 DNS 记录失败: {e}")
                return False

        return False


class DDNSDaemon:
    """DDNS 守护进程"""

    def __init__(self):
        self.config = None
        self.cache = IPCache()
        self.cf_api = None
        self.running = True

    def initialize(self):
        """初始化"""
        try:
            self.config = Config()
            self.cf_api = CloudflareAPI(
                self.config.cloudflare_api_token,
                self.config.cloudflare_zone_id
            )
            logger.info("初始化完成")
            return True
        except Exception as e:
            logger.error(f"初始化失败: {e}")
            return False

    def get_ips(self) -> Tuple[Optional[str], Optional[str], str]:
        """获取公网 IP，返回 (ipv4, ipv6, interface_name)"""
        ipv4, ipv6 = IPDetector.get_interface_ips(self.config.interface)

        iface_name = self.config.interface
        if iface_name == "auto":
            # 尝试检测实际使用的网卡
            system = platform.system()
            if system == "Windows":
                try:
                    result = subprocess.run(
                        ['powershell', '-Command',
                         'Get-NetIPAddress | Where-Object { $_.AddressState -eq "Preferred" } | '
                         'Select-Object InterfaceAlias -First 1'],
                        capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW
                    )
                    if result.returncode == 0:
                        iface_name = result.stdout.strip().split('\n')[-1].strip()
                except:
                    pass

        return ipv4, ipv6, iface_name

    def update_dns(self, domain_config: dict, ip: str) -> bool:
        """更新 DNS 记录"""
        name = domain_config.get('name')
        record_type = domain_config.get('type', 'A')
        ttl = domain_config.get('ttl', 300)
        proxied = domain_config.get('proxied', False)

        # 检查缓存
        cached_ip = self.cache.get(f"{name}_{record_type}")
        if cached_ip == ip:
            logger.debug(f"IP 未变化: {name} -> {ip}")
            return True

        # 更新 DNS
        if self.cf_api.update_record(name, record_type, ip, ttl, proxied):
            self.cache.set(f"{name}_{record_type}", ip)
            return True

        return False

    def run_once(self) -> bool:
        """执行一次检查"""
        ipv4, ipv6, iface_name = self.get_ips()

        # 记录检测到的 IP
        if ipv4:
            logger.info(f"检测到 IPv4: {ipv4} (网卡: {iface_name})")
        if ipv6:
            logger.info(f"检测到 IPv6: {ipv6} (网卡: {iface_name})")

        if not ipv4 and not ipv6:
            logger.warning("未检测到公网 IP")
            return False

        success = True
        for domain in self.config.domains:
            record_type = domain.get('type', 'A')
            ip_version = domain.get('ip_version', self.config.ip_version)

            # 确定使用的 IP
            ip = None
            if record_type == 'A':
                if ip_version in ('ipv4', 'both'):
                    ip = ipv4
            elif record_type == 'AAAA':
                if ip_version in ('ipv6', 'both'):
                    ip = ipv6

            if not ip:
                logger.warning(f"域名 {domain.get('name')} 未获取到 {record_type} 地址")
                continue

            if not self.update_dns(domain, ip):
                success = False

        return success

    def run(self):
        """主循环"""
        logger.info(f"开始监控... (检查间隔: {self.config.check_interval}秒)")

        while self.running:
            retries = 0
            success = False

            while retries < self.config.max_retries and not success:
                try:
                    success = self.run_once()
                    if not success and retries < self.config.max_retries - 1:
                        logger.warning(f"操作失败，{self.config.retry_interval}秒后重试...")
                        time.sleep(self.config.retry_interval)
                except Exception as e:
                    logger.error(f"发生错误: {e}")
                    retries += 1
                    if retries < self.config.max_retries:
                        logger.warning(f"{self.config.retry_interval}秒后重试...")
                        time.sleep(self.config.retry_interval)

            if not success:
                logger.error(f"达到最大重试次数 ({self.config.max_retries})，等待下次检查")

            time.sleep(self.config.check_interval)


def main():
    """主函数"""
    daemon = DDNSDaemon()

    if not daemon.initialize():
        sys.exit(1)

    try:
        daemon.run()
    except KeyboardInterrupt:
        logger.info("收到退出信号，正在停止...")
        daemon.running = False
    except Exception as e:
        logger.error(f"程序异常退出: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()