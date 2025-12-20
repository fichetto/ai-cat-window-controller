# Multi-Root Workspace Setup Guide

## 📋 Cosa Abbiamo Creato

Un workspace VS Code che gestisce **due progetti separati**:

1. **🖥️ Raspberry Pi (Hailo Detection)** - Connessione remota SSH
2. **🔌 ESP32 (Cat Feeder)** - Progetto locale sul tuo PC

## 🚀 Setup dal Tuo PC Locale

### Step 1: Scarica il Template ESP32

Dal tuo PC locale, scarica la cartella template:

```bash
# Crea la cartella Projects se non esiste
mkdir -p ~/Projects

# Scarica il template ESP32 dalla Raspberry Pi
scp -r pi@hailo26.local:/home/pi/esp32-catfeeder-template ~/Projects/esp32-catfeeder

# Scarica anche il workspace file
scp pi@hailo26.local:/home/pi/hailo-rpi5-examples/cat-feeding-system.code-workspace ~/Projects/
```

### Step 2: Installa Estensioni VS Code

Assicurati di avere installato:

1. **PlatformIO IDE** - Per ESP32
   - Apri VS Code
   - Extensions → Cerca "PlatformIO IDE"
   - Installa e riavvia VS Code

2. **Remote - SSH** (già installata)
   - Per la connessione alla Raspberry Pi

3. **C/C++** (per ESP32)
   - Extensions → Cerca "C/C++"
   - Installa "C/C++" di Microsoft

### Step 3: Configura WiFi dell'ESP32

Modifica `~/Projects/esp32-catfeeder/src/main.cpp`:

```cpp
// Sostituisci con le tue credenziali
const char* WIFI_SSID = "TuaReteWiFi";
const char* WIFI_PASSWORD = "TuaPasswordWiFi";

// Verifica l'indirizzo della Raspberry Pi
const char* MQTT_SERVER = "hailo26.local";  // o usa l'IP: "192.168.1.xxx"
```

### Step 4: Apri il Workspace

```bash
# Dal tuo PC locale
cd ~/Projects
code cat-feeding-system.code-workspace
```

VS Code aprirà **entrambi i progetti** in una singola finestra!

## 🎯 Come Usare il Workspace

### Vista Esploratore

Vedrai due cartelle nella sidebar:

```
🖥️ Raspberry Pi - Hailo Detection
  └── (files della RPi via SSH)

🔌 ESP32 - Cat Feeder
  └── (files locali ESP32)
```

### Terminali Separati

Puoi aprire terminali separati per ciascun progetto:

1. **Terminale RPi**: Clicca su "🖥️ Raspberry Pi" → Nuovo Terminale
   - Connesso via SSH alla Raspberry
   - Usa per: modifiche Python, git, debugging

2. **Terminale ESP32**: Clicca su "🔌 ESP32" → Nuovo Terminale
   - Terminale locale del tuo PC
   - Usa per: `pio run`, `pio upload`, ecc.

### Workflow Tipico

#### Per modificare codice Raspberry Pi:

1. Seleziona file in "🖥️ Raspberry Pi - Hailo Detection"
2. Modifica normalmente
3. Salva (il file si aggiorna sulla RPi via SSH)
4. Testa: apri terminale RPi e esegui

#### Per programmare ESP32:

1. Collega ESP32 via USB al tuo PC
2. Seleziona file in "🔌 ESP32 - Cat Feeder"
3. Modifica codice
4. Apri terminale ESP32:
   ```bash
   # Compila
   pio run

   # Upload su ESP32
   pio run -t upload

   # Monitora output seriale
   pio device monitor
   ```

## 🔧 Verifica Setup ESP32

### Test 1: Identifica Porta USB

```bash
# Linux/macOS
ls /dev/tty*

# Windows
# Usa Device Manager per vedere la porta COM
```

Aggiorna `platformio.ini` con la porta corretta:
```ini
upload_port = /dev/ttyUSB0  ; Linux/macOS
; upload_port = COM3         ; Windows
```

### Test 2: Build Iniziale

```bash
cd ~/Projects/esp32-catfeeder
pio run
```

Dovresti vedere:
```
Building in release mode
...
SUCCESS
```

### Test 3: Upload Test

```bash
# Collega ESP32 via USB
pio run -t upload
```

### Test 4: Monitor Seriale

```bash
pio device monitor
```

Dovresti vedere:
```
ESP32 Cat Feeder System Starting
Connecting to WiFi: TuaReteWiFi
✓ WiFi connected!
IP address: 192.168.1.xxx
✓ MQTT Connected!
```

## 🐛 Troubleshooting

### Problema: "Permission denied" su porta USB (Linux)

```bash
# Aggiungi il tuo utente al gruppo dialout
sudo usermod -a -G dialout $USER

# Logout e login per applicare
```

### Problema: ESP32 non trovato

1. Verifica che il cavo USB supporti dati (non solo ricarica)
2. Prova un'altra porta USB
3. Installa driver CH340/CP2102 se necessario

### Problema: MQTT non si connette

1. Verifica che Raspberry Pi sia raggiungibile:
   ```bash
   ping hailo26.local
   ```

2. Verifica mosquitto sulla RPi:
   ```bash
   ssh pi@hailo26.local
   systemctl status mosquitto
   ```

3. Test MQTT manualmente:
   ```bash
   # Da RPi, subscribe
   mosquitto_sub -h localhost -t "catfeeder/#" -v

   # Da ESP32, dovrebbe pubblicare su catfeeder/status
   ```

## ✅ Checklist Post-Setup

- [ ] VS Code apre il workspace con entrambi i progetti
- [ ] PlatformIO riconosce ESP32 (vedi barra in basso)
- [ ] `pio run` compila senza errori
- [ ] ESP32 si connette a WiFi
- [ ] ESP32 si connette a MQTT
- [ ] Raspberry Pi è accessibile via SSH nel workspace

## 📝 Prossimi Passi

1. **Configura hardware**: Collega motore, sensori
2. **Calibra motore**: Ajusta `STEPS_PER_PORTION`
3. **Test integrazione**: Invia comandi da Raspberry Pi
4. **Personalizza**: Aggiungi funzionalità specifiche

## 🔒 Sicurezza

**IMPORTANTE**: Non committare mai su Git:
- `src/credentials.h` (se lo crei)
- Password WiFi
- Configurazioni private

Il file `.gitignore` è già configurato per proteggerti.

## 📚 Risorse

- [PlatformIO Docs](https://docs.platformio.org/)
- [ESP32 Arduino Core](https://docs.espressif.com/projects/arduino-esp32/)
- [MQTT Protocol](https://mqtt.org/)
- [ArduinoJson](https://arduinojson.org/)

## 🆘 Serve Aiuto?

Se qualcosa non funziona:
1. Controlla i log seriali: `pio device monitor`
2. Verifica connessioni hardware
3. Testa MQTT manualmente con `mosquitto_pub/sub`
