#!/bin/bash

PROCESS_PATTERN="/usr/prog/klipper/klippy/klippy.py"
MAX_RETRIES=30
RETRY_COUNT=0

check_process() {
    if pgrep -f "$PROCESS_PATTERN" > /dev/null; then
        return 0  # 进程存在
    else
        return 1  # 进程不存在
    fi
}

# 主循环
while [ $RETRY_COUNT -le $MAX_RETRIES ]; do
    if check_process; then
        PID=$(pgrep -f "$PROCESS_PATTERN" | head -1)
        echo "找到进程，PID: $PID"
        chrt -f -p 50 $(pgrep -f "klippy.py")
        exit 0
    else
        if [ $RETRY_COUNT -eq 0 ]; then
            echo "进程不存在，等待 2 秒后重试..."
        else
            echo "第 ${RETRY_COUNT} 次重试，进程仍未启动，继续等待..."
        fi
        
        sleep 2
        RETRY_COUNT=$((RETRY_COUNT + 1))
    fi
done

echo "超过最大重试次数 ($MAX_RETRIES)，进程未启动"
exit 1
