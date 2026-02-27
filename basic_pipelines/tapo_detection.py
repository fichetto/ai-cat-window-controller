#!/usr/bin/env python3
"""
Sistema multi-camera per rilevamento AI su telecamere Tapo RTSP.
Supporta rilevamento di gatti, persone e altre classi COCO.
"""

import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib
import os
import sys
import signal
import threading
import resource
import numpy as np
import cv2
import hailo
import logging
import argparse
from datetime import datetime, timedelta
from hailo_rpi_common import (
    get_caps_from_pad,
    get_numpy_from_buffer,
    QUEUE,
)
from tapo_detector_callback import TapoDetectorCallback
from telegram_handler import TelegramHandler

# Importa configurazione
try:
    from tapo_config import (
        TELEGRAM_CONFIG,
        TAPO_CAMERAS,
        DETECTION_CONFIG,
        IMAGE_CONFIG,
        NOTIFICATION_CONFIG,
    )
except ImportError:
    print("ERROR: tapo_config.py not found. Copy tapo_config.example.py to tapo_config.py and configure.")
    sys.exit(1)

# Configurazione logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("/home/pi/hailo-rpi5-examples/tapo_detector.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Limite memoria e uptime per prevenire OOM
MAX_MEMORY_MB = 1500
MAX_UPTIME_HOURS = 12


class CameraThread(threading.Thread):
    """Thread per gestire una singola telecamera."""

    def __init__(self, camera_config, hef_path, telegram_handler, detection_config):
        super().__init__(daemon=True)
        self.camera_config = camera_config
        self.camera_name = camera_config['name']
        self.rtsp_url = camera_config['rtsp_url']
        self.detect_classes = camera_config['detect_classes']
        self.hef_path = hef_path
        self.telegram = telegram_handler
        self.detection_config = detection_config

        self.pipeline = None
        self.mainloop = None
        self.user_data = None
        self.running = False
        self.error_count = 0
        self.max_errors = 5

        logger.info(f"[{self.camera_name}] CameraThread initialized - URL: {self.rtsp_url[:50]}...")

    def build_pipeline(self):
        """Costruisce il pipeline GStreamer per RTSP."""
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

        # Nome base per elementi pipeline (evita conflitti)
        name = self.camera_name.lower().replace(' ', '_')

        pipeline_str = f'''
            rtspsrc location="{self.rtsp_url}" name={name}_src latency=300 !
            queue name={name}_rtpdepay_q leaky=downstream max-size-buffers=3 !
            rtph264depay !
            queue name={name}_parse_q leaky=downstream max-size-buffers=3 !
            h264parse !
            queue name={name}_decode_q leaky=downstream max-size-buffers=3 !
            avdec_h264 max-threads=2 !
            queue name={name}_scale_q leaky=no max-size-buffers=3 !
            videoscale n-threads=2 !
            queue name={name}_convert_q leaky=no max-size-buffers=3 !
            videoconvert n-threads=2 !
            video/x-raw, format=RGB, width=640, height=480 !
            queue name={name}_inference_q leaky=no max-size-buffers=3 !
            hailonet name={name}_hailonet hef-path={self.hef_path} batch-size=1 !
            queue name={name}_filter_q leaky=no max-size-buffers=3 !
            hailofilter name={name}_hailofilter so-path={post_process_so} qos=false !
            queue name={name}_callback_q leaky=no max-size-buffers=3 !
            identity name={name}_identity !
            fakesink sync=false name={name}_sink
        '''

        pipeline_str = ' '.join(line.strip() for line in pipeline_str.split('\n')).strip()
        logger.info(f"[{self.camera_name}] Creating pipeline...")

        try:
            pipeline = Gst.parse_launch(pipeline_str)
            if not pipeline:
                raise RuntimeError("Failed to create pipeline")
            return pipeline
        except GLib.Error as e:
            logger.error(f"[{self.camera_name}] Failed to create pipeline: {e}")
            raise

    def _setup_callback(self):
        """Configura il callback per il processamento dei frame."""
        name = self.camera_name.lower().replace(' ', '_')
        identity = self.pipeline.get_by_name(f"{name}_identity")
        if not identity:
            raise RuntimeError(f"Cannot find {name}_identity element")

        pad = identity.get_static_pad("src")
        if not pad:
            raise RuntimeError(f"Cannot find {name}_identity src pad")

        # Crea callback specifico per questa camera
        self.user_data = TapoDetectorCallback(
            self.camera_name,
            self.detect_classes,
            self.detection_config
        )
        self.user_data.telegram = self.telegram

        # Crea closure per il callback
        def camera_callback(pad, info, user_data):
            return self._process_frame(pad, info, user_data)

        pad.add_probe(Gst.PadProbeType.BUFFER, camera_callback, self.user_data)

    def _process_frame(self, pad, info, user_data):
        """Processa un frame dalla camera."""
        buffer = info.get_buffer()
        if buffer is None:
            return Gst.PadProbeReturn.OK

        user_data.increment()
        current_time = datetime.now()

        # Log periodico
        if user_data.frame_count % 300 == 0:
            logger.info(f"[{self.camera_name}] Processing frame {user_data.frame_count}")

        format, width, height = get_caps_from_pad(pad)

        frame = None
        if format is not None and width is not None and height is not None:
            try:
                frame = get_numpy_from_buffer(buffer, format, width, height)
            except Exception as e:
                logger.error(f"[{self.camera_name}] Error getting frame: {e}")
                return Gst.PadProbeReturn.OK

        # Estrai rilevazioni
        roi = hailo.get_roi_from_buffer(buffer)
        detections = roi.get_objects_typed(hailo.HAILO_DETECTION)

        # Prepara info rilevazioni
        detections_info = []
        for detection in detections:
            label = detection.get_label()
            confidence = detection.get_confidence()
            bbox = detection.get_bbox()

            detections_info.append({
                'label': label,
                'confidence': confidence,
                'bbox': (bbox.xmin(), bbox.ymin(), bbox.xmax(), bbox.ymax()),
            })

        # Converti frame per salvataggio (RGB -> BGR)
        frame_bgr = None
        if frame is not None:
            frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

        # Processa rilevazioni
        if detections_info:
            notifications = user_data.process_detections(detections_info, frame_bgr, current_time)

            # Invia notifiche
            for notification in notifications:
                user_data.send_telegram_notification(notification)

        return Gst.PadProbeReturn.OK

    def _on_bus_message(self, bus, message, loop):
        """Gestisce i messaggi del bus GStreamer."""
        t = message.type

        if t == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            logger.error(f"[{self.camera_name}] Pipeline error: {err} - {debug}")
            self.error_count += 1
            if self.error_count >= self.max_errors:
                logger.error(f"[{self.camera_name}] Max errors reached, stopping...")
                self.running = False
                loop.quit()
            else:
                # Prova a riavviare il pipeline
                logger.info(f"[{self.camera_name}] Attempting to restart pipeline...")
                self.pipeline.set_state(Gst.State.NULL)
                GLib.timeout_add_seconds(5, self._restart_pipeline)

        elif t == Gst.MessageType.EOS:
            logger.warning(f"[{self.camera_name}] End of stream")
            # Per RTSP, EOS non dovrebbe mai arrivare, riavvia
            GLib.timeout_add_seconds(5, self._restart_pipeline)

        elif t == Gst.MessageType.STATE_CHANGED:
            if message.src == self.pipeline:
                old, new, pending = message.parse_state_changed()
                if new == Gst.State.PLAYING:
                    logger.info(f"[{self.camera_name}] Pipeline is PLAYING")
                    self.error_count = 0  # Reset error count on successful start

        return True

    def _restart_pipeline(self):
        """Riavvia il pipeline dopo un errore."""
        try:
            logger.info(f"[{self.camera_name}] Restarting pipeline...")
            self.pipeline.set_state(Gst.State.NULL)
            GLib.usleep(1000000)  # 1 secondo
            self.pipeline.set_state(Gst.State.PLAYING)
            return False  # Non ripetere il timeout
        except Exception as e:
            logger.error(f"[{self.camera_name}] Failed to restart pipeline: {e}")
            return False

    def run(self):
        """Esegue il thread della camera."""
        self.running = True
        logger.info(f"[{self.camera_name}] Starting camera thread...")

        try:
            self.pipeline = self.build_pipeline()
            self._setup_callback()

            # Setup bus per messaggi
            bus = self.pipeline.get_bus()
            bus.add_signal_watch()

            self.mainloop = GLib.MainLoop()
            bus.connect("message", self._on_bus_message, self.mainloop)

            # Avvia pipeline
            self.pipeline.set_state(Gst.State.PLAYING)
            logger.info(f"[{self.camera_name}] Pipeline started")

            # Esegui main loop
            self.mainloop.run()

        except Exception as e:
            logger.error(f"[{self.camera_name}] Thread error: {e}", exc_info=True)
        finally:
            self.stop()

    def stop(self):
        """Ferma il thread della camera."""
        self.running = False
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
        if self.mainloop and self.mainloop.is_running():
            self.mainloop.quit()
        logger.info(f"[{self.camera_name}] Camera thread stopped")


class TapoMultiCameraDetector:
    """Gestore principale per rilevamento multi-camera."""

    def __init__(self, hef_path):
        Gst.init(None)
        self.hef_path = hef_path
        self.camera_threads = []
        self.telegram = None
        self.running = False
        self.start_time = datetime.now()

        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        logger.info("TapoMultiCameraDetector initialized")

    def _signal_handler(self, signum, frame):
        """Gestisce segnali di terminazione."""
        logger.info(f"Received signal {signum}, shutting down...")
        self.stop()

    def _initialize_telegram(self):
        """Inizializza il bot Telegram."""
        try:
            self.telegram = TelegramHandler()
            logger.info("Telegram handler initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Telegram handler: {e}")
            self.telegram = None

    def _check_health(self):
        """Controlla lo stato di salute del sistema."""
        # Controllo memoria
        mem_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
        if mem_mb > MAX_MEMORY_MB:
            logger.error(f"MEMORY LIMIT EXCEEDED: {mem_mb:.0f}MB > {MAX_MEMORY_MB}MB - Restarting...")
            self.stop()
            os._exit(1)

        # Controllo uptime
        uptime_hours = (datetime.now() - self.start_time).total_seconds() / 3600
        if uptime_hours > MAX_UPTIME_HOURS:
            logger.warning(f"MAX UPTIME REACHED: {uptime_hours:.1f}h - Preventive restart")
            self.stop()
            os._exit(0)

        # Controlla thread attivi
        active_cameras = sum(1 for t in self.camera_threads if t.is_alive())
        total_cameras = len(self.camera_threads)

        if active_cameras == 0 and total_cameras > 0:
            logger.error("All camera threads died, restarting...")
            self.stop()
            os._exit(1)

        # Log stato ogni 5 minuti
        logger.info(f"Health check: Memory={mem_mb:.0f}MB, Uptime={uptime_hours:.1f}h, "
                   f"Cameras={active_cameras}/{total_cameras}")

        return True  # Continua il timer

    def start(self):
        """Avvia il sistema multi-camera."""
        self.running = True
        logger.info("Starting Tapo Multi-Camera Detection System...")

        # Inizializza Telegram
        self._initialize_telegram()

        # Invia notifica avvio
        if self.telegram:
            enabled_cameras = [c['name'] for c in TAPO_CAMERAS if c.get('enabled', True)]
            self.telegram.send_message(
                f"🎥 Sistema Tapo Multi-Camera avviato\n"
                f"📹 Telecamere attive: {len(enabled_cameras)}\n"
                f"• " + "\n• ".join(enabled_cameras)
            )

        # Crea directory immagini
        save_dir = IMAGE_CONFIG.get('save_dir', 'detected_objects')
        if not os.path.exists(save_dir):
            os.makedirs(save_dir, exist_ok=True)
            logger.info(f"Created save directory: {save_dir}")

        # Avvia thread per ogni camera abilitata
        for camera_config in TAPO_CAMERAS:
            if not camera_config.get('enabled', True):
                logger.info(f"[{camera_config['name']}] Camera disabled, skipping")
                continue

            thread = CameraThread(
                camera_config,
                self.hef_path,
                self.telegram,
                DETECTION_CONFIG
            )
            self.camera_threads.append(thread)
            thread.start()

        # Avvia health check periodico
        GLib.timeout_add_seconds(300, self._check_health)  # Ogni 5 minuti

        # Main loop per tenere vivo il processo principale
        try:
            main_loop = GLib.MainLoop()
            main_loop.run()
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
        finally:
            self.stop()

    def stop(self):
        """Ferma il sistema."""
        self.running = False
        logger.info("Stopping Tapo Multi-Camera Detection System...")

        # Ferma tutti i thread camera
        for thread in self.camera_threads:
            thread.stop()

        # Aspetta che i thread terminino
        for thread in self.camera_threads:
            thread.join(timeout=5)

        # Notifica arresto
        if self.telegram:
            self.telegram.send_message("🔴 Sistema Tapo Multi-Camera arrestato")

        logger.info("System stopped")


def parse_args():
    """Analizza gli argomenti da linea di comando."""
    parser = argparse.ArgumentParser(description='Tapo Multi-Camera Detection System')
    parser.add_argument('--hef-path', default='../resources/yolov11m.hef',
                       help='Path to HEF file (default: YOLO11m)')
    return parser.parse_args()


def main():
    """Funzione principale."""
    args = parse_args()
    logger.info("=" * 60)
    logger.info("Starting Tapo Multi-Camera Detection System")
    logger.info("=" * 60)

    detector = TapoMultiCameraDetector(args.hef_path)
    try:
        detector.start()
    except Exception as e:
        logger.error(f"Application error: {e}", exc_info=True)
    finally:
        detector.stop()


if __name__ == "__main__":
    main()
