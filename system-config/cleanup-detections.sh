#!/bin/bash
# Daily cleanup of cat detection images. Keeps last 7 days.
# Installed in crontab; logs to syslog via logger.
set -u

RETENTION_DAYS=7
BASE=/home/pi/hailo-rpi5-examples

for dir in "$BASE/detected_objects" "$BASE/detected_cats"; do
    if [ -d "$dir" ]; then
        before=$(find "$dir" -type f | wc -l)
        find "$dir" -type f -mtime +$RETENTION_DAYS -delete
        after=$(find "$dir" -type f | wc -l)
        logger -t cleanup-detections "$dir: $((before - after)) file rimossi, $after conservati"
    fi
done

# Also prune empty subdirectories older than retention
find "$BASE/detected_objects" "$BASE/detected_cats" -mindepth 1 -type d -empty -mtime +$RETENTION_DAYS -delete 2>/dev/null || true
