"""
Gestore file per il sistema di rilevamento gatti.
Si occupa della gestione delle immagini, della loro cache e della pulizia dello storage.
"""

import os
import shutil
import logging
import glob
import time
from datetime import datetime, timedelta
from typing import List, Tuple, Optional
import threading

logger = logging.getLogger(__name__)

class FileManager:
    """
    Gestisce i file e lo storage del sistema di rilevamento gatti.
    Fornisce funzionalità per il salvataggio delle immagini, la cache
    e la pulizia automatica dello storage.
    """
    
    def __init__(self, 
                 base_dir: str = "detected_cats",
                 max_storage_mb: int = 1000,
                 cleanup_days: int = 7,
                 auto_cleanup: bool = True):
        """
        Inizializza il gestore file.
        
        Args:
            base_dir: Directory base per il salvataggio delle immagini
            max_storage_mb: Dimensione massima dello storage in MB
            cleanup_days: Giorni dopo i quali i file possono essere eliminati
            auto_cleanup: Se True, esegue la pulizia automatica dello storage
        """
        self.base_dir = base_dir
        self.max_storage_mb = max_storage_mb
        self.cleanup_days = cleanup_days
        self.auto_cleanup = auto_cleanup
        
        # Intervallo di controllo pulizia (in ore)
        self.cleanup_interval = 12
        
        # Cache delle immagini
        self.image_cache = {}
        self.cache_lock = threading.Lock()
        
        # Crea la directory se non esiste
        self._ensure_directory()
        
        # Avvia il thread di pulizia se richiesto
        if self.auto_cleanup:
            self._start_cleanup_thread()
            
        logger.info(f"File manager initialized with base directory: {self.base_dir}")
        logger.info(f"Storage limits: {self.max_storage_mb}MB, cleanup after {self.cleanup_days} days")
    
    def _ensure_directory(self):
        """Crea la directory base se non esiste."""
        try:
            os.makedirs(self.base_dir, exist_ok=True)
            logger.info(f"Directory {self.base_dir} is ready")
        except Exception as e:
            logger.error(f"Error creating directory {self.base_dir}: {e}")
    
    def _start_cleanup_thread(self):
        """Avvia un thread per la pulizia periodica dello storage."""
        thread = threading.Thread(target=self._cleanup_thread, daemon=True)
        thread.start()
        logger.info("Cleanup thread started")
    
    def _cleanup_thread(self):
        """Thread che esegue la pulizia periodica dello storage."""
        while True:
            try:
                # Esegui la pulizia
                deleted_files = self.cleanup_storage()
                
                if deleted_files:
                    logger.info(f"Automatic cleanup deleted {len(deleted_files)} files")
                
                # Attendi il prossimo intervallo (in secondi)
                time.sleep(self.cleanup_interval * 3600)
            except Exception as e:
                logger.error(f"Error in cleanup thread: {e}")
                # Attendi un po' prima di riprovare in caso di errore
                time.sleep(300)
    
    def get_storage_usage(self) -> Tuple[float, float, float]:
        """
        Calcola l'utilizzo dello storage.
        
        Returns:
            Tuple[float, float, float]: Spazio usato in MB, spazio totale in MB, percentuale di utilizzo
        """
        try:
            # Calcola lo spazio utilizzato nella directory base
            used_mb = sum(os.path.getsize(f) for f in glob.glob(f"{self.base_dir}/**/*.*", recursive=True)) / (1024 * 1024)
            
            # Se possibile, ottieni la dimensione del volume
            if hasattr(os, 'statvfs'):
                stats = os.statvfs(self.base_dir)
                total_mb = (stats.f_blocks * stats.f_frsize) / (1024 * 1024)
                avail_mb = (stats.f_bavail * stats.f_frsize) / (1024 * 1024)
                percent = (used_mb / total_mb) * 100 if total_mb > 0 else 0
            else:
                # Fallback al limite massimo configurato
                total_mb = self.max_storage_mb
                avail_mb = max(0, total_mb - used_mb)
                percent = (used_mb / total_mb) * 100 if total_mb > 0 else 0
            
            return (used_mb, total_mb, percent)
        except Exception as e:
            logger.error(f"Error calculating storage usage: {e}")
            return (0, self.max_storage_mb, 0)
    
    def storage_near_capacity(self) -> bool:
        """
        Verifica se lo storage è quasi pieno (>90%).
        
        Returns:
            bool: True se lo storage è quasi pieno, False altrimenti
        """
        _, _, percent = self.get_storage_usage()
        return percent > 90
    
    def save_image(self, image_data, prefix: str = "cat", confidence: float = 0.0) -> Optional[str]:
        """
        Salva un'immagine nella directory base.
        
        Args:
            image_data: Dati dell'immagine (numpy array)
            prefix: Prefisso per il nome del file
            confidence: Valore di confidenza del rilevamento
            
        Returns:
            str: Percorso del file salvato o None in caso di errore
        """
        import cv2
        
        try:
            # Verifica se lo storage è quasi pieno
            if self.storage_near_capacity():
                # Esegui la pulizia se necessario
                self.cleanup_storage()
            
            # Crea il nome del file con timestamp e confidenza
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{prefix}_{timestamp}_conf{confidence:.2f}.jpg"
            filepath = os.path.join(self.base_dir, filename)
            
            # Salva l'immagine
            cv2.imwrite(filepath, image_data)
            
            # Pulisci la cache se necessario
            self._clean_cache_if_needed()
            
            # Memorizza il percorso nella cache
            with self.cache_lock:
                self.image_cache[filepath] = {
                    'timestamp': datetime.now(),
                    'confidence': confidence
                }
            
            logger.debug(f"Image saved: {filepath}")
            return filepath
        except Exception as e:
            logger.error(f"Error saving image: {e}")
            return None
    
    def _clean_cache_if_needed(self, max_items: int = 100):
        """
        Pulisce la cache se il numero di elementi supera il massimo.
        
        Args:
            max_items: Numero massimo di elementi nella cache
        """
        with self.cache_lock:
            if len(self.image_cache) > max_items:
                # Ordina per timestamp (più vecchio prima)
                sorted_items = sorted(self.image_cache.items(), key=lambda x: x[1]['timestamp'])
                
                # Rimuovi i più vecchi fino a raggiungere il limite
                items_to_remove = len(self.image_cache) - max_items
                for i in range(items_to_remove):
                    item = sorted_items[i]
                    del self.image_cache[item[0]]
                
                logger.debug(f"Cache cleaned, removed {items_to_remove} items")
    
    def get_images_by_timerange(self, hours: int = 24) -> List[str]:
        """
        Ottiene i percorsi delle immagini nell'intervallo temporale specificato.
        
        Args:
            hours: Intervallo temporale in ore
            
        Returns:
            List[str]: Lista dei percorsi delle immagini
        """
        cutoff_time = datetime.now() - timedelta(hours=hours)
        
        # Prima controlla nella cache
        recent_images = []
        
        with self.cache_lock:
            for filepath, data in self.image_cache.items():
                if data['timestamp'] >= cutoff_time:
                    recent_images.append(filepath)
        
        # Se la cache non contiene abbastanza dati, cerca nei file
        if not recent_images:
            try:
                all_images = glob.glob(f"{self.base_dir}/*.jpg")
                
                for image_path in all_images:
                    try:
                        # Estrai la data dal nome del file
                        filename = os.path.basename(image_path)
                        parts = filename.split('_')
                        if len(parts) >= 2:
                            # Assume formato: prefix_YYYYMMDD_HHMMSS_...
                            date_str = parts[1]
                            time_str = parts[2] if len(parts) > 2 else "000000"
                            
                            if time_str.startswith("conf"):
                                time_str = "000000"
                            
                            try:
                                file_time = datetime.strptime(f"{date_str}_{time_str}", "%Y%m%d_%H%M%S")
                                if file_time >= cutoff_time:
                                    recent_images.append(image_path)
                            except ValueError:
                                # Ignora file con formato non valido
                                pass
                    except Exception:
                        # Ignora file che non possono essere analizzati
                        pass
            except Exception as e:
                logger.error(f"Error getting images by timerange: {e}")
        
        return recent_images
    
    def get_images_by_confidence(self, min_confidence: float = 0.5) -> List[str]:
        """
        Ottiene i percorsi delle immagini con confidenza superiore al valore specificato.
        
        Args:
            min_confidence: Valore minimo di confidenza
            
        Returns:
            List[str]: Lista dei percorsi delle immagini
        """
        high_conf_images = []
        
        # Prima controlla nella cache
        with self.cache_lock:
            for filepath, data in self.image_cache.items():
                if data['confidence'] >= min_confidence:
                    high_conf_images.append(filepath)
        
        # Se la cache non contiene abbastanza dati, cerca nei file
        if not high_conf_images:
            try:
                all_images = glob.glob(f"{self.base_dir}/*.jpg")
                
                for image_path in all_images:
                    try:
                        # Estrai la confidenza dal nome del file
                        filename = os.path.basename(image_path)
                        
                        # Cerca "conf0.XX" nel nome del file
                        if "conf" in filename:
                            conf_part = filename.split("conf")[1].split(".")[0] + "." + filename.split("conf")[1].split(".")[1]
                            try:
                                conf = float(conf_part)
                                if conf >= min_confidence:
                                    high_conf_images.append(image_path)
                            except ValueError:
                                # Ignora file con formato non valido
                                pass
                    except Exception:
                        # Ignora file che non possono essere analizzati
                        pass
            except Exception as e:
                logger.error(f"Error getting images by confidence: {e}")
        
        return high_conf_images
    
    def cleanup_storage(self) -> List[str]:
        """
        Pulisce lo storage eliminando i file più vecchi.
        
        Returns:
            List[str]: Lista dei file eliminati
        """
        deleted_files = []
        
        # Verifica se è necessaria la pulizia
        used_mb, total_mb, percent = self.get_storage_usage()
        
        try:
            if percent > 80:  # Pulizia se utilizzo > 80%
                logger.info(f"Storage at {percent:.1f}%, cleaning up...")
                
                # Ottieni tutti i file nella directory base
                all_files = []
                for ext in ['*.jpg', '*.jpeg', '*.png']:
                    all_files.extend(glob.glob(f"{self.base_dir}/{ext}"))
                
                # Ordina per data di modifica (più vecchi prima)
                all_files.sort(key=os.path.getmtime)
                
                # Calcola la data limite per la pulizia
                cutoff_date = datetime.now() - timedelta(days=self.cleanup_days)
                
                # Elimina i file più vecchi della data limite
                for file_path in all_files:
                    file_mod_time = datetime.fromtimestamp(os.path.getmtime(file_path))
                    
                    if file_mod_time < cutoff_date:
                        try:
                            os.remove(file_path)
                            deleted_files.append(file_path)
                            
                            # Rimuovi dalla cache se presente
                            with self.cache_lock:
                                if file_path in self.image_cache:
                                    del self.image_cache[file_path]
                            
                            logger.debug(f"Deleted old file: {file_path}")
                            
                            # Verifica se lo storage è ancora sopra la soglia dopo ogni eliminazione
                            used_mb, _, percent = self.get_storage_usage()
                            if percent < 70:
                                break
                        except Exception as e:
                            logger.error(f"Error deleting file {file_path}: {e}")
            
            return deleted_files
        except Exception as e:
            logger.error(f"Error during storage cleanup: {e}")
            return []
    
    def get_latest_image(self) -> Optional[str]:
        """
        Ottiene il percorso dell'immagine più recente.
        
        Returns:
            str: Percorso dell'immagine più recente o None se non ci sono immagini
        """
        try:
            all_images = glob.glob(f"{self.base_dir}/*.jpg")
            
            if not all_images:
                return None
            
            # Ordina per data di modifica (più recenti prima)
            latest_image = max(all_images, key=os.path.getmtime)
            return latest_image
        except Exception as e:
            logger.error(f"Error getting latest image: {e}")
            return None
