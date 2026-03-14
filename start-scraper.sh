#!/bin/bash
# 网页抓取助手 - 启动脚本

echo "🚀 网页抓取助手 - Web Scraper"
echo ""

cd "$(dirname "$0")"

# 检查Python
if ! command -v python3 &> /dev/null; then
    echo "❌ 未找到 Python3，请先安装"
    exit 1
fi

# 检查端口
PORT=5555
if lsof -Pi :$PORT -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo "⚠️  端口 $PORT 已被占用"
    echo "请先关闭占用端口的程序，或修改 server.py 中的端口号"
    exit 1
fi

echo "📡 启动服务器: http://localhost:$PORT"
echo "📄 保存路径: ~/Downloads/web-scraper"
echo ""
echo "按 Ctrl+C 停止服务器"
echo ""

# 打开浏览器
sleep 2 && open "http://localhost:$PORT" &

# 启动服务器
python3 server.py
