# DDNS Daemon

跨平台 Cloudflare DDNS 守护程序，支持 IPv4/IPv6 双栈，自动重试，日志记录。

## 功能特性

- ✅ 支持 IPv4 (A 记录) 和 IPv6 (AAAA 记录)
- ✅ 自动检测公网 IP 地址
- ✅ 网络异常自动重试
- ✅ 完整的日志记录
- ✅ 跨平台支持 (Linux + Windows)
- ✅ 开机自启动
- ✅ 配置文件管理

## 快速开始

### 1. 获取 Cloudflare API Token

1. 登录 [Cloudflare Dashboard](https://dash.cloudflare.com/)
2. 进入 **My Profile** > **API Tokens**
3. 点击 **Create Token**
4. 选择 **Edit zone DNS** 模板
5. 在 **Zone Resources** 中选择要更新的域名
6. 创建并复制 Token

### 2. 获取 Zone ID

1. 在 Cloudflare Dashboard 中选择你的域名
2. 在右侧 **API** 区域可以看到 **Zone ID**
3. 点击复制

### 3. 配置

复制配置模板并编辑：

```bash
cp config.json.example config.json
# 或直接编辑 config.json
```

配置说明：

```json
{
  "cloudflare": {
    "api_token": "your_cloudflare_api_token",  // Cloudflare API Token
    "zone_id": "your_zone_id"                   // Zone ID
  },
  "domains": [
    {
      "name": "example.com",    // 域名
      "type": "A",              // 记录类型: A 或 AAAA
      "ttl": 300,               // TTL (秒)
      "proxied": false          // 是否开启 Cloudflare 代理
    }
  ],
  "ip_version": "both",        // IP 版本: ipv4, ipv6, both
  "check_interval": 120,       // 检查间隔 (秒)
  "retry_interval": 30,        // 重试间隔 (秒)
  "max_retries": 3,            // 最大重试次数
  "interface": "auto"          // 网卡名称，auto 表示自动检测
}
```

### 4. 运行

**Linux:**

```bash
# 直接运行
python3 ddns_daemon.py

# 或安装为系统服务
sudo bash install.sh
sudo systemctl start ddns-daemon
```

**Windows:**

```powershell
# 直接运行
python ddns_daemon.py

# 或安装为任务计划（需要管理员权限）
.\install.ps1
```

## 安装为系统服务

### Linux (systemd)

```bash
# 安装服务
sudo bash install.sh

# 启动服务
sudo systemctl start ddns-daemon

# 查看状态
sudo systemctl status ddns-daemon

# 查看日志
tail -f ddns.log

# 停止服务
sudo systemctl stop ddns-daemon

# 禁用开机自启
sudo systemctl disable ddns-daemon
```

### Windows (任务计划程序)

```powershell
# 安装（需要管理员权限）
.\install.ps1

# 查看状态
Get-ScheduledTask -TaskName DDNS-Daemon

# 停止
Stop-ScheduledTask -TaskName DDNS-Daemon

# 启动
Start-ScheduledTask -TaskName DDNS-Daemon

# 卸载
.\install.ps1 -Uninstall
```

## 日志

日志文件位于 `ddns.log`，格式如下：

```
[2026-03-15 12:00:00] [INFO] 开始监控...
[2026-03-15 12:00:01] [INFO] 检测到 IPv4: 1.2.3.4 (网卡: eth0)
[2026-03-15 12:00:01] [INFO] 检测到 IPv6: 2400:xxxx::1 (网卡: eth0)
[2026-03-15 12:02:00] [INFO] IPv4 变化: 1.2.3.4 -> 5.6.7.8
[2026-03-15 12:02:01] [INFO] DNS 更新成功: example.com -> 5.6.7.8
[2026-03-15 12:05:00] [ERROR] 网络异常，30秒后重试...
```

## 公网 IP 检测规则

### IPv4

排除以下私有地址段：
- `10.0.0.0/8` - 私有网络
- `172.16.0.0/12` - 私有网络
- `192.168.0.0/16` - 私有网络
- `100.64.0.0/10` - CGNAT
- `127.0.0.0/8` - 本地回环
- `169.254.0.0/16` - 链路本地

### IPv6

只接受全球单播地址：
- `2000::/3` (即 `2000::-3fff:ffff:...`)

排除：
- `fe80::/10` - 链路本地
- `fc00::/7` - 唯一本地

## 故障排除

### 1. 未检测到公网 IP

- 检查网卡是否正确连接
- 确认 ISP 分配了公网 IP（非 NAT）
- 尝试手动指定网卡：`"interface": "eth0"`

### 2. DNS 更新失败

- 检查 API Token 是否正确
- 确认 Zone ID 正确
- 检查域名是否在 Cloudflare 托管

### 3. 服务无法启动

- 检查 Python 是否安装
- 检查配置文件格式是否正确
- 查看日志文件了解详细错误

## 文件说明

```
cfddns/
├── ddns_daemon.py      # 主程序
├── config.json         # 配置文件
├── ddns.log            # 日志文件（运行时生成）
├── .ip_cache.json      # IP 缓存（运行时生成）
├── install.sh          # Linux 安装脚本
├── install.ps1         # Windows 安装脚本
└── README.md           # 本文档
```

## 许可证

MIT License