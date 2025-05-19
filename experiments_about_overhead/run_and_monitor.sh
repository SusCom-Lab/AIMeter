#!/bin/bash

PYTHON_BIN="sudo /home/ldaphome/hhz/.conda/envs/llama/bin/python"
PID_FILE="python_pid.txt"
LOG_BASE_DIR="monitor_logs_sleep"
SCRIPT_LIST=("llm_with_monitor.py" "llm_without_monitor.py" "sleep.py")
REPEAT=10

for SCRIPT in "${SCRIPT_LIST[@]}"; do
    SCRIPT_NAME="${SCRIPT%.*}"  # 去掉.py扩展名
    echo "==== Running $SCRIPT ===="

    for i in $(seq 1 $REPEAT); do
        echo "---- Run $i for $SCRIPT ----"

        # 清除旧的 PID 文件（如果有）
        rm -f "$PID_FILE"

        # 启动 Python 脚本
        $PYTHON_BIN "$SCRIPT" &

        # 等待 PID 文件生成（最多等待 10 秒）
        for j in {1..10}; do
            if [ -f "$PID_FILE" ]; then
                break
            fi
            sleep 1
        done

        if [ ! -f "$PID_FILE" ]; then
            echo "Error: PID file not found after waiting."
            exit 1
        fi

        PID=$(cat "$PID_FILE")
        echo "Detected Python PID: $PID"

        # 创建日志目录
        LOG_DIR="${LOG_BASE_DIR}/${SCRIPT_NAME}_run${i}"
        mkdir -p "$LOG_DIR"

        # 启动监控
        echo "Starting CPU monitoring..."
        pidstat -u -p $PID 1 > "$LOG_DIR/cpu.csv" &

        echo "Starting memory monitoring..."
        pidstat -r -p $PID 1 > "$LOG_DIR/memory.csv" &

        echo "Starting disk I/O monitoring..."
        pidstat -d -p $PID 1 > "$LOG_DIR/disk.csv" &

        # 等待 Python 脚本执行完成
        wait $!

        # 终止监控子进程
        echo "Stopping monitoring..."
        pkill -P $$ pidstat

        echo "Completed run $i for $SCRIPT. Logs saved in $LOG_DIR"
        echo ""
    done
done

echo "All tests completed."
