"""
Sistema di controllo automatico per finestra per gatti basato su AI detection.
Versione headless con soglia di confidenza adattiva e supporto Telegram.
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
import threading
import time
from datetime import datetime, timedelta
from hailo_rpi_common import (
    get_caps_from_pad,
    get_numpy_from_buffer,
)
from cat_detector_callback import HeadlessCatDetectorCallback
from window_controller import WindowController
from telegram_handler import TelegramHandler
from cat_feeding_manager import CatFeedingManager
from detection_processor import DetectionProcessor, DetectionResult
import telegram_commands

# Importa configurazione telecamere RTSP (opzionale)
try:
    from tapo_config import TAPO_CAMERAS
except ImportError:
    TAPO_CAMERAS = []

# Intervallo iniezione frame RTSP (secondi)
RTSP_INJECT_INTERVAL = 2.0

# Quando la webcam USB è assente, una telecamera RTSP può essere "promossa" a
# primary e gestire il controllo finestra automatico. Il nome deve corrispondere
# esattamente a quello in tapo_config.TAPO_CAMERAS.
# Lascia None per disabilitare la promozione (modalità solo-notifiche).
PRIMARY_RTSP_FALLBACK_CAMERA = "Corridoio"
# Se True, le coordinate X della primary RTSP sono specchiate (1 - x) prima di
# applicare la logica USB. Necessario quando l'inquadratura ha la finestra a
# destra mentre la logica USB assume finestra a sinistra.
# Corridoio attuale: inquadra come la USB (finestra a sinistra) → mirror NON serve.
PRIMARY_RTSP_FALLBACK_MIRROR_X = False

# Configurazione logging con FileHandler
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("/home/pi/hailo-rpi5-examples/cat_detector.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Limite massimo di memoria (1.2GB) - se superato, il processo si riavvia
# Abbassato da 2GB per prevenire freeze del sistema dovuti a memory leak del driver Hailo
MAX_MEMORY_MB = 1200
MEMORY_CHECK_INTERVAL = 100  # Controlla ogni N frame

# File per salvare stato modalità manuale/automatico
STATE_FILE = "/tmp/cat_window_state.json"

# File marker per riavvio automatico (importato da telegram_notifications)
AUTO_RESTART_MARKER = "/tmp/cat_auto_restart.json"

def _mark_auto_restart(reason: str):
    """Crea un marker per indicare che il prossimo avvio è un riavvio automatico."""
    try:
        marker = {
            'reason': reason,
            'timestamp': datetime.now().isoformat()
        }
        with open(AUTO_RESTART_MARKER, 'w') as f:
            json.dump(marker, f)
        logger.info(f"Auto-restart marker created: {reason}")
    except Exception as e:
        logger.error(f"Failed to create auto-restart marker: {e}")

def _save_window_state(window_controller):
    """Salva lo stato della finestra prima del riavvio."""
    try:
        state = {
            'manual_mode': window_controller.manual_mode,
            'is_window_open': window_controller.is_window_open,
            'timestamp': datetime.now().isoformat()
        }
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f)
        logger.info(f"Window state saved: manual_mode={state['manual_mode']}, is_open={state['is_window_open']}")
    except Exception as e:
        logger.error(f"Failed to save window state: {e}")

def _load_window_state(window_controller):
    """Ripristina lo stato della finestra dopo il riavvio."""
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, 'r') as f:
                state = json.load(f)

            # Controlla che lo stato non sia troppo vecchio (max 5 minuti)
            saved_time = datetime.fromisoformat(state['timestamp'])
            if (datetime.now() - saved_time).total_seconds() < 300:
                window_controller.manual_mode = state['manual_mode']
                logger.info(f"Window state restored: manual_mode={state['manual_mode']}, was_open={state['is_window_open']}")
                # Rimuovi il file dopo averlo letto
                os.remove(STATE_FILE)
                return True
            else:
                logger.warning("Window state file too old, ignoring")
                os.remove(STATE_FILE)
    except Exception as e:
        logger.error(f"Failed to load window state: {e}")
    return False

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
        self.feeding_manager = None
        self.memory_check_counter = 0
        self.last_frame_time = time.monotonic()  # Watchdog: ultimo frame processato
        self.usb_enabled = True  # Sovrascritto in build_pipeline() in base alla presenza del device

        # Detection processor generico
        self.detection_processor = DetectionProcessor()

        # === RTSP Multi-camera support ===
        self.rtsp_cameras = [c for c in TAPO_CAMERAS if c.get('enabled', True)]
        self.rtsp_threads = []
        self.rtsp_running = False
        self.appsrc = None
        # Ultimo frame ricevuto per sorgente (per comando Telegram /foto).
        # Chiavi: "USB" per la webcam locale, nome camera per ogni RTSP.
        # Valori: (frame BGR np.ndarray, datetime).
        self.last_frames = {}
        self.last_frames_lock = threading.Lock()

        # Mappa pts→sorgente per tracking thread-safe (resistente ai drop delle code leaky)
        self.source_map = {}  # {pts (int): (source, camera, monotonic_time)}
        self.source_map_lock = threading.Lock()
        self.pending_rtsp_lock = threading.Lock()

        # Inizializza prima il controller della finestra
        logger.info("Initializing window controller...")
        self.window_controller = WindowController()

        # Ripristina stato manuale/automatico se c'è stato un riavvio recente
        _load_window_state(self.window_controller)
        
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

    def _initialize_feeding_manager(self):
        """Inizializza il sistema di alimentazione gatti."""
        try:
            self.feeding_manager = CatFeedingManager()

            # Imposta callback per Telegram
            if self.telegram:
                self.feeding_manager.set_telegram_callbacks(
                    message_callback=self.telegram.send_message,
                    photo_callback=self.telegram.send_photo
                )

            # Registra il feeding manager per i comandi Telegram
            telegram_commands.set_feeding_manager(self.feeding_manager)

            # Avvia il client MQTT
            self.feeding_manager.start()
            logger.info("Cat feeding manager initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize feeding manager: {e}")
            self.feeding_manager = None

    def _initialize_detector(self):
        """Inizializza il rilevatore di gatti."""
        self.user_data = HeadlessCatDetectorCallback()
        # Passa il controller finestra al detector
        self.user_data.window_controller = self.window_controller

    def _initialize_rtsp_cameras(self):
        """Inizializza i thread decoder per telecamere RTSP."""
        if not self.rtsp_cameras:
            logger.info("No RTSP cameras configured")
            return False  # Non ripetere

        self.rtsp_running = True
        for camera in self.rtsp_cameras:
            thread = threading.Thread(
                target=self._rtsp_decoder_thread,
                args=(camera,),
                daemon=True,
                name=f"RTSP-{camera['name']}"
            )
            self.rtsp_threads.append(thread)
            thread.start()
            logger.info(f"RTSP decoder thread started for [{camera['name']}]")

        return False  # Non ripetere GLib timeout

    def _rtsp_decoder_thread(self, camera_config):
        """Thread che decodifica RTSP e inietta frame nel pipeline."""
        camera_name = camera_config['name']
        rtsp_url = camera_config['rtsp_url']
        detect_classes = camera_config.get('detect_classes', ['cat', 'person'])

        logger.info(f"[{camera_name}] Connecting to {rtsp_url}")

        cap = None
        last_inject = 0
        reconnect_delay = 5

        while self.rtsp_running:
            try:
                # Connetti se necessario
                if cap is None or not cap.isOpened():
                    cap = cv2.VideoCapture(rtsp_url)
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    if not cap.isOpened():
                        logger.warning(f"[{camera_name}] Failed to connect, retrying in {reconnect_delay}s")
                        time.sleep(reconnect_delay)
                        continue
                    logger.info(f"[{camera_name}] Connected")

                # Leggi frame
                ret, frame = cap.read()
                if not ret:
                    logger.warning(f"[{camera_name}] Failed to read frame, reconnecting...")
                    cap.release()
                    cap = None
                    time.sleep(1)
                    continue

                # Rispetta intervallo iniezione
                now = time.time()
                if now - last_inject < RTSP_INJECT_INTERVAL:
                    continue

                # Memorizza ultimo frame full-res BGR per /foto Telegram
                self._store_last_frame(camera_name, frame)

                # Letterbox resize a 640x640
                frame_resized = self._letterbox_resize(frame, 640, 640)
                frame_rgb = cv2.cvtColor(frame_resized, cv2.COLOR_BGR2RGB)

                # Salva camera name per il tagger (prima dell'iniezione)
                with self.pending_rtsp_lock:
                    self._last_rtsp_camera = camera_name

                # Inietta nel pipeline
                if self.appsrc:
                    buffer = self._create_gst_buffer(frame_rgb)
                    ret = self.appsrc.emit('push-buffer', buffer)
                    if ret != Gst.FlowReturn.OK:
                        logger.warning(f"[{camera_name}] Frame injection failed: {ret}")
                    last_inject = now

            except Exception as e:
                logger.error(f"[{camera_name}] Error: {e}")
                time.sleep(reconnect_delay)

        if cap:
            cap.release()
        logger.info(f"[{camera_name}] Decoder thread stopped")

    def _letterbox_resize(self, frame, target_w, target_h):
        """Ridimensiona preservando aspect ratio con padding nero."""
        h, w = frame.shape[:2]
        scale = min(target_w / w, target_h / h)
        new_w, new_h = int(w * scale), int(h * scale)

        resized = cv2.resize(frame, (new_w, new_h))

        # Crea immagine nera e centra il frame
        padded = np.zeros((target_h, target_w, 3), dtype=np.uint8)
        y_offset = (target_h - new_h) // 2
        x_offset = (target_w - new_w) // 2
        padded[y_offset:y_offset+new_h, x_offset:x_offset+new_w] = resized

        return padded

    # === Snapshot API per /foto Telegram ===

    def _store_last_frame(self, name, frame_bgr):
        """Memorizza l'ultimo frame BGR ricevuto per la sorgente 'name'.
        Fa una copia per non condividere memoria con il chiamante."""
        if frame_bgr is None:
            return
        try:
            snapshot = frame_bgr.copy()
        except Exception:
            return
        with self.last_frames_lock:
            self.last_frames[name] = (snapshot, datetime.now())

    def get_snapshot(self, name):
        """Restituisce (frame_bgr_copy, datetime) o None se non disponibile.
        Lookup case-insensitive sul nome."""
        target = name.lower()
        with self.last_frames_lock:
            for key, (frame, ts) in self.last_frames.items():
                if key.lower() == target:
                    return frame.copy(), ts
        return None

    def get_available_snapshots(self):
        """Lista [(name, datetime)] ordinata per nome."""
        with self.last_frames_lock:
            items = [(name, ts) for name, (_, ts) in self.last_frames.items()]
        return sorted(items, key=lambda x: x[0].lower())

    def _create_gst_buffer(self, frame):
        """Crea un GstBuffer da un numpy array RGB."""
        data = frame.tobytes()
        buffer = Gst.Buffer.new_allocate(None, len(data), None)
        buffer.fill(0, data)
        buffer.pts = Gst.CLOCK_TIME_NONE
        buffer.dts = Gst.CLOCK_TIME_NONE
        buffer.duration = Gst.CLOCK_TIME_NONE
        return buffer

    # === Camera Management API per Telegram ===

    def get_status(self) -> str:
        """Restituisce stato breve telecamere."""
        if not self.rtsp_cameras:
            return None
        active = sum(1 for c in self.rtsp_cameras if c.get('enabled', True))
        return f"{active}/{len(self.rtsp_cameras)} attive"

    def get_cameras_info(self) -> str:
        """Restituisce info dettagliate telecamere."""
        if not self.rtsp_cameras:
            return "Nessuna telecamera RTSP configurata"

        msg = "*Telecamere RTSP:*\n\n"
        for cam in self.rtsp_cameras:
            status = "+" if cam.get('enabled', True) else "-"
            classes = ", ".join(cam.get('detect_classes', ['cat', 'person']))
            msg += f"{status} *{cam['name']}*\n   Classi: {classes}\n"
        return msg

    def toggle_camera(self, name: str, enable: bool) -> bool:
        """Abilita/disabilita una telecamera (richiede restart)."""
        for cam in self.rtsp_cameras:
            if cam['name'].lower() == name.lower():
                cam['enabled'] = enable
                return True
        return False

    def build_pipeline(self):
        """Costruisce il pipeline GStreamer con supporto multi-sorgente.

        Se la webcam USB (self.input_source) non è disponibile, costruisce una
        pipeline solo-RTSP: il servizio parte comunque e fa notifiche dalle Tapo,
        ma il controllo finestra automatico è disattivato (gestibile via Telegram).
        """
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

        self.usb_enabled = os.path.exists(self.input_source)
        if not self.usb_enabled:
            if PRIMARY_RTSP_FALLBACK_CAMERA:
                mirror_note = " (coordinate specchiate)" if PRIMARY_RTSP_FALLBACK_MIRROR_X else ""
                logger.warning(
                    f"USB camera {self.input_source} not found — promoting RTSP "
                    f"'{PRIMARY_RTSP_FALLBACK_CAMERA}' to primary{mirror_note}: "
                    f"controllo finestra automatico ATTIVO via questa telecamera"
                )
            else:
                logger.warning(
                    f"USB camera {self.input_source} not found — entering RTSP-only mode "
                    f"(automatic window control disabled, Telegram commands still work)"
                )

        if self.usb_enabled:
            # Pipeline con funnel per multi-sorgente
            # USB camera -> usb_tagger -> funnel -> hailonet -> callback
            # appsrc (RTSP) -> rtsp_tagger -> funnel
            pipeline_str = f'''
                v4l2src device={self.input_source} !
                video/x-raw, width=640, height=480 !
                queue name=usb_scale_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 !
                videoscale name=usb_videoscale n-threads=2 !
                queue name=usb_convert_q leaky=no max-size-buffers=3 max-size-bytes=0 max-size-time=0 !
                videoconvert n-threads=3 name=usb_convert qos=false !
                video/x-raw, format=RGB, width=640, height=640, pixel-aspect-ratio=1/1 !
                identity name=usb_tagger !
                funnel name=source_funnel !
                queue name=inference_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0 !
                hailonet name=inference_hailonet hef-path={self.hef_path} batch-size=1 !
                queue name=filter_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0 !
                hailofilter name=inference_hailofilter so-path={post_process_so} qos=false !
                queue name=callback_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0 !
                identity name=identity_callback !
                fakesink sync=false name=sink

                appsrc name=rtsp_appsrc is-live=true format=time do-timestamp=true
                    caps=video/x-raw,format=RGB,width=640,height=640,framerate=1/1 !
                queue name=rtsp_q leaky=downstream max-size-buffers=2 max-size-bytes=0 max-size-time=0 !
                identity name=rtsp_tagger !
                source_funnel.
            '''
        else:
            # Pipeline solo-RTSP: appsrc è l'unica sorgente, niente funnel
            pipeline_str = f'''
                appsrc name=rtsp_appsrc is-live=true format=time do-timestamp=true
                    caps=video/x-raw,format=RGB,width=640,height=640,framerate=1/1 !
                queue name=rtsp_q leaky=downstream max-size-buffers=2 max-size-bytes=0 max-size-time=0 !
                identity name=rtsp_tagger !
                queue name=inference_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0 !
                hailonet name=inference_hailonet hef-path={self.hef_path} batch-size=1 !
                queue name=filter_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0 !
                hailofilter name=inference_hailofilter so-path={post_process_so} qos=false !
                queue name=callback_q leaky=downstream max-size-buffers=10 max-size-bytes=0 max-size-time=0 !
                identity name=identity_callback !
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
        """Configura callback e source tagging."""
        # Setup USB source tagger (presente solo se webcam USB disponibile)
        if getattr(self, 'usb_enabled', True):
            usb_tagger = self.pipeline.get_by_name("usb_tagger")
            if usb_tagger:
                pad = usb_tagger.get_static_pad("src")
                pad.add_probe(Gst.PadProbeType.BUFFER, self._tag_usb_buffer, None)

        # Setup RTSP source tagger
        rtsp_tagger = self.pipeline.get_by_name("rtsp_tagger")
        if rtsp_tagger:
            pad = rtsp_tagger.get_static_pad("src")
            pad.add_probe(Gst.PadProbeType.BUFFER, self._tag_rtsp_buffer, None)

        # Get appsrc reference
        self.appsrc = self.pipeline.get_by_name("rtsp_appsrc")
        if self.appsrc:
            logger.info("RTSP appsrc configured")

        # Setup main callback
        identity = self.pipeline.get_by_name("identity_callback")
        if not identity:
            raise RuntimeError("Cannot find identity_callback element")

        pad = identity.get_static_pad("src")
        if not pad:
            raise RuntimeError("Cannot find identity_callback src pad")

        # Passa riferimenti al callback
        if self.telegram:
            self.user_data.telegram = self.telegram
            # Permetti al TelegramHandler di accedere a user_data per /notifiche
            self.telegram.user_data = self.user_data

        # Passa riferimento all'app per accedere a detection_processor e pending_rtsp_frame
        self.user_data.app = self
        pad.add_probe(Gst.PadProbeType.BUFFER, app_callback, self.user_data)

    def _tag_usb_buffer(self, pad, info, user_data):
        """Marca buffer come proveniente da USB indicizzando per pts."""
        buffer = info.get_buffer()
        if buffer and buffer.pts != Gst.CLOCK_TIME_NONE:
            with self.source_map_lock:
                self.source_map[buffer.pts] = ('usb', None, time.monotonic())
        return Gst.PadProbeReturn.OK

    def _tag_rtsp_buffer(self, pad, info, user_data):
        """Marca buffer come proveniente da RTSP indicizzando per pts."""
        buffer = info.get_buffer()
        if buffer and buffer.pts != Gst.CLOCK_TIME_NONE:
            with self.pending_rtsp_lock:
                camera_name = getattr(self, '_last_rtsp_camera', 'unknown')
            with self.source_map_lock:
                self.source_map[buffer.pts] = ('rtsp', camera_name, time.monotonic())
        return Gst.PadProbeReturn.OK
    
    def start(self):
        """Avvia l'applicazione."""
        try:
            # Inizializza i componenti nell'ordine corretto
            self._initialize_telegram()
            self._initialize_feeding_manager()
            self._initialize_detector()

            self.pipeline = self.build_pipeline()
            self._setup_callback()

            # Registra camera manager per comandi Telegram
            telegram_commands.set_camera_manager(self)

            # Avvia il mainloop
            self.mainloop = GLib.MainLoop()

            # Bus handler per errori GStreamer/Hailo
            bus = self.pipeline.get_bus()
            bus.add_signal_watch()
            bus.connect("message", self._on_bus_message)

            self.pipeline.set_state(Gst.State.PLAYING)
            logger.info("Pipeline started successfully")

            # Avvia decoder RTSP dopo che il pipeline è attivo (delay 3 sec)
            if self.rtsp_cameras:
                GLib.timeout_add_seconds(3, self._initialize_rtsp_cameras)
                logger.info(f"RTSP cameras scheduled: {len(self.rtsp_cameras)}")

            # Watchdog: controlla ogni 30s che i frame continuino a fluire
            GLib.timeout_add_seconds(30, self._pipeline_watchdog)

            # Cleanup periodico della source_map (entry da buffer droppati)
            GLib.timeout_add_seconds(10, self._cleanup_source_map)

            self.mainloop.run()

        except Exception as e:
            logger.error(f"Error starting application: {e}", exc_info=True)
            if self.telegram:
                self.telegram.send_message(f"Errore durante l'avvio: {str(e)}")
            self.stop()
            raise

    def _on_bus_message(self, bus, message):
        """Gestisce messaggi dal bus GStreamer. Riavvia solo su errori da elementi critici."""
        msg_type = message.type
        if msg_type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            src_name = message.src.get_name() if message.src else "unknown"
            # Solo errori da sorgente USB o inferenza Hailo richiedono riavvio
            critical_names = ("inference_hailonet", "inference_hailofilter")
            is_critical = src_name in critical_names or src_name.startswith("v4l2src")
            if is_critical:
                logger.error(f"GStreamer critical error from {src_name}: {err.message}")
                logger.error(f"Debug info: {debug}")
                _save_window_state(self.window_controller)
                _mark_auto_restart(f"pipeline_error: {src_name}: {err.message[:80]}")
                os._exit(1)
            else:
                # Errori da appsrc RTSP o elementi non critici: log e continua
                # Il watchdog frame (60s) interviene se il pipeline si blocca davvero
                logger.warning(f"Non-critical pipeline error from {src_name}: {err.message} — continuing")
        elif msg_type == Gst.MessageType.WARNING:
            err, debug = message.parse_warning()
            logger.warning(f"GStreamer pipeline warning: {err.message}")
        elif msg_type == Gst.MessageType.EOS:
            logger.error("Pipeline reached end of stream unexpectedly")
            _save_window_state(self.window_controller)
            _mark_auto_restart("pipeline_eos")
            os._exit(1)

    def _pipeline_watchdog(self):
        """Controlla che i frame continuino a fluire. Riavvia se bloccato."""
        elapsed = time.monotonic() - self.last_frame_time
        if elapsed > 60:
            logger.error(f"Pipeline watchdog: no frames for {elapsed:.0f}s - restarting")
            _save_window_state(self.window_controller)
            _mark_auto_restart(f"watchdog_no_frames_{elapsed:.0f}s")
            os._exit(1)
        return True  # Continua il timer

    def _cleanup_source_map(self):
        """Rimuove entry stale dalla source_map (buffer droppati che non sono mai arrivati al callback)."""
        cutoff = time.monotonic() - 5.0
        with self.source_map_lock:
            stale = [k for k, v in self.source_map.items() if v[2] < cutoff]
            for k in stale:
                del self.source_map[k]
            current_size = len(self.source_map)
        if stale:
            logger.debug(f"source_map cleanup: removed {len(stale)} stale entries, size now {current_size}")
        return True  # Continua il timer

    def stop(self):
        """Ferma l'applicazione."""
        # Stop RTSP threads
        self.rtsp_running = False
        for thread in self.rtsp_threads:
            thread.join(timeout=2)
        self.rtsp_threads.clear()

        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
        if self.mainloop and self.mainloop.is_running():
            self.mainloop.quit()
        if self.feeding_manager:
            self.feeding_manager.stop()
        if self.telegram:
            self.telegram.send_message("Sistema di rilevamento arrestato")
        logger.info("Application stopped")

def app_callback(pad, info, user_data):
    """Callback principale - routing per sorgente (USB o RTSP)."""
    buffer = info.get_buffer()
    if buffer is None:
        return Gst.PadProbeReturn.OK

    # Frame counter e monitoring
    if not hasattr(app_callback, 'frame_count'):
        app_callback.frame_count = 0
        app_callback.last_log_time = datetime.now()
        app_callback.start_time = datetime.now()

    app_callback.frame_count += 1
    current_time = datetime.now()

    # Aggiorna watchdog
    if hasattr(user_data, 'app') and user_data.app:
        user_data.app.last_frame_time = time.monotonic()

    # Log e memory check ogni 100 frames
    if app_callback.frame_count % 100 == 0:
        elapsed = (current_time - app_callback.last_log_time).total_seconds()
        fps = 100 / elapsed if elapsed > 0 else 0
        src = user_data.current_source
        logger.info(f"Frame {app_callback.frame_count} (FPS: {fps:.1f}, src: {src})")
        app_callback.last_log_time = current_time

        # Memory check
        mem_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
        if mem_mb > MAX_MEMORY_MB:
            if hasattr(user_data, 'window_controller') and user_data.window_controller.is_window_open:
                logger.warning(f"MEMORY {mem_mb:.0f}MB - window OPEN, waiting")
            else:
                logger.error(f"MEMORY {mem_mb:.0f}MB - restarting")
                if hasattr(user_data, 'window_controller'):
                    _save_window_state(user_data.window_controller)
                _mark_auto_restart(f"memory_{mem_mb:.0f}MB")
                os._exit(1)

        # Uptime check
        uptime_hours = (current_time - app_callback.start_time).total_seconds() / 3600
        if uptime_hours > 12:
            if hasattr(user_data, 'window_controller') and user_data.window_controller.is_window_open:
                pass  # Skip restart se finestra aperta
            else:
                if hasattr(user_data, 'window_controller'):
                    _save_window_state(user_data.window_controller)
                _mark_auto_restart(f"uptime_{uptime_hours:.1f}h")
                os._exit(0)

    # Estrai frame
    format, width, height = get_caps_from_pad(pad)
    frame = None
    if format and width and height:
        frame = get_numpy_from_buffer(buffer, format, width, height)

    # === ROUTING PER SORGENTE (lookup per pts del buffer) ===
    source = None
    camera = None
    if buffer.pts != Gst.CLOCK_TIME_NONE and hasattr(user_data, 'app') and user_data.app:
        with user_data.app.source_map_lock:
            tag = user_data.app.source_map.pop(buffer.pts, None)
        if tag:
            source, camera, _ = tag

    if source is None:
        # Tag mancante: skip senza assumere USB, per evitare la falsa
        # didascalia "fai entrare" su frame RTSP. Logga raramente.
        if app_callback.frame_count % 500 == 0:
            logger.warning(f"Frame {app_callback.frame_count} pts={buffer.pts} senza source tag, skip")
        return Gst.PadProbeReturn.OK

    # Aggiorna user_data per compatibilità
    user_data.current_source = source
    user_data.current_camera = camera

    # Promozione RTSP a primary quando USB manca: una specifica camera
    # (PRIMARY_RTSP_FALLBACK_CAMERA) viene trattata come la sorgente USB.
    app = user_data.app
    primary_rtsp_active = (
        source == 'rtsp'
        and not getattr(app, 'usb_enabled', True)
        and PRIMARY_RTSP_FALLBACK_CAMERA is not None
        and camera == PRIMARY_RTSP_FALLBACK_CAMERA
    )

    # Cattura snapshot USB ~1 volta al secondo per il comando Telegram /foto
    if source == 'usb' and frame is not None:
        now_mono = time.monotonic()
        if now_mono - getattr(app, '_last_usb_snap_time', 0.0) >= 1.0:
            app._last_usb_snap_time = now_mono
            try:
                app._store_last_frame('USB', cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
            except Exception as e:
                logger.debug(f"USB snapshot store failed: {e}")

    if source == 'usb':
        _process_usb_frame(buffer, frame, user_data, current_time)
    elif primary_rtsp_active:
        _process_usb_frame(buffer, frame, user_data, current_time,
                           mirror_x=PRIMARY_RTSP_FALLBACK_MIRROR_X)
    else:
        _process_rtsp_frame(buffer, frame, user_data, current_time)

    return Gst.PadProbeReturn.OK


def _process_usb_frame(buffer, frame, user_data, current_time, mirror_x=False):
    """Processa frame USB - logica completa controllo finestra.

    Args:
        mirror_x: se True specchia orizzontalmente le coordinate (1-x). Usato per
            frame RTSP "promossi" a primary quando la geometria della camera ha
            la finestra a destra invece che a sinistra come la webcam USB.
    """
    # Usa DetectionProcessor se disponibile
    if hasattr(user_data, 'app') and user_data.app.detection_processor:
        result = user_data.app.detection_processor.process(
            buffer,
            detect_classes=['cat'],
            min_confidence=user_data.get_current_confidence_threshold(),
            source='usb'
        )

        # Converti result in formato legacy per compatibilità
        cats_info = []
        for det in result.detections:
            cats_info.append({
                'confidence': det.confidence,
                'center_x': det.center_x,
                'is_left': det.is_left,
                'xmin': det.xmin,
                'xmax': det.xmax
            })
    else:
        # Fallback: estrazione manuale
        roi = hailo.get_roi_from_buffer(buffer)
        detections = roi.get_objects_typed(hailo.HAILO_DETECTION)
        current_threshold = user_data.get_current_confidence_threshold()

        cats_info = []
        for detection in detections:
            if detection.get_label() == "cat" and detection.get_confidence() >= current_threshold:
                bbox = detection.get_bbox()
                xmin, xmax = float(bbox.xmin()), float(bbox.xmax())
                center_x = (xmin + xmax) / 2
                cats_info.append({
                    'confidence': detection.get_confidence(),
                    'center_x': center_x,
                    'is_left': center_x < 0.5,
                    'xmin': xmin,
                    'xmax': xmax
                })

    # Mirror orizzontale per camere con finestra a destra (primary RTSP fallback)
    if mirror_x:
        for c in cats_info:
            c['center_x'] = 1.0 - c['center_x']
            c['xmin'], c['xmax'] = 1.0 - c['xmax'], 1.0 - c['xmin']
            c['is_left'] = c['center_x'] < 0.5

    # Logica esistente per controllo finestra
    cat_left = any(c['is_left'] for c in cats_info)
    cat_right = any(not c['is_left'] for c in cats_info)
    total_cats = len(cats_info)
    max_confidence = max((c['confidence'] for c in cats_info), default=0.0)
    best_cat = max(cats_info, key=lambda c: c['confidence']) if cats_info else None

    # Filtro temporale
    filtered_cat_left = user_data.update_detection_filter(cat_left, current_time)

    if cat_right:
        user_data.last_right_detection_time = current_time

    time_since_right = (current_time - user_data.last_right_detection_time) if user_data.last_right_detection_time else timedelta(seconds=999)
    no_recent_right = time_since_right > timedelta(seconds=5)

    should_open_window = filtered_cat_left and no_recent_right
    # Gatti nella zona di chiusura (entro il 60% sinistro) - la finestra non può chiudersi se presenti
    cat_in_close_zone = any(c['center_x'] < 0.7 for c in cats_info)
    user_data.process_cat_detection(frame, max_confidence, should_open_window, current_time, best_cat, cat_in_close_zone, total_cats=total_cats)

    # Tracking movimento
    if total_cats == 1 and best_cat:
        user_data.track_cat_movement(total_cats, 'left' if best_cat['is_left'] else 'right', current_time)
    else:
        user_data.track_cat_movement(total_cats, None, current_time)

    # Foto gatto fuori
    if frame is not None and cat_right and best_cat and not best_cat['is_left']:
        frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        saved_path = user_data.save_cat_image(frame_bgr, max_confidence)
        if saved_path and hasattr(user_data, 'telegram') and user_data.telegram:
            caption = "Gatto presente fuori.\nUsa /faientrare per aprire"
            user_data.telegram.send_photo(saved_path, caption=caption)


def _process_rtsp_frame(buffer, frame, user_data, current_time):
    """Processa frame RTSP - solo notifiche, no controllo finestra."""
    # Check se notifiche RTSP sono abilitate
    if not getattr(user_data, 'rtsp_notifications_enabled', True):
        return

    camera_name = user_data.current_camera or 'unknown'

    # Usa DetectionProcessor
    if hasattr(user_data, 'app') and user_data.app.detection_processor:
        result = user_data.app.detection_processor.process(
            buffer,
            detect_classes=['cat', 'person'],
            min_confidence=0.7,
            source=camera_name
        )

        for det in result.detections:
            # Check cooldown
            if not user_data.can_send_rtsp_notification(camera_name, det.label):
                continue

            emoji = {'cat': '🐱', 'person': '👤'}.get(det.label, '📦')
            message = (
                f"[{camera_name}]\n"
                f"{emoji} {det.label.capitalize()} ({det.confidence:.0%})\n"
                f"{current_time.strftime('%H:%M:%S')}"
            )

            logger.info(f"[{camera_name}] {det.label} detected ({det.confidence:.2f})")

            if hasattr(user_data, 'telegram') and user_data.telegram:
                if frame is not None:
                    saved_path = user_data.save_rtsp_image(frame, camera_name, det.label, det.confidence)
                    if saved_path:
                        user_data.telegram.send_photo(saved_path, caption=message)
                else:
                    user_data.telegram.send_message(message)

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