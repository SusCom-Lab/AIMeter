#!/bin/bash

# 注意：如果您还没有激活conda环境，请先运行：
# conda activate gpu_dp_opt

# 检查 python 是否存在
command -v python >/dev/null 2>&1 || { echo "需要 python 命令，但未找到。请检查环境。"; exit 1; }

# 检查 nohup 是否存在
command -v nohup >/dev/null 2>&1 || { echo "需要 nohup 命令，但未找到。请安装后再试。"; exit 1; }

# 获取脚本所在目录
SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
cd "$SCRIPT_DIR"

# 运行监控脚本，后台运行
echo "启动持续监控系统..."
nohup python continuous_monitor.py > monitor.out 2>&1 &

# 保存 PID 到文件，以便停止脚本使用
echo $! > monitor.pid
echo "监控系统已启动，PID: $!"
echo "日志输出重定向到 monitor.out"
echo "可以使用 ./stop_monitor.sh 停止监控"

# 等待几秒，检查进程是否还在运行
sleep 10
if ps -p $(cat monitor.pid) > /dev/null; then
    echo "监控系统运行正常"
else
    echo "监控系统启动失败，请检查 monitor.out 日志文件"
fi 