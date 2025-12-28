#!/bin/bash

# Colori per i messaggi
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Directory base
HAILO_BASE_DIR="$HOME/hailo-rpi5-examples"
VENV_DIR="venv_hailo_rpi5_examples"

# Funzione per stampare messaggi di stato
print_status() {
    echo -e "${BLUE}$1${NC}"
}

# Funzione per stampare errori
print_error() {
    echo -e "${RED}Error: $1${NC}"
    exit 1
}

# Funzione per stampare successo
print_success() {
    echo -e "${GREEN}$1${NC}"
}

# Verifica che la directory base esista
if [ ! -d "$HAILO_BASE_DIR" ]; then
    print_error "Directory $HAILO_BASE_DIR non trovata!"
fi

# Cambia alla directory base
cd "$HAILO_BASE_DIR" || print_error "Impossibile accedere a $HAILO_BASE_DIR"
print_status "Cambiato alla directory $(pwd)"

# Verifica che l'ambiente virtuale esista
if [ ! -d "$VENV_DIR" ]; then
    print_error "Ambiente virtuale $VENV_DIR non trovato!"
fi

# Attiva l'ambiente virtuale
print_status "Attivazione ambiente virtuale $VENV_DIR..."
source "$VENV_DIR/bin/activate"

# Verifica che l'ambiente virtuale sia stato attivato
if [ -z "$VIRTUAL_ENV" ]; then
    print_error "Attivazione ambiente virtuale fallita!"
else
    print_success "Ambiente virtuale attivato: $VIRTUAL_ENV"
fi

# Configura l'ambiente Hailo
print_status "Configurazione ambiente Hailo..."
source basic_pipelines/setup_env.sh

# Verifica che le variabili d'ambiente necessarie siano state impostate
if [ -z "$TAPPAS_POST_PROC_DIR" ]; then
    print_error "TAPPAS_POST_PROC_DIR non impostata!"
fi

if [ -z "$DEVICE_ARCHITECTURE" ]; then
    print_error "DEVICE_ARCHITECTURE non impostata!"
fi

# Stampa lo stato finale
print_success "Ambiente configurato correttamente!"
print_success "TAPPAS_POST_PROC_DIR = $TAPPAS_POST_PROC_DIR"
print_success "DEVICE_ARCHITECTURE = $DEVICE_ARCHITECTURE"

# Stampa istruzioni per l'uso
echo -e "\n${BLUE}L'ambiente è pronto per l'esecuzione delle applicazioni Hailo.${NC}"
echo -e "${BLUE}Puoi ora eseguire i tuoi script, per esempio:${NC}"
echo -e "  python3 basic_pipelines/detection-with-cat.py --input /dev/video0 --use-frame"
echo -e "  python3 basic_pipelines/pose_estimation.py --input /dev/video0\n"
