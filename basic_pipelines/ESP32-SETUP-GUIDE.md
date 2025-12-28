# ESP32 Cat Feeder - Setup Guide

Guida per sviluppare il sistema ESP32 Cat Feeder con due workspace VS Code separati.

## 🏗️ Architettura

```
TUO PC LOCALE:
├── ESP32 collegato via USB
└── ~/Projects/esp32-catfeeder/       ← Workspace locale (PlatformIO)

RASPBERRY PI (SSH):
└── /home/pi/hailo-rpi5-examples/     ← Workspace remoto (Python/Hailo)
    └── basic_pipelines/

Comunicazione: MQTT (ESP32 ↔ Raspberry Pi)
```

## 📥 Step 1: Scarica Template ESP32 sul Tuo PC

Dal tuo PC locale, esegui:

```bash
# Crea cartella Projects
mkdir -p ~/Projects

# Scarica template ESP32 dalla Raspberry
scp -r pi@hailo26.local:/home/pi/esp32-catfeeder-template ~/Projects/esp32-catfeeder

# Verifica
cd ~/Projects/esp32-catfeeder
ls -la
```

Dovresti vedere:
```
esp32-catfeeder/
├── platformio.ini
├── src/
│   └── main.cpp
├── lib/
├── include/
├── test/
└── README.md
```

## 🔧 Step 2: Configura VS Code sul PC

### Installa Estensioni

1. **PlatformIO IDE**
   - Extensions → Cerca "PlatformIO IDE"
   - Installa e riavvia VS Code

2. **C/C++** (Microsoft)
   - Extensions → Cerca "C/C++"
   - Installa

### Apri Progetto ESP32

```bash
# Dal tuo PC
cd ~/Projects/esp32-catfeeder
code .
```

VS Code aprirà il progetto con PlatformIO attivato (vedi icona aliena in basso).

## ⚙️ Step 3: Configura WiFi e MQTT

Modifica `src/main.cpp`:

```cpp
// === CONFIGURA QUI ===
const char* WIFI_SSID = "TuaReteWiFi";          // Il tuo WiFi
const char* WIFI_PASSWORD = "TuaPasswordWiFi";  // Password WiFi

// Raspberry Pi - usa hostname o IP
const char* MQTT_SERVER = "hailo26.local";  // oppure "192.168.1.xxx"
const int MQTT_PORT = 1883;
```

### Come Trovare l'IP della Raspberry

```bash
# Dalla Raspberry Pi (via SSH)
hostname -I

# oppure
ip addr show | grep "inet "
```

## 🔌 Step 4: Collega ESP32

1. Collega ESP32 al PC via USB
2. Identifica la porta:

**Linux/macOS:**
```bash
ls /dev/tty*
# Cerca: /dev/ttyUSB0 o /dev/ttyACM0
```

**Windows:**
- Device Manager → Ports (COM & LPT)
- Cerca: COM3, COM4, etc.

3. Aggiorna `platformio.ini` se necessario:

```ini
upload_port = /dev/ttyUSB0  ; Linux/macOS
; upload_port = COM3         ; Windows (togli il punto e virgola)
```

### Fix Permission (solo Linux)

```bash
# Aggiungi utente al gruppo dialout
sudo usermod -a -G dialout $USER

# Logout e login per applicare
```

## 🚀 Step 5: Compila e Upload

Nel terminale di VS Code (progetto ESP32 aperto):

```bash
# 1. Compila il progetto
pio run

# Dovresti vedere:
# Building in release mode
# ...
# SUCCESS

# 2. Upload su ESP32
pio run -t upload

# Dovresti vedere:
# Configuring upload protocol...
# Writing at 0x00010000... (100%)
# Hash of data verified.

# 3. Monitora output seriale
pio device monitor
```

### Output Atteso

```
ESP32 Cat Feeder System Starting
=================================

Connecting to WiFi: TuaReteWiFi
..
✓ WiFi connected!
IP address: 192.168.1.123

Connecting to MQTT broker...
✓ Connected!
✓ Subscribed to command topics

✓ System ready!
```

## 🧪 Step 6: Test Comunicazione MQTT

### Test 1: ESP32 → Raspberry Pi

L'ESP32 pubblica stato ogni 60 secondi. Sulla Raspberry Pi:

```bash
# Subscribe a tutti i topic dell'ESP32
mosquitto_sub -h localhost -t "catfeeder/#" -v

# Dovresti vedere ogni minuto:
# catfeeder/status {"status":"online","message":"System running",...}
```

### Test 2: Raspberry Pi → ESP32

Dalla Raspberry Pi, invia comando feed:

```bash
# Comando feed manuale
mosquitto_pub -h localhost -t "catfeeder/feed/manual" -m "1"

# L'ESP32 dovrebbe:
# 1. Ricevere il comando
# 2. Attivare il motore
# 3. Pubblicare "catfeeder/feed/complete"
```

Nel monitor seriale ESP32 vedrai:
```
Message arrived [catfeeder/feed/manual]: 1
→ Manual feed command received
🍽 Dispensing 1 portion(s)...
✓ Feed complete!
```

### Test 3: Feed con Porzioni Multiple

```bash
# Feed 2 porzioni
mosquitto_pub -h localhost -t "catfeeder/feed/portion" -m '{"portions": 2}'
```

## 🔄 Workflow di Sviluppo

### Per Lavorare su ESP32:

1. Apri VS Code: `code ~/Projects/esp32-catfeeder`
2. Modifica `src/main.cpp`
3. Compila: `pio run`
4. Upload: `pio run -t upload`
5. Debug: `pio device monitor`

### Per Lavorare su Raspberry Pi:

1. Continua come ora (SSH remoto)
2. Modifica Python normalmente
3. Test: il bot Telegram leggerà da `catfeeder/status`

### I Due Sistemi Comunicano via MQTT:

```
ESP32 (Local)           MQTT Topics              Raspberry Pi (Remote)
─────────────          ───────────────          ──────────────────────
Pubblica →      catfeeder/status         ← Legge (cat_feeding_manager.py)
Pubblica →      catfeeder/feed/complete  ← Legge
Legge    ←      catfeeder/feed/manual    → Pubblica (Telegram bot)
Legge    ←      catfeeder/feed/portion   → Pubblica
```

## 🐛 Troubleshooting

### ESP32 non si connette al WiFi

```
✗ Verifica SSID e password (case sensitive!)
✗ ESP32 supporta solo WiFi 2.4GHz (non 5GHz)
✗ Controlla firewall del router
```

### Upload Failed

```bash
# Prova a tenere premuto BOOT sull'ESP32 durante upload

# Oppure resetta manualmente:
pio run -t upload --upload-port /dev/ttyUSB0

# Verifica driver USB:
# - CH340: https://github.com/WCHSoftGroup/ch341ser_linux
# - CP2102: https://www.silabs.com/developers/usb-to-uart-bridge-vcp-drivers
```

### MQTT non funziona

```bash
# 1. Verifica Raspberry raggiungibile
ping hailo26.local

# 2. Verifica mosquitto attivo
ssh pi@hailo26.local
systemctl status mosquitto

# 3. Verifica porta 1883 aperta
telnet hailo26.local 1883
```

### Monitor Seriale Bloccato

```bash
# Esci con: Ctrl+C

# Riavvia:
pio device monitor
```

## 📝 Comandi Utili PlatformIO

```bash
# Compila
pio run

# Upload
pio run -t upload

# Monitor seriale
pio device monitor

# Clean (forza ricompilazione)
pio run -t clean

# Upload + Monitor in un comando
pio run -t upload && pio device monitor

# Lista porte seriali
pio device list
```

## 🔐 Sicurezza

**NON committare su Git:**
- Password WiFi in `main.cpp`
- Credenziali MQTT (se abiliti autenticazione)

Considera di creare un file separato `src/credentials.h` (già in `.gitignore`):

```cpp
// credentials.h
#define WIFI_SSID "TuaRete"
#define WIFI_PASSWORD "TuaPassword"
#define MQTT_SERVER "hailo26.local"
```

Poi in `main.cpp`:
```cpp
#include "credentials.h"
```

## 📚 Documentazione

- Template completo: `/home/pi/esp32-catfeeder-template/README.md`
- Topics MQTT: Vedi `cat_feeding_manager.py` per i topic usati
- PlatformIO Docs: https://docs.platformio.org/
- ESP32 Arduino: https://docs.espressif.com/projects/arduino-esp32/

## ✅ Checklist Setup Completo

- [ ] Template ESP32 scaricato su PC locale
- [ ] PlatformIO installato in VS Code
- [ ] WiFi e MQTT configurati in `main.cpp`
- [ ] ESP32 collegato via USB
- [ ] `pio run` compila senza errori
- [ ] `pio run -t upload` carica su ESP32
- [ ] ESP32 si connette a WiFi
- [ ] ESP32 si connette a MQTT
- [ ] Test feed da Raspberry Pi funziona
- [ ] Monitor seriale mostra output corretto

## 🎯 Prossimi Passi

1. **Hardware**: Collega motore stepper e driver
2. **Calibrazione**: Regola `STEPS_PER_PORTION` in base al tuo hardware
3. **Sensori**: Aggiungi load cell per misurare porzioni
4. **Test integrato**: Gatto rilevato → Telegram → Feed automatico
5. **Personalizzazione**: Aggiungi LED, buzzer, display, ecc.

---

**Note**: Questa è la configurazione raccomandata. Due workspace separati, comunicazione via MQTT, sviluppo indipendente ma integrato.
