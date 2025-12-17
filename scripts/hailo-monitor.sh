#!/bin/bash
# Hailo Health Monitor
# Logs Hailo temperature and DMA stats every 5 minutes

LOG_FILE="/var/log/hailo-monitor.log"
MAX_LOG_SIZE=$((10 * 1024 * 1024))  # 10MB

# Rotate log if too large
if [ -f "$LOG_FILE" ] && [ $(stat -f%z "$LOG_FILE" 2>/dev/null || stat -c%s "$LOG_FILE") -gt $MAX_LOG_SIZE ]; then
    mv "$LOG_FILE" "$LOG_FILE.old"
fi

timestamp=$(date '+%Y-%m-%d %H:%M:%S')

# Get Hailo temperature
temp=$(cat /sys/class/hwmon/hwmon*/temp*_input 2>/dev/null | head -1)
temp_c=$((temp / 1000))

# Get system load
load=$(uptime | awk -F'load average:' '{print $2}' | xargs)

# Get Hailo DMA info if available
dma_info=""
if [ -d /sys/kernel/debug/hailo/hailo0 ]; then
    dma_info=$(cat /sys/kernel/debug/hailo/hailo0/dma_* 2>/dev/null | head -3 | tr '\n' ' ')
fi

# Check if detection process is running
detection_running=$(pgrep -f "headless_detection.py" > /dev/null && echo "RUNNING" || echo "STOPPED")

# Log
echo "[$timestamp] Temp: ${temp_c}°C | Load: $load | Detection: $detection_running | DMA: $dma_info" >> "$LOG_FILE"

# Alert if temperature too high
if [ $temp_c -gt 80 ]; then
    logger -t hailo-monitor "WARNING: Hailo temperature high: ${temp_c}°C"
fi
