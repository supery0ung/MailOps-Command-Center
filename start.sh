#!/bin/bash

# MailOps Command Center local launcher

cd "$(dirname "$0")"

echo "========================================"
echo "MailOps Command Center"
echo "========================================"
echo ""
echo "正在启动服务器..."
echo ""
echo "Open: http://127.0.0.1:5001"
echo "按 Ctrl+C 停止服务器"
echo ""
echo "========================================"
echo ""

python3 web_app.py
