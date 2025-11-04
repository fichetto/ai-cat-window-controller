"""
Modulo di rilevamento gatti headless con integrazione migliorata
del bot Telegram, gestione degli errori e monitoraggio del sistema.
"""

import os
import cv2
import gi
import numpy as np
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Tuple

gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib

# Importa i moduli personalizzati
from file_manager import FileManager
from system_monitor import SystemMonitor
from telegram_handler import TelegramHandler
from window_controller import WindowController
from cat_config import DETECTION_CONFIG, WINDOW_CONFIG

# Importa i moduli Hailo
import hailo
from hailo_rpi_common import (
    get_caps_from_pad,
    get_numpy_from_buffer,
)

# Configurazione del logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("cat_detector.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class CatDetectorApp:
    """
    Applicazione di rilevamento gatti headless con supporto per
    Telegram, controllo finestra e monitoraggio del sistema.
    """
    
    def __init__(self, 
                 input_source: str = '/dev/video0',
                 hef_path: str = '../resources/yolov8m.hef',
                 post_process_so: str = '../resources/libyolo_hailortpp_postprocess.so'):
        """
        Inizializza l'applicazione di rilevamento gatti.
        
        Args:
            input_source: Sorgente video (ad es. /dev/video0)
            hef_path: Percorso del file HEF
            post_process_so: Percorso del file di post-processing
        """
        # Inizializza GStreamer
        Gst.init(None)
        
        # Parametri di input
        self.input_source = input_source
        self.hef_path = self._get_absolute_path(hef_path)
        self.post_process_so = self._get_absolute_path(post_process_so)
        
        # Pipeline GStreamer
        self.pipeline = None
        self.mainloop = None
        
        # Stato rilevamento
        self.current_detection_time = None
        self.current_no_detection_time = None
        self.recent_detections = []
        self.detection_filter_window = timedelta(seconds=DETECTION_CONFIG.get('detection_filter_window', 3))
        self.required_detection_time = timedelta(seconds=DETECTION_CONFIG.get('required_detection_time', 10))
        self.required_no_detection_time = timedelta(seconds=DETECTION_CONFIG.get('required_no_detection_time', 3))
        self.min_confidence = DETECTION_CONFIG.get('min_confidence', 0.7)
        
        # Confini ROI
        self.left_boundary = DETECTION_CONFIG.get('left_boundary', 0.4)
        self.right_boundary = DETECTION_CONFIG.get('right_boundary', 0.6)
        
        # Stato del sistema
        self.running = False
        self.error_count = 0
        self.last_error_time = None
        
        # Inizializza i componenti
        logger.info("Initializing system components...")
        self.initialize_components()
        
        logger.info("Cat detector initialization complete")
    
    def _get_absolute_path(self, path):
        """Converte un percorso relativo in assoluto."""
        if path.startswith('..') or path.startswith('./'):
            script_dir = os.path.dirname(os.path.abspath(__file__))
            return os.path.abspath(os.path.join(script_dir, path))
        return path
    
    def initialize_components(self):
        """Inizializza tutti i componenti del sistema."""
        try:
            # Inizializza il controller della finestra
            self.window_controller = WindowController()
            logger.info("Window controller initialized")
            
            # Inizializza il gestore file
            self.file_manager = FileManager()
            logger.info("File manager initialized")
            
            # Inizializza il monitor di sistema
            self.system_monitor = SystemMonitor()
            logger.info("System monitor initialized")
            
            # Inizializza il gestore Telegram
            self.telegram = TelegramHandler()
            self.telegram.window_controller = self.window_controller
            self.telegram.set_detector(self)
            logger.info("Telegram handler initialized")
            
            # Verifica che i file necessari esistano
            self._check_required_files()
        except Exception as e:
            logger.critical(f"Failed to initialize components: {e}")
            self.error_count += 1
            self.last_error_time = datetime.now()
            if hasattr(self, 'telegram'):
                self.telegram.send_error_notification(f"Inizializzazione fallita: {str(e)}")
            raise
    
    def _check_required_files(self):
        """Verifica la presenza dei file necessari."""
        # Controlla il file HEF
        if not os.path.exists(self.hef_path):
            error_msg = f"HEF file not found: {self.hef_path}"
            logger.critical(error_msg)
            raise FileNotFoundError(error_msg)
        
        # Controlla il file di post-processing
        if not os.path.exists(self.post_process_so):
            error_msg = f"Post-process SO file not found: {self.post_process_so}"
            logger.critical(error_msg)
            raise FileNotFoundError(error_msg)
        
        logger.info(f"Using HEF: {self.hef_path}")
        logger.info(f"Using post-process SO: {self.post_process_so}")
    
    def build_pipeline(self):
        """
        Costruisce il pipeline GStreamer.
        
        Returns:
            Gst.Pipeline: Pipeline GStreamer configurato
        """
        pipeline_str = f'''
            v4l2src device={self.input_source} ! 
            video/x-raw, width=640, height=480 !
            queue name=source_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 !
            videoscale name=source_videoscale n-threads=2 ! 
            queue name=source_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 !
            videoconvert n-threads=3 name=source_convert qos=false ! 
            video/x-raw, format=RGB, pixel-aspect-ratio=1/1 !
            queue name=inference_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 !
            videoscale name=inference_videoscale n-threads=2 qos=false !
            queue name=inference_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 !
            video/x-raw, pixel-aspect-ratio=1/1 ! 
            videoconvert name=inference_videoconvert n-threads=2 !
            queue name=inference_hailonet_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 !
            hailonet name=inference_hailonet hef-path={self.hef_path} batch-size=1 !
            queue name=inference_hailofilter_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 !
            hailofilter name=inference_hailofilter so-path={self.post_process_so} qos=false !
            queue name=identity_callback_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 !
            identity name=identity_callback !
            queue name=final_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 !
            fakesink sync=false name=sink
        '''
        
        # Semplifica la stringa rimuovendo gli spazi in eccesso
        pipeline_str = ' '.join(line.strip() for line in pipeline_str.split('\n')).strip()
        logger.debug(f"Pipeline: {pipeline_str}")
        
        try:
            pipeline = Gst.parse_launch(pipeline_str)
            if not pipeline:
                raise RuntimeError("Failed to create pipeline")
            return pipeline
        except GLib.Error as e:
            logger.error(f"Failed to create pipeline: {e}")
            raise
    
    def setup_callback(self):
        """Configura il callback per il processamento dei frame."""
        identity = self.pipeline.get_by_name("identity_callback")
        if not identity:
            raise RuntimeError("Cannot find identity_callback element")
            
        pad = identity.get_static_pad("src")
        if not pad:
            raise RuntimeError("Cannot find identity_callback src pad")
            
        # Imposta il callback
        pad.add_probe(Gst.PadProbeType.BUFFER, self.process_frame, None)
        logger.info("Frame processing callback configured")
    
    def process_frame(self, pad, info, user_data):
        """
        Processo principale per l'elaborazione dei frame video.
        
        Args:
            pad: Pad GStreamer
            info: Informazioni sul buffer
            user_data: Dati utente
            
        Returns:
            Gst.PadProbeReturn: Stato del probe
        """
        current_time = datetime.now()
        
        try:
            buffer = info.get_buffer()
            if buffer is None:
                return Gst.PadProbeReturn.OK
                
            # Ottieni il frame come numpy array
            format, width, height = get_caps_from_pad(pad)
            frame = None
            if format is not None and width is not None and height is not None:
                frame = get_numpy_from_buffer(buffer, format, width, height)
                
            # Ottieni i metadata dal buffer
            roi = hailo.get_roi_from_buffer(buffer)
            detections = roi.get_objects_typed(hailo.HAILO_DETECTION)
                
            # Rilevamento gatti con soglia adattiva
            cat_detected_in_roi = False  # Per controllo finestra (solo ROI)
            any_cat_detected = False      # Per cattura immagini (qualsiasi posizione)
            max_confidence = 0.0
            max_confidence_any = 0.0
            current_threshold = self.get_current_confidence_threshold()

            for detection in detections:
                # Verifica se è un gatto
                if detection.get_label() == "cat":
                    confidence = detection.get_confidence()
                    if confidence >= current_threshold:
                        # Rileva QUALSIASI gatto per la cattura immagini
                        any_cat_detected = True
                        max_confidence_any = max(max_confidence_any, confidence)

                        # Verifica se il gatto è nella ROI definita (per controllo finestra)
                        bbox = detection.get_bbox()
                        # Ottieni i valori numerici dalle proprietà invece di sommare i metodi
                        center_x = (float(bbox.xmin) + float(bbox.xmax)) / 2
                        # Se la ROI è attiva, verifica che il centro del gatto sia entro i confini
                        if self.is_within_roi(center_x, width):
                            cat_detected_in_roi = True
                            max_confidence = max(max_confidence, confidence)

            # Aggiorna il filtro temporale e ottieni lo stato filtrato (solo per gatti nella ROI)
            filtered_cat_present = self.update_detection_filter(cat_detected_in_roi, current_time)

            # Gestione della logica di rilevamento e controllo finestra (solo ROI)
            self.process_cat_detection(frame, max_confidence, filtered_cat_present, current_time)

            # Gestione cattura immagini (TUTTI i gatti rilevati)
            if frame is not None and any_cat_detected and max_confidence_any > 0:
                self.handle_image_capture(frame, max_confidence_any)
                
        except Exception as e:
            logger.error(f"Error processing frame: {e}")
            self.error_count += 1
            self.last_error_time = current_time
            self.system_monitor.record_error('detection')
                
        return Gst.PadProbeReturn.OK
    
    def get_current_confidence_threshold(self):
        """
        Restituisce la soglia di confidenza appropriata in base allo stato della finestra.
        
        Returns:
            float: Soglia di confidenza corrente
        """
        # La soglia è più bassa quando la finestra è aperta
        if self.window_controller.is_window_open:
            return self.min_confidence * 0.8  # Riduzione del 20%
        return self.min_confidence
    
    def is_within_roi(self, x_pos, width):
        """
        Verifica se un punto è entro la ROI definita.
        
        Args:
            x_pos: Posizione x del punto
            width: Larghezza totale dell'immagine
            
        Returns:
            bool: True se il punto è entro la ROI, False altrimenti
        """
        # Normalizza la posizione x
        normalized_x = x_pos / width
        
        # Verifica se è entro i confini
        return self.left_boundary <= normalized_x <= self.right_boundary
    
    def update_detection_filter(self, cat_detected, current_time):
        """
        Aggiorna il filtro temporale delle rilevazioni.
        
        Args:
            cat_detected: Indica se un gatto è stato rilevato nel frame corrente
            current_time: Timestamp corrente
            
        Returns:
            bool: True se il gatto è considerato presente dopo il filtraggio
        """
        # Rimuovi le rilevazioni più vecchie della finestra temporale
        self.recent_detections = [t for t in self.recent_detections 
                                 if current_time - t < self.detection_filter_window]
        
        # Aggiungi la rilevazione corrente se positiva
        if cat_detected:
            self.recent_detections.append(current_time)
            
            # Aggiorna le statistiche
            self.system_monitor.record_detection(cat_detected)
        
        # Gatto presente se c'è almeno una rilevazione nella finestra temporale
        return len(self.recent_detections) > 0
    
    def process_cat_detection(self, frame, max_confidence, filtered_cat_present, current_time):
        """
        Elabora il rilevamento del gatto e gestisce lo stato della finestra.
        
        Args:
            frame: Frame video corrente
            max_confidence: Massima confidenza rilevata nel frame
            filtered_cat_present: Indica se il gatto è presente dopo il filtraggio
            current_time: Timestamp corrente
        """
        # Verifica se il controllo automatico è abilitato
        if not self.window_controller.auto_control_enabled():
            return

        if filtered_cat_present:
            # Inizia a contare il tempo di presenza se è la prima rilevazione
            if self.current_detection_time is None:
                self.current_detection_time = current_time
                logger.info(f"Cat detected with confidence {max_confidence:.2f}")
                
            # Resetta il contatore di assenza
            self.current_no_detection_time = None
            
            # Verifica se il gatto è presente da abbastanza tempo
            cat_present_time = current_time - self.current_detection_time
            if cat_present_time >= self.required_detection_time:
                # Apri la finestra se non è già aperta
                if self.window_controller.set_window_position(True, manual=False):
                    message = f"Gatto presente da {cat_present_time.seconds}s con confidenza {max_confidence:.2f}"
                    logger.info(f"Opening window - {message}")
                    
                    # Registra l'apertura della finestra nelle statistiche
                    self.system_monitor.record_window_change(True)
                    
                    # Notifica Telegram
                    if self.telegram:
                        self.telegram.send_window_status(True, message)
                        self.telegram.record_window_opening()
        else:
            # Inizia a contare il tempo di assenza se è la prima non-rilevazione
            if self.current_no_detection_time is None:
                self.current_no_detection_time = current_time
                logger.info("Cat no longer detected")
                
            # Resetta il contatore di presenza
            self.current_detection_time = None
            
            # Verifica se il gatto è assente da abbastanza tempo
            if self.current_no_detection_time is not None:
                cat_absent_time = current_time - self.current_no_detection_time
                if cat_absent_time >= self.required_no_detection_time:
                    # Chiudi la finestra se non è già chiusa
                    if self.window_controller.set_window_position(False):
                        message = f"Gatto assente da {cat_absent_time.seconds}s"
                        logger.info(f"Closing window - {message}")
                        
                        # Registra la chiusura della finestra nelle statistiche
                        self.system_monitor.record_window_change(False)
                        
                        # Notifica Telegram
                        if self.telegram:
                            self.telegram.send_window_status(False, message)
    
    def handle_image_capture(self, frame, confidence):
        """
        Gestisce la cattura e il salvataggio delle immagini dei gatti.
        
        Args:
            frame: Frame video corrente
            confidence: Confidenza del rilevamento
        """
        try:
            # Converti l'immagine in BGR per salvarla con OpenCV
            frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            
            # Salva l'immagine usando il gestore file
            saved_path = self.file_manager.save_image(frame_bgr, prefix="cat", confidence=confidence)
            
            # Aggiorna le statistiche
            if saved_path:
                self.system_monitor.record_image_capture()
                
                # Verifica se l'immagine deve essere inviata a Telegram
                capture_confidence = DETECTION_CONFIG.get('capture_confidence', 0.7)
                if confidence >= capture_confidence and self.telegram:
                    self.telegram.send_cat_photo(saved_path, confidence)
        except Exception as e:
            logger.error(f"Error handling image capture: {e}")
            self.error_count += 1
            self.last_error_time = datetime.now()
    
    def capture_photo(self):
        """
        Cattura una foto dal sistema su richiesta (ad esempio, dal bot Telegram).
        
        Returns:
            str: Percorso della foto catturata o None in caso di errore
        """
        # Ottieni l'ultima immagine catturata
        latest_image = self.file_manager.get_latest_image()
        
        # Se non ci sono immagini recenti, non possiamo fare nulla
        # In un sistema più avanzato, potremmo catturare un'immagine dalla pipeline
        return latest_image
    
    def start(self):
        """Avvia l'applicazione di rilevamento gatti."""
        if self.running:
            logger.warning("Cat detector is already running")
            return
            
        logger.info("Starting cat detector...")
        
        try:
            # Costruisci la pipeline
            self.pipeline = self.build_pipeline()
            
            # Configura il callback
            self.setup_callback()
            
            # Avvia il mainloop
            self.mainloop = GLib.MainLoop()
            self.pipeline.set_state(Gst.State.PLAYING)
            self.running = True
            
            logger.info("Cat detector started successfully")
            
            # Notifica di avvio
            if self.telegram:
                self.telegram.send_message("🟢 Sistema di rilevamento gatti avviato e operativo")
            
            # Esegui il mainloop
            self.mainloop.run()
            
        except Exception as e:
            logger.error(f"Error starting cat detector: {e}")
            self.error_count += 1
            self.last_error_time = datetime.now()
            
            if self.telegram:
                self.telegram.send_error_notification(f"Errore durante l'avvio: {str(e)}")
                
            self.stop()
            raise
    
    def stop(self):
        """Ferma l'applicazione di rilevamento gatti."""
        logger.info("Stopping cat detector...")
        
        try:
            # Ferma la pipeline
            if self.pipeline:
                self.pipeline.set_state(Gst.State.NULL)
                
            # Ferma il mainloop
            if self.mainloop and self.mainloop.is_running():
                self.mainloop.quit()
                
            # Salva le statistiche
            if hasattr(self, 'system_monitor'):
                self.system_monitor.save_stats()
                
            # Notifica di arresto
            if hasattr(self, 'telegram'):
                self.telegram.send_message("🔴 Sistema di rilevamento gatti arrestato")
                
            self.running = False
            logger.info("Cat detector stopped")
            
        except Exception as e:
            logger.error(f"Error stopping cat detector: {e}")
            self.error_count += 1
            self.last_error_time = datetime.now()
    
    def restart(self):
        """Riavvia l'applicazione di rilevamento gatti."""
        logger.info("Restarting cat detector...")
        
        if self.telegram:
            self.telegram.send_system_restart()
            
        self.stop()
        time.sleep(2)  # Attendi un po' prima di riavviare
        self.start()
    
    def check_health(self):
        """
        Verifica lo stato di salute del sistema.
        
        Returns:
            bool: True se il sistema è in buono stato, False altrimenti
        """
        # Verifica lo stato del sistema
        health_status, health_details = self.system_monitor.get_system_health()
        
        # Logga lo stato
        if health_status != "good":
            logger.warning(f"System health: {health_status}")
            for key, value in health_details.items():
                logger.warning(f"  {key}: {value}")
        
        # Riavvia se necessario
        if health_status == "critical":
            logger.critical("System in critical state, restarting...")
            self.restart()
            return False
            
        return health_status == "good"
    
    def run_daily_tasks(self):
        """Esegue attività giornaliere come l'invio del riepilogo."""
        try:
            # Invia il riepilogo giornaliero
            if self.telegram:
                self.telegram.send_daily_summary()
                
            # Pulisci lo storage se necessario
            self.file_manager.cleanup_storage()
            
            # Salva le statistiche
            self.system_monitor.save_stats()
            
            logger.info("Daily tasks completed successfully")
            return True
        except Exception as e:
            logger.error(f"Error running daily tasks: {e}")
            return False

def main():
    """Funzione principale."""
    
    # Parse args ...
    input_source = '/dev/video0'
    hef_path = '../resources/yolov8m.hef'
    
    # Crea e avvia il rilevatore di gatti
    detector = CatDetectorApp(input_source, hef_path)
    
    try:
        # Avvia il rilevatore
        detector.start()
        
        # Aggiungi un thread per le attività periodiche
        def periodic_tasks():
            while detector.running:
                try:
                    # Verifica lo stato di salute ogni ora
                    detector.check_health()
                    
                    # Verifica se è ora di eseguire le attività giornaliere
                    now = datetime.now()
                    if now.hour == 0 and now.minute < 15:  # Esegui intorno a mezzanotte
                        detector.run_daily_tasks()
                        
                    # Attendi prima del prossimo controllo
                    time.sleep(3600)  # 1 ora
                except Exception as e:
                    logger.error(f"Error in periodic tasks: {e}")
                    time.sleep(300)  # 5 minuti in caso di errore
        
        # Avvia il thread per le attività periodiche
        tasks_thread = threading.Thread(target=periodic_tasks, daemon=True)
        tasks_thread.start()
        
        # Il mainloop sta già girando nel thread principale
        
    except KeyboardInterrupt:
        logger.info("Application stopped by user")
    except Exception as e:
        logger.error(f"Application error: {e}", exc_info=True)
    finally:
        detector.stop()
