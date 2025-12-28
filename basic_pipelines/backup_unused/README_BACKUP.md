# Backup File Non Utilizzati

Questa cartella contiene file che NON fanno parte del sistema attualmente in esecuzione.

## Sistema Attuale (headless_detection.py)

Il sistema in produzione usa questi file:
- `headless_detection.py` - Main entry point
- `cat_detector_callback.py` - Detection logic
- `cat_config.py` - Configurazione
- `window_controller.py` - Controllo hardware
- `telegram_base.py` - Base bot Telegram
- `telegram_commands.py` - Comandi bot
- `telegram_handler.py` - Handler bot
- `telegram_notifications.py` - Notifiche bot
- `cat_window.py` - Tool CLI standalone

## File in Questa Cartella (backup)

File di un'implementazione alternativa non utilizzata:

- **cat_detector.py** - Sistema alternativo con ROI detection
- **file_manager.py** - File manager (usato solo da cat_detector.py)
- **system_monitor.py** - System monitor (usato solo da cat_detector.py)
- **run_cat_detector.py** - Script avvio alternativo
- **headless_pipeline.py** - Pipeline alternativa

## Note

Questi file sono stati spostati qui il 2025-11-07 per pulire la directory principale.
Possono essere ripristinati se necessario.
