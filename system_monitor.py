"""
Modulo di monitoraggio del sistema per il rilevamento gatti.
Gestisce statistiche, monitoraggio delle risorse e stato del sistema.
"""

import os
import time
import logging
import threading
import json
import psutil
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Tuple

logger = logging.getLogger(__name__)

class SystemMonitor:
    """
    Monitora lo stato del sistema, raccoglie statistiche e tiene traccia delle risorse.
    Fornisce informazioni sulla salute del sistema e supporta il salvataggio periodico
    delle statistiche.
    """
    
    def __init__(self, stats_file="system_stats.json", save_interval=3600):
        """
        Inizializza il monitor di sistema.
        
        Args:
            stats_file: File per il salvataggio delle statistiche
            save_interval: Intervallo in secondi per il salvataggio automatico delle statistiche
        """
        self.stats_file = stats_file
        self.save_interval = save_interval
        
        # Statistiche di base
        self.stats = {
            # Rilevamenti
            'total_detections': 0,
            'daily_detections': 0,
            'weekly_detections': 0,
            'detection_times': [],
            
            # Finestra
            'window_openings': 0,
            'total_open_time': 0,
            'last_window_change': None,
            'window_state_history': [],
            
            # Sistema
            'start_time': datetime.now().isoformat(),
            'uptime_seconds': 0,
            'boot_count': 0,
            
            # Immagini
            'images_captured': 0,
            'storage_usage': 0,
            
            # Performance
            'avg_detection_confidence': 0,
            'min_detection_confidence': 1.0,
            'max_detection_confidence': 0,
            
            # Errori
            'total_errors': 0,
            'network_errors': 0,
            'window_errors': 0,
            'detection_errors': 0
        }
        
        # Carica statistiche esistenti se disponibili
        self._load_stats()
        
        # Incrementa il contatore di riavvii
        self.stats['boot_count'] += 1
        
        # Stato attuale
        self.window_is_open = False
        self.window_open_time = None
        
        # Avvia thread di monitoraggio
        self.monitoring = True
        self.monitor_thread = threading.Thread(target=self._monitoring_loop, daemon=True)
        self.monitor_thread.start()
        
        logger.info("System monitor initialized")
    
    def _load_stats(self):
        """Carica le statistiche dal file se esiste."""
        try:
            if os.path.exists(self.stats_file):
                with open(self.stats_file, 'r') as f:
                    loaded_stats = json.load(f)
                    # Aggiorna le statistiche mantenendo i valori predefiniti per le chiavi mancanti
                    for key, value in loaded_stats.items():
                        if key in self.stats:
                            self.stats[key] = value
                logger.info(f"Statistics loaded from {self.stats_file}")
        except Exception as e:
            logger.error(f"Error loading statistics: {e}")
    
    def save_stats(self):
        """Salva le statistiche su file."""
        try:
            # Aggiorna il tempo di attività prima di salvare
            self.stats['uptime_seconds'] = (datetime.now() - datetime.fromisoformat(self.stats['start_time'])).total_seconds()
            
            with open(self.stats_file, 'w') as f:
                json.dump(self.stats, f, indent=2)
            logger.debug(f"Statistics saved to {self.stats_file}")
            return True
        except Exception as e:
            logger.error(f"Error saving statistics: {e}")
            return False
    
    def _monitoring_loop(self):
        """Thread di monitoraggio continuo del sistema."""
        last_save_time = time.time()
        
        while self.monitoring:
            try:
                current_time = time.time()
                
                # Aggiorna statistiche del sistema
                self._update_system_stats()
                
                # Aggiorna conteggio del tempo di apertura finestra
                self._update_window_time()
                
                # Salva le statistiche periodicamente
                if current_time - last_save_time >= self.save_interval:
                    self.save_stats()
                    last_save_time = current_time
                
                # Pulizia delle statistiche temporali
                self._cleanup_stats()
                
                # Attendi prima del prossimo aggiornamento
                time.sleep(60)  # Controlla ogni minuto
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                time.sleep(300)  # Attendere più a lungo in caso di errore
    
    def _update_system_stats(self):
        """Aggiorna le statistiche di sistema."""
        try:
            # CPU e memoria
            self.stats['cpu_percent'] = psutil.cpu_percent()
            self.stats['memory_percent'] = psutil.virtual_memory().percent
            
            # Temperatura (se disponibile)
            if hasattr(psutil, "sensors_temperatures"):
                temps = psutil.sensors_temperatures()
                if temps and 'cpu_thermal' in temps:
                    self.stats['cpu_temperature'] = temps['cpu_thermal'][0].current
            
            # Spazio su disco
            disk = psutil.disk_usage('/')
            self.stats['disk_usage_percent'] = disk.percent
            
            # Uptime
            self.stats['uptime_seconds'] = (datetime.now() - datetime.fromisoformat(self.stats['start_time'])).total_seconds()
        except Exception as e:
            logger.error(f"Error updating system stats: {e}")
    
    def _update_window_time(self):
        """Aggiorna il tempo di apertura della finestra se è aperta."""
        if self.window_is_open and self.window_open_time:
            elapsed = (datetime.now() - self.window_open_time).total_seconds()
            # Converti in minuti
            self.stats['total_open_time'] = self.stats.get('total_open_time', 0) + (elapsed / 60)
            # Aggiorna il tempo di inizio
            self.window_open_time = datetime.now()
    
    def _cleanup_stats(self):
        """Pulisce le statistiche temporali più vecchie."""
        now = datetime.now()
        
        # Pulisci i tempi di rilevamento più vecchi di 7 giorni
        if 'detection_times' in self.stats:
            self.stats['detection_times'] = [
                t for t in self.stats['detection_times'] 
                if (now - datetime.fromisoformat(t)).days < 7
            ]
        
        # Pulisci lo storico dei cambiamenti di stato della finestra più vecchi di 30 giorni
        if 'window_state_history' in self.stats:
            self.stats['window_state_history'] = [
                h for h in self.stats['window_state_history']
                if (now - datetime.fromisoformat(h['timestamp'])).days < 30
            ]
    
    def record_detection(self, confidence: float):
        """
        Registra un rilevamento.
        
        Args:
            confidence: Confidenza del rilevamento
        """
        self.stats['total_detections'] += 1
        self.stats['daily_detections'] += 1
        self.stats['weekly_detections'] += 1
        
        # Registra il timestamp del rilevamento
        detection_time = datetime.now().isoformat()
        self.stats['detection_times'].append(detection_time)
        
        # Aggiorna statistiche di confidenza
        if 'avg_detection_confidence' in self.stats:
            # Calcola la nuova media ponderata
            prev_avg = self.stats['avg_detection_confidence']
            prev_count = self.stats['total_detections'] - 1
            self.stats['avg_detection_confidence'] = (prev_avg * prev_count + confidence) / self.stats['total_detections']
        else:
            self.stats['avg_detection_confidence'] = confidence
        
        # Aggiorna min/max confidenza
        self.stats['min_detection_confidence'] = min(self.stats['min_detection_confidence'], confidence)
        self.stats['max_detection_confidence'] = max(self.stats['max_detection_confidence'], confidence)
    
    def record_window_change(self, is_open: bool):
        """
        Registra un cambiamento nello stato della finestra.
        
        Args:
            is_open: True se la finestra è aperta, False altrimenti
        """
        now = datetime.now()
        
        # Se lo stato è cambiato
        if self.window_is_open != is_open:
            # Se la finestra passa da aperta a chiusa, registra il tempo di apertura
            if self.window_is_open and self.window_open_time:
                elapsed_minutes = (now - self.window_open_time).total_seconds() / 60
                self.stats['total_open_time'] += elapsed_minutes
            
            # Se la finestra passa da chiusa ad aperta, registra l'apertura
            if not self.window_is_open and is_open:
                self.stats['window_openings'] += 1
                self.window_open_time = now
            else:
                self.window_open_time = None
            
            # Aggiorna lo stato corrente
            self.window_is_open = is_open
            
            # Registra il cambiamento nello storico
            state_change = {
                'timestamp': now.isoformat(),
                'state': 'open' if is_open else 'closed'
            }
            self.stats['window_state_history'].append(state_change)
            
            # Aggiorna l'ultimo cambiamento
            self.stats['last_window_change'] = now.isoformat()
    
    def record_image_capture(self):
        """Registra la cattura di un'immagine."""
        self.stats['images_captured'] += 1
    
    def record_error(self, error_type: str = 'general'):
        """
        Registra un errore.
        
        Args:
            error_type: Tipo di errore (general, network, window, detection)
        """
        self.stats['total_errors'] += 1
        
        if error_type == 'network':
            self.stats['network_errors'] += 1
        elif error_type == 'window':
            self.stats['window_errors'] += 1
        elif error_type == 'detection':
            self.stats['detection_errors'] += 1
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Ottiene una copia delle statistiche correnti.
        
        Returns:
            Dict[str, Any]: Statistiche del sistema
        """
        # Aggiorna alcune statistiche dinamiche prima di restituirle
        self._update_system_stats()
        
        # Crea una copia per evitare modifiche esterne
        return dict(self.stats)
    
    def get_daily_stats(self) -> Dict[str, Any]:
        """
        Ottiene le statistiche giornaliere.
        
        Returns:
            Dict[str, Any]: Statistiche giornaliere
        """
        daily_stats = {
            'detections': self.stats['daily_detections'],
            'window_openings': self.stats.get('daily_window_openings', 0),
            'images_captured': self.stats.get('daily_images', 0),
            'errors': self.stats.get('daily_errors', 0),
            'avg_confidence': self.stats.get('avg_detection_confidence', 0)
        }
        
        # Calcola tempo di apertura della finestra nell'ultimo giorno
        today = datetime.now()
        yesterday = today - timedelta(days=1)
        
        window_time_today = 0
        for entry in self.stats.get('window_state_history', []):
            try:
                entry_time = datetime.fromisoformat(entry['timestamp'])
                if entry_time >= yesterday and entry['state'] == 'open':
                    # Calcola il tempo fino alla prossima chiusura o fino ad ora
                    next_close = None
                    for next_entry in self.stats.get('window_state_history', []):
                        next_entry_time = datetime.fromisoformat(next_entry['timestamp'])
                        if next_entry_time > entry_time and next_entry['state'] == 'closed':
                            next_close = next_entry_time
                            break
                    
                    if next_close:
                        window_time_today += (next_close - entry_time).total_seconds() / 60
                    elif self.window_is_open:
                        # Se la finestra è ancora aperta, conta fino ad ora
                        window_time_today += (today - entry_time).total_seconds() / 60
            except (ValueError, KeyError):
                continue
        
        daily_stats['window_open_time'] = round(window_time_today)
        
        return daily_stats
    
    def reset_daily_stats(self):
        """Resetta le statistiche giornaliere."""
        self.stats['daily_detections'] = 0
        self.stats['daily_window_openings'] = 0
        self.stats['daily_images'] = 0
        self.stats['daily_errors'] = 0
    
    def get_system_health(self) -> Tuple[str, Dict[str, Any]]:
        """
        Valuta lo stato di salute del sistema.
        
        Returns:
            Tuple[str, Dict[str, Any]]: Stato di salute (good, warning, critical) e dettagli
        """
        health_status = "good"
        health_details = {}
        
        try:
            # Controllo CPU
            cpu_percent = psutil.cpu_percent(interval=0.5)
            if cpu_percent > 90:
                health_status = "critical"
                health_details["cpu"] = f"Critical CPU usage: {cpu_percent}%"
            elif cpu_percent > 75:
                health_status = max(health_status, "warning")
                health_details["cpu"] = f"High CPU usage: {cpu_percent}%"
            
            # Controllo memoria
            memory = psutil.virtual_memory()
            if memory.percent > 90:
                health_status = "critical"
                health_details["memory"] = f"Critical memory usage: {memory.percent}%"
            elif memory.percent > 80:
                health_status = max(health_status, "warning")
                health_details["memory"] = f"High memory usage: {memory.percent}%"
            
            # Controllo disco
            disk = psutil.disk_usage('/')
            if disk.percent > 95:
                health_status = "critical"
                health_details["disk"] = f"Critical disk usage: {disk.percent}%"
            elif disk.percent > 85:
                health_status = max(health_status, "warning")
                health_details["disk"] = f"High disk usage: {disk.percent}%"
            
            # Controllo temperatura (se disponibile)
            if hasattr(psutil, "sensors_temperatures"):
                temps = psutil.sensors_temperatures()
                if temps and 'cpu_thermal' in temps:
                    cpu_temp = temps['cpu_thermal'][0].current
                    if cpu_temp > 80:
                        health_status = "critical"
                        health_details["temperature"] = f"Critical CPU temperature: {cpu_temp}°C"
                    elif cpu_temp > 70:
                        health_status = max(health_status, "warning")
                        health_details["temperature"] = f"High CPU temperature: {cpu_temp}°C"
            
            # Controllo errori
            error_rate = self.stats.get('total_errors', 0) / max(1, self.stats.get('total_detections', 1))
            if error_rate > 0.1:  # Più del 10% di errori
                health_status = max(health_status, "warning")
                health_details["errors"] = f"High error rate: {error_rate:.2%}"
        
        except Exception as e:
            logger.error(f"Error checking system health: {e}")
            health_status = "unknown"
            health_details["error"] = f"Failed to check system health: {str(e)}"
        
        return health_status, health_details
    
    def __del__(self):
        """Cleanup alla chiusura."""
        self.monitoring = False
        if hasattr(self, 'monitor_thread') and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=1)
        self.save_stats()
