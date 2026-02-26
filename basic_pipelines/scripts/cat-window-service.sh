#!/bin/bash

# Script wrapper per il servizio systemd cat-window
# Prepara l'ambiente e lancia l'applicazione

set -e

PROJECT_DIR="/home/pi/hailo-rpi5-examples"
VENV_DIR="$PROJECT_DIR/venv_hailo_rpi5_examples"
PIPELINES_DIR="$PROJECT_DIR/basic_pipelines"

cd "$PROJECT_DIR"

# Attiva virtual environment
source "$VENV_DIR/bin/activate"

# Configura TAPPAS_POST_PROC_DIR
if pkg-config --exists hailo-tappas-core; then
    export TAPPAS_POST_PROC_DIR=$(pkg-config --variable=tappas_postproc_lib_dir hailo-tappas-core)
elif pkg-config --exists hailo_tappas; then
    TAPPAS_WORKSPACE=$(pkg-config --variable=tappas_workspace hailo_tappas)
    export TAPPAS_POST_PROC_DIR="${TAPPAS_WORKSPACE}/apps/h8/gstreamer/libs/post_processes/"
else
    echo "Errore: hailo-tappas-core o hailo_tappas non trovato"
    exit 1
fi

# Rileva architettura device Hailo
output=$(hailortcli fw-control identify 2>/dev/null | tr -d '\0')
device_arch=$(echo "$output" | grep "Device Architecture" | awk -F": " '{print $2}')
if [ -z "$device_arch" ]; then
    echo "Errore: Device Architecture non trovata"
    exit 1
fi
export DEVICE_ARCHITECTURE="$device_arch"

echo "Ambiente configurato:"
echo "  TAPPAS_POST_PROC_DIR=$TAPPAS_POST_PROC_DIR"
echo "  DEVICE_ARCHITECTURE=$DEVICE_ARCHITECTURE"

# Avvia applicazione
exec "$VENV_DIR/bin/python" "$PIPELINES_DIR/headless_detection.py" --input /dev/video0
