"""
Base del gestore Telegram per il sistema di rilevamento gatti.
Fornisce le funzionalità di base per il bot Telegram.
"""

import logging
import threading
import asyncio
import time
from typing import Optional, Callable, Any, Dict
from datetime import datetime
from telegram import Update, BotCommand, Bot
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes
)
from telegram.error import (
    TelegramError, 
    NetworkError, 
    TimedOut, 
    RetryAfter
)

# Configurazione logging
logger = logging.getLogger(__name__)

class TelegramBase:
    """
    Classe base per il gestore Telegram con funzionalità essenziali
    e gestione robusta degli errori.
    """
    
    def __init__(self, token: str, chat_id: str):
        """
        Inizializza il gestore base Telegram.
        
        Args:
            token: Token del bot Telegram
            chat_id: ID della chat a cui inviare i messaggi
        """
        self.token = token
        self.chat_id = chat_id
        self.application = None
        self.event_loop = None
        self.bot_thread = None
        self.retry_queue = []
        self.queue_processor_running = False
        self.window_controller = None
        self.bot_initialized = False

        # Configurazione retry
        self.max_retries = 5
        self.base_retry_delay = 2  # secondi

        # Watchdog per monitorare la connessione
        self.last_heartbeat = time.time()
        self.watchdog_running = False
        self.watchdog_interval = 300  # Controlla ogni 5 minuti
        self.heartbeat_timeout = 900  # 15 minuti senza heartbeat = problema
        self.connection_failures = 0  # Contatore fallimenti consecutivi
        self.max_connection_failures = 3  # Riavvia dopo 3 fallimenti consecutivi

        logger.info("Initializing Telegram base handler...")
    
    def start(self):
        """Avvia il bot in un thread separato in modo sicuro."""
        # Avvia il bot in un thread separato
        self.bot_thread = threading.Thread(target=self._run_bot)
        self.bot_thread.daemon = True
        self.bot_thread.start()
        
        # Attendi che il bot sia inizializzato
        timeout = 10  # secondi
        start_time = time.time()
        while not self.bot_initialized and (time.time() - start_time) < timeout:
            time.sleep(0.5)
        
        if not self.bot_initialized:
            logger.warning("Bot initialization timed out. Some functionality may not work.")
        else:
            logger.info("Bot initialization completed successfully.")
            
        # Avvia il processo di gestione della coda dei ritentativi
        self._start_queue_processor()

        # Avvia il watchdog per monitorare la connessione
        self._start_watchdog()

    def _start_watchdog(self):
        """Avvia il thread watchdog per monitorare la connessione del bot."""
        if not self.watchdog_running:
            self.watchdog_running = True
            watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True)
            watchdog_thread.start()
            logger.info("Watchdog avviato per monitorare la connessione Telegram")

    def _watchdog_loop(self):
        """Loop del watchdog che controlla periodicamente la connessione."""
        while self.watchdog_running:
            try:
                time.sleep(self.watchdog_interval)

                # Verifica se il bot è inizializzato
                if not self.bot_initialized:
                    logger.warning("Watchdog: Bot non inizializzato")
                    continue

                # Controlla l'ultimo heartbeat
                time_since_heartbeat = time.time() - self.last_heartbeat
                if time_since_heartbeat > self.heartbeat_timeout:
                    logger.error(f"Watchdog: Nessun heartbeat da {time_since_heartbeat:.0f}s - Bot potrebbe essere disconnesso")
                    # Tenta di riavviare il bot
                    self._restart_bot()
                    self.connection_failures = 0  # Reset contatore dopo riavvio
                else:
                    # Tenta un ping per verificare la connessione
                    if not self._check_connection():
                        self.connection_failures += 1
                        logger.warning(f"Watchdog: Controllo connessione fallito ({self.connection_failures}/{self.max_connection_failures})")
                        # Riavvia solo dopo N fallimenti consecutivi
                        if self.connection_failures >= self.max_connection_failures:
                            logger.error(f"Watchdog: Troppi fallimenti consecutivi, riavvio bot")
                            self._restart_bot()
                            self.connection_failures = 0
                    else:
                        # Reset contatore se connessione OK
                        if self.connection_failures > 0:
                            logger.info(f"Watchdog: Connessione ripristinata dopo {self.connection_failures} fallimenti")
                        self.connection_failures = 0
                        logger.debug(f"Watchdog: Connessione OK (ultimo heartbeat: {time_since_heartbeat:.0f}s fa)")

            except Exception as e:
                logger.error(f"Watchdog: Errore nel loop: {e}")

    def _check_connection(self) -> bool:
        """
        Verifica la connessione del bot provando a fare una chiamata API leggera.

        Returns:
            True se la connessione è attiva, False altrimenti
        """
        try:
            if self.application and self.event_loop and self.bot_initialized:
                # Prova a ottenere le info del bot (operazione leggera)
                result = self._run_coroutine(self.application.bot.get_me())
                if result:
                    # Aggiorna l'heartbeat se la chiamata ha successo
                    self.last_heartbeat = time.time()
                    return True
            return False
        except Exception as e:
            logger.debug(f"Controllo connessione fallito: {e}")
            return False

    def _restart_bot(self):
        """Riavvia il bot in caso di disconnessione."""
        try:
            logger.warning("Tentativo di riavvio del bot Telegram...")

            # Ferma il bot corrente
            self.bot_initialized = False
            if self.event_loop and self.event_loop.is_running():
                self.event_loop.call_soon_threadsafe(self.event_loop.stop)

            # Attendi che il thread si fermi
            time.sleep(2)

            # Riavvia il bot
            self.bot_thread = threading.Thread(target=self._run_bot)
            self.bot_thread.daemon = True
            self.bot_thread.start()

            # Attendi l'inizializzazione
            timeout = 15
            start_time = time.time()
            while not self.bot_initialized and (time.time() - start_time) < timeout:
                time.sleep(0.5)

            if self.bot_initialized:
                logger.info("✅ Bot riavviato con successo")
                self.last_heartbeat = time.time()
            else:
                logger.error("❌ Riavvio del bot fallito")

        except Exception as e:
            logger.error(f"Errore durante il riavvio del bot: {e}")

    def _start_queue_processor(self):
        """Avvia il thread di elaborazione della coda dei ritentativi."""
        if not self.queue_processor_running:
            self.queue_processor_running = True
            threading.Thread(target=self._process_retry_queue, daemon=True).start()
    
    def _process_retry_queue(self):
        """Processa la coda dei ritentativi per i messaggi falliti."""
        while self.queue_processor_running:
            if self.retry_queue:
                # Preleva l'elemento più vecchio dalla coda
                item = self.retry_queue.pop(0)
                func, args, kwargs, retries = item
                
                try:
                    # Esegui la funzione nel loop degli eventi
                    if self.event_loop:
                        asyncio.run_coroutine_threadsafe(func(*args, **kwargs), self.event_loop)
                        logger.info(f"Retry attempt {retries} successful for {func.__name__}")
                except Exception as e:
                    # Se ci sono ancora tentativi disponibili, rimetti in coda
                    if retries < self.max_retries:
                        # Calcola il ritardo con backoff esponenziale
                        delay = self.base_retry_delay * (2 ** retries)
                        logger.warning(f"Retry {retries} failed for {func.__name__}, retrying in {delay}s: {str(e)}")
                        self.retry_queue.append((func, args, kwargs, retries + 1))
                        time.sleep(delay)
                    else:
                        logger.error(f"Max retries reached for {func.__name__}, giving up: {str(e)}")
            
            # Attendi un po' prima di controllare nuovamente la coda
            time.sleep(0.5)
    
    def _run_bot(self):
        """Esegue il bot in un thread separato con gestione degli errori."""
        try:
            # Crea un nuovo event loop per questo thread
            self.event_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.event_loop)
            
            # Esegui la configurazione del bot
            self.event_loop.run_until_complete(self._setup_bot())
            
            # Imposta il flag di inizializzazione
            self.bot_initialized = True
            
            # Mantieni il loop in esecuzione
            self.event_loop.run_forever()
        except Exception as e:
            logger.error(f"Bot thread error: {e}", exc_info=True)
            self.bot_initialized = False
    
    async def _setup_bot(self):
        """
        Configurazione base del bot.
        Questo metodo deve essere esteso nelle classi derivate.
        """
        try:
            # Crea l'applicazione con gestione automatica delle eccezioni
            self.application = ApplicationBuilder().token(self.token).build()
            
            # Inizializza ma non avviare ancora i componenti
            await self.application.initialize()
            await self.application.start()
            
            # Questo metodo sarà esteso dalle classi derivate
            await self._setup_handlers()
            
            # Avvia il polling
            await self.application.updater.start_polling(
                poll_interval=0.5,
                timeout=10,
                bootstrap_retries=5,
                read_timeout=15,
                write_timeout=15,
                connect_timeout=15,
                drop_pending_updates=True
            )
            
            logger.info("Telegram bot base initialized")
            await self._send_message("🟢 Sistema di rilevamento gatti avviato")
            
        except Exception as e:
            logger.error(f"Failed to initialize Telegram bot: {e}", exc_info=True)
            self.bot_initialized = False
            raise
    
    async def _setup_handlers(self):
        """
        Configura gli handler del bot.
        Questo metodo deve essere implementato nelle classi derivate.
        """
        pass
    
    def _run_coroutine(self, coroutine):
        """
        Esegue una coroutine nel loop degli eventi del bot in modo sicuro.
        
        Args:
            coroutine: La coroutine da eseguire
            
        Returns:
            Il risultato della coroutine o None in caso di errore
        """
        if self.event_loop and self.bot_initialized:
            try:
                future = asyncio.run_coroutine_threadsafe(coroutine, self.event_loop)
                # Attendi il risultato con timeout
                return future.result(timeout=10)
            except (asyncio.TimeoutError, concurrent.futures.TimeoutError):
                logger.error("Coroutine execution timed out")
            except Exception as e:
                logger.error(f"Error executing coroutine: {e}")
        else:
            logger.error("Event loop not available or bot not initialized")
        return None
    
    def send_message(self, text: str) -> bool:
        """
        Invia un messaggio di testo con gestione degli errori.
        
        Args:
            text: Il testo del messaggio
            
        Returns:
            True se il messaggio è stato inviato o messo in coda, False altrimenti
        """
        if self.application and self.event_loop and self.bot_initialized:
            try:
                self._run_coroutine(self._send_message(text))
                return True
            except Exception as e:
                logger.error(f"Error sending message, queuing for retry: {e}")
                # Metti in coda per ritentare
                self.retry_queue.append((self._send_message, (text,), {}, 0))
                return True
        else:
            logger.error("Cannot send message - bot not initialized")
            return False
    
    async def _send_message(self, text: str) -> bool:
        """
        Invia un messaggio di testo in modo asincrono con gestione degli errori.
        
        Args:
            text: Il testo del messaggio
            
        Returns:
            True se il messaggio è stato inviato, False altrimenti
        """
        try:
            # Tentativi con backoff esponenziale incorporato
            for attempt in range(self.max_retries):
                try:
                    await self.application.bot.send_message(
                        chat_id=self.chat_id,
                        text=text,
                        disable_notification=False,
                        read_timeout=10,
                        write_timeout=10,
                        connect_timeout=10,
                        pool_timeout=10
                    )
                    logger.debug(f"Message sent successfully: {text[:50]}...")
                    # Aggiorna l'heartbeat dopo un invio riuscito
                    self.last_heartbeat = time.time()
                    return True
                except RetryAfter as e:
                    # Ritardo richiesto da Telegram
                    wait_time = e.retry_after
                    logger.warning(f"Rate limited by Telegram, waiting {wait_time}s")
                    await asyncio.sleep(wait_time)
                except (NetworkError, TimedOut) as e:
                    # Problemi di rete, ritenta con ritardo esponenziale
                    wait_time = self.base_retry_delay * (2 ** attempt)
                    logger.warning(f"Network error, retry {attempt+1}/{self.max_retries} in {wait_time}s: {e}")
                    await asyncio.sleep(wait_time)
                except Exception as e:
                    logger.error(f"Failed to send message (attempt {attempt+1}/{self.max_retries}): {e}")
                    if attempt == self.max_retries - 1:
                        raise
                    await asyncio.sleep(self.base_retry_delay * (2 ** attempt))
            
            return False
        except Exception as e:
            logger.error(f"Final error sending message: {e}")
            return False
    
    def send_photo(self, photo_path: str, caption: str = None) -> bool:
        """
        Invia una foto con gestione degli errori.
        
        Args:
            photo_path: Il percorso del file immagine
            caption: La didascalia della foto (opzionale)
            
        Returns:
            True se la foto è stata inviata o messa in coda, False altrimenti
        """
        if self.application and self.event_loop and self.bot_initialized:
            try:
                self._run_coroutine(self._send_photo(photo_path, caption))
                return True
            except Exception as e:
                logger.error(f"Error sending photo, queuing for retry: {e}")
                # Metti in coda per ritentare
                self.retry_queue.append((self._send_photo, (photo_path, caption), {}, 0))
                return True
        else:
            logger.error("Cannot send photo - bot not initialized")
            return False
    
    async def _send_photo(self, photo_path: str, caption: str = None) -> bool:
        """
        Invia una foto in modo asincrono con gestione degli errori.
        
        Args:
            photo_path: Il percorso del file immagine
            caption: La didascalia della foto (opzionale)
            
        Returns:
            True se la foto è stata inviata, False altrimenti
        """
        try:
            # Tentativi con backoff esponenziale incorporato
            for attempt in range(self.max_retries):
                try:
                    with open(photo_path, 'rb') as photo:
                        await self.application.bot.send_photo(
                            chat_id=self.chat_id,
                            photo=photo,
                            caption=caption,
                            read_timeout=20,  # Tempi maggiori per l'upload
                            write_timeout=20,
                            connect_timeout=10,
                            pool_timeout=20
                        )
                    logger.debug(f"Photo sent successfully: {photo_path}")
                    # Aggiorna l'heartbeat dopo un invio riuscito
                    self.last_heartbeat = time.time()
                    return True
                except FileNotFoundError:
                    logger.error(f"Photo file not found: {photo_path}")
                    return False
                except RetryAfter as e:
                    # Ritardo richiesto da Telegram
                    wait_time = e.retry_after
                    logger.warning(f"Rate limited by Telegram, waiting {wait_time}s")
                    await asyncio.sleep(wait_time)
                except (NetworkError, TimedOut) as e:
                    # Problemi di rete, ritenta con ritardo esponenziale
                    wait_time = self.base_retry_delay * (2 ** attempt)
                    logger.warning(f"Network error, retry {attempt+1}/{self.max_retries} in {wait_time}s: {e}")
                    await asyncio.sleep(wait_time)
                except Exception as e:
                    logger.error(f"Failed to send photo (attempt {attempt+1}/{self.max_retries}): {e}")
                    if attempt == self.max_retries - 1:
                        raise
                    await asyncio.sleep(self.base_retry_delay * (2 ** attempt))
            
            return False
        except Exception as e:
            logger.error(f"Final error sending photo: {e}")
            return False
    
    def __del__(self):
        """Cleanup alla chiusura."""
        self.queue_processor_running = False
        if self.event_loop:
            try:
                self._run_coroutine(self._cleanup())
            except Exception as e:
                logger.error(f"Error during cleanup: {e}")

    async def _cleanup(self):
        """Pulisce le risorse del bot."""
        try:
            if self.application:
                await self.application.stop()
                await self.application.shutdown()
                logger.info("Telegram bot stopped")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
