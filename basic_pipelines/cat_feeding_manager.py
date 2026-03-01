#!/usr/bin/env python3
"""
Cat Feeding Manager - Gestisce la comunicazione MQTT con ESP32 e la logica di alimentazione.
Segue l'architettura definita in cat_feeding_system_architecture.md
"""

import json
import base64
import os
import logging
import threading
from datetime import datetime
from typing import Optional, Callable, Dict, Any

import paho.mqtt.client as mqtt
import requests

from cat_database import CatDatabase

logger = logging.getLogger(__name__)


class CatFeedingManager:
    """
    Gestisce il sistema di alimentazione gatti.

    Funzionalità:
    - Riceve pesate e foto da ESP32 via MQTT
    - Identifica gatti per peso
    - Decide se erogare cibo
    - Salva foto per training
    - Notifica via Telegram
    """

    # Topic MQTT (da architettura)
    TOPIC_WEIGHT_STABLE = "casa/gatti/mangiatoia/peso/stable"
    TOPIC_CAT_DETECTED = "casa/gatti/mangiatoia/evento/gatto_rilevato"
    TOPIC_CAT_LEFT = "casa/gatti/mangiatoia/evento/gatto_partito"
    TOPIC_PHOTO_REQUEST = "casa/gatti/mangiatoia/foto/richiesta"
    TOPIC_PHOTO_DATA = "casa/gatti/mangiatoia/foto/data"
    TOPIC_DISPENSE_CMD = "casa/gatti/mangiatoia/erogazione/comando"
    TOPIC_DISPENSE_STATUS = "casa/gatti/mangiatoia/erogazione/stato"
    TOPIC_CONFIG_UPDATE = "casa/gatti/mangiatoia/config/update"
    TOPIC_ESP32_STATUS = "casa/gatti/sistema/status/esp32"
    TOPIC_RPI_STATUS = "casa/gatti/sistema/status/rpi"

    def __init__(self, mqtt_host: str = "localhost", mqtt_port: int = 1883,
                 db_path: str = None, photo_dir: str = None):
        """
        Inizializza il manager.

        Args:
            mqtt_host: Host del broker MQTT
            mqtt_port: Porta del broker MQTT
            db_path: Percorso database (default: cat_feeding.db)
            photo_dir: Directory per salvare le foto
        """
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port

        # Database
        self.db = CatDatabase(db_path)

        # Directory foto
        if photo_dir is None:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            photo_dir = os.path.join(script_dir, "cat_feeder_photos")
        self.photo_dir = photo_dir
        os.makedirs(photo_dir, exist_ok=True)

        # MQTT Client
        self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.mqtt_client.on_connect = self._on_connect
        self.mqtt_client.on_message = self._on_message
        self.mqtt_client.on_disconnect = self._on_disconnect
        self.mqtt_connected = False

        # Stato corrente
        self.current_weight = None
        self.current_cat = None
        self.waiting_for_photo = False
        self.pending_reading_id = None
        self.esp32_ip = None  # Populated from ESP32 status messages

        # Modalità
        self.rules_enabled = False  # False = eroga sempre, True = applica regole
        self.registration_mode = False
        self.registration_cat_name = None

        # Callback per Telegram
        self.telegram_callback: Optional[Callable] = None
        self.telegram_photo_callback: Optional[Callable] = None

        # Thread per heartbeat
        self._heartbeat_thread = None
        self._running = False

        logger.info(f"CatFeedingManager initialized (MQTT: {mqtt_host}:{mqtt_port})")

    def set_telegram_callbacks(self, message_callback: Callable,
                               photo_callback: Callable = None):
        """Imposta i callback per inviare messaggi/foto a Telegram."""
        self.telegram_callback = message_callback
        self.telegram_photo_callback = photo_callback

    def start(self):
        """Avvia il manager e connette a MQTT."""
        try:
            self.mqtt_client.connect(self.mqtt_host, self.mqtt_port, 60)
            self._running = True
            self.mqtt_client.loop_start()
            logger.info("CatFeedingManager started")
        except Exception as e:
            logger.error(f"Failed to connect to MQTT: {e}")
            raise

    def stop(self):
        """Ferma il manager."""
        self._running = False
        self.mqtt_client.loop_stop()
        self.mqtt_client.disconnect()
        logger.info("CatFeedingManager stopped")

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        """Callback connessione MQTT."""
        if reason_code == 0:
            self.mqtt_connected = True
            logger.info("Connected to MQTT broker")

            # Subscribe ai topic necessari
            topics = [
                (self.TOPIC_WEIGHT_STABLE, 1),
                (self.TOPIC_CAT_DETECTED, 1),
                (self.TOPIC_CAT_LEFT, 1),
                (self.TOPIC_PHOTO_DATA, 1),
                (self.TOPIC_DISPENSE_STATUS, 1),
                (self.TOPIC_ESP32_STATUS, 1),
            ]
            client.subscribe(topics)
            logger.info(f"Subscribed to {len(topics)} topics")

            # Invia status iniziale
            self._send_status()
        else:
            logger.error(f"Failed to connect to MQTT: {reason_code}")

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        """Callback disconnessione MQTT."""
        self.mqtt_connected = False
        logger.warning(f"Disconnected from MQTT: {reason_code}")

    def _on_message(self, client, userdata, msg):
        """Callback ricezione messaggi MQTT."""
        try:
            topic = msg.topic
            payload = json.loads(msg.payload.decode())
            logger.debug(f"MQTT message: {topic} -> {payload}")

            if topic == self.TOPIC_WEIGHT_STABLE:
                self._handle_weight(payload)
            elif topic == self.TOPIC_CAT_DETECTED:
                self._handle_cat_detected(payload)
            elif topic == self.TOPIC_CAT_LEFT:
                self._handle_cat_left(payload)
            elif topic == self.TOPIC_PHOTO_DATA:
                self._handle_photo(payload)
            elif topic == self.TOPIC_DISPENSE_STATUS:
                self._handle_dispense_status(payload)
            elif topic == self.TOPIC_ESP32_STATUS:
                self._handle_esp32_status(payload)

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in MQTT message: {e}")
        except Exception as e:
            logger.error(f"Error processing MQTT message: {e}")

    def _handle_weight(self, payload: Dict):
        """Gestisce una pesata stabile (log only, la logica è in _handle_cat_detected)."""
        weight = payload.get('weight', 0)
        logger.info(f"Stable weight received: {weight}kg")
        self.current_weight = weight

    def _handle_cat_detected(self, payload: Dict):
        """Gestisce evento: gatto rilevato sulla bilancia."""
        weight = payload.get('weight', 0)
        logger.info(f"Cat detected on scale: {weight}kg")
        self.current_weight = weight
        self.db.log_event('detection', 'esp32', details={'event': 'cat_on_scale', 'weight': weight})

        # Identifica gatto e cattura foto
        cat = self.db.identify_cat_by_weight(weight)
        self.current_cat = cat

        # Scarica foto dalla ESP32
        photo_path = self._fetch_photo_from_esp32(
            cat_id=cat['id'] if cat else None,
            weight=weight
        )

        # Registra pesata
        reading_id = self.db.add_weight_reading(
            weight=weight,
            cat_id=cat['id'] if cat else None,
            confidence=cat['confidence'] if cat else None,
            food_dispensed=not self.rules_enabled
        )
        self.pending_reading_id = reading_id

        # Notifica Telegram con foto
        if cat:
            msg = f"🐱 {cat['name']} sulla bilancia\n"
            msg += f"• Peso: {weight}kg\n"
            msg += f"• Pasti oggi: {self.db.get_feeding_count_today(cat['id'])}"
        else:
            msg = f"❓ Gatto sconosciuto sulla bilancia\n"
            msg += f"• Peso: {weight}kg"

        if photo_path and self.telegram_photo_callback:
            self.telegram_photo_callback(photo_path, msg)
        elif self.telegram_callback:
            self.telegram_callback(msg)

    def _handle_cat_left(self, payload: Dict):
        """Gestisce evento: gatto lascia la bilancia."""
        logger.info("Cat left the scale")
        self.current_weight = None
        self.current_cat = None
        self.db.log_event('detection', 'esp32', details={'event': 'cat_left_scale'})

    def _handle_photo(self, payload: Dict):
        """Gestisce ricezione foto da ESP32 (URL o base64)."""
        timestamp = payload.get('timestamp', datetime.now().isoformat())
        weight = payload.get('weight', self.current_weight)
        cat_id = payload.get('cat_id', self.current_cat['id'] if self.current_cat else None)

        # Nuovo formato: ESP32 invia URL per fetch HTTP
        photo_url = payload.get('url', '')
        if photo_url:
            logger.info(f"Photo URL received: {photo_url} (photo already fetched in _handle_cat_detected)")
            return

        image_base64 = payload.get('image_base64', '')
        if not image_base64:
            logger.warning("Empty photo received (no url or base64)")
            return

        # Decodifica e salva foto
        try:
            # Rimuovi header data:image/jpeg;base64, se presente
            if ',' in image_base64:
                image_base64 = image_base64.split(',')[1]

            image_data = base64.b64decode(image_base64)

            # Genera nome file
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            if cat_id:
                filename = f"{cat_id}_{ts}.jpg"
                # Crea subdirectory per gatto
                cat_dir = os.path.join(self.photo_dir, cat_id)
                os.makedirs(cat_dir, exist_ok=True)
                photo_path = os.path.join(cat_dir, filename)
            else:
                filename = f"unknown_{ts}_{weight:.2f}kg.jpg"
                unknown_dir = os.path.join(self.photo_dir, "unknown")
                os.makedirs(unknown_dir, exist_ok=True)
                photo_path = os.path.join(unknown_dir, filename)

            # Salva file
            with open(photo_path, 'wb') as f:
                f.write(image_data)

            logger.info(f"Photo saved: {photo_path}")

            # Registra nel database
            photo_id = self.db.add_cat_photo(
                photo_path=photo_path,
                source='feeder',
                cat_id=cat_id,
                weight=weight,
                verified=(cat_id is not None)
            )

            # Se c'è la pesata pendente, aggiorna con path foto
            # TODO: implementare update reading con photo_path

            # Invia foto a Telegram
            if self.telegram_photo_callback:
                if cat_id and self.current_cat:
                    caption = f"📸 Foto di {self.current_cat['name']}\n"
                    caption += f"• Peso: {weight}kg"
                else:
                    caption = f"📸 Foto gatto sconosciuto\n"
                    caption += f"• Peso: {weight}kg\n"
                    caption += f"• Chi è questo gatto?"
                self.telegram_photo_callback(photo_path, caption)

            self.waiting_for_photo = False

        except Exception as e:
            logger.error(f"Error saving photo: {e}")

    def _handle_dispense_status(self, payload: Dict):
        """Gestisce conferma erogazione da ESP32."""
        success = payload.get('success', False)
        amount = payload.get('amount', 0)
        logger.info(f"Dispense status: success={success}, amount={amount}")

        if success:
            self.db.log_event('feeding', 'esp32',
                            cat_id=self.current_cat['id'] if self.current_cat else None,
                            details={'amount': amount})

    def _handle_esp32_status(self, payload: Dict):
        """Gestisce heartbeat/status ESP32."""
        if 'ip' in payload:
            self.esp32_ip = payload['ip']
        logger.debug(f"ESP32 status: {payload}")

    def _should_dispense(self, cat: Dict) -> bool:
        """
        Decide se erogare cibo per un gatto.

        Args:
            cat: Dati del gatto identificato

        Returns:
            True se deve erogare
        """
        # Se le regole non sono attive, eroga sempre
        if not self.rules_enabled:
            return True

        # Se il gatto non è autorizzato, non erogare
        if not cat.get('authorized', True):
            return False

        # TODO: Implementare logiche avanzate:
        # - Limite pasti giornalieri
        # - Intervallo minimo tra pasti
        # - Regole per peso forma

        return True

    def _request_photo(self):
        """Richiede una foto alla ESP32."""
        self.waiting_for_photo = True
        payload = {"request": True, "timestamp": datetime.now().isoformat()}
        self.mqtt_client.publish(self.TOPIC_PHOTO_REQUEST, json.dumps(payload))
        logger.info("Photo requested from ESP32")

    def _fetch_photo_from_esp32(self, cat_id: str = None, weight: float = 0) -> Optional[str]:
        """Scarica foto dalla ESP32 via HTTP e la salva su disco."""
        if not self.esp32_ip:
            logger.warning("ESP32 IP not known yet, cannot fetch photo")
            return None

        url = f"http://{self.esp32_ip}/capture"
        try:
            resp = requests.get(url, timeout=5)
            if resp.status_code != 200:
                logger.error(f"ESP32 photo request failed: {resp.status_code}")
                return None

            # Genera path
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            if cat_id:
                cat_dir = os.path.join(self.photo_dir, cat_id)
                os.makedirs(cat_dir, exist_ok=True)
                photo_path = os.path.join(cat_dir, f"{cat_id}_{ts}.jpg")
            else:
                unknown_dir = os.path.join(self.photo_dir, "unknown")
                os.makedirs(unknown_dir, exist_ok=True)
                photo_path = os.path.join(unknown_dir, f"unknown_{ts}_{weight:.2f}kg.jpg")

            with open(photo_path, 'wb') as f:
                f.write(resp.content)

            logger.info(f"Photo fetched and saved: {photo_path} ({len(resp.content)} bytes)")

            # Registra nel database
            self.db.add_cat_photo(
                photo_path=photo_path,
                source='feeder',
                cat_id=cat_id,
                weight=weight,
                verified=(cat_id is not None)
            )

            return photo_path

        except requests.RequestException as e:
            logger.error(f"Failed to fetch photo from ESP32: {e}")
            return None

    def _send_dispense_command(self, dispense: bool, doses: int = 1):
        """Invia comando di erogazione alla ESP32."""
        payload = {
            "dispense": dispense,
            "doses": doses if dispense else 0,
            "timestamp": datetime.now().isoformat()
        }
        self.mqtt_client.publish(self.TOPIC_DISPENSE_CMD, json.dumps(payload))
        logger.info(f"Dispense command sent: {dispense}")

    def _send_status(self):
        """Invia status RPi via MQTT."""
        payload = {
            "online": True,
            "rules_enabled": self.rules_enabled,
            "cats_count": len(self.db.get_all_cats()),
            "timestamp": datetime.now().isoformat()
        }
        self.mqtt_client.publish(self.TOPIC_RPI_STATUS, json.dumps(payload))

    def send_config_to_esp32(self):
        """Invia configurazione gatti alla ESP32."""
        config = self.db.get_cats_for_esp32()
        self.mqtt_client.publish(self.TOPIC_CONFIG_UPDATE, json.dumps(config))
        logger.info("Config sent to ESP32")

    # ==================== API PER TELEGRAM ====================

    def register_cat(self, name: str, weight: float, tolerance: float = 0.3) -> bool:
        """
        Registra un nuovo gatto.

        Args:
            name: Nome del gatto
            weight: Peso in kg
            tolerance: Tolleranza ±kg
        """
        cat_id = name.lower().replace(' ', '_')
        success = self.db.add_cat(cat_id, name, weight, tolerance)
        if success:
            self.send_config_to_esp32()
        return success

    def identify_last_reading(self, cat_name: str) -> bool:
        """Assegna l'ultima pesata non identificata a un gatto."""
        cat_id = cat_name.lower().replace(' ', '_')

        # Cerca o crea il gatto
        cat = self.db.get_cat(cat_id)
        if not cat:
            # Crea nuovo gatto con il peso dell'ultima lettura
            readings = self.db.get_unidentified_readings(1)
            if readings:
                weight = readings[0]['weight']
                self.db.add_cat(cat_id, cat_name, weight)

        # Assegna la pesata
        readings = self.db.get_unidentified_readings(1)
        if readings:
            return self.db.assign_cat_to_reading(readings[0]['id'], cat_id)
        return False

    def get_feeding_stats(self) -> str:
        """Genera report alimentazione giornaliera."""
        stats = self.db.get_daily_feeding_stats()
        if not stats:
            return "📊 Nessun dato di alimentazione oggi"

        msg = "📊 Classifica pasti oggi:\n"
        for i, stat in enumerate(stats, 1):
            emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "  "
            count = stat['feeding_count'] or 0
            msg += f"{emoji} {stat['name']}: {count} pasti\n"

        return msg

    def get_cats_list(self) -> str:
        """Genera lista gatti registrati."""
        cats = self.db.get_all_cats()
        if not cats:
            return "🐱 Nessun gatto registrato"

        msg = "🐱 Gatti registrati:\n"
        for cat in cats:
            status = "✅" if cat['authorized'] else "❌"
            msg += f"{status} {cat['name']}: {cat['weight_avg']:.1f}kg "
            msg += f"(±{(cat['weight_max']-cat['weight_min'])/2:.1f}kg)\n"

        return msg

    def set_rules_enabled(self, enabled: bool):
        """Attiva/disattiva le regole di alimentazione."""
        self.rules_enabled = enabled
        self._send_status()
        logger.info(f"Rules {'enabled' if enabled else 'disabled'}")


# Test del modulo
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    manager = CatFeedingManager()

    # Test callback Telegram
    def test_telegram(msg):
        print(f"TELEGRAM: {msg}")

    def test_telegram_photo(path, caption):
        print(f"TELEGRAM PHOTO: {path} - {caption}")

    manager.set_telegram_callbacks(test_telegram, test_telegram_photo)

    try:
        manager.start()

        # Attendi un po' per testare
        import time
        print("Manager running... Press Ctrl+C to stop")
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("Stopping...")
    finally:
        manager.stop()
