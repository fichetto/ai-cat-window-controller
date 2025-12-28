"""
Modulo per la gestione delle notifiche Telegram per il sistema di rilevamento gatti.
"""

import logging
import os
from datetime import datetime
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

class TelegramNotifications:
    """Mixin per la gestione delle notifiche Telegram."""
    
    def send_startup_notification(self) -> bool:
        """
        Invia una notifica di avvio del sistema.
        
        Returns:
            bool: True se la notifica è stata inviata, False altrimenti
        """
        try:
            startup_message = "🟢 Sistema di rilevamento gatti avviato e operativo"
            return self.send_message(startup_message)
        except Exception as e:
            logger.error(f"Failed to send startup notification: {e}")
            return False
    
    def send_shutdown_notification(self) -> bool:
        """
        Invia una notifica di arresto del sistema.
        
        Returns:
            bool: True se la notifica è stata inviata, False altrimenti
        """
        try:
            shutdown_message = "🔴 Sistema di rilevamento gatti arrestato"
            return self.send_message(shutdown_message)
        except Exception as e:
            logger.error(f"Failed to send shutdown notification: {e}")
            return False
    
    def send_window_status(self, is_open: bool, reason: str = "") -> bool:
        """
        Invia un aggiornamento sullo stato della finestra.
        
        Args:
            is_open: True se la finestra è aperta, False se è chiusa
            reason: Motivazione del cambio di stato (opzionale)
            
        Returns:
            bool: True se la notifica è stata inviata, False altrimenti
        """
        try:
            status = "aperta 🟢" if is_open else "chiusa 🔴"
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            message = f"🪟 Finestra {status}\n⏰ {timestamp}"
            if reason:
                message += f"\n📝 {reason}"
                
            return self.send_message(message)
        except Exception as e:
            logger.error(f"Failed to send window status notification: {e}")
            return False
    
    def send_cat_detection_photo(self, photo_path: str, confidence: float) -> bool:
        """
        Invia una foto di un gatto rilevato con didascalia.
        
        Args:
            photo_path: Percorso della foto
            confidence: Valore di confidenza del rilevamento
            
        Returns:
            bool: True se la foto è stata inviata, False altrimenti
        """
        if not os.path.exists(photo_path):
            logger.error(f"Photo file does not exist: {photo_path}")
            return False
            
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            caption = f"🐱 Gatto rilevato!\n📊 Confidenza: {confidence:.2f}\n⏰ {timestamp}"
            
            return self.send_photo(photo_path, caption)
        except Exception as e:
            logger.error(f"Failed to send cat detection photo: {e}")
            return False
    
    def send_error_notification(self, error_message: str, error_type: str = "Generico") -> bool:
        """
        Invia una notifica di errore.
        
        Args:
            error_message: Descrizione dell'errore
            error_type: Tipo di errore (opzionale)
            
        Returns:
            bool: True se la notifica è stata inviata, False altrimenti
        """
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            message = f"⚠️ Errore {error_type}\n⏰ {timestamp}\n{error_message}"
            
            return self.send_message(message)
        except Exception as e:
            logger.error(f"Failed to send error notification: {e}")
            return False
    
    def send_battery_warning(self, battery_level: int) -> bool:
        """
        Invia un avviso di batteria scarica.
        
        Args:
            battery_level: Livello di batteria in percentuale
            
        Returns:
            bool: True se l'avviso è stato inviato, False altrimenti
        """
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            message = f"🔋 Avviso batteria: {battery_level}%\n⏰ {timestamp}"
            
            if battery_level <= 10:
                message = f"🚨 BATTERIA CRITICA: {battery_level}%\n⚠️ Il sistema potrebbe spegnersi!\n⏰ {timestamp}"
            elif battery_level <= 20:
                message = f"⚠️ Batteria molto bassa: {battery_level}%\n⏰ {timestamp}"
            
            return self.send_message(message)
        except Exception as e:
            logger.error(f"Failed to send battery warning: {e}")
            return False
    
    def send_network_status(self, is_connected: bool) -> bool:
        """
        Invia un aggiornamento sullo stato della connessione.
        
        Args:
            is_connected: True se connesso, False altrimenti
            
        Returns:
            bool: True se la notifica è stata inviata, False altrimenti
        """
        try:
            status = "🟢 connesso" if is_connected else "🔴 disconnesso"
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            message = f"🌐 Stato rete: {status}\n⏰ {timestamp}"
            
            return self.send_message(message)
        except Exception as e:
            logger.error(f"Failed to send network status notification: {e}")
            return False
    
    def send_cat_stats(self, stats: Dict[str, Any]) -> bool:
        """
        Invia statistiche sui rilevamenti dei gatti.
        
        Args:
            stats: Dizionario con le statistiche (rilevamenti, ore, ecc.)
            
        Returns:
            bool: True se la notifica è stata inviata, False altrimenti
        """
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            message = f"📊 Statistiche rilevamento gatti\n⏰ {timestamp}\n\n"
            
            if 'total_detections' in stats:
                message += f"🐱 Rilevamenti totali: {stats['total_detections']}\n"
            
            if 'today_detections' in stats:
                message += f"📅 Rilevamenti oggi: {stats['today_detections']}\n"
            
            if 'window_openings' in stats:
                message += f"🪟 Aperture finestra: {stats['window_openings']}\n"
            
            if 'avg_confidence' in stats:
                message += f"🎯 Confidenza media: {stats['avg_confidence']:.2f}\n"
            
            if 'total_time_open' in stats:
                hours = int(stats['total_time_open'] // 60)
                minutes = int(stats['total_time_open'] % 60)
                message += f"⏱️ Tempo totale apertura: {hours}h {minutes}m\n"
            
            if 'images_captured' in stats:
                message += f"📸 Immagini catturate: {stats['images_captured']}\n"
            
            return self.send_message(message)
        except Exception as e:
            logger.error(f"Failed to send cat stats notification: {e}")
            return False
    
    def send_system_restart(self) -> bool:
        """
        Invia una notifica di riavvio del sistema.
        
        Returns:
            bool: True se la notifica è stata inviata, False altrimenti
        """
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            message = f"🔄 Sistema in riavvio\n⏰ {timestamp}"
            
            return self.send_message(message)
        except Exception as e:
            logger.error(f"Failed to send system restart notification: {e}")
            return False
            
    def send_service_status(self, service_name: str, is_running: bool) -> bool:
        """
        Invia lo stato di un servizio.
        
        Args:
            service_name: Nome del servizio
            is_running: True se in esecuzione, False altrimenti
            
        Returns:
            bool: True se la notifica è stata inviata, False altrimenti
        """
        try:
            status = "🟢 attivo" if is_running else "🔴 inattivo"
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            message = f"🔧 Servizio {service_name}: {status}\n⏰ {timestamp}"
            
            return self.send_message(message)
        except Exception as e:
            logger.error(f"Failed to send service status notification: {e}")
            return False
    
    def send_daily_report(self, report_data: Dict[str, Any]) -> bool:
        """
        Invia un report giornaliero sulle attività.
        
        Args:
            report_data: Dati per il report
            
        Returns:
            bool: True se la notifica è stata inviata, False altrimenti
        """
        try:
            date = datetime.now().strftime("%Y-%m-%d")
            message = f"📋 Report giornaliero {date}\n\n"
            
            # Dati generali
            if 'detections' in report_data:
                message += f"🐱 Gatti rilevati: {report_data['detections']}\n"
            
            if 'window_activity' in report_data:
                message += f"🪟 Aperture finestra: {report_data['window_activity']}\n"
            
            if 'images_saved' in report_data:
                message += f"📸 Immagini salvate: {report_data['images_saved']}\n"
            
            # Statistiche di tempo
            if 'window_open_time' in report_data:
                minutes = report_data['window_open_time']
                hours = minutes // 60
                mins = minutes % 60
                message += f"⏱️ Tempo finestra aperta: {hours}h {mins}m\n"
            
            # Sistema
            if 'system_uptime' in report_data:
                message += f"🔌 Uptime sistema: {report_data['system_uptime']}h\n"
            
            if 'errors' in report_data and report_data['errors'] > 0:
                message += f"⚠️ Errori riscontrati: {report_data['errors']}\n"
            
            if 'storage_usage' in report_data:
                message += f"💾 Spazio utilizzato: {report_data['storage_usage']}%\n"
            
            return self.send_message(message)
        except Exception as e:
            logger.error(f"Failed to send daily report: {e}")
            return False
