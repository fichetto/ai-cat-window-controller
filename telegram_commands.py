"""
Modulo per la gestione dei comandi Telegram per il sistema di rilevamento gatti.
Include comandi per finestra e gestione alimentazione gatti.
"""

import logging
import asyncio
from telegram import Update, BotCommand
from telegram.ext import (
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes
)
from telegram.error import TimedOut, NetworkError

logger = logging.getLogger(__name__)

# Il feeding manager verrà impostato dall'esterno
_feeding_manager = None

def set_feeding_manager(manager):
    """Imposta il feeding manager globale."""
    global _feeding_manager
    _feeding_manager = manager

class TelegramCommands:
    """Mixin per la gestione dei comandi Telegram."""

    async def _send_message_with_retry(self, update: Update, message: str, max_retries: int = 3, timeout: int = 10) -> bool:
        """
        Invia un messaggio Telegram con retry automatico in caso di timeout.

        Args:
            update: Update object di Telegram
            message: Messaggio da inviare
            max_retries: Numero massimo di tentativi (default: 3)
            timeout: Timeout per ogni tentativo in secondi (default: 10)

        Returns:
            True se il messaggio è stato inviato con successo, False altrimenti
        """
        for attempt in range(max_retries):
            try:
                await asyncio.wait_for(
                    update.message.reply_text(message),
                    timeout=timeout
                )
                return True
            except (TimedOut, asyncio.TimeoutError) as e:
                if attempt < max_retries - 1:
                    logger.warning(f"Timeout sending message (attempt {attempt + 1}/{max_retries}), retrying...")
                    await asyncio.sleep(1)  # Breve pausa prima del retry
                else:
                    logger.error(f"Failed to send message after {max_retries} attempts: {str(e)}")
                    return False
            except NetworkError as e:
                if attempt < max_retries - 1:
                    logger.warning(f"Network error (attempt {attempt + 1}/{max_retries}), retrying...")
                    await asyncio.sleep(2)
                else:
                    logger.error(f"Network error after {max_retries} attempts: {str(e)}")
                    return False
            except Exception as e:
                logger.error(f"Unexpected error sending message: {str(e)}")
                return False

        return False

    async def register_commands(self):
        """Registra i comandi disponibili nel menu del bot."""
        commands = [
            BotCommand("start", "Avvia il bot e mostra i comandi disponibili"),
            BotCommand("apri", "Apre la finestra (passa a manuale)"),
            BotCommand("faientrare", "Apre la finestra (mantiene modalità)"),
            BotCommand("chiudi", "Chiude la finestra"),
            BotCommand("status", "Mostra lo stato della finestra"),
            BotCommand("auto", "Attiva controllo automatico"),
            BotCommand("manuale", "Disattiva controllo automatico"),
            BotCommand("foto", "Richiedi una foto dal sistema"),
            # Comandi gestione gatti/alimentazione
            BotCommand("gatti", "Lista gatti registrati"),
            BotCommand("classifica", "Classifica pasti giornaliera"),
            BotCommand("registra", "Registra nuovo gatto: /registra Nome Peso"),
            BotCommand("chiesto", "Identifica ultimo gatto: /chiesto Nome"),
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
        # Comandi finestra
        self.application.add_handler(CommandHandler("start", self._start_command))
        self.application.add_handler(CommandHandler("apri", self._open_command))
        self.application.add_handler(CommandHandler("faientrare", self._let_in_command))
        self.application.add_handler(CommandHandler("chiudi", self._close_command))
        self.application.add_handler(CommandHandler("status", self._status_command))
        self.application.add_handler(CommandHandler("auto", self._auto_command))
        self.application.add_handler(CommandHandler("manuale", self._manual_command))
        self.application.add_handler(CommandHandler("foto", self._photo_command))
        # Comandi gestione gatti
        self.application.add_handler(CommandHandler("gatti", self._cats_list_command))
        self.application.add_handler(CommandHandler("classifica", self._feeding_stats_command))
        self.application.add_handler(CommandHandler("registra", self._register_cat_command))
        self.application.add_handler(CommandHandler("chiesto", self._identify_cat_command))
        # Handler per comandi sconosciuti
        self.application.add_handler(MessageHandler(filters.COMMAND, self._unknown_command))
        logger.info("Command handlers configured")
    
    async def _unknown_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gestisce comandi sconosciuti."""
        await update.message.reply_text(
            "⚠️ Comando non riconosciuto\n\n"
            "📍 Comandi finestra:\n"
            "/apri - Apre la finestra\n"
            "/faientrare - Apre per far entrare il gatto\n"
            "/chiudi - Chiude la finestra\n"
            "/status - Stato della finestra\n"
            "/auto - Modalità automatica\n"
            "/manuale - Modalità manuale\n\n"
            "🐱 Comandi gatti:\n"
            "/gatti - Lista gatti registrati\n"
            "/classifica - Pasti di oggi\n"
            "/registra Nome Peso - Registra gatto\n"
            "/chiesto Nome - Identifica ultimo gatto"
        )
        logger.info(f"Unknown command received: {update.message.text}")

    async def _start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gestisce il comando /start."""
        logger.info("Start command received")
        await update.message.reply_text(
            "👋 Ciao! Sono il bot di controllo gatti.\n\n"
            "📍 Comandi finestra:\n"
            "/apri - Apre la finestra\n"
            "/faientrare - Apre per far entrare il gatto\n"
            "/chiudi - Chiude la finestra\n"
            "/status - Stato della finestra\n"
            "/auto - Modalità automatica\n"
            "/manuale - Modalità manuale\n\n"
            "🐱 Comandi gatti:\n"
            "/gatti - Lista gatti registrati\n"
            "/classifica - Pasti di oggi\n"
            "/registra Nome Peso - Registra gatto\n"
            "/chiesto Nome - Identifica ultimo gatto"
        )

    async def _open_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gestisce il comando /apri."""
        logger.info("Open command received")
        if not self.window_controller:
            await self._send_message_with_retry(update, "❌ Controller finestra non disponibile")
            logger.error("Window controller not available")
            return

        # Esegui il comando sulla finestra PRIMA di rispondere
        command_success = False
        error_message = None

        try:
            # Forza la modalità manuale quando si usa il comando
            command_success = self.window_controller.set_window_position(True, manual=True)
        except Exception as e:
            error_message = str(e)
            logger.error(f"Error executing window command: {e}")

        # Ora invia la risposta con retry
        if error_message:
            await self._send_message_with_retry(update, f"❌ Errore durante l'apertura: {error_message}")
        elif command_success:
            await self._send_message_with_retry(update, "✅ Comando di apertura inviato!\nModalità manuale attivata")
            logger.info("Window open command executed successfully")
        else:
            await self._send_message_with_retry(update, "⚠️ La finestra è già aperta o in movimento")
            logger.info("Window already open or moving")

    async def _let_in_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gestisce il comando /faientrare - apre senza cambiare modalità."""
        logger.info("Let-in command received")
        if not self.window_controller:
            await self._send_message_with_retry(update, "❌ Controller finestra non disponibile")
            logger.error("Window controller not available")
            return

        # Esegui il comando sulla finestra PRIMA di rispondere
        command_success = False
        error_message = None
        current_mode = None

        try:
            # Apre la finestra SENZA cambiare la modalità (manual=False)
            # Se era in automatico, rimane automatico
            # Se era in manuale, rimane manuale
            current_mode = "automatica" if self.window_controller.auto_control_enabled() else "manuale"
            command_success = self.window_controller.set_window_position(True, manual=False)

            if command_success:
                # Imposta il timestamp let-in per estendere il tempo di chiusura
                self.window_controller.set_let_in_time()
        except Exception as e:
            error_message = str(e)
            logger.error(f"Error executing let-in command: {e}")

        # Ora invia la risposta con retry
        if error_message:
            await self._send_message_with_retry(update, f"❌ Errore durante l'apertura: {error_message}")
        elif command_success:
            await self._send_message_with_retry(
                update,
                f"✅ Finestra aperta per far entrare il gatto!\n"
                f"🔄 Modalità: {current_mode} (invariata)\n"
                f"⏱️ Chiusura ritardata di 3 secondi extra"
            )
            logger.info(f"Let-in command executed, mode unchanged: {current_mode}, close delay extended")
        else:
            await self._send_message_with_retry(update, "⚠️ La finestra è già aperta o in movimento")
            logger.info("Window already open or moving")

    async def _close_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gestisce il comando /chiudi."""
        logger.info("Close command received")
        if not self.window_controller:
            await self._send_message_with_retry(update, "❌ Controller finestra non disponibile")
            logger.error("Window controller not available")
            return

        # Esegui il comando sulla finestra PRIMA di rispondere
        command_success = False
        error_message = None

        try:
            # Forza la modalità manuale quando si usa il comando
            command_success = self.window_controller.set_window_position(False, manual=True)
        except Exception as e:
            error_message = str(e)
            logger.error(f"Error executing window command: {e}")

        # Ora invia la risposta con retry
        if error_message:
            await self._send_message_with_retry(update, f"❌ Errore durante la chiusura: {error_message}")
        elif command_success:
            await self._send_message_with_retry(update, "✅ Comando di chiusura inviato!\nModalità manuale attivata")
            logger.info("Window close command executed successfully")
        else:
            await self._send_message_with_retry(update, "⚠️ La finestra è già chiusa o in movimento")
            logger.info("Window already closed or moving")

    async def _status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gestisce il comando /status."""
        logger.info("Status command received")
        if not self.window_controller:
            await self._send_message_with_retry(update, "❌ Controller finestra non disponibile")
            logger.error("Window controller not available")
            return

        try:
            status = "🟢 APERTA" if self.window_controller.is_window_open else "🔴 CHIUSA"
            angle = self.window_controller.current_angle
            mode = "🤖 Automatica" if self.window_controller.auto_control_enabled() else "👋 Manuale"
            message = f"Stato finestra: {status}\nAngolo attuale: {angle}°\nModalità: {mode}"
            await self._send_message_with_retry(update, message)
            logger.info(f"Status sent: {message}")
        except Exception as e:
            error_msg = f"Errore nella lettura dello stato: {str(e)}"
            await self._send_message_with_retry(update, f"❌ {error_msg}")
            logger.error(error_msg)

    async def _auto_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gestisce il comando /auto."""
        logger.info("Auto mode command received")
        if not self.window_controller:
            await self._send_message_with_retry(update, "❌ Controller finestra non disponibile")
            logger.error("Window controller not available")
            return

        try:
            self.window_controller.enable_auto_control()
            await self._send_message_with_retry(update, "✅ Modalità automatica attivata")
            logger.info("Automatic control enabled")
        except Exception as e:
            error_msg = f"Errore nell'attivazione modalità automatica: {str(e)}"
            await self._send_message_with_retry(update, f"❌ {error_msg}")
            logger.error(error_msg)

    async def _manual_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gestisce il comando /manuale."""
        logger.info("Manual mode command received")
        if not self.window_controller:
            await self._send_message_with_retry(update, "❌ Controller finestra non disponibile")
            logger.error("Window controller not available")
            return

        try:
            self.window_controller.disable_auto_control()
            await self._send_message_with_retry(update, "✅ Modalità manuale attivata\nLa finestra rimarrà nella posizione impostata")
            logger.info("Manual control enabled")
        except Exception as e:
            error_msg = f"Errore nell'attivazione modalità manuale: {str(e)}"
            await self._send_message_with_retry(update, f"❌ {error_msg}")
            logger.error(error_msg)

    async def _photo_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Gestisce il comando /foto.
        Richiede una foto al sistema. Deve essere implementato dalle classi derivate.
        """
        await update.message.reply_text("⚠️ Funzionalità non implementata")
        logger.warning("Photo command not implemented in base class")

    # ==================== COMANDI GESTIONE GATTI ====================

    async def _cats_list_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gestisce il comando /gatti - Lista gatti registrati."""
        logger.info("Cats list command received")
        global _feeding_manager

        if _feeding_manager is None:
            await update.message.reply_text("⚠️ Sistema alimentazione non disponibile")
            return

        try:
            msg = _feeding_manager.get_cats_list()
            await update.message.reply_text(msg)
        except Exception as e:
            logger.error(f"Error getting cats list: {e}")
            await update.message.reply_text(f"❌ Errore: {e}")

    async def _feeding_stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gestisce il comando /classifica - Statistiche pasti giornalieri."""
        logger.info("Feeding stats command received")
        global _feeding_manager

        if _feeding_manager is None:
            await update.message.reply_text("⚠️ Sistema alimentazione non disponibile")
            return

        try:
            msg = _feeding_manager.get_feeding_stats()
            await update.message.reply_text(msg)
        except Exception as e:
            logger.error(f"Error getting feeding stats: {e}")
            await update.message.reply_text(f"❌ Errore: {e}")

    async def _register_cat_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Gestisce il comando /registra - Registra un nuovo gatto.
        Uso: /registra Nome Peso
        Esempio: /registra Luna 4.2
        """
        logger.info("Register cat command received")
        global _feeding_manager

        if _feeding_manager is None:
            await update.message.reply_text("⚠️ Sistema alimentazione non disponibile")
            return

        args = context.args
        if len(args) < 2:
            await update.message.reply_text(
                "❌ Uso: /registra Nome Peso\n"
                "Esempio: /registra Luna 4.2"
            )
            return

        name = args[0]
        try:
            weight = float(args[1].replace(',', '.'))
        except ValueError:
            await update.message.reply_text("❌ Peso non valido. Usa un numero (es. 4.2)")
            return

        # Tolleranza opzionale (default 0.3kg)
        tolerance = 0.3
        if len(args) >= 3:
            try:
                tolerance = float(args[2].replace(',', '.'))
            except ValueError:
                pass

        try:
            success = _feeding_manager.register_cat(name, weight, tolerance)
            if success:
                await update.message.reply_text(
                    f"✅ Gatto registrato!\n"
                    f"• Nome: {name}\n"
                    f"• Peso: {weight}kg (±{tolerance}kg)"
                )
            else:
                await update.message.reply_text(f"⚠️ Gatto '{name}' già esistente")
        except Exception as e:
            logger.error(f"Error registering cat: {e}")
            await update.message.reply_text(f"❌ Errore: {e}")

    async def _identify_cat_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Gestisce il comando /chiesto - Identifica l'ultimo gatto sconosciuto.
        Uso: /chiesto Nome
        Esempio: /chiesto Luna
        """
        logger.info("Identify cat command received")
        global _feeding_manager

        if _feeding_manager is None:
            await update.message.reply_text("⚠️ Sistema alimentazione non disponibile")
            return

        args = context.args
        if len(args) < 1:
            await update.message.reply_text(
                "❌ Uso: /chiesto Nome\n"
                "Esempio: /chiesto Luna\n\n"
                "Questo comando assegna l'ultima pesata sconosciuta al gatto indicato."
            )
            return

        name = args[0]

        try:
            success = _feeding_manager.identify_last_reading(name)
            if success:
                await update.message.reply_text(
                    f"✅ Pesata assegnata a {name}!\n"
                    f"Il gatto è stato aggiunto/aggiornato nel database."
                )
            else:
                await update.message.reply_text(
                    f"⚠️ Nessuna pesata da assegnare o errore.\n"
                    f"Assicurati che ci sia una pesata non identificata."
                )
        except Exception as e:
            logger.error(f"Error identifying cat: {e}")
            await update.message.reply_text(f"❌ Errore: {e}")
