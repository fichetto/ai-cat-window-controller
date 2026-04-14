#!/usr/bin/env python3
"""
Callback handler per il rilevamento dei gatti e la gestione della finestra.
"""

import os
import json
import cv2
import logging
from datetime import datetime, timedelta
from hailo_rpi_common import app_callback_class

# Configurazione logging
logger = logging.getLogger(__name__)

# File persistente per le preferenze notifiche RTSP (non in /tmp/ per sopravvivere ai reboot)
RTSP_SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.rtsp_notifications.json')

class HeadlessCatDetectorCallback(app_callback_class):
    """
    Gestisce la logica di rilevamento dei gatti e il controllo della finestra.
    Implementa una soglia di confidenza adattiva basata sullo stato della finestra.
    """
    
    def __init__(self):
        """Inizializza il detector con configurazione predefinita."""
        super().__init__()
        self.window_controller = None  # Verrà impostato da headless_detection.py

        # Il gestore Telegram verrà impostato dall'applicazione principale
        self.telegram = None

        # === Source tracking per multi-camera ===
        self.current_source = 'usb'  # 'usb' o 'rtsp'
        self.current_camera = None   # Nome camera RTSP (None per USB)
        self.rtsp_notification_cooldowns = {}  # {(camera, label): last_time}
        self.rtsp_notification_cooldown = timedelta(seconds=60)  # Cooldown 1 minuto
        self.rtsp_save_dir = "detected_objects"
        self.rtsp_notifications_enabled = True  # Flag per abilitare/disabilitare notifiche RTSP
        self._load_rtsp_notifications()  # Ripristina preferenza salvata

        # Configurazione soglie di confidenza
        self.min_confidence_closed = 0.8  # Soglia quando finestra chiusa (alzata per ridurre falsi positivi)
        self.min_confidence_open = 0.7    # Soglia ridotta quando finestra aperta

        # Parametri temporali
        self.last_cat_time = None
        self.last_no_cat_time = None
        self.required_detection_time = timedelta(seconds=10)
        self.required_no_detection_time = timedelta(seconds=3)

        # Filtro rilevazioni con buffer più lungo per finestra aperta
        self.detection_filter_window = timedelta(seconds=5)
        self.recent_detections = []
        self.last_right_detection_time = None  # Traccia ultima rilevazione a destra

        # Configurazione salvataggio immagini
        self.save_dir = "detected_cats"
        self.ensure_save_directory()
        self.last_capture_time = None
        self.capture_cooldown = timedelta(seconds=30)
        self.capture_confidence_threshold = 0.8  # Alzata per ridurre falsi positivi

        # Tracking transizione manual → auto (per reset timer)
        self._was_manual_mode = False

        # Tracking movimento gatto (per rilevare entrata/uscita)
        self.last_single_cat_position = None  # 'left' o 'right' - ultima posizione con 1 solo gatto
        self.last_single_cat_time = None  # Quando è stata vista l'ultima posizione
        self.window_opened_for_entry = False  # True se finestra aperta con /faientrare
        self.window_opened_for_exit = False  # True se finestra aperta automaticamente (gatto dentro vuole uscire)

        # Cooldown progressivo anti-oscillazione (Waffle che guarda dalla finestra)
        self.auto_cycle_count = 0
        self.last_auto_open_time = None
        self.last_auto_close_time = None
        self.cooldown_until = None
        self.cooldown_base = 30          # 30s, 60s, 120s, 240s...
        self.cooldown_multiplier = 2
        self.cooldown_max = 240          # Cap a 4 minuti
        self.cat_gone_reset = timedelta(minutes=2)  # Reset cooldown se gatto assente per 2 min
        self.last_cat_seen_time = None   # Ultimo momento in cui un gatto è stato visto

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

    def track_cat_movement(self, total_cats, cat_position, current_time):
        """
        Traccia il movimento del gatto per rilevare entrata/uscita.

        Args:
            total_cats (int): Numero totale di gatti rilevati
            cat_position (str): 'left' o 'right' - posizione del gatto (se singolo)
            current_time (datetime): Timestamp corrente

        Returns:
            str or None: 'entered', 'exited', o None se nessun movimento rilevato
        """
        # Solo se c'è esattamente 1 gatto possiamo tracciare il movimento
        if total_cats != 1:
            # Reset tracking se non c'è un gatto singolo
            if total_cats == 0:
                # Nessun gatto - se la finestra era aperta e c'era un gatto prima,
                # potrebbe essere passato (ma non possiamo essere sicuri della direzione)
                pass
            return None

        # C'è esattamente 1 gatto
        previous_position = self.last_single_cat_position
        previous_time = self.last_single_cat_time

        # Aggiorna la posizione corrente
        self.last_single_cat_position = cat_position
        self.last_single_cat_time = current_time

        # Se non avevamo una posizione precedente, non possiamo rilevare movimento
        if previous_position is None:
            return None

        # Verifica che il cambio sia recente (entro 10 secondi)
        if previous_time and (current_time - previous_time) > timedelta(seconds=10):
            # Troppo tempo passato, non è un movimento continuo
            return None

        # Rileva cambio di posizione
        if previous_position != cat_position:
            if previous_position == 'left' and cat_position == 'right':
                # SINISTRA → DESTRA = Il gatto è USCITO
                if self.window_controller.is_window_open:
                    logger.info("🚪➡️ MOVIMENTO RILEVATO: Gatto passato da SINISTRA a DESTRA = USCITO!")
                    if self.telegram:
                        self.telegram.send_message("🐱➡️🚪 Gatto USCITO! (da sinistra a destra)")
                    return 'exited'

            elif previous_position == 'right' and cat_position == 'left':
                # DESTRA → SINISTRA = Il gatto è ENTRATO
                if self.window_controller.is_window_open:
                    logger.info("🚪⬅️ MOVIMENTO RILEVATO: Gatto passato da DESTRA a SINISTRA = ENTRATO!")
                    if self.telegram:
                        self.telegram.send_message("🐱⬅️🏠 Gatto ENTRATO! (da destra a sinistra)")
                    return 'entered'

        return None

    def _compute_auto_open_cooldown(self):
        """Calcola il cooldown progressivo basato sul numero di cicli."""
        if self.auto_cycle_count <= 0:
            return timedelta(seconds=0)
        seconds = min(
            self.cooldown_base * (self.cooldown_multiplier ** (self.auto_cycle_count - 1)),
            self.cooldown_max
        )
        return timedelta(seconds=seconds)

    def _reset_cooldown(self, reason=""):
        """Resetta il cooldown progressivo."""
        if self.auto_cycle_count > 0:
            logger.info(f"Cooldown progressivo RESET (era ciclo {self.auto_cycle_count}). Motivo: {reason}")
        self.auto_cycle_count = 0
        self.cooldown_until = None

    def process_cat_detection(self, frame, max_confidence, should_open_window, current_time, best_cat=None, cat_in_close_zone=False, total_cats=0):
        """
        Elabora il rilevamento del gatto e gestisce lo stato della finestra.

        Args:
            frame (numpy.ndarray): Frame video corrente
            max_confidence (float): Massima confidenza rilevata nel frame
            should_open_window (bool): Se True, aprire la finestra (gatto a sinistra, solo uno)
            current_time (datetime): Timestamp corrente
            best_cat (dict): Info sul gatto con confidence maggiore (opzionale)
            cat_in_close_zone (bool): Se True, c'è un gatto entro il 70% sinistro del frame
            total_cats (int): Numero totale di gatti rilevati nel frame
        """
        # Verifica se il controllo automatico è abilitato
        current_manual = self.window_controller.manual_mode
        if current_manual:
            self._was_manual_mode = True
            return

        # Se appena passato da manuale ad automatico, resetta i timer
        # per evitare chiusura immediata basata su timer stale
        if self._was_manual_mode:
            self._was_manual_mode = False
            self.last_cat_time = None
            self.last_no_cat_time = None
            self.last_cat_seen_time = None
            self._reset_cooldown("uscita da modalità manuale")
            logger.info("Auto mode re-enabled - detection timers reset")

        # Reset cooldown se il gatto è assente da 2 minuti
        if (self.last_cat_seen_time is not None and
                current_time - self.last_cat_seen_time > self.cat_gone_reset):
            self._reset_cooldown("gatto assente >2 minuti")

        # Reset cooldown se ci sono 2+ gatti con almeno uno nella zona sinistra
        if total_cats >= 2 and cat_in_close_zone:
            self._reset_cooldown("secondo gatto rilevato a sinistra")

        current_threshold = self.get_current_confidence_threshold()

        # Aggiorna timestamp ultimo avvistamento gatto (qualsiasi posizione)
        if total_cats > 0:
            self.last_cat_seen_time = current_time

        if should_open_window:
            if self.last_cat_time is None:
                self.last_cat_time = current_time
                logger.info(f"Cat detected (LEFT, single) with confidence {max_confidence:.2f} " +
                          f"(threshold: {current_threshold:.2f})")
            self.last_no_cat_time = None

            cat_present_time = current_time - self.last_cat_time
            if cat_present_time >= self.required_detection_time:
                # Cooldown progressivo anti-oscillazione
                if self.cooldown_until and current_time < self.cooldown_until:
                    remaining = int((self.cooldown_until - current_time).total_seconds())
                    logger.info(f"Cooldown progressivo attivo: {remaining}s rimanenti (ciclo {self.auto_cycle_count})")
                    return

                if self.window_controller.set_window_position(True, manual=False):
                    self.last_auto_open_time = current_time
                    # Crea messaggio con info posizione
                    message = "🐱 Gatto a sinistra (solo), apro la finestra"
                    if best_cat:
                        position_pct = best_cat['center_x'] * 100
                        message += f"\n• Posizione: {position_pct:.1f}%"
                        message += f"\n• Confidenza: {best_cat['confidence']:.2f}"

                    logger.info(f"Opening window - {message}")
                    if self.telegram:
                        self.telegram.send_window_status(True, message)
        else:
            # Nessun gatto a sinistra (o multipli gatti) - chiudi finestra
            # Ma solo se non c'è nessun gatto nella zona di chiusura (entro 60% sinistro)
            if cat_in_close_zone:
                # C'è ancora un gatto nella zona di chiusura, non avviare il timer
                self.last_no_cat_time = None
                logger.debug("Cat still in close zone (<70%), not starting close timer")
                return

            if self.last_no_cat_time is None:
                self.last_no_cat_time = current_time
                logger.info("No cat in close zone (<70%) - starting close timer " +
                           f"(using threshold: {current_threshold:.2f})")
            self.last_cat_time = None

            # Controlla se è stato eseguito /faientrare - resetta il timer di chiusura
            if self.window_controller.let_in_timer_reset_needed:
                self.last_no_cat_time = current_time  # Resetta il timer
                self.window_controller.let_in_timer_reset_needed = False
                logger.info("Close timer reset due to /faientrare command")

            if self.last_no_cat_time is not None:
                cat_absent_time = current_time - self.last_no_cat_time
                # Aggiungi estensione tempo chiusura dopo /faientrare (3 secondi extra)
                close_delay = self.required_no_detection_time + self.window_controller.get_close_delay_extension()
                if cat_absent_time >= close_delay:
                    if self.window_controller.set_window_position(False):
                        self.last_auto_close_time = current_time

                        # Rileva ciclo di oscillazione automatico
                        if self.last_auto_open_time is not None:
                            time_open = current_time - self.last_auto_open_time
                            if time_open < timedelta(seconds=60):
                                # Ciclo breve = oscillazione (Waffle)
                                self.auto_cycle_count += 1
                                cooldown = self._compute_auto_open_cooldown()
                                self.cooldown_until = current_time + cooldown
                                logger.info(f"Ciclo auto #{self.auto_cycle_count} "
                                           f"(aperta {time_open.seconds}s). "
                                           f"Cooldown: {cooldown.seconds}s")
                                if self.telegram:
                                    self.telegram.send_message(
                                        f"🔄 Ciclo auto apertura→chiusura #{self.auto_cycle_count} "
                                        f"(finestra aperta {time_open.seconds}s).\n"
                                        f"⏳ Cooldown: {int(cooldown.total_seconds())}s prima della prossima apertura automatica."
                                    )
                            else:
                                # Finestra aperta a lungo = uso genuino
                                self._reset_cooldown("finestra aperta >60s (uso genuino)")
                            self.last_auto_open_time = None

                        message = f"Nessun gatto a sinistra da {cat_absent_time.seconds}s, chiudo finestra"
                        logger.info(f"Closing window - {message}")
                        if self.telegram:
                            self.telegram.send_window_status(False, message)

    # === Metodi per RTSP multi-camera ===

    def _load_rtsp_notifications(self):
        """Carica preferenza notifiche RTSP da file persistente."""
        try:
            if os.path.exists(RTSP_SETTINGS_FILE):
                with open(RTSP_SETTINGS_FILE, 'r') as f:
                    settings = json.load(f)
                self.rtsp_notifications_enabled = settings.get('rtsp_notifications_enabled', True)
                logger.info(f"RTSP notifications loaded: {'enabled' if self.rtsp_notifications_enabled else 'disabled'}")
        except Exception as e:
            logger.error(f"Failed to load RTSP settings: {e}")

    def save_rtsp_notifications(self):
        """Salva preferenza notifiche RTSP su file persistente."""
        try:
            with open(RTSP_SETTINGS_FILE, 'w') as f:
                json.dump({'rtsp_notifications_enabled': self.rtsp_notifications_enabled}, f)
            logger.info(f"RTSP notifications saved: {'enabled' if self.rtsp_notifications_enabled else 'disabled'}")
        except Exception as e:
            logger.error(f"Failed to save RTSP settings: {e}")

    def can_send_rtsp_notification(self, camera_name, label):
        """
        Verifica se è possibile inviare una notifica per una camera RTSP.

        Args:
            camera_name (str): Nome della camera
            label (str): Classe rilevata (cat, person, etc.)

        Returns:
            bool: True se può inviare notifica (cooldown scaduto)
        """
        key = (camera_name, label)
        current_time = datetime.now()

        last_time = self.rtsp_notification_cooldowns.get(key)
        if last_time is None or (current_time - last_time) >= self.rtsp_notification_cooldown:
            self.rtsp_notification_cooldowns[key] = current_time
            return True
        return False

    def save_rtsp_image(self, frame, camera_name, label, confidence):
        """
        Salva un'immagine rilevata da camera RTSP.

        Args:
            frame (numpy.ndarray): Frame da salvare (BGR)
            camera_name (str): Nome della camera
            label (str): Classe rilevata
            confidence (float): Confidenza del rilevamento

        Returns:
            str: Percorso del file salvato
        """
        # Crea directory per camera se non esiste
        camera_dir = os.path.join(self.rtsp_save_dir, camera_name.lower().replace(' ', '_'))
        os.makedirs(camera_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{camera_dir}/{label}_{timestamp}_{confidence:.2f}.jpg"

        try:
            # Converti da RGB a BGR se necessario
            if frame is not None and len(frame.shape) == 3:
                frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                cv2.imwrite(filename, frame_bgr)
                logger.info(f"[{camera_name}] Image saved: {filename}")
                return filename
        except Exception as e:
            logger.error(f"[{camera_name}] Error saving image: {e}")

        return None