#!/bin/bash
# Watchdog di rete: verifica che wlan0 funzioni davvero (perdita verso il gateway),
# non solo che NetworkManager lo consideri "connesso", e lo ripara con escalation:
#   riassociazione -> ricarica driver brcmfmac -> reboot (con rate limit).
# Lanciato ogni minuto da net-watchdog.timer. Log: journalctl -t net-watchdog
#
# Installazione:
#   sudo install -m 755 net-watchdog.sh /usr/local/sbin/net-watchdog
#   sudo install -m 644 net-watchdog.service net-watchdog.timer /etc/systemd/system/
#   sudo systemctl daemon-reload && sudo systemctl enable --now net-watchdog.timer
#
# Test senza azioni: sudo DRY_RUN=1 GW_OVERRIDE=192.168.1.250 STATE_DIR=/tmp/nwd /usr/local/sbin/net-watchdog

IFACE=wlan0
CONN=Riva
STATE_DIR=${STATE_DIR:-/run/net-watchdog}  # azzerato a ogni boot
PERSIST_DIR=/var/lib/net-watchdog          # sopravvive al reboot (rate limit reboot)
PINGS=10
LOSS_BAD=30                # % perdita verso il gateway oltre cui il minuto è "cattivo"
BAD_BEFORE_REASSOC=3       # minuti cattivi consecutivi prima di riassociare
BAD_BEFORE_RELOAD=8        # ... prima di ricaricare il driver Wi-Fi
BAD_BEFORE_REBOOT=15       # ... prima di riavviare il sistema
RETRY_EVERY=10             # oltre la soglia di reboot, riprova ogni N minuti
MIN_UPTIME_REBOOT=1800     # mai reboot nei primi 30 min dal boot
MIN_REBOOT_INTERVAL=21600  # al massimo un reboot ogni 6 ore
LOG_OK_EVERY=15            # riga di stato ogni N minuti anche se tutto ok

log() { logger -t net-watchdog "$*"; }

run() {
    if [ -n "$DRY_RUN" ]; then
        log "DRY_RUN: $*"
    else
        "$@"
    fi
}

reassociate() {
    log "AZIONE: riassociazione di '$CONN'"
    run nmcli connection down "$CONN" >/dev/null 2>&1
    run sleep 3
    run nmcli connection up "$CONN" >/dev/null 2>&1 || log "riassociazione fallita"
}

reload_driver() {
    log "AZIONE: ricarico driver brcmfmac"
    run modprobe -r brcmfmac_wcc brcmfmac
    run sleep 2
    run modprobe brcmfmac
    run sleep 10
    run nmcli connection up "$CONN" >/dev/null 2>&1 || log "riconnessione dopo reload fallita"
}

try_reboot() {
    local uptime_s now last
    uptime_s=$(cut -d. -f1 /proc/uptime)
    now=$(date +%s)
    last=$(cat "$PERSIST_DIR/last_reboot" 2>/dev/null || echo 0)
    if [ "$uptime_s" -lt "$MIN_UPTIME_REBOOT" ]; then
        log "reboot rimandato: uptime ${uptime_s}s < ${MIN_UPTIME_REBOOT}s"
        return 1
    fi
    if [ $((now - last)) -lt "$MIN_REBOOT_INTERVAL" ]; then
        log "reboot rimandato: ultimo reboot del watchdog $(( (now - last) / 60 )) min fa"
        return 1
    fi
    log "AZIONE: reboot del sistema (rete degradata da $bad min)"
    [ -z "$DRY_RUN" ] && echo "$now" > "$PERSIST_DIR/last_reboot"
    run systemctl reboot
}

mkdir -p "$STATE_DIR" "$PERSIST_DIR"
bad=$(cat "$STATE_DIR/bad" 2>/dev/null || echo 0)
tick=$(cat "$STATE_DIR/tick" 2>/dev/null || echo 0)

link=$(iw dev "$IFACE" link 2>/dev/null)
bssid=$(awk '/Connected to/{print $3}' <<<"$link")
signal=$(awk '/signal:/{print $2}' <<<"$link")
rx=$(awk '/rx bitrate:/{print $3}' <<<"$link")
tx=$(awk '/tx bitrate:/{print $3}' <<<"$link")
gw=${GW_OVERRIDE:-$(ip -4 route show default dev "$IFACE" 2>/dev/null | awk '{print $3; exit}')}

if [ -z "$gw" ]; then
    loss=100
else
    loss=$(ping -n -q -I "$IFACE" -c "$PINGS" -i 0.2 -W 1 "$gw" 2>/dev/null \
        | grep -oE '[0-9.]+% packet loss' | cut -d% -f1)
    loss=${loss:-100}
    loss=${loss%.*}
fi

status="gw=${gw:-nessuno} loss=${loss}% bssid=${bssid:-nessuno} signal=${signal:-?}dBm rx=${rx:-?} tx=${tx:-?}Mbit/s"

if [ "$loss" -lt "$LOSS_BAD" ]; then
    [ "$bad" -gt 0 ] && log "rete di nuovo OK dopo $bad min: $status"
    echo 0 > "$STATE_DIR/bad"
    tick=$((tick + 1))
    echo "$tick" > "$STATE_DIR/tick"
    [ $((tick % LOG_OK_EVERY)) -eq 1 ] && log "ok: $status"
    exit 0
fi

bad=$((bad + 1))
echo "$bad" > "$STATE_DIR/bad"
log "rete degradata da $bad min: $status"

if [ "$bad" -eq "$BAD_BEFORE_REASSOC" ]; then
    reassociate
elif [ "$bad" -eq "$BAD_BEFORE_RELOAD" ]; then
    reload_driver
elif [ "$bad" -ge "$BAD_BEFORE_REBOOT" ] && [ $(( (bad - BAD_BEFORE_REBOOT) % RETRY_EVERY )) -eq 0 ]; then
    try_reboot || reassociate
fi
exit 0
