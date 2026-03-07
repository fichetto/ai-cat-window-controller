#!/usr/bin/env python3
"""
Sistema unificato per rilevamento AI con multiple sorgenti video.
Combina USB camera (cat window) e RTSP cameras (Tapo) in un singolo pipeline Hailo.

Architettura:
- USB camera: lato sinistro (0-50% X) -> controllo finestra gatti
- RTSP cameras: lato destro (50-100% X) -> solo notifiche
"""

import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib
import os
import sys
import resource
import numpy as np
import cv2
import hailo
import logging
import argparse
import json
from datetime import datetime, timedelta
from hailo_rpi_common import get_caps_from_pad, get_numpy_from_buffer

# Import esistenti
from cat_detector_callback import HeadlessCatDetectorCallback
from window_controller import WindowController
from telegram_handler import TelegramHandler
from cat_feeding_manager import CatFeedingManager
import telegram_commands

# Configurazione logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("/home/pi/hailo-rpi5-examples/cat_detector.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Limiti memoria
MAX_MEMORY_MB = 1500
STATE_FILE = "/tmp/cat_window_state.json"
AUTO_RESTART_MARKER = "/tmp/cat_auto_restart.json"


def _load_rtsp_cameras():
    """Carica configurazione telecamere RTSP."""
    try:
        from tapo_config import TAPO_CAMERAS
        return [c for c in TAPO_CAMERAS if c.get('enabled', True)]
    except ImportError:
        return []


class UnifiedDetectorApp:
    """
    Applicazione unificata per rilevamento con multiple sorgenti.
    Usa un singolo pipeline GStreamer con compositor per combinare le sorgenti.
    """

    def __init__(self, usb_source, hef_path, rtsp_cameras=None):
        Gst.init(None)
        self.usb_source = usb_source
        self.hef_path = hef_path
        self.rtsp_cameras = rtsp_cameras or []

        self.pipeline = None
        self.mainloop = None
        self.user_data = None
        self.telegram = None
        self.feeding_manager = None

        # Dimensioni video
        self.source_width = 640
        self.source_height = 480
        self.num_sources = 1 + len(self.rtsp_cameras)  # USB + RTSP

        # Controller finestra
        self.window_controller = WindowController()
        self._load_window_state()

        # Tracking RTSP
        self.rtsp_last_notification = {}
        self.rtsp_notification_cooldown = timedelta(seconds=60)
        self.rtsp_save_dir = "detected_objects"
        os.makedirs(self.rtsp_save_dir, exist_ok=True)

        # Frame counter
        self.frame_count = 0
        self.start_time = None

        # Detection stats per camera
        self.camera_stats = {cam['name']: {'detections': 0, 'last_detection': None}
                           for cam in self.rtsp_cameras}

        logger.info(f"UnifiedDetectorApp initialized with {self.num_sources} sources")

    # ==================== CAMERA MANAGEMENT API ====================

    def get_status(self) -> str:
        """Restituisce stato breve delle telecamere per /status."""
        active = sum(1 for cam in self.rtsp_cameras if cam.get('enabled', True))
        total = len(self.rtsp_cameras)
        if total == 0:
            return "Nessuna RTSP"
        return f"{active}/{total} attive"

    def get_cameras_info(self) -> str:
        """Restituisce info dettagliate telecamere per /telecamere."""
        if not self.rtsp_cameras:
            return "📷 Nessuna telecamera RTSP configurata"

        msg = "📷 *Telecamere RTSP:*\n\n"
        for cam in self.rtsp_cameras:
            status = "🟢" if cam.get('enabled', True) else "🔴"
            name = cam['name']
            classes = ", ".join(cam.get('detect_classes', ['cat', 'person']))

            # Stats
            stats = self.camera_stats.get(name, {})
            detections = stats.get('detections', 0)
            last = stats.get('last_detection')
            last_str = last.strftime("%H:%M") if last else "mai"

            msg += f"{status} *{name}*\n"
            msg += f"   Classi: {classes}\n"
            msg += f"   Rilevamenti: {detections} (ultimo: {last_str})\n\n"

        return msg

    def toggle_camera(self, camera_name: str, enable: bool) -> bool:
        """Abilita/disabilita una telecamera (richiede restart)."""
        for cam in self.rtsp_cameras:
            if cam['name'].lower() == camera_name.lower():
                cam['enabled'] = enable
                logger.info(f"Camera {camera_name} {'enabled' if enable else 'disabled'}")
                return True
        return False

    def _load_window_state(self):
        """Carica stato finestra salvato."""
        try:
            if os.path.exists(STATE_FILE):
                with open(STATE_FILE, 'r') as f:
                    state = json.load(f)
                saved_time = datetime.fromisoformat(state['timestamp'])
                if (datetime.now() - saved_time).total_seconds() < 300:
                    self.window_controller.manual_mode = state['manual_mode']
                    os.remove(STATE_FILE)
        except Exception as e:
            logger.warning(f"Could not load window state: {e}")

    def _initialize_telegram(self):
        """Inizializza Telegram."""
        try:
            self.telegram = TelegramHandler()
            self.telegram.window_controller = self.window_controller
            logger.info("Telegram initialized")
        except Exception as e:
            logger.error(f"Telegram init failed: {e}")
            self.telegram = None

    def _initialize_feeding_manager(self):
        """Inizializza feeding manager."""
        try:
            self.feeding_manager = CatFeedingManager()
            if self.telegram:
                self.feeding_manager.set_telegram_callbacks(
                    message_callback=self.telegram.send_message,
                    photo_callback=self.telegram.send_photo
                )
            telegram_commands.set_feeding_manager(self.feeding_manager)
            self.feeding_manager.start()
        except Exception as e:
            logger.warning(f"Feeding manager init failed: {e}")

        # Registra camera manager per comandi Telegram
        telegram_commands.set_camera_manager(self)

    def _initialize_detector(self):
        """Inizializza callback detector."""
        self.user_data = HeadlessCatDetectorCallback()
        self.user_data.window_controller = self.window_controller
        if self.telegram:
            self.user_data.telegram = self.telegram

    def _build_source_pipeline(self, idx, source_type, source_path, name):
        """Costruisce pipeline per una singola sorgente."""
        xpos = idx * self.source_width

        if source_type == 'usb':
            return f'''
                v4l2src device={source_path} name={name}_src !
                video/x-raw, width={self.source_width}, height={self.source_height} !
                queue leaky=no max-size-buffers=3 !
                videoconvert !
                videoscale !
                video/x-raw, format=RGB, width={self.source_width}, height={self.source_height} !
                queue leaky=no max-size-buffers=3 !
                compositor.sink_{idx}
            '''
        else:  # rtsp
            return f'''
                rtspsrc location="{source_path}" latency=300 name={name}_src !
                queue leaky=downstream max-size-buffers=3 !
                rtph264depay ! h264parse ! avdec_h264 max-threads=2 !
                queue leaky=downstream max-size-buffers=3 !
                videoconvert !
                videoscale !
                video/x-raw, format=RGB, width={self.source_width}, height={self.source_height} !
                queue leaky=no max-size-buffers=3 !
                compositor.sink_{idx}
            '''

    def build_pipeline(self):
        """Costruisce il pipeline unificato."""
        script_dir = os.path.dirname(os.path.abspath(__file__))
        base_dir = os.path.dirname(script_dir)

        if self.hef_path.startswith(".."):
            self.hef_path = os.path.abspath(os.path.join(script_dir, self.hef_path))

        post_process_so = os.path.join(base_dir, 'resources', 'libyolo_hailortpp_postprocess.so')

        # Larghezza totale del compositore
        total_width = self.source_width * self.num_sources

        # Costruisci pipeline sorgenti
        sources_str = ""

        # USB camera (indice 0, lato sinistro)
        sources_str += self._build_source_pipeline(0, 'usb', self.usb_source, 'usb')

        # RTSP cameras (indice 1+)
        for idx, cam in enumerate(self.rtsp_cameras, start=1):
            name = cam['name'].lower().replace(' ', '_')
            sources_str += self._build_source_pipeline(idx, 'rtsp', cam['rtsp_url'], name)

        # Configurazione sink del compositor
        sink_configs = ""
        for i in range(self.num_sources):
            xpos = i * self.source_width
            sink_configs += f"sink_{i}::xpos={xpos} sink_{i}::ypos=0 "

        pipeline_str = f'''
            compositor name=compositor {sink_configs} !
            video/x-raw, width={total_width}, height={self.source_height} !
            queue leaky=no max-size-buffers=3 !
            videoscale n-threads=2 !
            videoconvert n-threads=2 !
            video/x-raw, format=RGB, width=640, height=640 !
            queue leaky=no max-size-buffers=3 !
            hailonet hef-path={self.hef_path} batch-size=1 !
            queue leaky=no max-size-buffers=3 !
            hailofilter so-path={post_process_so} qos=false !
            identity name=identity_callback !
            fakesink sync=false

            {sources_str}
        '''

        pipeline_str = ' '.join(line.strip() for line in pipeline_str.split('\n')).strip()
        logger.info(f"Creating unified pipeline with {self.num_sources} sources")

        try:
            pipeline = Gst.parse_launch(pipeline_str)
            return pipeline
        except GLib.Error as e:
            logger.error(f"Pipeline creation failed: {e}")
            raise

    def _setup_callback(self):
        """Configura callback."""
        identity = self.pipeline.get_by_name("identity_callback")
        pad = identity.get_static_pad("src")
        pad.add_probe(Gst.PadProbeType.BUFFER, self._app_callback, None)

    def _app_callback(self, pad, info, user_data):
        """Callback unificato che gestisce rilevamenti da tutte le sorgenti."""
        buffer = info.get_buffer()
        if not buffer:
            return Gst.PadProbeReturn.OK

        current_time = datetime.now()

        # Frame counter
        if self.start_time is None:
            self.start_time = current_time
        self.frame_count += 1

        # Memory check ogni 100 frame
        if self.frame_count % 100 == 0:
            mem_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
            if mem_mb > MAX_MEMORY_MB:
                logger.error(f"Memory limit exceeded: {mem_mb:.0f}MB")
                os._exit(1)

        # Estrai frame
        format, width, height = get_caps_from_pad(pad)
        frame = None
        if format and width and height:
            try:
                frame = get_numpy_from_buffer(buffer, format, width, height)
            except Exception:
                pass

        # Estrai rilevamenti
        roi = hailo.get_roi_from_buffer(buffer)
        detections = roi.get_objects_typed(hailo.HAILO_DETECTION)

        # Dividi rilevamenti per sorgente basandosi sulla posizione X
        # USB = 0-50%, RTSP = 50-100% (per 2 sorgenti)
        source_boundary = 1.0 / self.num_sources

        usb_detections = []
        rtsp_detections = []

        for det in detections:
            bbox = det.get_bbox()
            center_x = (bbox.xmin() + bbox.xmax()) / 2

            # Normalizza posizione X alla sorgente originale
            source_idx = int(center_x / source_boundary)
            source_idx = min(source_idx, self.num_sources - 1)

            if source_idx == 0:
                # USB camera - rimappa X a 0-1
                remapped_x = center_x / source_boundary
                usb_detections.append((det, remapped_x))
            else:
                # RTSP camera
                camera_name = self.rtsp_cameras[source_idx - 1]['name'] if self.rtsp_cameras else "Unknown"
                rtsp_detections.append((det, camera_name, source_idx))

        # Processa rilevamenti USB (logica cat window esistente)
        self._process_usb_detections(usb_detections, frame, current_time)

        # Processa rilevamenti RTSP
        self._process_rtsp_detections(rtsp_detections, frame, current_time)

        return Gst.PadProbeReturn.OK

    def _process_usb_detections(self, detections, frame, current_time):
        """Processa rilevamenti dalla USB camera (logica cat window)."""
        cats_info = []
        current_threshold = self.user_data.get_current_confidence_threshold()

        for det, remapped_x in detections:
            if det.get_label() != "cat":
                continue
            confidence = det.get_confidence()
            if confidence < current_threshold:
                continue

            is_left = remapped_x < 0.5
            cats_info.append({
                'confidence': confidence,
                'center_x': remapped_x,
                'is_left': is_left
            })

        # Logica esistente per cat window
        cat_detected = len(cats_info) > 0
        cat_left = any(cat['is_left'] for cat in cats_info)
        max_confidence = max((cat['confidence'] for cat in cats_info), default=0.0)
        best_cat = max(cats_info, key=lambda c: c['confidence']) if cats_info else None

        filtered_cat_left = self.user_data.update_detection_filter(cat_left, current_time)
        should_open = filtered_cat_left

        self.user_data.process_cat_detection(frame, max_confidence, should_open, current_time, best_cat)

    def _process_rtsp_detections(self, detections, frame, current_time):
        """Processa rilevamenti dalle RTSP cameras."""
        for det, camera_name, source_idx in detections:
            label = det.get_label()
            confidence = det.get_confidence()

            if confidence < 0.7:
                continue
            if label not in ['cat', 'person', 'dog']:
                continue

            # Cooldown per camera+classe
            key = f"{camera_name}_{label}"
            last = self.rtsp_last_notification.get(key)
            if last and (current_time - last) < self.rtsp_notification_cooldown:
                continue

            self.rtsp_last_notification[key] = current_time

            # Salva immagine
            image_path = None
            if frame is not None and confidence >= 0.8:
                frame_h, frame_w = frame.shape[:2]
                x_start = int(source_idx * frame_w / self.num_sources)
                x_end = int((source_idx + 1) * frame_w / self.num_sources)
                frame_bgr = cv2.cvtColor(frame[:, x_start:x_end], cv2.COLOR_RGB2BGR)
                ts = current_time.strftime("%Y%m%d_%H%M%S")
                cam_dir = os.path.join(self.rtsp_save_dir, camera_name.lower().replace(' ', '_'))
                os.makedirs(cam_dir, exist_ok=True)
                image_path = f"{cam_dir}/{label}_{ts}_{confidence:.2f}.jpg"
                cv2.imwrite(image_path, frame_bgr)

            # Notifica
            emoji = {'cat': '🐱', 'person': '👤', 'dog': '🐕'}.get(label, '📦')
            message = (
                f"📷 [{camera_name}]\n"
                f"{emoji} {label.capitalize()} rilevato\n"
                f"📊 Confidenza: {confidence:.0%}\n"
                f"🕐 {current_time.strftime('%H:%M:%S')}"
            )

            logger.info(f"[{camera_name}] {label} detected ({confidence:.2f})")

            # Aggiorna statistiche camera
            if camera_name in self.camera_stats:
                self.camera_stats[camera_name]['detections'] += 1
                self.camera_stats[camera_name]['last_detection'] = current_time

            if self.telegram:
                if image_path and os.path.exists(image_path):
                    self.telegram.send_photo(image_path, caption=message)
                else:
                    self.telegram.send_message(message)

    def start(self):
        """Avvia l'applicazione."""
        try:
            self._initialize_telegram()
            self._initialize_feeding_manager()
            self._initialize_detector()

            self.pipeline = self.build_pipeline()
            self._setup_callback()

            self.mainloop = GLib.MainLoop()
            self.pipeline.set_state(Gst.State.PLAYING)

            cameras_info = ", ".join([c['name'] for c in self.rtsp_cameras]) or "nessuna"
            logger.info(f"Unified pipeline started (USB + RTSP: {cameras_info})")

            if self.telegram:
                self.telegram.send_message(
                    f"🟢 Sistema unificato avviato\n"
                    f"📹 USB: {self.usb_source}\n"
                    f"📷 RTSP: {cameras_info}"
                )

            self.mainloop.run()

        except Exception as e:
            logger.error(f"Start error: {e}", exc_info=True)
            self.stop()
            raise

    def stop(self):
        """Ferma l'applicazione."""
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
        if self.mainloop and self.mainloop.is_running():
            self.mainloop.quit()
        if self.feeding_manager:
            self.feeding_manager.stop()
        if self.telegram:
            self.telegram.send_message("🔴 Sistema unificato arrestato")
        logger.info("Application stopped")


def main():
    parser = argparse.ArgumentParser(description='Unified Detection System')
    parser.add_argument('--input', '-i', default='/dev/video0')
    parser.add_argument('--hef-path', default='../resources/yolov11m.hef')
    args = parser.parse_args()

    rtsp_cameras = _load_rtsp_cameras()
    logger.info(f"Loaded {len(rtsp_cameras)} RTSP cameras from config")

    app = UnifiedDetectorApp(args.input, args.hef_path, rtsp_cameras)
    try:
        app.start()
    except KeyboardInterrupt:
        pass
    finally:
        app.stop()


if __name__ == "__main__":
    main()
