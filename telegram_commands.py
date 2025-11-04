"""
Modulo per la gestione dei comandi Telegram per il sistema di rilevamento gatti.
"""

import logging
from telegram import Update, BotCommand
from telegram.ext import (
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes
)

logger = logging.getLogger(__name__)

class TelegramCommands:
    """Mixin per la gestione dei comandi Telegram."""
    
    async def register_commands(self):
        """Registra i comandi disponibili nel menu del bot."""
        commands = [
            BotCommand("start", "Avvia il bot e mostra i comandi disponibili"),
            BotCommand("apri", "Apre la finestra"),
            BotCommand("chiudi", "Chiude la finestra"),
            BotCommand("status", "Mostra lo stato della finestra"),
            BotCommand("auto", "Attiva controllo automatico"),
            BotCommand("manuale", "Disattiva controllo automatico"),
            BotCommand("foto", "Richiedi una foto dal sistema")
        ]
        
        try:
            await self.application.bot.set_my_commands(commands)
            logger.info("Bot commands registered successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to register bot commands: {e}")
            return False
    
    def setup_command_handlers(self):
        """Aggiunge gli handler per i comandi."""
        self.application.add_handler(CommandHandler("start", self._start_command))
        self.application.add_handler(CommandHandler("apri", self._open_command))
        self.application.add_handler(CommandHandler("chiudi", self._close_command))
        self.application.add_handler(CommandHandler("status", self._status_command))
        self.application.add_handler(CommandHandler("auto", self._auto_command))
        self.application.add_handler(CommandHandler("manuale", self._manual_command))
        self.application.add_handler(CommandHandler("foto", self._photo_command))
        self.application.add_handler(MessageHandler(filters.COMMAND, self._unknown_command))
        logger.info("Command handlers configured")
    
    async def _unknown_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gestisce comandi sconosciuti."""
        await update.message.reply_text(
            "⚠️ Comando non riconosciuto\n\n"
            "Comandi disponibili:\n"
            "/apri - Apre la finestra\n"
            "/chiudi - Chiude la finestra\n"
            "/status - Stato della finestra\n"
            "/auto - Attiva controllo automatico\n"
            "/manuale - Disattiva controllo automatico\n"
            "/foto - Richiedi una foto dal sistema"
        )
        logger.info(f"Unknown command received: {update.message.text}")

    async def _start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gestisce il comando /start."""
        logger.info("Start command received")
        await update.message.reply_text(
            "👋 Ciao! Sono il bot di controllo della finestra per gatti.\n\n"
            "Comandi disponibili:\n"
            "/apri - Apre la finestra\n"
            "/chiudi - Chiude la finestra\n"
            "/status - Stato della finestra\n"
            "/auto - Attiva controllo automatico\n"
            "/manuale - Disattiva controllo automatico\n"
            "/foto - Richiedi una foto dal sistema"
        )

    async def _open_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gestisce il comando /apri."""
        logger.info("Open command received")
        if not self.window_controller:
            await update.message.reply_text("❌ Controller finestra non disponibile")
            logger.error("Window controller not available")
            return
            
        try:
            # Forza la modalità manuale quando si usa il comando
            if self.window_controller.set_window_position(True, manual=True):
                await update.message.reply_text("✅ Comando di apertura inviato!\nModalità manuale attivata")
                logger.info("Window open command executed successfully")
            else:
                await update.message.reply_text("⚠️ La finestra è già aperta o in movimento")
                logger.info("Window already open or moving")
        except Exception as e:
            error_msg = f"Errore durante l'apertura: {str(e)}"
            await update.message.reply_text(f"❌ {error_msg}")
            logger.error(error_msg)

    async def _close_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gestisce il comando /chiudi."""
        logger.info("Close command received")
        if not self.window_controller:
            await update.message.reply_text("❌ Controller finestra non disponibile")
            logger.error("Window controller not available")
            return
            
        try:
            # Forza la modalità manuale quando si usa il comando
            if self.window_controller.set_window_position(False, manual=True):
                await update.message.reply_text("✅ Comando di chiusura inviato!\nModalità manuale attivata")
                logger.info("Window close command executed successfully")
            else:
                await update.message.reply_text("⚠️ La finestra è già chiusa o in movimento")
                logger.info("Window already closed or moving")
        except Exception as e:
            error_msg = f"Errore durante la chiusura: {str(e)}"
            await update.message.reply_text(f"❌ {error_msg}")
            logger.error(error_msg)

    async def _status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gestisce il comando /status."""
        logger.info("Status command received")
        if not self.window_controller:
            await update.message.reply_text("❌ Controller finestra non disponibile")
            logger.error("Window controller not available")
            return
            
        try:
            status = "🟢 APERTA" if self.window_controller.is_window_open else "🔴 CHIUSA"
            angle = self.window_controller.current_angle
            mode = "🤖 Automatica" if self.window_controller.auto_control_enabled() else "👋 Manuale"
            message = f"Stato finestra: {status}\nAngolo attuale: {angle}°\nModalità: {mode}"
            await update.message.reply_text(message)
            logger.info(f"Status sent: {message}")
        except Exception as e:
            error_msg = f"Errore nella lettura dello stato: {str(e)}"
            await update.message.reply_text(f"❌ {error_msg}")
            logger.error(error_msg)

    async def _auto_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gestisce il comando /auto."""
        logger.info("Auto mode command received")
        if not self.window_controller:
            await update.message.reply_text("❌ Controller finestra non disponibile")
            logger.error("Window controller not available")
            return
            
        try:
            self.window_controller.enable_auto_control()
            await update.message.reply_text("✅ Modalità automatica attivata")
            logger.info("Automatic control enabled")
        except Exception as e:
            error_msg = f"Errore nell'attivazione modalità automatica: {str(e)}"
            await update.message.reply_text(f"❌ {error_msg}")
            logger.error(error_msg)

    async def _manual_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gestisce il comando /manuale."""
        logger.info("Manual mode command received")
        if not self.window_controller:
            await update.message.reply_text("❌ Controller finestra non disponibile")
            logger.error("Window controller not available")
            return
            
        try:
            self.window_controller.disable_auto_control()
            await update.message.reply_text("✅ Modalità manuale attivata\nLa finestra rimarrà nella posizione impostata")
            logger.info("Manual control enabled")
        except Exception as e:
            error_msg = f"Errore nell'attivazione modalità manuale: {str(e)}"
            await update.message.reply_text(f"❌ {error_msg}")
            logger.error(error_msg)

    async def _photo_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Gestisce il comando /foto.
        Richiede una foto al sistema. Deve essere implementato dalle classi derivate.
        """
        await update.message.reply_text("⚠️ Funzionalità non implementata")
        logger.warning("Photo command not implemented in base class")
