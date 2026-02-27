# tapo_config.example.py

"""
Configurazione per il sistema multi-camera Tapo con rilevamento AI.
Copia questo file come tapo_config.py e modifica con i tuoi valori.

Per ottenere l'URL RTSP delle telecamere Tapo:
1. Apri l'app Tapo sul tuo smartphone
2. Seleziona la telecamera
3. Vai in Impostazioni > Avanzate > Camera Account
4. Crea un username e password per l'accesso RTSP
5. L'URL sarà: rtsp://username:password@IP_CAMERA:554/stream1
   - stream1 = alta qualità (1080p)
   - stream2 = bassa qualità (360p) - RACCOMANDATO per AI
"""

# Configurazione Telegram (riusa le stesse credenziali di cat_config.py)
TELEGRAM_CONFIG = {
    'token': 'YOUR_BOT_TOKEN',  # Token del bot Telegram
    'chat_id': '-YOUR_CHAT_ID',  # ID del gruppo (negativo per i gruppi)
}

# Lista telecamere Tapo
# Aggiungi una entry per ogni telecamera
TAPO_CAMERAS = [
    {
        'name': 'Giardino',           # Nome identificativo (usato nelle notifiche)
        'rtsp_url': 'rtsp://user:pass@192.168.1.100:554/stream2',
        'detect_classes': ['cat', 'person'],  # Classi da rilevare
        'enabled': True,              # Abilita/disabilita questa camera
    },
    {
        'name': 'Ingresso',
        'rtsp_url': 'rtsp://user:pass@192.168.1.101:554/stream2',
        'detect_classes': ['person'],  # Solo persone
        'enabled': True,
    },
    {
        'name': 'Cortile',
        'rtsp_url': 'rtsp://user:pass@192.168.1.102:554/stream2',
        'detect_classes': ['cat', 'person', 'dog'],
        'enabled': True,
    },
    {
        'name': 'Garage',
        'rtsp_url': 'rtsp://user:pass@192.168.1.103:554/stream2',
        'detect_classes': ['person', 'car'],  # Persone e veicoli
        'enabled': False,  # Disabilitata
    },
]

# Configurazione rilevamento
DETECTION_CONFIG = {
    'min_confidence': 0.7,              # Confidenza minima per il rilevamento
    'capture_confidence': 0.8,          # Confidenza minima per cattura foto
    'detection_filter_window': 3,       # Finestra filtro temporale (secondi)
}

# Configurazione salvataggio immagini
IMAGE_CONFIG = {
    'save_dir': 'detected_objects',     # Directory principale per il salvataggio
    'capture_cooldown': 30,             # Secondi tra le catture (per camera)
    'create_camera_subdirs': True,      # Crea sottodirectory per ogni camera
}

# Configurazione notifiche
NOTIFICATION_CONFIG = {
    'send_photo': True,                 # Invia foto con la notifica
    'cooldown_per_class': {             # Cooldown notifiche per classe (secondi)
        'cat': 60,                      # Notifica gatti ogni 60 secondi
        'person': 30,                   # Notifica persone ogni 30 secondi
        'dog': 60,
        'car': 120,
    },
    'quiet_hours': {                    # Ore silenziose (nessuna notifica)
        'enabled': False,
        'start': '23:00',
        'end': '07:00',
    },
}

# Classi COCO supportate (per riferimento)
# Le più comuni per sorveglianza:
# 'person', 'cat', 'dog', 'car', 'motorcycle', 'bicycle', 'truck', 'bird'
