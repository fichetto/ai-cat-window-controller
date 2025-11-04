#!/usr/bin/env python3
"""
Callback handler per il rilevamento dei gatti e la gestione della finestra.
"""

import os
import cv2
import logging
from datetime import datetime, timedelta
from hailo_rpi_common import app_callback_class
from window_controller import WindowController

# Configurazione logging
logger = logging.getLogger(__name__)

class HeadlessCatDetectorCallback(app_callback_class):
    """
    Gestisce la logica di rilevamento dei gatti e il controllo della finestra.
    Implementa una soglia di confidenza adattiva basata sullo stato della finestra.
    """
    
    def __init__(self):
        """Inizializza il detector con configurazione predefinita."""
        super().__init__()
        self.window_controller = WindowController()
        
        # Il gestore Telegram verrà impostato dall'applicazione principale
        self.telegram = None
        
        # Configurazione soglie di confidenza
        self.min_confidence_closed = 0.7  # Soglia quando finestra chiusa
        self.min_confidence_open = 0.5    # Soglia ridotta quando finestra aperta
        
        # Parametri temporali
        self.last_cat_time = None
        self.last_no_cat_time = None
        self.required_detection_time = timedelta(seconds=10)
        self.required_no_detection_time = timedelta(seconds=3)
        
        # Filtro rilevazioni con buffer più lungo per finestra aperta
        self.detection_filter_window = timedelta(seconds=5)
        self.recent_detections = []

        # Configurazione salvataggio immagini
        self.save_dir = "detected_cats"
        self.ensure_save_directory()
        self.last_capture_time = None
        self.capture_cooldown = timedelta(seconds=30)
        self.capture_confidence_threshold = 0.8
        
        logger.info("Headless Cat Detector Callback initialized with adaptive thresholds")

    def ensure_save_directory(self):
        """Crea la directory per il salvataggio delle immagini se non esiste."""
        if not os.path.exists(self.save_dir):
            os.makedirs(self.save_dir, exist_ok=True)
            logger.info(f"Created directory: {self.save_dir}")

    def should_capture_image(self, confidence):
        """
        Determina se è il momento giusto per catturare un'immagine.
        
        Args:
            confidence (float): Confidenza del rilevamento corrente
            
        Returns:
            bool: True se si può catturare l'immagine, False altrimenti
        """
        current_time = datetime.now()
        
        if (self.last_capture_time is None or 
            current_time - self.last_capture_time >= self.capture_cooldown):
            if confidence >= self.capture_confidence_threshold:
                return True
        return False

    def save_cat_image(self, frame, confidence):
        """
        Salva l'immagine del gatto con timestamp e confidenza.
        
        Args:
            frame (numpy.ndarray): Frame video da salvare
            confidence (float): Confidenza del rilevamento
            
        Returns:
            str or None: Percorso del file salvato o None se il salvataggio fallisce
        """
        if not self.should_capture_image(confidence):
            return None

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{self.save_dir}/cat_{timestamp}_conf{confidence:.2f}.jpg"
        
        try:
            cv2.imwrite(filename, frame)
            self.last_capture_time = datetime.now()
            logger.info(f"Cat image saved: {filename} (confidence: {confidence:.2f})")
            return filename
        except Exception as e:
            logger.error(f"Error saving image: {e}")
            return None

    def get_current_confidence_threshold(self):
        """
        Restituisce la soglia di confidenza appropriata in base allo stato della finestra.
        
        Returns:
            float: Soglia di confidenza corrente
        """
        return self.min_confidence_open if self.window_controller.is_window_open else self.min_confidence_closed

    def update_detection_filter(self, cat_detected, current_time):
        """
        Aggiorna il filtro temporale delle rilevazioni.
        
        Args:
            cat_detected (bool): Indica se un gatto è stato rilevato nel frame corrente
            current_time (datetime): Timestamp corrente
            
        Returns:
            bool: True se il gatto è considerato presente dopo il filtraggio
        """
        self.recent_detections = [t for t in self.recent_detections 
                                if current_time - t < self.detection_filter_window]
        if cat_detected:
            self.recent_detections.append(current_time)
        
        return len(self.recent_detections) > 0

    def process_cat_detection(self, frame, max_confidence, filtered_cat_present, current_time):
        """
        Elabora il rilevamento del gatto e gestisce lo stato della finestra.
        
        Args:
            frame (numpy.ndarray): Frame video corrente
            max_confidence (float): Massima confidenza rilevata nel frame
            filtered_cat_present (bool): Indica se il gatto è presente dopo il filtraggio
            current_time (datetime): Timestamp corrente
        """
        # Verifica se il controllo automatico è abilitato
        if not self.window_controller.auto_control_enabled():
            return

        current_threshold = self.get_current_confidence_threshold()

        if filtered_cat_present:
            if self.last_cat_time is None:
                self.last_cat_time = current_time
                logger.info(f"Cat detected with confidence {max_confidence:.2f} " +
                          f"(threshold: {current_threshold:.2f})")
            self.last_no_cat_time = None
            
            cat_present_time = current_time - self.last_cat_time
            if cat_present_time >= self.required_detection_time:
                if self.window_controller.set_window_position(True, manual=False):
                    message = f"Gatto presente da {cat_present_time.seconds}s con confidenza {max_confidence:.2f}"
                    logger.info(f"Opening window - {message}")
                    if self.telegram:
                        self.telegram.send_window_status(True, message)
        else:
            if self.last_no_cat_time is None:
                self.last_no_cat_time = current_time
                logger.info("Cat no longer detected " +
                           f"(using threshold: {current_threshold:.2f})")
            self.last_cat_time = None
            
            if self.last_no_cat_time is not None:
                cat_absent_time = current_time - self.last_no_cat_time
                if cat_absent_time >= self.required_no_detection_time:
                    if self.window_controller.set_window_position(False):
                        message = f"Gatto assente da {cat_absent_time.seconds}s"
                        logger.info(f"Closing window - {message}")
                        if self.telegram:
                            self.telegram.send_window_status(False, message)