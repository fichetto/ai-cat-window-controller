"""
Controller per la finestra motorizzata con serratura.
"""

import os
import logging
import subprocess
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
        self.is_window_open = False
        self.is_window_locked = True
        
        # Setup percorso script
        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        self.window_script = os.path.join(self.script_dir, "cat_window.py")
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
            cmd_args = ['python3', self.window_script, command]
            for arg in args:
                cmd_args.append(str(arg))
                
            logger.info(f"Executing window command: {' '.join(cmd_args)}")
            result = subprocess.run(cmd_args, capture_output=True, text=True, check=True)
            
            logger.info(f"Window command completed successfully")
            return True
        except Exception as e:
            logger.error(f"Error executing window command: {e}")
            return False

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
            logger.info(f"Window is already {'open' if should_be_open else 'closed'}")
            return False

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
            self.last_command_time = current_time
            logger.info(f"Window successfully {'opened' if should_be_open else 'closed'}")
            return True
        else:
            logger.error(f"Failed to {'open' if should_be_open else 'close'} window")
            return False

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
            self.last_command_time = current_time
            logger.info(f"Lock successfully {'locked' if should_be_locked else 'unlocked'}")
            return True
        else:
            logger.error(f"Failed to {'lock' if should_be_locked else 'unlock'}")
            return False

    def set_window_angle(self, angle, manual=False):
        """
        Imposta un angolo specifico per la finestra.
        
        Args:
            angle (float): Angolo desiderato (77-120 gradi)
            manual (bool): True se il comando viene da un'interazione manuale
            
        Returns:
            bool: True se il comando è stato inviato, False altrimenti
        """
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

        # Imposta l'angolo della finestra
        success = self._execute_window_command('finestra', angle)
        
        if success:
            self.current_angle = angle
            self.target_angle = angle
            self.is_window_open = (angle > self.CLOSED_ANGLE + 5)  # Considera aperta se più di 5° sopra "chiusa"
            self.last_command_time = current_time
            logger.info(f"Window angle set to {angle}°")
            return True
        else:
            logger.error(f"Failed to set window angle to {angle}°")
            return False

    def auto_control_enabled(self):
        """
        Verifica se il controllo automatico è abilitato.
        
        Returns:
            bool: True se il controllo automatico è abilitato
        """
        return not self.manual_mode

    def disable_auto_control(self):
        """Disabilita il controllo automatico."""
        self.manual_mode = True
        logger.info("Automatic control disabled")

    def enable_auto_control(self):
        """Abilita il controllo automatico."""
        self.manual_mode = False
        logger.info("Automatic control enabled")
