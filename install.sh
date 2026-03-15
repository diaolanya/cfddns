#!/bin/bash
# DDNS Daemon Linux 安装脚本

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="ddns-daemon"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

# 检查 root 权限
if [ "$EUID" -ne 0 ]; then
    echo "请使用 root 权限运行此脚本"
    echo "sudo $0"
    exit 1
fi

# 检查 Python3
if ! command -v python3 &> /dev/null; then
    echo "错误: 未找到 python3"
    echo "请先安装 Python3: apt install python3"
    exit 1
fi

# 检查配置文件
if [ ! -f "${SCRIPT_DIR}/config.json" ]; then
    echo "错误: 未找到配置文件 config.json"
    echo "请先复制 config.json.example 并填写配置"
    exit 1
fi

# 创建 systemd 服务文件
cat > "${SERVICE_FILE}" << EOF
[Unit]
Description=DDNS Daemon - Cloudflare Dynamic DNS
After=network.target network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 ${SCRIPT_DIR}/ddns_daemon.py
WorkingDirectory=${SCRIPT_DIR}
Restart=always
RestartSec=10
StandardOutput=append:${SCRIPT_DIR}/ddns.log
StandardError=append:${SCRIPT_DIR}/ddns.log

[Install]
WantedBy=multi-user.target
EOF

echo "已创建 systemd 服务: ${SERVICE_FILE}"

# 重载 systemd
systemctl daemon-reload

# 启用服务
systemctl enable ${SERVICE_NAME}

echo ""
echo "安装完成!"
echo ""
echo "常用命令:"
echo "  启动服务:   sudo systemctl start ${SERVICE_NAME}"
echo "  停止服务:   sudo systemctl stop ${SERVICE_NAME}"
echo "  查看状态:   sudo systemctl status ${SERVICE_NAME}"
echo "  查看日志:   tail -f ${SCRIPT_DIR}/ddns.log"
echo ""
echo "请确保已正确配置 config.json 文件"