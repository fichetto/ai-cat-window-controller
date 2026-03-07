# Guida Deployment - AI Cat Window Controller

Guida passo-passo per configurare un Raspberry Pi 5 da zero per eseguire il sistema Cat Window Controller.

## Prerequisiti Hardware

| Componente | Descrizione |
|-----------|-------------|
| Raspberry Pi 5 | 8GB RAM consigliato |
| Hailo AI HAT / AI Kit | Hailo-8 (26 TOPS) o Hailo-8L (13 TOPS) |
| Camera USB | Qualsiasi webcam USB compatibile V4L2 |
| Arduino ATMEGA2560 | Controller servo finestra + serratura |
| PCA9685 | Driver PWM per servo (collegato all'Arduino) |
| 2x Servo motori | Canale 0: finestra, Canale 1: serratura |
| Alimentatore 27W USB-C | Alimentatore ufficiale Raspberry Pi |
| Cavo USB A-B | Per collegamento Arduino |

### Hardware opzionale (sistema alimentazione)
| Componente | Descrizione |
|-----------|-------------|
| ESP32 | Controller sistema alimentazione |
| Cella di carico + HX711 | Pesatura ciotola cibo |
| Dispenser cibo | Controllato via ESP32 |

---

## Fase 1: Installazione OS e Hailo SDK

Segui la guida dettagliata in [doc/install-raspberry-pi5.md](doc/install-raspberry-pi5.md):

1. Installa **Raspberry Pi OS (64-bit)** con Raspberry Pi Imager
2. Aggiorna il sistema:
   ```bash
   sudo apt update && sudo apt full-upgrade
   ```
3. Abilita **PCIe Gen3**:
   ```bash
   sudo raspi-config  # 6 Advanced Options → A8 PCIe Speed → Yes
   sudo reboot
   ```
4. Installa **Hailo SDK**:
   ```bash
   sudo apt install hailo-all
   sudo reboot
   ```
5. Verifica installazione:
   ```bash
   hailortcli fw-control identify
   gst-inspect-1.0 hailotools
   gst-inspect-1.0 hailo
   ```

---

## Fase 2: Clone Repository e Ambiente Python

```bash
cd /home/pi
git clone <repository-url> hailo-rpi5-examples
cd hailo-rpi5-examples

# Crea virtual environment
python3 -m venv venv_hailo_rpi5_examples
source venv_hailo_rpi5_examples/bin/activate

# Installa dipendenze
pip install -r basic_pipelines/requirements.txt

# Scarica risorse (modelli HEF, post-processing)
./download_resources.sh
```

### Verifica ambiente
```bash
source venv_hailo_rpi5_examples/bin/activate
python -c "import cv2; import numpy; import telegram; print('OK')"
```

---

## Fase 3: Regole udev (Arduino + WiFi)

Le regole udev creano il symlink `/dev/ttyCAT` per l'Arduino e disabilitano il power saving WiFi.

```bash
# Copia tutte le regole udev
sudo cp system-config/udev/99-arduino.rules /etc/udev/rules.d/
sudo cp system-config/udev/99-cat-window.rules /etc/udev/rules.d/
sudo cp system-config/udev/99-usb-serial.rules /etc/udev/rules.d/
sudo cp system-config/udev/70-wifi-powersave.rules /etc/udev/rules.d/

# Ricarica regole
sudo udevadm control --reload-rules
sudo udevadm trigger
```

### Verifica
Collega l'Arduino via USB e verifica:
```bash
ls -la /dev/ttyCAT
# Deve puntare a /dev/ttyUSB0 o /dev/ttyACM0
```

### Note sulle regole udev

Le regole supportano due tipi di chip USB-seriale:
- **Arduino Mega 2560 originale** (vendor `2341`, product `0042`) - in `99-arduino.rules`
- **Chip CH340** clone (vendor `1a86`, product `7523`) - in `99-cat-window.rules` e `99-usb-serial.rules`

Se il tuo Arduino usa un chip diverso, identifica vendor/product con:
```bash
udevadm info -a /dev/ttyUSB0 | grep -E "idVendor|idProduct"
```

---

## Fase 4: Watchdog Hardware

Il watchdog resetta automaticamente il Raspberry Pi se il kernel si blocca (es. freeze driver Hailo).

### 4a. Installa e configura watchdog
```bash
sudo apt install watchdog

# Copia configurazione
sudo cp system-config/watchdog/watchdog.conf /etc/watchdog.conf

# Abilita e avvia
sudo systemctl enable watchdog
sudo systemctl start watchdog
```

### 4b. Configura kernel panic su hung tasks
```bash
# Copia configurazione sysctl
sudo cp system-config/sysctl/99-watchdog-panic.conf /etc/sysctl.d/

# Applica subito
sudo sysctl -p /etc/sysctl.d/99-watchdog-panic.conf
```

### Verifica
```bash
sudo systemctl status watchdog
sysctl kernel.hung_task_panic kernel.panic
# Output atteso: kernel.hung_task_panic = 1, kernel.panic = 10
```

---

## Fase 5: MQTT Broker (Mosquitto)

Necessario per l'integrazione con il sistema alimentazione ESP32.

```bash
sudo apt install mosquitto mosquitto-clients

# Copia configurazione
sudo cp system-config/mosquitto/catfeeder.conf /etc/mosquitto/conf.d/

# Riavvia
sudo systemctl enable mosquitto
sudo systemctl restart mosquitto
```

### Verifica
```bash
# In un terminale:
mosquitto_sub -t "test/topic"
# In un altro terminale:
mosquitto_pub -t "test/topic" -m "hello"
# Il primo terminale deve mostrare "hello"
```

---

## Fase 6: Configurazione Applicazione

### 6a. File di configurazione
```bash
cd /home/pi/hailo-rpi5-examples/basic_pipelines

# Copia template e personalizza
cp cat_config.example.py cat_config.py
nano cat_config.py
```

Parametri da configurare in `cat_config.py`:
| Parametro | Descrizione | Esempio |
|-----------|-------------|---------|
| `TELEGRAM_TOKEN` | Token bot da @BotFather | `"7435601846:AAF..."` |
| `TELEGRAM_CHAT_ID` | Chat ID (negativo per gruppi) | `"-100123456789"` |
| `WINDOW_CLOSED_ANGLE` | Angolo servo finestra chiusa | `77` |
| `WINDOW_OPEN_ANGLE` | Angolo servo finestra aperta | `130` |

### 6b. Creazione bot Telegram
1. Apri [@BotFather](https://t.me/botfather) su Telegram
2. Invia `/newbot` e segui le istruzioni
3. Salva il token ricevuto
4. Per ottenere il chat ID, invia un messaggio al bot e visita:
   ```
   https://api.telegram.org/bot<TOKEN>/getUpdates
   ```
5. Per gruppi: aggiungi il bot al gruppo e usa il chat ID negativo

---

## Fase 7: Firmware Arduino

### 7a. Flash firmware
Il firmware per l'ATMEGA2560 si trova in [cpp/Firmware_Arduino/](cpp/Firmware_Arduino/).

Con Arduino IDE:
1. Apri `cpp/Firmware_Arduino/Firmware_Arduino.ino`
2. Seleziona Board: "Arduino Mega 2560"
3. Seleziona porta: `/dev/ttyCAT` o `/dev/ttyUSB0`
4. Carica

Oppure con firmware pre-compilato:
```bash
avrdude -p m2560 -c wiring -P /dev/ttyCAT -b 115200 \
  -U flash:w:20250118_ATMEGA2560SERVO_FINESTRA.ino.hex:i
```

### 7b. Verifica comunicazione Modbus
```bash
source venv_hailo_rpi5_examples/bin/activate
python basic_pipelines/cat_window.py status
# Deve mostrare gli angoli correnti dei servo
```

---

## Fase 8: Hailo Health Monitor (cron)

Lo script monitora temperatura Hailo e stato del processo ogni 5 minuti.

```bash
# Copia lo script monitor
cp basic_pipelines/scripts/hailo-monitor.sh /home/pi/hailo-monitor.sh
chmod +x /home/pi/hailo-monitor.sh

# Crea il log file
sudo touch /var/log/hailo-monitor.log
sudo chown pi:pi /var/log/hailo-monitor.log

# Aggiungi cron job
(crontab -l 2>/dev/null; echo "*/5 * * * * /home/pi/hailo-monitor.sh") | sort -u | crontab -
```

### Verifica
```bash
/home/pi/hailo-monitor.sh
cat /var/log/hailo-monitor.log
# Output: [timestamp] Temp: XXC | Load: ... | Detection: STOPPED
```

---

## Fase 9: Servizio systemd

Il servizio gestisce l'avvio automatico e il restart dell'applicazione.

```bash
# Copia service file
sudo cp basic_pipelines/scripts/cat-window.service /etc/systemd/system/

# Reload, abilita e avvia
sudo systemctl daemon-reload
sudo systemctl enable cat-window
sudo systemctl start cat-window
```

### Verifica
```bash
# Stato servizio
sudo systemctl status cat-window

# Log in tempo reale
journalctl -u cat-window -f

# Deve mostrare: Active: active (running)
# E nei log: frame processing, FPS, RTSP, Telegram HTTP requests
```

---

## Fase 10: Verifica Completa

### Checklist post-installazione

```bash
# 1. Hailo AI funzionante
hailortcli fw-control identify

# 2. Camera USB riconosciuta
v4l2-ctl --list-devices

# 3. Arduino collegato
ls -la /dev/ttyCAT

# 4. Servizio in esecuzione
systemctl is-active cat-window

# 5. Watchdog attivo
systemctl is-active watchdog

# 6. MQTT funzionante
systemctl is-active mosquitto

# 7. Cron monitor attivo
crontab -l | grep hailo

# 8. Temperatura Hailo OK
cat /sys/class/hwmon/hwmon*/temp*_input | awk '{print $1/1000 "C"}'

# 9. Log applicazione
journalctl -u cat-window --since "5 min ago" --no-pager | tail -5

# 10. Bot Telegram risponde
# Invia /status al bot su Telegram
```

---

## Struttura File di Sistema

Riepilogo di tutti i file che vengono installati fuori dal repository:

```
/etc/systemd/system/
  cat-window.service            ← basic_pipelines/scripts/cat-window.service

/etc/udev/rules.d/
  70-wifi-powersave.rules       ← system-config/udev/70-wifi-powersave.rules
  99-arduino.rules              ← system-config/udev/99-arduino.rules
  99-cat-window.rules           ← system-config/udev/99-cat-window.rules
  99-usb-serial.rules           ← system-config/udev/99-usb-serial.rules

/etc/watchdog.conf              ← system-config/watchdog/watchdog.conf

/etc/sysctl.d/
  99-watchdog-panic.conf        ← system-config/sysctl/99-watchdog-panic.conf

/etc/mosquitto/conf.d/
  catfeeder.conf                ← system-config/mosquitto/catfeeder.conf

/home/pi/hailo-monitor.sh       ← basic_pipelines/scripts/hailo-monitor.sh

crontab (user pi):
  */5 * * * * /home/pi/hailo-monitor.sh
```

---

## Troubleshooting

Vedi [basic_pipelines/README.md](basic_pipelines/README.md#-troubleshooting) per la guida completa.

### Problemi comuni post-deployment

| Problema | Causa | Soluzione |
|----------|-------|-----------|
| `/dev/ttyCAT` non esiste | Arduino non collegato o regole udev mancanti | Controlla USB, ricarica udev rules |
| Servizio non si avvia | Hailo non pronto o venv mancante | Controlla `journalctl -u cat-window` |
| Bot Telegram non risponde | Token errato o rete assente | Verifica `cat_config.py` e connessione |
| FPS basso (<10) | PCIe Gen2 o temperatura alta | Verifica PCIe Gen3, controlla temperatura |
| Servizio non si riavvia | Restart policy errata | Deve essere `Restart=always` nel service file |
| Freeze sistema | Driver Hailo bloccato | Il watchdog dovrebbe riavviare automaticamente |
