#!/bin/bash
# deploy.sh - Script di deployment automatizzato per Cat Window Controller
# Esegue tutte le fasi di configurazione sistema descritte in DEPLOYMENT.md
#
# Uso: sudo ./deploy.sh
# Oppure per singole fasi: sudo ./deploy.sh --phase 3

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"
VENV_DIR="$PROJECT_DIR/venv_hailo_rpi5_examples"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

ok()   { echo -e "${GREEN}[OK]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
err()  { echo -e "${RED}[ERR]${NC} $1"; }
info() { echo -e "     $1"; }

phase_header() {
    echo ""
    echo -e "${GREEN}════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}  Fase $1: $2${NC}"
    echo -e "${GREEN}════════════════════════════════════════════════════${NC}"
}

# Controlla se siamo root (necessario per file di sistema)
check_root() {
    if [ "$EUID" -ne 0 ]; then
        err "Questo script deve essere eseguito come root: sudo ./deploy.sh"
        exit 1
    fi
}

# Fase 3: Regole udev
phase_udev() {
    phase_header 3 "Regole udev (Arduino + WiFi)"

    for f in "$PROJECT_DIR"/system-config/udev/*.rules; do
        fname=$(basename "$f")
        cp "$f" "/etc/udev/rules.d/$fname"
        ok "Installato /etc/udev/rules.d/$fname"
    done

    udevadm control --reload-rules
    udevadm trigger
    ok "Regole udev ricaricate"

    if [ -e /dev/ttyCAT ]; then
        ok "/dev/ttyCAT presente"
    else
        warn "/dev/ttyCAT non trovato - collega l'Arduino e verifica"
    fi
}

# Fase 4: Watchdog
phase_watchdog() {
    phase_header 4 "Watchdog Hardware"

    apt-get install -y watchdog > /dev/null 2>&1
    ok "Pacchetto watchdog installato"

    cp "$PROJECT_DIR/system-config/watchdog/watchdog.conf" /etc/watchdog.conf
    ok "Configurazione watchdog copiata"

    cp "$PROJECT_DIR/system-config/sysctl/99-watchdog-panic.conf" /etc/sysctl.d/
    sysctl -p /etc/sysctl.d/99-watchdog-panic.conf > /dev/null 2>&1
    ok "Configurazione sysctl applicata"

    systemctl enable watchdog > /dev/null 2>&1
    systemctl restart watchdog
    ok "Servizio watchdog abilitato e avviato"
}

# Fase 5: OpenVPN (raspa - tun1)
phase_vpn() {
    phase_header 5 "VPN (OpenVPN - raspa tun1)"

    apt-get install -y openvpn > /dev/null 2>&1
    ok "OpenVPN installato"

    if [ -f /etc/openvpn/client/raspa.conf ]; then
        ok "raspa.conf gia' presente in /etc/openvpn/client/"
    else
        if [ -f /home/pi/raspa.hailo.ovpn ]; then
            cp /home/pi/raspa.hailo.ovpn /etc/openvpn/client/raspa.conf
            sed -i 's/^dev tun$/dev tun1/' /etc/openvpn/client/raspa.conf
            ok "raspa.conf installato (dev tun1)"
        else
            warn "File raspa.hailo.ovpn non trovato in /home/pi/"
            info "  Copia il file .ovpn e riesegui: sudo ./deploy.sh --phase 5"
            return
        fi
    fi

    if [ ! -f /etc/openvpn/pass.txt ]; then
        warn "/etc/openvpn/pass.txt non trovato - credenziali VPN necessarie"
        info "  Crea il file con username e password su righe separate"
        return
    fi

    systemctl enable openvpn-client@raspa > /dev/null 2>&1
    systemctl start openvpn-client@raspa 2>/dev/null || true
    sleep 3

    if ip link show tun1 > /dev/null 2>&1; then
        local ip=$(ip -4 addr show tun1 | grep -oP '(?<=inet\s)\d+(\.\d+){3}')
        ok "VPN raspa attiva: tun1 = $ip"
    else
        warn "tun1 non attivo - controlla: journalctl -u openvpn-client@raspa"
    fi
}

# Fase 6: Mosquitto MQTT
phase_mosquitto() {
    phase_header 6 "MQTT Broker (Mosquitto)"

    apt-get install -y mosquitto mosquitto-clients > /dev/null 2>&1
    ok "Mosquitto installato"

    cp "$PROJECT_DIR/system-config/mosquitto/catfeeder.conf" /etc/mosquitto/conf.d/
    ok "Configurazione catfeeder copiata"

    systemctl enable mosquitto > /dev/null 2>&1
    systemctl restart mosquitto
    ok "Mosquitto abilitato e avviato"
}

# Fase 7: Ambiente Python (da eseguire come user pi)
phase_python() {
    phase_header 7 "Ambiente Python"

    if [ ! -d "$VENV_DIR" ]; then
        sudo -u pi python3 -m venv "$VENV_DIR"
        ok "Virtual environment creato"
    else
        ok "Virtual environment gia' esistente"
    fi

    sudo -u pi "$VENV_DIR/bin/pip" install -r "$PROJECT_DIR/basic_pipelines/requirements.txt" > /dev/null 2>&1
    ok "Dipendenze Python installate"

    # Verifica
    if sudo -u pi "$VENV_DIR/bin/python" -c "import cv2; import numpy" 2>/dev/null; then
        ok "Import Python verificati"
    else
        warn "Alcuni moduli Python mancanti - controlla manualmente"
    fi
}

# Fase 8: Configurazione cat_config.py
phase_config() {
    phase_header 8 "Configurazione Applicazione"

    local config="$PROJECT_DIR/basic_pipelines/cat_config.py"
    local example="$PROJECT_DIR/basic_pipelines/cat_config.example.py"

    if [ -f "$config" ]; then
        ok "cat_config.py gia' presente"
        warn "Verifica manualmente che token Telegram e chat ID siano corretti"
    elif [ -f "$example" ]; then
        cp "$example" "$config"
        chown pi:pi "$config"
        warn "cat_config.py creato da template - DEVI EDITARLO con le tue credenziali"
        info "  nano $config"
    else
        err "cat_config.example.py non trovato"
    fi
}

# Fase 9: Hailo monitor cron
phase_monitor() {
    phase_header 9 "Hailo Health Monitor (cron)"

    cp "$PROJECT_DIR/basic_pipelines/scripts/hailo-monitor.sh" /home/pi/hailo-monitor.sh
    chmod +x /home/pi/hailo-monitor.sh
    chown pi:pi /home/pi/hailo-monitor.sh
    ok "Script monitor copiato"

    touch /var/log/hailo-monitor.log
    chown pi:pi /var/log/hailo-monitor.log
    ok "File log creato"

    # Aggiungi cron job se non esiste
    if sudo -u pi crontab -l 2>/dev/null | grep -q "hailo-monitor"; then
        ok "Cron job gia' presente"
    else
        (sudo -u pi crontab -l 2>/dev/null; echo "*/5 * * * * /home/pi/hailo-monitor.sh") | sudo -u pi crontab -
        ok "Cron job aggiunto (ogni 5 minuti)"
    fi
}

# Fase 10: Servizio systemd
phase_systemd() {
    phase_header 10 "Servizio systemd"

    cp "$PROJECT_DIR/basic_pipelines/scripts/cat-window.service" /etc/systemd/system/
    ok "Service file copiato"

    systemctl daemon-reload
    systemctl enable cat-window > /dev/null 2>&1
    ok "Servizio abilitato"

    echo ""
    read -p "  Avviare il servizio cat-window ora? [y/N] " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        systemctl start cat-window
        sleep 3
        if systemctl is-active --quiet cat-window; then
            ok "Servizio avviato con successo"
        else
            err "Servizio non avviato - controlla: journalctl -u cat-window"
        fi
    else
        info "Avvia manualmente con: sudo systemctl start cat-window"
    fi
}

# Fase 11: Verifica finale
phase_verify() {
    phase_header 11 "Verifica Completa"

    echo ""
    # Hailo
    if hailortcli fw-control identify > /dev/null 2>&1; then
        ok "Hailo AI: funzionante"
    else
        err "Hailo AI: non rilevato"
    fi

    # Camera
    if v4l2-ctl --list-devices > /dev/null 2>&1; then
        ok "Camera USB: rilevata"
    else
        warn "Camera USB: non rilevata"
    fi

    # Arduino
    if [ -e /dev/ttyCAT ]; then
        ok "Arduino (/dev/ttyCAT): collegato"
    else
        warn "Arduino (/dev/ttyCAT): non collegato"
    fi

    # VPN
    if ip link show tun1 > /dev/null 2>&1; then
        ok "VPN raspa (tun1): attiva"
    else
        warn "VPN raspa (tun1): non attiva"
    fi

    # Servizi
    for svc in cat-window watchdog mosquitto; do
        if systemctl is-active --quiet "$svc" 2>/dev/null; then
            ok "Servizio $svc: attivo"
        else
            warn "Servizio $svc: non attivo"
        fi
    done

    # Cron
    if sudo -u pi crontab -l 2>/dev/null | grep -q "hailo-monitor"; then
        ok "Cron hailo-monitor: configurato"
    else
        warn "Cron hailo-monitor: mancante"
    fi

    # Temperatura
    temp=$(cat /sys/class/hwmon/hwmon*/temp*_input 2>/dev/null | head -1)
    if [ -n "$temp" ]; then
        temp_c=$((temp / 1000))
        if [ "$temp_c" -lt 80 ]; then
            ok "Temperatura Hailo: ${temp_c}C"
        else
            warn "Temperatura Hailo: ${temp_c}C (ALTA!)"
        fi
    fi

    echo ""
    echo -e "${GREEN}════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}  Deployment completato!${NC}"
    echo -e "${GREEN}════════════════════════════════════════════════════${NC}"
    echo ""
    info "Prossimi passi:"
    info "  1. Verifica cat_config.py con le credenziali Telegram"
    info "  2. Flash firmware Arduino (vedi DEPLOYMENT.md Fase 8)"
    info "  3. Invia /status al bot Telegram per verificare"
    info "  4. Controlla i log: journalctl -u cat-window -f"
}

# Main
main() {
    check_root

    echo ""
    echo -e "${GREEN}╔══════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║   Cat Window Controller - Deployment Script     ║${NC}"
    echo -e "${GREEN}╚══════════════════════════════════════════════════╝${NC}"
    echo ""

    if [ "$1" = "--phase" ] && [ -n "$2" ]; then
        case "$2" in
            3)  phase_udev ;;
            4)  phase_watchdog ;;
            5)  phase_vpn ;;
            6)  phase_mosquitto ;;
            7)  phase_python ;;
            8)  phase_config ;;
            9)  phase_monitor ;;
            10) phase_systemd ;;
            11) phase_verify ;;
            *)  err "Fase non valida: $2 (disponibili: 3-11)"; exit 1 ;;
        esac
    else
        phase_udev
        phase_watchdog
        phase_vpn
        phase_mosquitto
        phase_python
        phase_config
        phase_monitor
        phase_systemd
        phase_verify
    fi
}

main "$@"
