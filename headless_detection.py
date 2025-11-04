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
from datetime import datetime
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

    current_time = datetime.now()
    format, width, height = get_caps_from_pad(pad)
    
    frame = None
    if format is not None and width is not None and height is not None:
        frame = get_numpy_from_buffer(buffer, format, width, height)

    roi = hailo.get_roi_from_buffer(buffer)
    detections = roi.get_objects_typed(hailo.HAILO_DETECTION)

    # Rilevamento gatti con soglia adattiva
    cat_detected = False
    max_confidence = 0.0
    current_threshold = user_data.get_current_confidence_threshold()
    
    for detection in detections:
        if detection.get_label() == "cat":
            confidence = detection.get_confidence()
            if confidence >= current_threshold:
                cat_detected = True
                max_confidence = max(max_confidence, confidence)

    # Aggiorna il filtro temporale e ottieni lo stato filtrato
    filtered_cat_present = user_data.update_detection_filter(cat_detected, current_time)

    # Gestione della logica di rilevamento e controllo finestra
    user_data.process_cat_detection(frame, max_confidence, filtered_cat_present, current_time)

    # Gestione cattura immagini e invio Telegram
    if frame is not None and cat_detected and max_confidence > 0:
        frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        saved_path = user_data.save_cat_image(frame_bgr, max_confidence)
        
        # Se l'immagine è stata salvata e abbiamo Telegram configurato, inviala
        if saved_path and hasattr(user_data, 'telegram') and user_data.telegram:
            user_data.telegram.send_photo(saved_path, max_confidence)

    return Gst.PadProbeReturn.OK

def parse_args():
    """Analizza gli argomenti da linea di comando."""
    parser = argparse.ArgumentParser(description='Headless Cat Detection System')
    parser.add_argument('--input', '-i', default='/dev/video0',
                      help='Input source (default: /dev/video0)')
    parser.add_argument('--hef-path', default='../resources/yolov8m.hef',
                       help='Path to HEF file')
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