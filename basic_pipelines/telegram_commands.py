"""
Modulo per la gestione dei comandi Telegram per il sistema di rilevamento gatti.
Include comandi per finestra e gestione alimentazione gatti.
"""

import logging
import asyncio
from datetime import datetime
from telegram import Update, BotCommand, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes
)
from telegram.error import TimedOut, NetworkError

logger = logging.getLogger(__name__)

# Manager globali (impostati dall'esterno)
_feeding_manager = None
_camera_manager = None

def set_feeding_manager(manager):
    """Imposta il feeding manager globale."""
    global _feeding_manager
    _feeding_manager = manager

def set_camera_manager(manager):
    """Imposta il camera manager globale per gestione telecamere RTSP."""
    global _camera_manager
    _camera_manager = manager

# Mappa bottoni → comandi (solo per i bottoni che mappano 1:1 su un comando)
BUTTON_MAP = {
    "🟢 Apri": "/apri",
    "🔴 Chiudi": "/chiudi",
    "🐱 Fai entrare": "/faientrare",
    "📊 Status": "/status",
    "🤖 Auto": "/auto",
    "👋 Manuale": "/manuale",
    "🔔 Notifiche ON": "/notificheon",
    "🔕 Notifiche OFF": "/notificheoff",
    "📷 Telecamere": "/telecamere",
    "🔧 Reset Servo": "/resetservo",
    "🎛️ Servo": "/servo",
}

# Etichette pulsanti per il sottomenu Foto: (etichetta_bottone → nome_camera passato a /foto)
FOTO_BUTTONS = {
    "📸 USB": "USB",
    "📸 Corridoio": "Corridoio",
    "📸 Divano": "Divano",
    "📸 Portico": "Portico",
}

def get_main_keyboard():
    """Crea la tastiera persistente con bottoni."""
    keyboard = [
        [KeyboardButton("🟢 Apri"), KeyboardButton("🔴 Chiudi"), KeyboardButton("🐱 Fai entrare")],
        [KeyboardButton("🤖 Auto"), KeyboardButton("👋 Manuale"), KeyboardButton("📊 Status")],
        [KeyboardButton("🔔 Notifiche ON"), KeyboardButton("🔕 Notifiche OFF"), KeyboardButton("📷 Telecamere")],
        [KeyboardButton("📸 Foto"), KeyboardButton("🔧 Reset Servo"), KeyboardButton("🎛️ Servo")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_foto_keyboard():
    """Sottomenu Foto: scelta camera + toggle notifiche + indietro."""
    keyboard = [
        [KeyboardButton("📸 USB"), KeyboardButton("📸 Corridoio")],
        [KeyboardButton("📸 Divano"), KeyboardButton("📸 Portico")],
        [KeyboardButton("🔔 Notifiche ON"), KeyboardButton("🔕 Notifiche OFF")],
        [KeyboardButton("⬅️ Indietro")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_servo_keyboard(servo_type, current_angle):
    """Crea la inline keyboard per il controllo step di un servo."""
    label = "Finestra" if servo_type == "window" else "Serratura"
    keyboard = [
        [
            InlineKeyboardButton("-5°", callback_data=f"servo_{servo_type}_-5"),
            InlineKeyboardButton("-1°", callback_data=f"servo_{servo_type}_-1"),
            InlineKeyboardButton("+1°", callback_data=f"servo_{servo_type}_+1"),
            InlineKeyboardButton("+5°", callback_data=f"servo_{servo_type}_+5"),
        ],
        [
            InlineKeyboardButton(f"📐 {label}: {current_angle:.1f}°", callback_data="servo_noop"),
        ],
        [
            InlineKeyboardButton("✅ Fatto", callback_data="servo_done"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_servo_choice_keyboard():
    """Crea la inline keyboard per scegliere quale servo controllare."""
    keyboard = [
        [
            InlineKeyboardButton("🪟 Finestra", callback_data="servo_choose_window"),
            InlineKeyboardButton("🔒 Serratura", callback_data="servo_choose_lock"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


class TelegramCommands:
    """Mixin per la gestione dei comandi Telegram."""

    async def _send_message_with_retry(self, update: Update, message: str, max_retries: int = 3, timeout: int = 10) -> bool:
        """Invia un messaggio Telegram con retry automatico in caso di timeout."""
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
                    await asyncio.sleep(1)
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
            BotCommand("status", "Mostra lo stato del sistema"),
            BotCommand("auto", "Attiva controllo automatico"),
            BotCommand("manuale", "Disattiva controllo automatico"),
            BotCommand("foto", "Snapshot telecamera: /foto [nome] (USB o RTSP)"),
            # Comandi telecamere RTSP
            BotCommand("telecamere", "Lista telecamere e stato"),
            BotCommand("cam", "Abilita/disabilita camera: /cam nome on|off"),
            BotCommand("notifiche", "Stato notifiche RTSP"),
            BotCommand("notificheon", "Attiva notifiche RTSP"),
            BotCommand("notificheoff", "Disattiva notifiche RTSP"),
            # Comandi manutenzione
            BotCommand("resetservo", "Reset servo in protezione"),
            BotCommand("servo", "Controllo manuale servo step-by-step"),
            BotCommand("servofinestra", "Controllo manuale servo finestra"),
            BotCommand("servoserratura", "Controllo manuale servo serratura"),
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
        # Comandi manutenzione
        self.application.add_handler(CommandHandler("resetservo", self._reset_servo_command))
        # Comandi controllo manuale servo
        self.application.add_handler(CommandHandler("servo", self._servo_choice_command))
        self.application.add_handler(CommandHandler("servofinestra", self._servo_window_command))
        self.application.add_handler(CommandHandler("servoserratura", self._servo_lock_command))
        self.application.add_handler(CallbackQueryHandler(self._servo_callback, pattern="^servo_"))
        # Comandi telecamere RTSP
        self.application.add_handler(CommandHandler("telecamere", self._cameras_list_command))
        self.application.add_handler(CommandHandler("cam", self._camera_toggle_command))
        self.application.add_handler(CommandHandler("notifiche", self._notifications_toggle_command))
        self.application.add_handler(CommandHandler("notificheon", self._notifications_on_command))
        self.application.add_handler(CommandHandler("notificheoff", self._notifications_off_command))
        # Comandi gestione gatti
        self.application.add_handler(CommandHandler("gatti", self._cats_list_command))
        self.application.add_handler(CommandHandler("classifica", self._feeding_stats_command))
        self.application.add_handler(CommandHandler("registra", self._register_cat_command))
        self.application.add_handler(CommandHandler("chiesto", self._identify_cat_command))
        # Handler per bottoni tastiera (testo che corrisponde ai bottoni)
        self.application.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND, self._button_handler
        ))
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
            "/status - Stato del sistema\n"
            "/auto - Modalità automatica\n"
            "/manuale - Modalità manuale\n\n"
            "📷 Comandi telecamere:\n"
            "/telecamere - Lista telecamere\n"
            "/cam nome on|off - Abilita/disabilita\n"
            "/notifiche on|off - Notifiche RTSP\n\n"
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
            "Usa i bottoni qui sotto oppure i comandi /slash.",
            reply_markup=get_main_keyboard()
        )

    async def _button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gestisce i tap sui bottoni della tastiera."""
        text = update.message.text

        # Navigazione sottomenu Foto
        if text == "📸 Foto":
            logger.info("Button pressed: 📸 Foto -> open foto submenu")
            await update.message.reply_text(
                "📷 Scegli la telecamera per la foto, oppure attiva/disattiva le notifiche:",
                reply_markup=get_foto_keyboard()
            )
            return
        if text == "⬅️ Indietro":
            logger.info("Button pressed: ⬅️ Indietro -> main keyboard")
            await update.message.reply_text("⬅️ Menu principale", reply_markup=get_main_keyboard())
            return

        # Bottoni del sottomenu foto: scatto da camera specifica
        if text in FOTO_BUTTONS:
            camera_name = FOTO_BUTTONS[text]
            logger.info(f"Button pressed: {text} -> /foto {camera_name}")
            context.args = [camera_name]
            await self._photo_command(update, context)
            return

        # Bottoni mappati 1:1 su un comando
        command = BUTTON_MAP.get(text)
        if command is None:
            return  # Ignora messaggi non riconosciuti

        logger.info(f"Button pressed: {text} -> {command}")

        handlers = {
            "/apri": self._open_command,
            "/chiudi": self._close_command,
            "/faientrare": self._let_in_command,
            "/status": self._status_command,
            "/auto": self._auto_command,
            "/manuale": self._manual_command,
            "/notificheon": self._notifications_on_command,
            "/notificheoff": self._notifications_off_command,
            "/telecamere": self._cameras_list_command,
            "/resetservo": self._reset_servo_command,
            "/servo": self._servo_choice_command,
        }

        handler = handlers.get(command)
        if handler:
            await handler(update, context)

    async def _open_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gestisce il comando /apri."""
        logger.info("Open command received")
        if not self.window_controller:
            await self._send_message_with_retry(update, "❌ Controller finestra non disponibile")
            logger.error("Window controller not available")
            return

        command_success = False
        error_message = None

        try:
            command_success = await asyncio.get_event_loop().run_in_executor(
                None, self.window_controller.set_window_position, True, True
            )
        except Exception as e:
            error_message = str(e)
            logger.error(f"Error executing window command: {e}")

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

        command_success = False
        error_message = None
        current_mode = None

        try:
            current_mode = "automatica" if self.window_controller.auto_control_enabled() else "manuale"
            command_success = await asyncio.get_event_loop().run_in_executor(
                None, self.window_controller.set_window_position, True, False
            )

            if command_success:
                self.window_controller.set_let_in_time()
        except Exception as e:
            error_message = str(e)
            logger.error(f"Error executing let-in command: {e}")

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

        command_success = False
        error_message = None

        try:
            command_success = await asyncio.get_event_loop().run_in_executor(
                None, self.window_controller.set_window_position, False, True
            )
        except Exception as e:
            error_message = str(e)
            logger.error(f"Error executing window command: {e}")

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

        message_parts = []

        if self.window_controller:
            try:
                status = "🟢 APERTA" if self.window_controller.is_window_open else "🔴 CHIUSA"
                angle = self.window_controller.current_angle
                mode = "🤖 Auto" if self.window_controller.auto_control_enabled() else "👋 Manuale"
                message_parts.append(f"🪟 Finestra: {status} ({angle}°)\n📍 Modalità: {mode}")
            except Exception as e:
                message_parts.append(f"🪟 Finestra: ❌ Errore")
                logger.error(f"Window status error: {e}")
        else:
            message_parts.append("🪟 Finestra: ⚠️ Non disponibile")

        global _camera_manager
        if _camera_manager:
            try:
                cam_status = _camera_manager.get_status()
                if cam_status:
                    notif_enabled = getattr(self.user_data, 'rtsp_notifications_enabled', True) if hasattr(self, 'user_data') else True
                    notif_status = "🔔" if notif_enabled else "🔕"
                    message_parts.append(f"\n📷 Telecamere: {cam_status} {notif_status}")
            except Exception as e:
                logger.error(f"Camera status error: {e}")

        message = "\n".join(message_parts)
        await self._send_message_with_retry(update, message)
        logger.info("Status sent")

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
        """Gestisce il comando /foto - Snapshot dall'ultimo frame ricevuto.

        Uso:
          /foto             → lista delle telecamere disponibili
          /foto <nome>      → invia lo snapshot della telecamera (USB o RTSP)
        """
        global _camera_manager
        logger.info(f"Photo command received: args={context.args}")

        if _camera_manager is None or not hasattr(_camera_manager, 'get_snapshot'):
            await update.message.reply_text("⚠️ Snapshot non disponibile (camera manager assente)")
            return

        # Senza argomenti: lista
        if not context.args:
            available = _camera_manager.get_available_snapshots()
            if not available:
                await update.message.reply_text(
                    "📷 Nessuno snapshot ancora disponibile.\n"
                    "Le telecamere stanno appena partendo, riprova tra qualche secondo."
                )
                return

            from datetime import datetime as _dt
            now = _dt.now()
            lines = ["📷 *Telecamere disponibili per /foto:*\n"]
            for name, ts in available:
                age = (now - ts).total_seconds()
                lines.append(f"• `{name}` _(frame di {age:.0f}s fa)_")
            lines.append("\nUso: `/foto <nome>`")
            await update.message.reply_text("\n".join(lines), parse_mode='Markdown')
            return

        # Con argomento: invia foto
        name = " ".join(context.args)
        snap = _camera_manager.get_snapshot(name)
        if snap is None:
            available = [n for n, _ in _camera_manager.get_available_snapshots()]
            await update.message.reply_text(
                f"❌ Telecamera '{name}' non trovata o senza frame.\n"
                f"Disponibili: {', '.join(available) if available else 'nessuna'}"
            )
            return

        frame_bgr, ts = snap

        # Encode JPG fuori dal loop asincrono (cv2 è sincrono)
        import cv2
        import io
        loop = asyncio.get_event_loop()

        def _encode():
            ok, buf = cv2.imencode('.jpg', frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if not ok:
                return None
            return buf.tobytes()

        try:
            jpg = await loop.run_in_executor(None, _encode)
        except Exception as e:
            logger.error(f"Photo encode error: {e}")
            await update.message.reply_text(f"❌ Errore encoding JPG: {e}")
            return

        if jpg is None:
            await update.message.reply_text("❌ Encoding JPG fallito")
            return

        age = (datetime.now() - ts).total_seconds() if isinstance(ts, datetime) else 0
        h, w = frame_bgr.shape[:2]
        caption = f"📷 {name} — {w}x{h}, frame di {age:.0f}s fa"

        try:
            # Timeout generosi: l'upload della foto a Telegram può superare
            # i default (15s) sotto jitter di rete, generando un falso "Timed out"
            # anche quando la foto è in realtà stata consegnata.
            await update.message.reply_photo(
                photo=io.BytesIO(jpg),
                caption=caption,
                read_timeout=60,
                write_timeout=60,
                connect_timeout=15,
                pool_timeout=20,
            )
        except Exception as e:
            logger.error(f"Photo send error: {e}")
            await update.message.reply_text(f"❌ Invio foto fallito: {e}")

    # ==================== COMANDI MANUTENZIONE ====================

    async def _reset_servo_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Gestisce il comando /resetservo - Reset servo in protezione.
        Prova prima il reset soft (PCA9685), poi DTR, poi USB.
        """
        logger.info("Reset servo command received")
        await self._send_message_with_retry(update, "🔧 Tentativo reset servo...")

        import subprocess
        import os

        script_dir = os.path.dirname(os.path.abspath(__file__))
        cat_window = os.path.join(script_dir, "cat_window.py")

        def _run_subprocess(args):
            return subprocess.run(args, capture_output=True, text=True, timeout=15)

        loop = asyncio.get_event_loop()

        # 1. Prova reset soft PCA9685
        try:
            result = await loop.run_in_executor(
                None, _run_subprocess, ["python3", cat_window, "reset"]
            )
            if result.returncode == 0:
                await self._send_message_with_retry(
                    update,
                    "✅ Reset PCA9685 completato!\nIl servo dovrebbe essere operativo."
                )
                logger.info("PCA9685 soft reset successful")
                return
            else:
                logger.warning(f"PCA9685 soft reset failed: {result.stderr}")
        except Exception as e:
            logger.warning(f"PCA9685 soft reset error: {e}")

        # 2. Fallback: reset Arduino via DTR
        await self._send_message_with_retry(update, "⚠️ Reset soft fallito, provo reset Arduino via DTR...")
        try:
            result = await loop.run_in_executor(
                None, _run_subprocess, ["python3", cat_window, "hardreset"]
            )
            if result.returncode == 0:
                await self._send_message_with_retry(
                    update,
                    "✅ Reset Arduino completato!\nAttendere qualche secondo prima di usare la finestra."
                )
                logger.info("Arduino DTR reset successful")
                return
            else:
                logger.warning(f"Arduino DTR reset failed: {result.stderr}")
        except Exception as e:
            logger.warning(f"Arduino DTR reset error: {e}")

        # 3. Ultimo tentativo: reset USB
        await self._send_message_with_retry(update, "⚠️ Reset DTR fallito, provo reset USB...")
        try:
            result = await loop.run_in_executor(
                None, _run_subprocess, ["python3", cat_window, "usbreset"]
            )
            if result.returncode == 0:
                await self._send_message_with_retry(
                    update,
                    "✅ Reset USB completato!\nAttendere 5 secondi prima di usare la finestra."
                )
                logger.info("USB reset successful")
                return
        except Exception as e:
            logger.error(f"USB reset error: {e}")

        await self._send_message_with_retry(
            update,
            "❌ Tutti i tentativi di reset falliti.\nPotrebbe essere necessario togliere alimentazione."
        )
        logger.error("All servo reset attempts failed")

    # ==================== CONTROLLO MANUALE SERVO ====================

    async def _servo_choice_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gestisce il comando /servo - Mostra scelta servo da controllare."""
        logger.info("Servo choice command received")
        if not self.window_controller:
            await self._send_message_with_retry(update, "❌ Controller finestra non disponibile")
            return

        await update.message.reply_text(
            "🎛️ Controllo manuale servo\nScegli quale servo controllare:",
            reply_markup=get_servo_choice_keyboard()
        )

    async def _servo_window_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gestisce il comando /servofinestra - Controllo step finestra."""
        logger.info("Servo window manual control command received")
        if not self.window_controller:
            await self._send_message_with_retry(update, "❌ Controller finestra non disponibile")
            return

        # Leggi angolo attuale
        angles = await asyncio.get_event_loop().run_in_executor(
            None, self.window_controller.read_servo_angles
        )
        if angles is None:
            await self._send_message_with_retry(update, "❌ Impossibile leggere posizione servo")
            return

        self.window_controller.manual_mode = True
        await update.message.reply_text(
            f"🪟 Controllo manuale FINESTRA\n"
            f"Modalità: manuale\n"
            f"Usa i bottoni per muovere di 1° o 5°",
            reply_markup=get_servo_keyboard("window", angles["window"])
        )

    async def _servo_lock_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gestisce il comando /servoserratura - Controllo step serratura."""
        logger.info("Servo lock manual control command received")
        if not self.window_controller:
            await self._send_message_with_retry(update, "❌ Controller finestra non disponibile")
            return

        # Leggi angolo attuale
        angles = await asyncio.get_event_loop().run_in_executor(
            None, self.window_controller.read_servo_angles
        )
        if angles is None:
            await self._send_message_with_retry(update, "❌ Impossibile leggere posizione servo")
            return

        self.window_controller.manual_mode = True
        await update.message.reply_text(
            f"🔒 Controllo manuale SERRATURA\n"
            f"Modalità: manuale\n"
            f"Usa i bottoni per muovere di 1° o 5°",
            reply_markup=get_servo_keyboard("lock", angles["lock"])
        )

    async def _servo_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gestisce i callback dei bottoni inline servo."""
        query = update.callback_query
        await query.answer()  # Acknowledges subito per evitare timeout

        data = query.data

        if data == "servo_noop":
            return

        if data == "servo_done":
            # Sincronizza stato e chiudi
            if self.window_controller:
                angles = await asyncio.get_event_loop().run_in_executor(
                    None, self.window_controller.sync_state_from_hardware
                )
                if angles:
                    await query.edit_message_text(
                        f"✅ Controllo servo terminato\n"
                        f"🪟 Finestra: {angles['window']:.1f}°\n"
                        f"🔒 Serratura: {angles['lock']:.1f}°\n"
                        f"Modalità: manuale"
                    )
                else:
                    await query.edit_message_text("✅ Controllo servo terminato")
            else:
                await query.edit_message_text("✅ Controllo servo terminato")
            return

        # Scelta servo dal menu /servo
        if data == "servo_choose_window":
            if not self.window_controller:
                await query.edit_message_text("❌ Controller non disponibile")
                return
            angles = await asyncio.get_event_loop().run_in_executor(
                None, self.window_controller.read_servo_angles
            )
            if angles is None:
                await query.edit_message_text("❌ Impossibile leggere posizione servo")
                return
            self.window_controller.manual_mode = True
            await query.edit_message_text(
                f"🪟 Controllo manuale FINESTRA\n"
                f"Modalità: manuale\n"
                f"Usa i bottoni per muovere di 1° o 5°",
                reply_markup=get_servo_keyboard("window", angles["window"])
            )
            return

        if data == "servo_choose_lock":
            if not self.window_controller:
                await query.edit_message_text("❌ Controller non disponibile")
                return
            angles = await asyncio.get_event_loop().run_in_executor(
                None, self.window_controller.read_servo_angles
            )
            if angles is None:
                await query.edit_message_text("❌ Impossibile leggere posizione servo")
                return
            self.window_controller.manual_mode = True
            await query.edit_message_text(
                f"🔒 Controllo manuale SERRATURA\n"
                f"Modalità: manuale\n"
                f"Usa i bottoni per muovere di 1° o 5°",
                reply_markup=get_servo_keyboard("lock", angles["lock"])
            )
            return

        # Parsing step: servo_{window|lock}_{delta}
        parts = data.split("_")
        if len(parts) != 3:
            return

        servo_type = parts[1]  # "window" o "lock"
        try:
            delta = int(parts[2])
        except ValueError:
            return

        if not self.window_controller:
            await query.edit_message_text("❌ Controller non disponibile")
            return

        # Esegui step in executor per non bloccare l'event loop
        try:
            success, target, readback = await asyncio.get_event_loop().run_in_executor(
                None, self.window_controller.step_servo, servo_type, delta
            )
        except Exception as e:
            logger.error(f"Servo step error: {e}")
            label = "Finestra" if servo_type == "window" else "Serratura"
            await query.edit_message_text(
                f"❌ Errore: {e}\nRiprova con i bottoni.",
                reply_markup=get_servo_keyboard(servo_type, 0)
            )
            return

        if success:
            label = "FINESTRA" if servo_type == "window" else "SERRATURA"
            await query.edit_message_text(
                f"{'🪟' if servo_type == 'window' else '🔒'} Controllo manuale {label}\n"
                f"Target: {target:.1f}° → Letto: {readback:.1f}°",
                reply_markup=get_servo_keyboard(servo_type, readback)
            )
        else:
            label = "Finestra" if servo_type == "window" else "Serratura"
            await query.edit_message_text(
                f"⚠️ {label}: comando fallito (target: {target:.1f}°)\nRiprova.",
                reply_markup=get_servo_keyboard(servo_type, readback)
            )

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
        """Gestisce il comando /registra - Registra un nuovo gatto."""
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
        """Gestisce il comando /chiesto - Identifica l'ultimo gatto sconosciuto."""
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

    # ==================== COMANDI TELECAMERE RTSP ====================

    async def _cameras_list_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gestisce il comando /telecamere - Lista telecamere configurate."""
        logger.info("Cameras list command received")
        global _camera_manager

        if _camera_manager is None:
            try:
                from tapo_config import TAPO_CAMERAS
                if not TAPO_CAMERAS:
                    await update.message.reply_text("📷 Nessuna telecamera configurata")
                    return

                msg = "📷 *Telecamere configurate:*\n\n"
                for cam in TAPO_CAMERAS:
                    status = "🟢" if cam.get('enabled', True) else "🔴"
                    classes = ", ".join(cam.get('detect_classes', ['cat', 'person']))
                    msg += f"{status} *{cam['name']}*\n"
                    msg += f"   Classi: {classes}\n"
                await update.message.reply_text(msg, parse_mode='Markdown')
            except ImportError:
                await update.message.reply_text("⚠️ Configurazione telecamere non trovata")
            except Exception as e:
                await update.message.reply_text(f"❌ Errore: {e}")
            return

        try:
            msg = _camera_manager.get_cameras_info()
            await update.message.reply_text(msg, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Error getting cameras list: {e}")
            await update.message.reply_text(f"❌ Errore: {e}")

    async def _camera_toggle_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gestisce il comando /cam - Abilita o disabilita una telecamera."""
        logger.info("Camera toggle command received")
        global _camera_manager

        args = context.args
        if len(args) < 2:
            await update.message.reply_text(
                "❌ Uso: /cam nome on|off\n"
                "Esempio: /cam corridoio off\n\n"
                "Usa /telecamere per vedere le telecamere disponibili."
            )
            return

        camera_name = args[0]
        action = args[1].lower()

        if action not in ['on', 'off']:
            await update.message.reply_text("❌ Azione non valida. Usa 'on' o 'off'")
            return

        enable = (action == 'on')

        if _camera_manager is None:
            try:
                import tapo_config
                found = False
                for cam in tapo_config.TAPO_CAMERAS:
                    if cam['name'].lower() == camera_name.lower():
                        cam['enabled'] = enable
                        found = True
                        break

                if found:
                    status = "abilitata 🟢" if enable else "disabilitata 🔴"
                    await update.message.reply_text(
                        f"✅ Telecamera *{camera_name}* {status}\n"
                        f"⚠️ Riavvia il servizio per applicare:\n"
                        f"`sudo systemctl restart cat-window`",
                        parse_mode='Markdown'
                    )
                else:
                    await update.message.reply_text(f"❌ Telecamera '{camera_name}' non trovata")
            except Exception as e:
                await update.message.reply_text(f"❌ Errore: {e}")
            return

        try:
            success = _camera_manager.toggle_camera(camera_name, enable)
            if success:
                status = "abilitata 🟢" if enable else "disabilitata 🔴"
                await update.message.reply_text(f"✅ Telecamera *{camera_name}* {status}", parse_mode='Markdown')
            else:
                await update.message.reply_text(f"❌ Telecamera '{camera_name}' non trovata")
        except Exception as e:
            logger.error(f"Error toggling camera: {e}")
            await update.message.reply_text(f"❌ Errore: {e}")

    async def _notifications_toggle_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gestisce il comando /notifiche - Abilita/disabilita notifiche RTSP."""
        logger.info("Notifications toggle command received")

        if not hasattr(self, 'user_data') or self.user_data is None:
            await update.message.reply_text("⚠️ Sistema non disponibile")
            return

        args = context.args

        if not args:
            enabled = getattr(self.user_data, 'rtsp_notifications_enabled', True)
            status = "🟢 Attive" if enabled else "🔴 Disattivate"
            await update.message.reply_text(
                f"📷 Notifiche telecamere RTSP: {status}\n\n"
                f"Usa /notifiche on|off per modificare"
            )
            return

        action = args[0].lower()
        if action not in ['on', 'off']:
            await update.message.reply_text("❌ Uso: /notifiche on|off")
            return

        enable = (action == 'on')
        self.user_data.rtsp_notifications_enabled = enable
        self.user_data.save_rtsp_notifications()

        status = "🟢 attivate" if enable else "🔴 disattivate"
        await update.message.reply_text(f"✅ Notifiche telecamere RTSP {status}")
        logger.info(f"RTSP notifications {'enabled' if enable else 'disabled'}")

    async def _notifications_on_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gestisce il comando /notificheon."""
        if not hasattr(self, 'user_data') or self.user_data is None:
            await update.message.reply_text("⚠️ Sistema non disponibile")
            return
        self.user_data.rtsp_notifications_enabled = True
        self.user_data.save_rtsp_notifications()
        await update.message.reply_text("✅ Notifiche telecamere RTSP 🟢 attivate")
        logger.info("RTSP notifications enabled via direct command")

    async def _notifications_off_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gestisce il comando /notificheoff."""
        if not hasattr(self, 'user_data') or self.user_data is None:
            await update.message.reply_text("⚠️ Sistema non disponibile")
            return
        self.user_data.rtsp_notifications_enabled = False
        self.user_data.save_rtsp_notifications()
        await update.message.reply_text("✅ Notifiche telecamere RTSP 🔴 disattivate")
        logger.info("RTSP notifications disabled via direct command")
