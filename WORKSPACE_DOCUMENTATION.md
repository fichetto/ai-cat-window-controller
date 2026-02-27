# Documentazione Workspace: Hailo-RPi5-Examples

Questo documento elenca tutti i file del progetto con descrizioni dettagliate delle loro funzionalità per facilitare la navigazione e le modifiche future.

---

## Panoramica del Progetto

**AI Cat Window Controller** - Sistema avanzato di rilevamento gatti con acceleratore AI Hailo su Raspberry Pi 5. Include controllo automatico finestra motorizzata, integrazione Telegram, e sistema di alimentazione intelligente.

---

## Struttura Directory

```
hailo-rpi5-examples/
├── basic_pipelines/          # Applicazione principale e pipeline
│   ├── scripts/              # Script di avvio e monitoraggio
│   └── backup_unused/        # File di backup non utilizzati
├── cpp/                      # Firmware Arduino
│   └── Firmware_Arduino/     # Codice sorgente servo controller
├── resources/                # Modelli HEF e configurazioni
├── doc/                      # Documentazione installazione
├── tests/                    # Test suite
├── community_projects/       # Progetti della community
├── detected_cats/            # Immagini catturate automaticamente
├── named_cats/               # Dataset gatti identificati
└── dataset/                  # Split train/val/test per ML
```

---

## File Root Directory

| File | Descrizione |
|------|-------------|
| `README.md` | Documentazione principale del progetto |
| `requirements.txt` | Dipendenze Python globali (numpy, opencv, setproctitle) |
| `install.sh` | Script installazione automatica |
| `download_resources.sh` | Download modelli HEF e binari post-processing |
| `compile_postprocess.sh` | Compilazione librerie C++ post-processing |
| `setup_env.sh` | Symlink a `basic_pipelines/setup_env.sh` |
| `LICENSE` | Licenza MIT |

### File Dati e Configurazione

| File | Descrizione |
|------|-------------|
| `cats_database.json` | Database JSON dei gatti rilevati/nominati con foto |
| `cat_window_state.json` | Stato attuale finestra (modo manuale/auto, posizione) |
| `cat_classifier.h5` | Modello Keras (33.9 MB) per classificazione gatti individuali |
| `system_stats.json` | Statistiche sistema e uptime |

### Firmware

| File | Descrizione |
|------|-------------|
| `20250118_ATMEGA2560SERVO_FINESTRA.ino.hex` | Firmware Arduino compilato per servo controller |

---

## Basic Pipelines - Applicazione Principale

### File Core del Cat Window Controller

| File | Descrizione | Funzionalità Chiave |
|------|-------------|---------------------|
| [headless_detection.py](basic_pipelines/headless_detection.py) | **Entry point principale** dell'applicazione headless | Lancia pipeline GStreamer, gestisce memory leak (limite 1.2GB), integra detector/controller/Telegram, salva/carica stato finestra |
| [cat_detector_callback.py](basic_pipelines/cat_detector_callback.py) | Callback rilevamento gatti | Classe `HeadlessCatDetectorCallback`, filtro temporale 5s, soglie adattive (0.8 chiuso/0.7 aperto), logica posizione sinistra=entrata/destra=foto, cooldown 30s cattura immagini |
| [window_controller.py](basic_pipelines/window_controller.py) | Controller hardware servo finestra | Classe `WindowController`, comandi: `apri`, `chiudi`, `finestra`, `sblocca`/`blocca`, threading lock, cooldown 5s, switch modo manuale/automatico |
| [cat_window.py](basic_pipelines/cat_window.py) | CLI controllo manuale finestra | Comunicazione Modbus diretta via `/dev/ttyCAT`, funzioni `set_window_angle()`, `set_lock_angle()`, verifica completamento movimento |
| [cat_config.py](basic_pipelines/cat_config.py) | Configurazione attiva con credenziali | Token bot Telegram, chat ID, angoli finestra (77° chiuso, 130° aperto), soglie rilevamento, directory immagini |
| [cat_config.example.py](basic_pipelines/cat_config.example.py) | Template configurazione | Esempio per setup sicuro credenziali |

### Integrazione Telegram

| File | Descrizione | Funzionalità Chiave |
|------|-------------|---------------------|
| [telegram_base.py](basic_pipelines/telegram_base.py) | Fondazione bot Telegram | Classe `TelegramBase`, inizializzazione bot in thread separato, watchdog heartbeat ogni 5 min, coda retry con backoff esponenziale, restart dopo 15 min timeout |
| [telegram_commands.py](basic_pipelines/telegram_commands.py) | Gestione comandi | Classe mixin `TelegramCommands`, comandi: `/start`, `/apri`, `/chiudi`, `/status`, `/auto`, `/manuale`, `/foto`, `/gatti`, `/classifica`, `/registra`, retry logic 3 tentativi |
| [telegram_notifications.py](basic_pipelines/telegram_notifications.py) | Sistema notifiche | Classe mixin `TelegramNotifications`, notifiche startup/shutdown, aggiornamenti stato finestra, alert rilevamento gatti con foto e confidence |
| [telegram_handler.py](basic_pipelines/telegram_handler.py) | Orchestratore Telegram integrato | Classe `TelegramHandler` che eredita da Base, Commands, Notifications, statistiche sistema, gestione cattura foto |

### Database e Sistema Alimentazione

| File | Descrizione | Funzionalità Chiave |
|------|-------------|---------------------|
| [cat_database.py](basic_pipelines/cat_database.py) | Database SQLite gestione gatti | Classe `CatDatabase`, tabelle: `cats`, `weight_readings`, `system_events`, `cat_photos`, metodi identificazione peso, statistiche alimentazione |
| [cat_feeding_manager.py](basic_pipelines/cat_feeding_manager.py) | Controller sistema alimentazione MQTT | Classe `CatFeedingManager`, integrazione ESP32, topic MQTT peso/rilevamento/foto/dispensazione, identificazione gatto per peso |
| [cat_feeding_system_architecture.md](basic_pipelines/cat_feeding_system_architecture.md) | Documentazione architettura | Design sistema, specifiche hardware, schema MQTT, schema database |

### Pipeline Base ed Esempi

| File | Descrizione | Funzionalità Chiave |
|------|-------------|---------------------|
| [hailo_rpi_common.py](basic_pipelines/hailo_rpi_common.py) | **Libreria utility fondamentale** (588 righe) | Classe `app_callback_class`, `GStreamerApp`, builder pipeline (`SOURCE_PIPELINE`, `INFERENCE_PIPELINE`, `DISPLAY_PIPELINE`), conversione buffer numpy, rilevamento architettura Hailo |
| [detection.py](basic_pipelines/detection.py) | Esempio rilevamento oggetti | Demo callback con YOLOv8, filtraggio per classe "person" |
| [detection_pipeline.py](basic_pipelines/detection_pipeline.py) | Builder pipeline GStreamer detection | Classe `GStreamerDetectionApp`, auto-detect architettura hailo8/hailo8l, batch size 2, risoluzione 640x640 |
| [pose_estimation.py](basic_pipelines/pose_estimation.py) | Esempio stima pose | Estrazione coordinate occhi da landmark keypoint |
| [pose_estimation_pipeline.py](basic_pipelines/pose_estimation_pipeline.py) | Pipeline GStreamer pose estimation | Configurazione pipeline per modelli pose |
| [instance_segmentation.py](basic_pipelines/instance_segmentation.py) | Esempio segmentazione istanze | Estrazione maschere da rilevamenti |
| [instance_segmentation_pipeline.py](basic_pipelines/instance_segmentation_pipeline.py) | Pipeline GStreamer segmentation | Configurazione pipeline segmentazione |
| [get_usb_camera.py](basic_pipelines/get_usb_camera.py) | Utility rilevamento camera USB | Lista dispositivi `/dev/videoX`, filtro camera USB |
| [cat_reclassify.py](basic_pipelines/cat_reclassify.py) | GUI Tkinter riclassificazione dataset | App interattiva categorizzazione immagini, spostamento tra split train/val/test |

### Script di Avvio e Monitoraggio

| File | Descrizione | Funzionalità Chiave |
|------|-------------|---------------------|
| [scripts/start-cat-window.sh](basic_pipelines/scripts/start-cat-window.sh) | **Script avvio principale** (cron @reboot) | Attende connettività internet, attiva ambiente, auto-restart max 10/ora, reset counter dopo 1h stabile |
| [scripts/start-hailo-env.sh](basic_pipelines/scripts/start-hailo-env.sh) | Attivazione ambiente Hailo | Attiva venv e variabili ambiente Hailo |
| [scripts/hailo-monitor.sh](basic_pipelines/scripts/hailo-monitor.sh) | Monitoraggio salute sistema | Check temperatura Hailo ogni 5 min, log stats sistema, alert se >80°C |
| [setup_env.sh](basic_pipelines/setup_env.sh) | Setup ambiente development | Rileva versione TAPPAS, crea/attiva venv, imposta TAPPAS_POST_PROC_DIR |

### Requisiti

| File | Descrizione |
|------|-------------|
| [requirements.txt](basic_pipelines/requirements.txt) | Dipendenze specifiche: numpy==2.0.2, opencv-python==4.10.0.84, pymodbus==3.8.3, python-telegram-bot==21.10 |

---

## Firmware Arduino

| File | Descrizione | Funzionalità Chiave |
|------|-------------|---------------------|
| [cpp/Firmware_Arduino/Firmware_Arduino.ino](cpp/Firmware_Arduino/Firmware_Arduino.ino) | **Controller servo ATMEGA2560** | Canale 0: servo finestra (77-135°), Canale 1: servo serratura (0-90°), driver PCA9685, Modbus RTU 115200 baud, ramping graduale 0.1°/step |

### Registri Modbus Arduino

| Registro | Descrizione |
|----------|-------------|
| 0 | Angolo finestra richiesto × 10 |
| 1 | Angolo finestra corrente × 10 |
| 2 | Angolo serratura richiesto × 10 |
| 3 | Angolo serratura corrente × 10 |

---

## Documentazione

| File | Descrizione |
|------|-------------|
| [doc/basic-pipelines.md](doc/basic-pipelines.md) | Guida uso esempi base, setup camera USB, supporto modelli custom |
| [doc/install-raspberry-pi5.md](doc/install-raspberry-pi5.md) | Guida installazione Hailo SDK |
| [doc/retraining-example.md](doc/retraining-example.md) | Tutorial retraining modelli con Hailo Dataflow Compiler |
| [basic_pipelines/README.md](basic_pipelines/README.md) | Documentazione completa sistema Cat Window |
| [basic_pipelines/ESP32-SETUP-GUIDE.md](basic_pipelines/ESP32-SETUP-GUIDE.md) | Guida setup ESP32 per sistema alimentazione |

---

## Test

| File | Descrizione |
|------|-------------|
| [tests/test_hailo_rpi5_examples.py](tests/test_hailo_rpi5_examples.py) | Test suite principale |
| [tests/test_advanced.py](tests/test_advanced.py) | Test funzionalità avanzate |
| [tests/test_edge_cases.py](tests/test_edge_cases.py) | Test casi limite |
| [tests/test_sanity_check.py](tests/test_sanity_check.py) | Sanity check |
| [tests/run_tests.sh](tests/run_tests.sh) | Script esecuzione test |

---

## Resources

| File | Descrizione |
|------|-------------|
| `resources/yolov5n_seg.json` | Config YOLOv5 Nano segmentazione |
| `resources/yolov5m_seg.json` | Config YOLOv5 Medium segmentazione |
| `resources/barcode-labels.json` | Label custom per modelli retrainati |

---

## Community Projects

| File | Descrizione |
|------|-------------|
| [community_projects/NeoPixel/example.py](community_projects/NeoPixel/example.py) | Esempio LED RGB |
| [community_projects/NeoPixel/follow_detection.py](community_projects/NeoPixel/follow_detection.py) | Controllo LED basato su detection |

---

## Grafo Dipendenze Python

```
headless_detection.py (Entry Point)
├── hailo_rpi_common.py (Pipeline GStreamer, utility)
├── cat_detector_callback.py (Logica rilevamento)
├── window_controller.py (Controllo servo)
├── telegram_handler.py (Orchestrazione Telegram)
│   ├── telegram_base.py (Fondazione bot, watchdog)
│   ├── telegram_commands.py (Processamento comandi)
│   └── telegram_notifications.py (Notifiche)
├── cat_feeding_manager.py (MQTT + alimentazione)
│   └── cat_database.py (SQLite dati gatti)
├── cat_config.py (Configurazione)
└── Librerie Esterne:
    ├── gi.repository (GStreamer)
    ├── hailo (Hailo Python API)
    ├── cv2 (OpenCV)
    ├── numpy (Operazioni array)
    ├── telegram (python-telegram-bot)
    ├── paho.mqtt (Client MQTT)
    ├── sqlite3 (Database)
    └── pymodbus (Modbus seriale)
```

---

## Flusso Dati Sistema

```
Video Input (/dev/video0)
    ↓
[Pipeline GStreamer]
    ↓
[Inferenza AI Hailo - YOLOv11m]
    ↓
[HeadlessCatDetectorCallback]
    ├─→ Filtro Temporale (5s)
    ├─→ Soglia Confidence (0.7-0.8)
    ├─→ Analisi Posizione (sinistra/destra)
    ├─→ Cattura Immagine (se destra + confidence >0.8)
    └─→ State Machine
         ├─→ Apertura Finestra (sinistra + 10s continui)
         └─→ Chiusura Finestra (no detection + 3s)
    ↓
[Window Controller]
    ├─→ subprocess cat_window.py
    ├─→ Comando Modbus seriale
    └─→ Controllo servo Arduino
    ↓
[Telegram Handler]
    ├─→ Invio notifiche
    ├─→ Invio foto gatti
    ├─→ Processamento comandi bot
    └─→ Monitoraggio watchdog
    ↓
[Database/Log]
    ├─→ cat_detector.log
    ├─→ detected_cats/
    ├─→ cats_database.json
    ├─→ system_stats.json
    └─→ SQLite DB (feeding)
```

---

## Specifiche Tecniche

| Componente | Dettagli |
|------------|----------|
| **Acceleratore AI** | Hailo-8L (13 TOPS) o Hailo-8 (26 TOPS) |
| **Modello Detection** | YOLOv11m (33 MB) o YOLOv8s/m |
| **Rate Inferenza** | ~23 FPS (Hailo-8 + YOLOv11m) |
| **Risoluzione Input** | 640×640 RGB |
| **Soglie Confidence** | 0.7-0.8 (adattive) |
| **Finestra Filtro Detection** | 5 secondi |
| **Range Angolare Servo** | Finestra: 77-135°, Serratura: 0-90° |
| **Velocità Movimento** | ~0.1°/10ms = ~4-5 sec corsa completa |
| **Heartbeat Telegram** | 5 minuti (restart se 15 min silenzio) |
| **Limite Memoria** | 1.2GB (auto-restart su overflow) |
| **Alert Temperatura Hailo** | >80°C (monitorato ogni 5 min) |
| **Cooldown Cattura Immagine** | 30 secondi |
| **Broker MQTT** | Mosquitto (locale) |
| **Database** | SQLite3 (cat_feeding.db) |

---

## Comandi Rapidi

### Avvio Manuale Applicazione
```bash
cd /home/pi/hailo-rpi5-examples
source venv_hailo_rpi5_examples/bin/activate
python basic_pipelines/headless_detection.py --input /dev/video0
```

### Controllo Manuale Finestra
```bash
python basic_pipelines/cat_window.py apri      # Apre finestra
python basic_pipelines/cat_window.py chiudi    # Chiude finestra
python basic_pipelines/cat_window.py finestra 100  # Angolo specifico
```

### Comandi Telegram Bot
| Comando | Descrizione |
|---------|-------------|
| `/start` | Avvia interazione bot |
| `/apri` | Apre finestra |
| `/chiudi` | Chiude finestra |
| `/status` | Stato attuale sistema |
| `/auto` | Passa a modo automatico |
| `/manuale` | Passa a modo manuale |
| `/foto` | Scatta foto |
| `/gatti` | Lista gatti nel database |
| `/classifica` | Classifica rilevamenti |

---

*Documento generato automaticamente per facilitare la navigazione del codebase.*
