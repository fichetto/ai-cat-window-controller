#!/usr/bin/env python3
"""
Callback handler per il rilevamento multi-classe su telecamere Tapo.
Supporta rilevamento di gatti, persone, e altre classi COCO.
"""

import os
import cv2
import logging
from datetime import datetime, timedelta
from hailo_rpi_common import app_callback_class

# Configurazione logging
logger = logging.getLogger(__name__)


class TapoDetectorCallback(app_callback_class):
    """
    Gestisce la logica di rilevamento multi-classe per telecamere Tapo RTSP.
    """

    def __init__(self, camera_name, detect_classes, config=None):
        """
        Inizializza il detector per una specifica telecamera.

        Args:
            camera_name (str): Nome identificativo della telecamera
            detect_classes (list): Lista di classi da rilevare (es. ['cat', 'person'])
            config (dict): Configurazione opzionale
        """
        super().__init__()

        self.camera_name = camera_name
        self.detect_classes = set(detect_classes)  # Set per lookup veloce

        # Configurazione di default
        self.min_confidence = 0.7
        self.capture_confidence = 0.8
        self.detection_filter_window = timedelta(seconds=3)

        # Applica configurazione personalizzata
        if config:
            self.min_confidence = config.get('min_confidence', self.min_confidence)
            self.capture_confidence = config.get('capture_confidence', self.capture_confidence)
            filter_seconds = config.get('detection_filter_window', 3)
            self.detection_filter_window = timedelta(seconds=filter_seconds)

        # Telegram handler (verrà impostato dall'applicazione principale)
        self.telegram = None

        # Configurazione salvataggio immagini
        self.save_dir = "detected_objects"
        self.capture_cooldown = timedelta(seconds=60)

        # Tracking cooldown per classe
        self.last_capture_time = {}  # {class_name: datetime}
        self.last_notification_time = {}  # {class_name: datetime}
        self.notification_cooldown = {
            'cat': timedelta(seconds=60),
            'person': timedelta(seconds=60),
            'dog': timedelta(seconds=60),
            'car': timedelta(seconds=120),
        }
        self.default_notification_cooldown = timedelta(seconds=60)

        # Filtro temporale rilevazioni per classe
        self.recent_detections = {}  # {class_name: [timestamps]}

        # Statistiche
        self.detection_count = {}  # {class_name: count}

        # Crea directory di salvataggio
        self.ensure_save_directory()

        logger.info(f"[{self.camera_name}] TapoDetectorCallback initialized - "
                   f"Classes: {self.detect_classes}, Min confidence: {self.min_confidence}")

    def ensure_save_directory(self):
        """Crea la directory per il salvataggio delle immagini se non esiste."""
        camera_dir = os.path.join(self.save_dir, self.camera_name.lower().replace(' ', '_'))
        if not os.path.exists(camera_dir):
            os.makedirs(camera_dir, exist_ok=True)
            logger.info(f"[{self.camera_name}] Created directory: {camera_dir}")
        self.camera_save_dir = camera_dir

    def should_detect_class(self, label):
        """
        Verifica se la classe rilevata è tra quelle da monitorare.

        Args:
            label (str): Label della classe rilevata

        Returns:
            bool: True se la classe deve essere processata
        """
        return label in self.detect_classes

    def update_detection_filter(self, class_name, current_time):
        """
        Aggiorna il filtro temporale delle rilevazioni per una classe.

        Args:
            class_name (str): Nome della classe rilevata
            current_time (datetime): Timestamp corrente

        Returns:
            bool: True se l'oggetto è considerato presente (rilevazione stabile)
        """
        if class_name not in self.recent_detections:
            self.recent_detections[class_name] = []

        # Rimuovi rilevazioni vecchie
        self.recent_detections[class_name] = [
            t for t in self.recent_detections[class_name]
            if current_time - t < self.detection_filter_window
        ]

        # Aggiungi nuova rilevazione
        self.recent_detections[class_name].append(current_time)

        return len(self.recent_detections[class_name]) > 0

    def should_capture_image(self, class_name, confidence):
        """
        Determina se è il momento giusto per catturare un'immagine.

        Args:
            class_name (str): Nome della classe
            confidence (float): Confidenza del rilevamento

        Returns:
            bool: True se si può catturare l'immagine
        """
        if confidence < self.capture_confidence:
            return False

        current_time = datetime.now()
        last_capture = self.last_capture_time.get(class_name)

        if last_capture is None or current_time - last_capture >= self.capture_cooldown:
            return True
        return False

    def should_send_notification(self, class_name):
        """
        Determina se è il momento di inviare una notifica.

        Args:
            class_name (str): Nome della classe

        Returns:
            bool: True se si può inviare notifica
        """
        current_time = datetime.now()
        last_notification = self.last_notification_time.get(class_name)
        cooldown = self.notification_cooldown.get(class_name, self.default_notification_cooldown)

        if last_notification is None or current_time - last_notification >= cooldown:
            return True
        return False

    def save_detection_image(self, frame, class_name, confidence):
        """
        Salva l'immagine del rilevamento.

        Args:
            frame (numpy.ndarray): Frame video da salvare
            class_name (str): Nome della classe rilevata
            confidence (float): Confidenza del rilevamento

        Returns:
            str or None: Percorso del file salvato o None se fallisce
        """
        if not self.should_capture_image(class_name, confidence):
            return None

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{self.camera_save_dir}/{class_name}_{timestamp}_conf{confidence:.2f}.jpg"

        try:
            cv2.imwrite(filename, frame)
            self.last_capture_time[class_name] = datetime.now()
            logger.info(f"[{self.camera_name}] Image saved: {filename}")
            return filename
        except Exception as e:
            logger.error(f"[{self.camera_name}] Error saving image: {e}")
            return None

    def get_class_emoji(self, class_name):
        """Restituisce l'emoji appropriata per la classe."""
        emoji_map = {
            'cat': '🐱',
            'person': '👤',
            'dog': '🐕',
            'car': '🚗',
            'truck': '🚚',
            'motorcycle': '🏍️',
            'bicycle': '🚲',
            'bird': '🐦',
        }
        return emoji_map.get(class_name, '📦')

    def process_detections(self, detections_info, frame, current_time):
        """
        Processa le rilevazioni e gestisce notifiche/salvataggio.

        Args:
            detections_info (list): Lista di dict con info rilevazioni
                [{'label': str, 'confidence': float, 'bbox': tuple}, ...]
            frame (numpy.ndarray): Frame video corrente
            current_time (datetime): Timestamp corrente

        Returns:
            list: Lista di rilevazioni processate da notificare
        """
        notifications_to_send = []

        # Raggruppa rilevazioni per classe
        detections_by_class = {}
        for det in detections_info:
            label = det['label']
            if self.should_detect_class(label):
                if label not in detections_by_class:
                    detections_by_class[label] = []
                detections_by_class[label].append(det)

        # Processa ogni classe
        for class_name, class_detections in detections_by_class.items():
            # Prendi il migliore (maggiore confidence)
            best_detection = max(class_detections, key=lambda x: x['confidence'])
            confidence = best_detection['confidence']

            if confidence < self.min_confidence:
                continue

            # Aggiorna filtro temporale
            is_stable = self.update_detection_filter(class_name, current_time)

            if is_stable:
                # Aggiorna statistiche
                self.detection_count[class_name] = self.detection_count.get(class_name, 0) + 1

                # Salva immagine
                saved_path = self.save_detection_image(frame, class_name, confidence)

                # Prepara notifica
                if self.should_send_notification(class_name):
                    self.last_notification_time[class_name] = current_time
                    notifications_to_send.append({
                        'class_name': class_name,
                        'confidence': confidence,
                        'count': len(class_detections),
                        'image_path': saved_path,
                        'emoji': self.get_class_emoji(class_name),
                    })

        return notifications_to_send

    def send_telegram_notification(self, notification):
        """
        Invia notifica Telegram per un rilevamento.

        Args:
            notification (dict): Dati della notifica
        """
        if not self.telegram:
            return

        emoji = notification['emoji']
        class_name = notification['class_name']
        confidence = notification['confidence']
        count = notification['count']
        image_path = notification.get('image_path')

        # Costruisci messaggio
        time_str = datetime.now().strftime("%H:%M:%S")
        message = f"📷 [{self.camera_name}] - Rilevamento\n"
        message += f"{emoji} {class_name.capitalize()}"
        if count > 1:
            message += f" (x{count})"
        message += f" - conf: {confidence:.2f}\n"
        message += f"🕐 {time_str}"

        # Invia con o senza foto
        if image_path and os.path.exists(image_path):
            self.telegram.send_photo(image_path, caption=message)
        else:
            self.telegram.send_message(message)

        logger.info(f"[{self.camera_name}] Notification sent: {class_name} ({confidence:.2f})")

    def get_stats(self):
        """
        Restituisce statistiche di rilevamento.

        Returns:
            dict: Statistiche per questa camera
        """
        return {
            'camera_name': self.camera_name,
            'detect_classes': list(self.detect_classes),
            'frame_count': self.frame_count,
            'detection_count': dict(self.detection_count),
        }
