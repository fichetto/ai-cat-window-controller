"""
Sistema di controllo automatico per finestra per gatti basato su AI detection.
Versione headless con soglia di confidenza adattiva e supporto Telegram.
"""

import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib
import os
import numpy as np
import cv2
import hailo
import logging
import argparse
from datetime import datetime, timedelta
from hailo_rpi_common import (
    get_caps_from_pad,
    get_numpy_from_buffer,
)
from cat_detector_callback import HeadlessCatDetectorCallback
from window_controller import WindowController
from telegram_handler import TelegramHandler

# Configurazione logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class HeadlessDetectorApp:
    """Applicazione standalone per rilevamento gatti in modalità headless."""
    
    def __init__(self, input_source, hef_path):
        """Inizializza l'applicazione."""
        Gst.init(None)
        self.input_source = input_source
        self.hef_path = hef_path
        self.pipeline = None
        self.mainloop = None
        self.user_data = None
        self.telegram = None
        
        # Inizializza prima il controller della finestra
        logger.info("Initializing window controller...")
        self.window_controller = WindowController()
        
    def _initialize_telegram(self):
        """Inizializza e configura il bot Telegram."""
        try:
            self.telegram = TelegramHandler()
            # Passa il controller finestra al gestore Telegram
            logger.info("Configuring Telegram with window controller...")
            self.telegram.window_controller = self.window_controller
            logger.info("Telegram handler initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Telegram handler: {e}")
            self.telegram = None

    def _initialize_detector(self):
        """Inizializza il rilevatore di gatti."""
        self.user_data = HeadlessCatDetectorCallback()
        # Passa il controller finestra al detector
        self.user_data.window_controller = self.window_controller

    def build_pipeline(self):
        """Costruisce il pipeline GStreamer."""
        script_dir = os.path.dirname(os.path.abspath(__file__))
        base_dir = os.path.dirname(script_dir)
        
        if self.hef_path.startswith(".."):
            self.hef_path = os.path.abspath(os.path.join(script_dir, self.hef_path))
        
        post_process_so = os.path.abspath(os.path.join(base_dir, 'resources', 
                                                      'libyolo_hailortpp_postprocess.so'))
        
        if not os.path.exists(self.hef_path):
            raise FileNotFoundError(f"HEF file not found: {self.hef_path}")
        if not os.path.exists(post_process_so):
            raise FileNotFoundError(f"Post-process SO file not found: {post_process_so}")
            
        logger.info(f"Using HEF file: {self.hef_path}")
        logger.info(f"Using post-process SO: {post_process_so}")

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
            hailofilter name=inference_hailofilter so-path={post_process_so} qos=false !
            queue name=identity_callback_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 !
            identity name=identity_callback !
            queue name=final_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 !
            fakesink sync=false name=sink
        '''
        
        pipeline_str = ' '.join(line.strip() for line in pipeline_str.split('\n')).strip()
        logger.info(f"Creating pipeline: {pipeline_str}")
        
        try:
            pipeline = Gst.parse_launch(pipeline_str)
            if not pipeline:
                raise RuntimeError("Failed to create pipeline")
            return pipeline
        except GLib.Error as e:
            logger.error(f"Failed to create pipeline: {e}")
            raise
    
    def _setup_callback(self):
        """Configura il callback per il processamento dei frame."""
        identity = self.pipeline.get_by_name("identity_callback")
        if not identity:
            raise RuntimeError("Cannot find identity_callback element")
            
        pad = identity.get_static_pad("src")
        if not pad:
            raise RuntimeError("Cannot find identity_callback src pad")
            
        # Passa il gestore Telegram al callback
        if self.telegram:
            self.user_data.telegram = self.telegram
        pad.add_probe(Gst.PadProbeType.BUFFER, app_callback, self.user_data)
    
    def start(self):
        """Avvia l'applicazione."""
        try:
            # Inizializza i componenti nell'ordine corretto
            self._initialize_telegram()
            self._initialize_detector()
            
            self.pipeline = self.build_pipeline()
            self._setup_callback()
            
            # Avvia il mainloop
            self.mainloop = GLib.MainLoop()
            self.pipeline.set_state(Gst.State.PLAYING)
            logger.info("Pipeline started successfully")
            self.mainloop.run()
            
        except Exception as e:
            logger.error(f"Error starting application: {e}", exc_info=True)
            if self.telegram:
                self.telegram.send_message(f"❌ Errore durante l'avvio: {str(e)}")
            self.stop()
            raise
    
    def stop(self):
        """Ferma l'applicazione."""
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
        if self.mainloop and self.mainloop.is_running():
            self.mainloop.quit()
        if self.telegram:
            self.telegram.send_message("🔴 Sistema di rilevamento gatti arrestato")
        logger.info("Application stopped")

def app_callback(pad, info, user_data):
    """Callback principale per l'elaborazione dei frame."""
    buffer = info.get_buffer()
    if buffer is None:
        return Gst.PadProbeReturn.OK

    # Frame counter per debug
    if not hasattr(app_callback, 'frame_count'):
        app_callback.frame_count = 0
        app_callback.last_log_time = datetime.now()

    app_callback.frame_count += 1
    current_time = datetime.now()

    # Log ogni 100 frames (~3 secondi a 30fps)
    if app_callback.frame_count % 100 == 0:
        elapsed = (current_time - app_callback.last_log_time).total_seconds()
        fps = 100 / elapsed if elapsed > 0 else 0
        logger.info(f"Processing frame {app_callback.frame_count} (FPS: {fps:.1f})")
        app_callback.last_log_time = current_time
    format, width, height = get_caps_from_pad(pad)
    
    frame = None
    if format is not None and width is not None and height is not None:
        frame = get_numpy_from_buffer(buffer, format, width, height)

    roi = hailo.get_roi_from_buffer(buffer)
    detections = roi.get_objects_typed(hailo.HAILO_DETECTION)

    # Debug: log tutte le detection ogni 300 frames
    if app_callback.frame_count % 300 == 0 and len(detections) > 0:
        logger.info(f"Total detections: {len(detections)}, Labels: {[d.get_label() for d in detections]}")

    # Rilevamento gatti con soglia adattiva e raccolta informazioni posizione
    cats_info = []  # Lista di tutti i gatti rilevati con info posizione
    current_threshold = user_data.get_current_confidence_threshold()

    for detection in detections:
        if detection.get_label() == "cat":
            confidence = detection.get_confidence()
            if confidence >= current_threshold:
                # Estrai coordinate bbox
                bbox = detection.get_bbox()
                xmin = float(bbox.xmin())
                xmax = float(bbox.xmax())
                center_x = (xmin + xmax) / 2

                # Classifica posizione: sinistra (0-0.5) o destra (0.5-1.0)
                is_left = center_x < 0.5

                cats_info.append({
                    'confidence': confidence,
                    'center_x': center_x,
                    'is_left': is_left,
                    'xmin': xmin,
                    'xmax': xmax
                })

    # Determina stato basato su TUTTI i gatti rilevati
    cat_detected = len(cats_info) > 0
    cat_left = any(cat['is_left'] for cat in cats_info)
    cat_right = any(not cat['is_left'] for cat in cats_info)
    total_cats = len(cats_info)

    # Trova il gatto con confidence maggiore per foto
    max_confidence = max((cat['confidence'] for cat in cats_info), default=0.0)
    best_cat = max(cats_info, key=lambda c: c['confidence']) if cats_info else None

    # Aggiorna filtro temporale per LEFT: mantiene persistenza ignorando scomparse < 5 secondi
    # Questo risolve il problema di frame mancanti o detection intermittenti
    filtered_cat_left = user_data.update_detection_filter(cat_left, current_time)

    # Traccia ultima volta che abbiamo visto un gatto a DESTRA
    if cat_right:
        user_data.last_right_detection_time = current_time

    # Calcola quanto tempo è passato dall'ultima rilevazione a destra
    time_since_right = (current_time - user_data.last_right_detection_time) if user_data.last_right_detection_time else timedelta(seconds=999)
    no_recent_right = time_since_right > timedelta(seconds=5)

    # Condizione per apertura: gatto a sinistra PERSISTENTE (negli ultimi 5 sec)
    # E nessun gatto a destra negli ultimi 5 secondi
    should_open_window = filtered_cat_left and no_recent_right

    # Gestione controllo finestra con la nuova logica
    user_data.process_cat_detection(frame, max_confidence, should_open_window, current_time, best_cat)

    # Gestione cattura immagini: SOLO quando gatto a DESTRA (fuori, vuole entrare)
    # Gatto a SINISTRA = dentro, finestra si apre automaticamente, no notifica
    if frame is not None and cat_right and best_cat and not best_cat['is_left']:
        frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        saved_path = user_data.save_cat_image(frame_bgr, max_confidence)

        # Invia foto con notifica - gatto è fuori e vuole entrare!
        if saved_path:
            logger.info(f"Photo saved: {saved_path}")
            if hasattr(user_data, 'telegram') and user_data.telegram:
                # Crea caption con informazioni
                position_pct = best_cat['center_x'] * 100

                caption = f"🐱 Gatto FUORI vuole entrare!\n"
                caption += f"• Posizione: DESTRA ({position_pct:.1f}%)\n"
                caption += f"• Confidenza: {best_cat['confidence']:.2f}\n"
                caption += f"• Usa /faientrare per aprire"

                user_data.telegram.send_photo(saved_path, caption=caption)
                logger.info(f"Photo sent to Telegram - cat outside wants to enter")
            else:
                logger.warning("Telegram handler not available")
        else:
            logger.info(f"Photo not saved (cooldown or low confidence: {max_confidence:.2f})")

    return Gst.PadProbeReturn.OK

def parse_args():
    """Analizza gli argomenti da linea di comando."""
    parser = argparse.ArgumentParser(description='Headless Cat Detection System')
    parser.add_argument('--input', '-i', default='/dev/video0',
                      help='Input source (default: /dev/video0)')
    parser.add_argument('--hef-path', default='../resources/yolov11m.hef',
                       help='Path to HEF file (default: YOLO11m for better accuracy)')
    return parser.parse_args()

def main():
    """Funzione principale dell'applicazione."""
    args = parse_args()
    logger.info("Starting Headless Cat Window Detection System...")
    logger.info("Window will initialize to closed position (77°)")
    
    app = HeadlessDetectorApp(args.input, args.hef_path)
    try:
        app.start()
    except KeyboardInterrupt:
        logger.info("Application stopped by user")
    except Exception as e:
        logger.error(f"Application error: {e}", exc_info=True)
    finally:
        app.stop()

if __name__ == "__main__":
    main()