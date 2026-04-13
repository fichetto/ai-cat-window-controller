"""
Controller per la finestra motorizzata con serratura.
"""

import os
import sys
import json
import logging
import subprocess
import threading
import time
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class WindowController:
    def __init__(self):
        """Inizializza il controller della finestra."""
        self.CLOSED_ANGLE = 77   # Angolo di chiusura
        self.OPEN_ANGLE = 120    # Angolo di apertura
        self.LOCK_CLOSED = 0     # Angolo serratura chiusa
        self.LOCK_OPEN = 90      # Angolo serratura aperta

        self.current_angle = self.CLOSED_ANGLE
        self.target_angle = self.CLOSED_ANGLE
        self.current_lock_angle = self.LOCK_CLOSED
        self.target_lock_angle = self.LOCK_CLOSED

        self.last_command_time = None
        self.command_cooldown = timedelta(seconds=5)
        self.manual_mode = False  # Flag per modalità manuale
        self._movement_lock = threading.Lock()  # Lock per prevenire comandi concorrenti
        self._is_moving = False  # Flag per indicare movimento in corso
        self.is_window_open = False
        self.is_window_locked = True
        self.last_let_in_time = None  # Timestamp ultimo /faientrare
        self.let_in_timer_reset_needed = False  # Flag per resettare il timer di chiusura

        # Setup percorso script - usa lo stesso Python del processo corrente
        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        self.window_script = os.path.join(self.script_dir, "cat_window.py")
        self.python_exe = sys.executable  # Usa il Python corrente (venv)
        logger.info(f"Window controller initialized with script at: {self.window_script}")
        logger.info(f"Window controller now supports lock functionality")

    def _execute_window_command(self, command, *args):
        """
        Esegue un comando per la finestra.
        
        Args:
            command: Comando da eseguire
            *args: Argomenti aggiuntivi
            
        Returns:
            bool: True se il comando è riuscito, False altrimenti
        """
        try:
            cmd_args = [self.python_exe, self.window_script, command]
            for arg in args:
                cmd_args.append(str(arg))
                
            logger.info(f"Executing window command: {' '.join(cmd_args)}")
            result = subprocess.run(cmd_args, capture_output=True, text=True, check=True)
            
            logger.info(f"Window command completed successfully")
            return True
        except Exception as e:
            logger.error(f"Error executing window command: {e}")
            return False

    def _execute_window_command_with_output(self, command, *args):
        """
        Esegue un comando per la finestra e ritorna anche lo stdout.

        Returns:
            tuple: (success: bool, stdout: str)
        """
        try:
            cmd_args = [self.python_exe, self.window_script, command]
            for arg in args:
                cmd_args.append(str(arg))

            logger.info(f"Executing window command (with output): {' '.join(cmd_args)}")
            result = subprocess.run(cmd_args, capture_output=True, text=True, check=True)
            return True, result.stdout.strip()
        except subprocess.CalledProcessError as e:
            logger.error(f"Window command failed: {e.stderr}")
            return False, e.stdout.strip() if e.stdout else ""
        except Exception as e:
            logger.error(f"Error executing window command: {e}")
            return False, ""

    def read_servo_angles(self):
        """
        Legge gli angoli attuali dei servo dall'hardware.

        Returns:
            dict: {"window": float, "lock": float} oppure None
        """
        success, output = self._execute_window_command_with_output('leggi')
        if not success:
            logger.error("Failed to read servo angles")
            return None
        try:
            # L'output può contenere messaggi di connessione prima del JSON
            # Prendi solo l'ultima riga che contiene il JSON
            lines = output.strip().split('\n')
            json_line = lines[-1]
            angles = json.loads(json_line)
            if "error" in angles:
                logger.error(f"Hardware read error: {angles['error']}")
                return None
            return angles
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Failed to parse servo angles: {e}, output: {output}")
            return None

    def step_servo(self, servo_type, delta):
        """
        Muove un servo di delta gradi. Per uso manuale d'emergenza.
        Nessun cooldown, entra automaticamente in modalità manuale.

        Args:
            servo_type: "window" o "lock"
            delta: gradi da muovere (positivo o negativo)

        Returns:
            tuple: (success: bool, target_angle: float, readback_angle: float)
        """
        self.manual_mode = True

        with self._movement_lock:
            self._is_moving = True
            try:
                # Leggi posizione attuale
                angles = self.read_servo_angles()
                if angles is None:
                    return False, 0, 0

                current = angles[servo_type]
                target = current + delta

                # Invia comando
                if servo_type == "window":
                    cmd = "finestra"
                else:
                    cmd = "serratura"

                success = self._execute_window_command(cmd, target)
                if not success:
                    return False, target, current

                time.sleep(0.5)

                # Rileggi posizione
                angles = self.read_servo_angles()
                if angles is None:
                    readback = target  # Assume target raggiunto
                else:
                    readback = angles[servo_type]

                # Aggiorna stato interno
                if servo_type == "window":
                    self.current_angle = readback
                    self.target_angle = target
                    self.is_window_open = (readback > self.CLOSED_ANGLE + 5)
                else:
                    self.current_lock_angle = readback
                    self.target_lock_angle = target
                    self.is_window_locked = (readback < 10)

                logger.info(f"Step servo {servo_type}: {current:.1f}° → {target:.1f}° (readback: {readback:.1f}°)")
                return True, target, readback
            finally:
                self._is_moving = False

    def sync_state_from_hardware(self):
        """
        Sincronizza lo stato interno con la posizione reale dei servo.
        Da chiamare dopo il controllo manuale step.

        Returns:
            dict: {"window": float, "lock": float} oppure None
        """
        angles = self.read_servo_angles()
        if angles is None:
            return None

        self.current_angle = angles["window"]
        self.current_lock_angle = angles["lock"]
        self.is_window_open = (angles["window"] > self.CLOSED_ANGLE + 5)
        self.is_window_locked = (angles["lock"] < 10)

        logger.info(f"State synced from hardware: window={angles['window']:.1f}° "
                    f"({'open' if self.is_window_open else 'closed'}), "
                    f"lock={angles['lock']:.1f}° "
                    f"({'locked' if self.is_window_locked else 'unlocked'})")
        return angles

    def set_window_position(self, should_be_open, manual=False):
        """
        Imposta la posizione della finestra, gestendo anche la serratura.

        Args:
            should_be_open (bool): True per aprire la finestra, False per chiuderla
            manual (bool): True se il comando viene da un'interazione manuale

        Returns:
            bool: True se il comando è stato inviato, False se era già nella posizione
                 richiesta o se è in cooldown
        """
        # Blocca se c'è un movimento in corso
        if self._is_moving:
            logger.warning("Movement in progress, ignoring command")
            return False

        current_time = datetime.now()

        if (self.last_command_time is not None and
            current_time - self.last_command_time < self.command_cooldown):
            logger.info(f"Command cooldown active. Please wait.")
            return False

        # Imposta la modalità manuale se richiesto
        if manual:
            self.manual_mode = True
            logger.info("Entering manual mode")

        # Se lo stato richiesto è uguale a quello attuale, non fare nulla
        # TRANNE se è un comando manuale (che deve sempre eseguire)
        if should_be_open == self.is_window_open and not manual:
            logger.debug(f"Window is already {'open' if should_be_open else 'closed'}")
            return False

        # Acquisisce il lock per prevenire comandi concorrenti
        with self._movement_lock:
            self._is_moving = True
            try:
                # Esegui il comando appropriato
                if should_be_open:
                    success = self._execute_window_command('apri')
                    if success:
                        self.current_angle = self.OPEN_ANGLE
                        self.target_angle = self.OPEN_ANGLE
                        self.current_lock_angle = self.LOCK_OPEN
                        self.target_lock_angle = self.LOCK_OPEN
                        self.is_window_open = True
                        self.is_window_locked = False
                else:
                    success = self._execute_window_command('chiudi')
                    if success:
                        self.current_angle = self.CLOSED_ANGLE
                        self.target_angle = self.CLOSED_ANGLE
                        self.current_lock_angle = self.LOCK_CLOSED
                        self.target_lock_angle = self.LOCK_CLOSED
                        self.is_window_open = False
                        self.is_window_locked = True

                if success:
                    self.last_command_time = datetime.now()
                    logger.info(f"Window successfully {'opened' if should_be_open else 'closed'}")
                    return True
                else:
                    logger.error(f"Failed to {'open' if should_be_open else 'close'} window")
                    return False
            finally:
                self._is_moving = False

    def set_lock_position(self, should_be_locked, manual=False):
        """
        Imposta la posizione della serratura.

        Args:
            should_be_locked (bool): True per bloccare la serratura, False per sbloccarla
            manual (bool): True se il comando viene da un'interazione manuale

        Returns:
            bool: True se il comando è stato inviato, False se era già nella posizione
                 richiesta o se è in cooldown
        """
        # Blocca se c'è un movimento in corso
        if self._is_moving:
            logger.warning("Movement in progress, ignoring lock command")
            return False

        current_time = datetime.now()

        if (self.last_command_time is not None and
            current_time - self.last_command_time < self.command_cooldown):
            logger.info(f"Command cooldown active. Please wait.")
            return False

        # Imposta la modalità manuale se richiesto
        if manual:
            self.manual_mode = True
            logger.info("Entering manual mode")

        # Se lo stato richiesto è uguale a quello attuale, non fare nulla
        # TRANNE se è un comando manuale (che deve sempre eseguire)
        if should_be_locked == self.is_window_locked and not manual:
            logger.info(f"Lock is already {'locked' if should_be_locked else 'unlocked'}")
            return False

        # Acquisisce il lock per prevenire comandi concorrenti
        with self._movement_lock:
            self._is_moving = True
            try:
                # Esegui il comando appropriato
                if should_be_locked:
                    success = self._execute_window_command('blocca')
                    if success:
                        self.current_lock_angle = self.LOCK_CLOSED
                        self.target_lock_angle = self.LOCK_CLOSED
                        self.is_window_locked = True
                else:
                    success = self._execute_window_command('sblocca')
                    if success:
                        self.current_lock_angle = self.LOCK_OPEN
                        self.target_lock_angle = self.LOCK_OPEN
                        self.is_window_locked = False

                if success:
                    self.last_command_time = datetime.now()
                    logger.info(f"Lock successfully {'locked' if should_be_locked else 'unlocked'}")
                    return True
                else:
                    logger.error(f"Failed to {'lock' if should_be_locked else 'unlock'}")
                    return False
            finally:
                self._is_moving = False

    def set_window_angle(self, angle, manual=False):
        """
        Imposta un angolo specifico per la finestra.

        Args:
            angle (float): Angolo desiderato (77-120 gradi)
            manual (bool): True se il comando viene da un'interazione manuale

        Returns:
            bool: True se il comando è stato inviato, False altrimenti
        """
        # Blocca se c'è un movimento in corso
        if self._is_moving:
            logger.warning("Movement in progress, ignoring angle command")
            return False

        current_time = datetime.now()

        if (self.last_command_time is not None and
            current_time - self.last_command_time < self.command_cooldown):
            return False

        # Imposta la modalità manuale se richiesto
        if manual:
            self.manual_mode = True
            logger.info("Entering manual mode")

        # Verifica che l'angolo sia nel range valido
        if not (self.CLOSED_ANGLE <= angle <= self.OPEN_ANGLE):
            logger.error(f"Angle {angle} out of range ({self.CLOSED_ANGLE}-{self.OPEN_ANGLE})")
            return False

        # Se la finestra è chiusa, prima sblocca la serratura
        if self.is_window_locked:
            logger.info("Unlocking window before adjusting angle")
            if not self.set_lock_position(False, manual):
                logger.error("Failed to unlock window")
                return False
            # Breve pausa per assicurarsi che la serratura sia sbloccata
            import time
            time.sleep(1)

        # Acquisisce il lock per prevenire comandi concorrenti
        with self._movement_lock:
            self._is_moving = True
            try:
                # Imposta l'angolo della finestra
                success = self._execute_window_command('finestra', angle)

                if success:
                    self.current_angle = angle
                    self.target_angle = angle
                    self.is_window_open = (angle > self.CLOSED_ANGLE + 5)
                    self.last_command_time = datetime.now()
                    logger.info(f"Window angle set to {angle}°")
                    return True
                else:
                    logger.error(f"Failed to set window angle to {angle}°")
                    return False
            finally:
                self._is_moving = False

    def auto_control_enabled(self):
        """
        Verifica se il controllo automatico è abilitato.

        Returns:
            bool: True se il controllo automatico è abilitato
        """
        return not self.manual_mode

    def set_let_in_time(self):
        """Imposta il timestamp di 'let-in' per estendere il tempo prima della chiusura."""
        self.last_let_in_time = datetime.now()
        self.let_in_timer_reset_needed = True  # Flag per resettare il timer nel callback
        logger.info("Let-in time set - close timer will be reset")

    def get_close_delay_extension(self):
        """
        Restituisce l'estensione del delay di chiusura dopo un 'let-in'.

        Returns:
            timedelta: Estensione del tempo (3 secondi se recente let-in, 0 altrimenti)
        """
        if self.last_let_in_time is None:
            return timedelta(seconds=0)

        # Se il let-in è avvenuto negli ultimi 30 secondi, estendi il tempo di chiusura
        time_since_let_in = datetime.now() - self.last_let_in_time
        if time_since_let_in < timedelta(seconds=30):
            return timedelta(seconds=3)

        return timedelta(seconds=0)

    def disable_auto_control(self):
        """Disabilita il controllo automatico."""
        self.manual_mode = True
        logger.info("Automatic control disabled")

    def enable_auto_control(self):
        """Abilita il controllo automatico."""
        self.manual_mode = False
        logger.info("Automatic control enabled")
