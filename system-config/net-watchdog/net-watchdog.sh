#!/bin/bash
# Watchdog di rete: verifica che wlan0 funzioni davvero (perdita verso il gateway,
# velocità di ricezione), non solo che NetworkManager lo consideri "connesso".
#
# Rete giù (perdita >= 30% per minuti consecutivi), escalation:
#   riassociazione -> ricarica driver brcmfmac -> reboot (con rate limit).
# Rete degradata ma non giù, cambio di access point della mesh (max 1 ogni 30 min):
#   - Wi-Fi lento: rx < 20 Mbit/s per 10 minuti consecutivi
#   - perdite intermittenti: >= 4 minuti cattivi negli ultimi 30
# Lanciato ogni minuto da net-watchdog.timer. Log: journalctl -t net-watchdog
#
# Installazione:
#   sudo install -m 755 net-watchdog.sh /usr/local/sbin/net-watchdog
#   sudo install -m 644 net-watchdog.service net-watchdog.timer /etc/systemd/system/
#   sudo systemctl daemon-reload && sudo systemctl enable --now net-watchdog.timer
#
# Test senza azioni: sudo DRY_RUN=1 GW_OVERRIDE=192.168.1.250 STATE_DIR=/tmp/nwd /usr/local/sbin/net-watchdog
# (RX_OVERRIDE=6.0 simula un collegamento lento)

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
SLOW_RX=20                 # Mbit/s: sotto questa velocità di ricezione il minuto è "lento"
SLOW_BEFORE_ROAM=10        # minuti lenti consecutivi prima di cambiare access point
WINDOW=30                  # finestra mobile (minuti) per le perdite intermittenti
WINDOW_BAD=4               # minuti cattivi nella finestra prima di cambiare access point
ROAM_COOLDOWN=1800         # al massimo un cambio di access point ogni 30 min
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

# Passa al miglior altro access point a 5 GHz della mesh (BSSID diverso dall'attuale).
# Rate limit: ROAM_COOLDOWN. Ritorna 1 se non ha fatto nulla.
roam_away() {
    local reason=$1 now last target
    now=$(date +%s)
    last=$(cat "$STATE_DIR/last_roam" 2>/dev/null || echo 0)
    if [ $((now - last)) -lt "$ROAM_COOLDOWN" ]; then
        log "cambio access point rimandato ($reason): ultimo $(( (now - last) / 60 )) min fa"
        return 1
    fi
    echo "$now" > "$STATE_DIR/last_roam"
    target=$(nmcli -t -e no -f SSID,FREQ,SIGNAL,BSSID dev wifi list ifname "$IFACE" --rescan yes 2>/dev/null \
        | awk -F: -v ssid="$CONN" -v cur="${bssid^^}" '
            $1 == ssid && $2 + 0 >= 5000 {
                b = $4 ":" $5 ":" $6 ":" $7 ":" $8 ":" $9
                if (b != cur && $3 + 0 > best) { best = $3 + 0; pick = b }
            }
            END { print pick }')
    if [ -z "$target" ]; then
        log "AZIONE ($reason): nessun altro access point a 5 GHz visibile"
        reassociate
        return 0
    fi
    log "AZIONE ($reason): passo da ${bssid:-nessuno} a $target"
    run nmcli connection up "$CONN" ifname "$IFACE" ap "$target" >/dev/null 2>&1 || {
        log "connessione a $target fallita"
        reassociate
    }
    return 0
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
slow=$(cat "$STATE_DIR/slow" 2>/dev/null || echo 0)
tick=$(cat "$STATE_DIR/tick" 2>/dev/null || echo 0)
history=$(cat "$STATE_DIR/history" 2>/dev/null)  # un carattere per minuto: 1 = cattivo

link=$(iw dev "$IFACE" link 2>/dev/null)
bssid=$(awk '/Connected to/{print $3}' <<<"$link")
signal=$(awk '/signal:/{print $2}' <<<"$link")
rx=${RX_OVERRIDE:-$(awk '/rx bitrate:/{print $3}' <<<"$link")}
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

if [ "$loss" -ge "$LOSS_BAD" ]; then
    history="${history}1"
else
    history="${history}0"
fi
[ ${#history} -gt "$WINDOW" ] && history=${history: -$WINDOW}
echo "$history" > "$STATE_DIR/history"

if [ "$loss" -lt "$LOSS_BAD" ]; then
    [ "$bad" -gt 0 ] && log "rete di nuovo OK dopo $bad min: $status"
    echo 0 > "$STATE_DIR/bad"
    tick=$((tick + 1))
    echo "$tick" > "$STATE_DIR/tick"
    [ $((tick % LOG_OK_EVERY)) -eq 1 ] && log "ok: $status"

    window_bad=${history//0/}
    window_bad=${#window_bad}
    if [ -n "$rx" ] && [ "${rx%.*}" -lt "$SLOW_RX" ]; then
        slow=$((slow + 1))
    else
        slow=0
    fi
    echo "$slow" > "$STATE_DIR/slow"

    if [ "$window_bad" -ge "$WINDOW_BAD" ]; then
        log "perdite intermittenti: $window_bad min cattivi negli ultimi ${#history}: $status"
        roam_away "perdite intermittenti" && echo "" > "$STATE_DIR/history"
    elif [ "$slow" -ge "$SLOW_BEFORE_ROAM" ] && [ $((slow % SLOW_BEFORE_ROAM)) -eq 0 ]; then
        log "Wi-Fi lento da $slow min: $status"
        roam_away "Wi-Fi lento"
    fi
    exit 0
fi

echo 0 > "$STATE_DIR/slow"
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
