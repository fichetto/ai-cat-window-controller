"""
Gestore Telegram per l'invio di foto, notifiche e gestione comandi.
Versione modulare con migliorata gestione degli errori.
"""

import logging
import os
import threading
import asyncio
import concurrent.futures
from datetime import datetime
from typing import Optional, Dict, Any, List

# Importa i moduli Telegram
from telegram_base import TelegramBase
from telegram_commands import TelegramCommands
from telegram_notifications import TelegramNotifications

# Importa la configurazione
from cat_config import TELEGRAM_CONFIG

# Configurazione logging
logger = logging.getLogger(__name__)

class TelegramHandler(TelegramBase, TelegramCommands, TelegramNotifications):
    """
    Gestore Telegram completo che integra funzionalità di base, comandi e notifiche.
    """
    
    def __init__(self):
        """Inizializza il gestore Telegram con i componenti necessari."""
        # Inizializza la classe base
        super().__init__(
            token=TELEGRAM_CONFIG['token'],
            chat_id=TELEGRAM_CONFIG['chat_id']
        )
        
        # Attributi specifici
        self.detector = None  # Sarà impostato dall'applicazione principale
        self.system_stats = {
            'total_detections': 0,
            'today_detections': 0,
            'window_openings': 0,
            'avg_confidence': 0.0,
            'total_time_open': 0,
            'images_captured': 0
        }
        
        # Avvia il bot
        self.start()
        
        # Invia notifica di avvio
        self.send_startup_notification()
        
        logger.info("Telegram handler fully initialized")
    
    async def _setup_handlers(self):
        """Configura gli handler del bot."""
        # Configura gli handler per i comandi
        self.setup_command_handlers()
        
        # Registra i comandi disponibili
        await self.register_commands()
    
    async def _photo_command(self, update, context):
        """
        Implementazione del comando /foto.
        Richiede una foto dal sistema e la invia all'utente.
        """
        await update.message.reply_text("📸 Richiesta foto in elaborazione...")
        
        try:
            # Verifica se il detector è disponibile
            if self.detector and hasattr(self.detector, 'capture_photo'):
                # Richiedi una foto al detector
                photo_path = self.detector.capture_photo()
                
                if photo_path and os.path.exists(photo_path):
                    await update.message.reply_photo(
                        photo=open(photo_path, 'rb'),
                        caption=f"📸 Foto scattata il {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                    logger.info(f"Photo sent successfully: {photo_path}")
                else:
                    await update.message.reply_text("❌ Impossibile acquisire la foto")
                    logger.error("Failed to capture photo")
            else:
                await update.message.reply_text("❌ Funzione di acquisizione foto non disponibile")
                logger.error("Photo capture function not available")
        except Exception as e:
            await update.message.reply_text(f"❌ Errore durante l'acquisizione della foto: {str(e)}")
            logger.error(f"Error capturing photo: {e}")
    
    def set_detector(self, detector):
        """
        Imposta il riferimento al detector.
        
        Args:
            detector: Istanza del rilevatore di gatti
        """
        self.detector = detector
        logger.info("Detector reference set in Telegram handler")
    
    def update_stats(self, stats):
        """
        Aggiorna le statistiche di sistema.
        
        Args:
            stats: Dizionario con le statistiche da aggiornare
        """
        self.system_stats.update(stats)
    
    def send_cat_photo(self, photo_path, confidence):
        """
        Invia una foto di un gatto con migliorata gestione degli errori.
        
        Args:
            photo_path: Percorso del file immagine
            confidence: Confidenza del rilevamento
            
        Returns:
            bool: True se la richiesta è stata elaborata, False altrimenti
        """
        # Aggiorna le statistiche
        self.system_stats['images_captured'] += 1
        
        # Delega l'invio al metodo specifico delle notifiche
        return self.send_cat_detection_photo(photo_path, confidence)
    
    def record_window_opening(self):
        """Registra un'apertura della finestra nelle statistiche."""
        self.system_stats['window_openings'] += 1
    
    def record_detection(self, confidence):
        """
        Registra un rilevamento nelle statistiche.
        
        Args:
            confidence: Confidenza del rilevamento
        """
        self.system_stats['total_detections'] += 1
        self.system_stats['today_detections'] += 1
        
        # Aggiorna la confidenza media
        if self.system_stats['total_detections'] > 0:
            current_avg = self.system_stats['avg_confidence']
            current_count = self.system_stats['total_detections'] - 1
            
            # Formula per aggiornare la media incrementalmente
            self.system_stats['avg_confidence'] = (current_avg * current_count + confidence) / self.system_stats['total_detections']
    
    def reset_daily_stats(self):
        """Resetta le statistiche giornaliere."""
        self.system_stats['today_detections'] = 0
        self.system_stats['window_openings'] = 0
    
    def send_daily_summary(self):
        """Invia un riepilogo giornaliero delle attività."""
        try:
            # Prepara i dati per il report
            report_data = {
                'detections': self.system_stats['today_detections'],
                'window_activity': self.system_stats['window_openings'],
                'images_saved': self.system_stats.get('images_captured', 0),
                'window_open_time': int(self.system_stats.get('total_time_open', 0)),
                'storage_usage': self._get_storage_usage()
            }
            
            # Invia il report
            self.send_daily_report(report_data)
            
            # Resetta le statistiche giornaliere
            self.reset_daily_stats()
            logger.info("Daily summary sent and stats reset")
            return True
        except Exception as e:
            logger.error(f"Error sending daily summary: {e}")
            return False
    
    def _get_storage_usage(self):
        """
        Ottiene la percentuale di utilizzo dello storage.
        
        Returns:
            float: Percentuale di utilizzo
        """
        try:
            if hasattr(os, 'statvfs'):
                # Verificare lo spazio su disco nella directory corrente
                stats = os.statvfs('.')
                # Calcola lo spazio totale e libero in GB
                total = (stats.f_blocks * stats.f_frsize) / (1024**3)
                free = (stats.f_bavail * stats.f_frsize) / (1024**3)
                # Calcola la percentuale di utilizzo
                used_percent = 100 - (free / total * 100)
                return round(used_percent, 1)
            else:
                # Fallback per sistemi che non supportano statvfs
                return 0
        except Exception as e:
            logger.error(f"Error getting storage usage: {e}")
            return 0
