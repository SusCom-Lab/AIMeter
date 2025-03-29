#!/bin/bash

# 获取脚本所在目录
SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
cd "$SCRIPT_DIR"

# 检查PID文件是否存在
if [ ! -f "monitor.pid" ]; then
    echo "找不到 monitor.pid 文件，监控系统可能未运行"
    exit 1
fi

# 读取PID
PID=$(cat monitor.pid)

# 检查进程是否存在
if ! ps -p $PID > /dev/null; then
    echo "进程 $PID 已不存在，监控系统可能已经停止"
    rm monitor.pid
    exit 0
fi

echo "正在停止监控系统（PID: $PID）..."

# 发送SIGTERM信号，使脚本能够优雅退出
kill $PID

# 等待进程结束
TIMEOUT=10
counter=0
while ps -p $PID > /dev/null && [ $counter -lt $TIMEOUT ]; do
    sleep 1
    counter=$((counter+1))
    echo -n "."
done
echo ""

# 检查进程是否仍在运行
if ps -p $PID > /dev/null; then
    echo "进程未在 $TIMEOUT 秒内退出，尝试强制终止..."
    kill -9 $PID
    sleep 1
fi

# 最终检查
if ps -p $PID > /dev/null; then
    echo "无法终止监控系统，请手动检查进程 $PID"
else
    echo "监控系统已成功停止"
    rm monitor.pid
fi 