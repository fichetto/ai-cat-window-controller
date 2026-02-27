#!/usr/bin/env python3
"""
Modulo per monitoraggio telecamere RTSP con rilevamento AI.
Progettato per integrarsi con headless_detection.py condividendo il device Hailo.
"""

import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib
import os
import cv2
import logging
import threading
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Callable
import hailo
from hailo_rpi_common import get_caps_from_pad, get_numpy_from_buffer

logger = logging.getLogger(__name__)


@dataclass
class RtspCamera:
    """Configurazione di una telecamera RTSP."""
    name: str
    url: str
    detect_classes: List[str] = field(default_factory=lambda: ['cat', 'person'])
    enabled: bool = True
    min_confidence: float = 0.7


@dataclass
class Detection:
    """Rilevamento da una telecamera."""
    camera_name: str
    label: str
    confidence: float
    timestamp: datetime
    image_path: Optional[str] = None


class RtspCameraHandler:
    """Gestisce una singola telecamera RTSP."""

    def __init__(self, camera: RtspCamera, hef_path: str, post_process_so: str,
                 on_detection: Optional[Callable] = None):
        self.camera = camera
        self.hef_path = hef_path
        self.post_process_so = post_process_so
        self.on_detection = on_detection

        self.pipeline = None
        self.running = False
        self.frame_count = 0
        self.last_notification = {}  # {class: timestamp}
        self.notification_cooldown = timedelta(seconds=60)

        # Directory salvataggio
        self.save_dir = f"detected_objects/{camera.name.lower().replace(' ', '_')}"
        os.makedirs(self.save_dir, exist_ok=True)

    def _build_pipeline_string(self) -> str:
        """Costruisce la stringa del pipeline GStreamer."""
        name = self.camera.name.lower().replace(' ', '_')

        return f'''
            rtspsrc location="{self.camera.url}" latency=300 name={name}_src !
            queue leaky=downstream max-size-buffers=3 !
            rtph264depay ! h264parse ! avdec_h264 max-threads=2 !
            queue leaky=no max-size-buffers=3 !
            videoscale n-threads=2 ! videoconvert n-threads=2 !
            video/x-raw, format=RGB, width=640, height=480 !
            queue leaky=no max-size-buffers=3 !
            hailonet hef-path={self.hef_path} batch-size=1 !
            queue leaky=no max-size-buffers=3 !
            hailofilter so-path={self.post_process_so} qos=false !
            identity name={name}_cb !
            fakesink sync=false
        '''

    def _on_buffer(self, pad, info, user_data):
        """Callback per ogni frame."""
        buffer = info.get_buffer()
        if not buffer:
            return Gst.PadProbeReturn.OK

        self.frame_count += 1
        current_time = datetime.now()

        # Log periodico
        if self.frame_count % 500 == 0:
            logger.info(f"[{self.camera.name}] Frame {self.frame_count}")

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

        for det in detections:
            label = det.get_label()
            confidence = det.get_confidence()

            # Filtra per classi e confidence
            if label not in self.camera.detect_classes:
                continue
            if confidence < self.camera.min_confidence:
                continue

            # Controlla cooldown notifiche
            last = self.last_notification.get(label)
            if last and (current_time - last) < self.notification_cooldown:
                continue

            self.last_notification[label] = current_time

            # Salva immagine
            image_path = None
            if frame is not None:
                frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                ts = current_time.strftime("%Y%m%d_%H%M%S")
                image_path = f"{self.save_dir}/{label}_{ts}_{confidence:.2f}.jpg"
                cv2.imwrite(image_path, frame_bgr)

            # Callback
            if self.on_detection:
                detection = Detection(
                    camera_name=self.camera.name,
                    label=label,
                    confidence=confidence,
                    timestamp=current_time,
                    image_path=image_path
                )
                self.on_detection(detection)

        return Gst.PadProbeReturn.OK

    def start(self):
        """Avvia il pipeline."""
        if self.running:
            return

        pipeline_str = self._build_pipeline_string()
        pipeline_str = ' '.join(line.strip() for line in pipeline_str.split('\n'))

        try:
            self.pipeline = Gst.parse_launch(pipeline_str)
        except GLib.Error as e:
            logger.error(f"[{self.camera.name}] Pipeline error: {e}")
            return

        # Setup callback
        name = self.camera.name.lower().replace(' ', '_')
        identity = self.pipeline.get_by_name(f"{name}_cb")
        if identity:
            pad = identity.get_static_pad("src")
            pad.add_probe(Gst.PadProbeType.BUFFER, self._on_buffer, None)

        # Bus per errori
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message::error", self._on_error)

        self.pipeline.set_state(Gst.State.PLAYING)
        self.running = True
        logger.info(f"[{self.camera.name}] Pipeline avviato")

    def _on_error(self, bus, message):
        """Gestisce errori del pipeline."""
        err, debug = message.parse_error()
        logger.error(f"[{self.camera.name}] Errore: {err}")
        # Riavvia dopo 5 secondi
        GLib.timeout_add_seconds(5, self._restart)

    def _restart(self):
        """Riavvia il pipeline."""
        self.stop()
        GLib.timeout_add_seconds(2, self.start)
        return False

    def stop(self):
        """Ferma il pipeline."""
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
        self.running = False
        logger.info(f"[{self.camera.name}] Pipeline fermato")


class RtspMonitor:
    """
    Gestore centrale per telecamere RTSP.
    Uso: istanziare in headless_detection.py e chiamare start().
    """

    def __init__(self, telegram_handler=None):
        self.telegram = telegram_handler
        self.cameras: List[RtspCameraHandler] = []
        self.running = False

        # Percorsi Hailo
        script_dir = os.path.dirname(os.path.abspath(__file__))
        base_dir = os.path.dirname(script_dir)
        self.hef_path = os.path.join(base_dir, 'resources', 'yolov11m.hef')
        self.post_process_so = os.path.join(base_dir, 'resources',
                                            'libyolo_hailortpp_postprocess.so')

    def add_camera(self, name: str, url: str,
                   detect_classes: List[str] = None,
                   min_confidence: float = 0.7):
        """Aggiunge una telecamera da monitorare."""
        camera = RtspCamera(
            name=name,
            url=url,
            detect_classes=detect_classes or ['cat', 'person'],
            min_confidence=min_confidence
        )

        handler = RtspCameraHandler(
            camera=camera,
            hef_path=self.hef_path,
            post_process_so=self.post_process_so,
            on_detection=self._on_detection
        )
        self.cameras.append(handler)
        logger.info(f"[RtspMonitor] Aggiunta camera: {name}")

    def load_from_config(self):
        """Carica telecamere da tapo_config.py."""
        try:
            from tapo_config import TAPO_CAMERAS
            for cam in TAPO_CAMERAS:
                if cam.get('enabled', True):
                    self.add_camera(
                        name=cam['name'],
                        url=cam['rtsp_url'],
                        detect_classes=cam.get('detect_classes', ['cat', 'person']),
                        min_confidence=cam.get('min_confidence', 0.7)
                    )
            logger.info(f"[RtspMonitor] Caricate {len(self.cameras)} telecamere da config")
        except ImportError:
            logger.warning("[RtspMonitor] tapo_config.py non trovato")

    def _on_detection(self, detection: Detection):
        """Callback quando viene rilevato un oggetto."""
        emoji = {'cat': '🐱', 'person': '👤', 'dog': '🐕'}.get(detection.label, '📦')
        time_str = detection.timestamp.strftime("%H:%M:%S")

        message = (
            f"📷 [{detection.camera_name}]\n"
            f"{emoji} {detection.label.capitalize()} rilevato\n"
            f"📊 Confidenza: {detection.confidence:.0%}\n"
            f"🕐 {time_str}"
        )

        logger.info(f"[{detection.camera_name}] {detection.label} ({detection.confidence:.2f})")

        if self.telegram:
            if detection.image_path and os.path.exists(detection.image_path):
                self.telegram.send_photo(detection.image_path, caption=message)
            else:
                self.telegram.send_message(message)

    def start(self):
        """Avvia il monitoraggio di tutte le telecamere."""
        if not self.cameras:
            logger.info("[RtspMonitor] Nessuna telecamera configurata")
            return

        self.running = True
        for handler in self.cameras:
            # Avvia con delay per evitare picchi
            GLib.timeout_add_seconds(len(self.cameras), handler.start)

        logger.info(f"[RtspMonitor] Avviato con {len(self.cameras)} telecamere")

    def stop(self):
        """Ferma tutte le telecamere."""
        self.running = False
        for handler in self.cameras:
            handler.stop()
        logger.info("[RtspMonitor] Fermato")
