#!/bin/bash

# Script di avvio per il sistema di controllo finestra gatti
# Questo script è progettato per essere eseguito al boot via crontab

# Ottieni la directory dello script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
PIPELINES_DIR="$PROJECT_DIR/basic_pipelines"

# Imposta il log file
exec 1> >(logger -s -t $(basename $0)) 2>&1

# Log dell'avvio
echo "Script avviato: $(date)"
echo "SCRIPT_DIR: $SCRIPT_DIR"
echo "PROJECT_DIR: $PROJECT_DIR"

# Attendi che il sistema sia pronto
sleep 30
echo "Attesa iniziale completata"

# Vai alla directory del progetto
cd "$PROJECT_DIR" || { echo "Errore: impossibile accedere a $PROJECT_DIR"; exit 1; }
echo "Directory progetto: $(pwd)"

# Attiva l'ambiente
echo "Attivazione ambiente hailo..."
source "$SCRIPT_DIR/start-hailo-env.sh"
echo "Ambiente attivato"

# Avvia l'applicazione con restart automatico
echo "Avvio applicazione con auto-restart..."
MAX_RESTARTS=10
RESTART_COUNT=0
RESTART_WINDOW=3600  # Reset counter dopo 1 ora di uptime stabile
LAST_START=$(date +%s)

while true; do
    echo "$(date): Avvio applicazione (restart #$RESTART_COUNT)..."
    "$PROJECT_DIR/venv_hailo_rpi5_examples/bin/python" "$PIPELINES_DIR/headless_detection.py" --input /dev/video0
    EXIT_CODE=$?

    CURRENT_TIME=$(date +%s)
    UPTIME=$((CURRENT_TIME - LAST_START))

    echo "$(date): Applicazione terminata con exit code $EXIT_CODE dopo ${UPTIME}s"

    # Se l'app è stata su per più di 1 ora, reset counter
    if [ $UPTIME -gt $RESTART_WINDOW ]; then
        RESTART_COUNT=0
        echo "Uptime stabile ($UPTIME s), reset restart counter"
    fi

    RESTART_COUNT=$((RESTART_COUNT + 1))

    if [ $RESTART_COUNT -gt $MAX_RESTARTS ]; then
        echo "ERRORE: Troppi restart ($RESTART_COUNT), stop definitivo"
        exit 1
    fi

    echo "Attesa 10 secondi prima del restart..."
    sleep 10
    LAST_START=$(date +%s)
done
