#!/usr/bin/env python3
"""
Database per la gestione dei gatti, pesate e eventi.
Schema basato su cat_feeding_system_architecture.md
"""

import sqlite3
import json
import os
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

class CatDatabase:
    """Gestisce il database SQLite per il sistema di alimentazione gatti."""

    def __init__(self, db_path: str = None):
        """
        Inizializza il database.

        Args:
            db_path: Percorso del database. Default: cat_feeding.db nella stessa directory
        """
        if db_path is None:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            db_path = os.path.join(script_dir, "cat_feeding.db")

        self.db_path = db_path
        self._init_database()
        logger.info(f"Cat database initialized at {db_path}")

    def _get_connection(self) -> sqlite3.Connection:
        """Ottiene una connessione al database."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_database(self):
        """Inizializza le tabelle del database."""
        conn = self._get_connection()
        cursor = conn.cursor()

        # Tabella Gatti
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS cats (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                weight_min REAL NOT NULL,
                weight_max REAL NOT NULL,
                weight_avg REAL,
                weight_target REAL,
                authorized BOOLEAN DEFAULT TRUE,
                window_allowed BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                notes TEXT
            )
        ''')

        # Tabella Pesate
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS weight_readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                weight REAL NOT NULL,
                cat_id TEXT,
                confidence REAL,
                duration REAL,
                photo_path TEXT,
                authorized BOOLEAN,
                food_dispensed BOOLEAN,
                identified BOOLEAN DEFAULT FALSE,
                FOREIGN KEY (cat_id) REFERENCES cats(id)
            )
        ''')

        # Tabella Eventi Sistema
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS system_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                event_type TEXT NOT NULL,
                source TEXT NOT NULL,
                cat_id TEXT,
                details TEXT,
                FOREIGN KEY (cat_id) REFERENCES cats(id)
            )
        ''')

        # Tabella Foto Gatti (per training)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS cat_photos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                cat_id TEXT,
                photo_path TEXT NOT NULL,
                source TEXT NOT NULL,
                weight REAL,
                verified BOOLEAN DEFAULT FALSE,
                FOREIGN KEY (cat_id) REFERENCES cats(id)
            )
        ''')

        conn.commit()
        conn.close()
        logger.info("Database tables initialized")

    # ==================== GESTIONE GATTI ====================

    def add_cat(self, cat_id: str, name: str, weight: float,
                tolerance: float = 0.3, notes: str = None) -> bool:
        """
        Aggiunge un nuovo gatto al database.

        Args:
            cat_id: ID univoco del gatto (es. 'luna', 'codina')
            name: Nome visualizzato
            weight: Peso attuale in kg
            tolerance: Tolleranza peso ±kg (default 0.3kg = 300g)
            notes: Note opzionali

        Returns:
            True se aggiunto con successo
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO cats (id, name, weight_min, weight_max, weight_avg, notes)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (cat_id.lower(), name, weight - tolerance, weight + tolerance, weight, notes))
            conn.commit()
            logger.info(f"Cat added: {name} ({cat_id}) - weight: {weight}kg ±{tolerance}kg")
            return True
        except sqlite3.IntegrityError:
            logger.warning(f"Cat {cat_id} already exists")
            return False
        finally:
            conn.close()

    def get_cat(self, cat_id: str) -> Optional[Dict[str, Any]]:
        """Ottiene i dati di un gatto."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM cats WHERE id = ?', (cat_id.lower(),))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def get_all_cats(self) -> List[Dict[str, Any]]:
        """Ottiene tutti i gatti registrati."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM cats ORDER BY name')
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def update_cat_weight(self, cat_id: str, new_weight: float,
                          tolerance: float = None) -> bool:
        """Aggiorna il peso di un gatto."""
        conn = self._get_connection()
        cursor = conn.cursor()

        if tolerance is None:
            # Mantieni la tolleranza esistente
            cursor.execute('SELECT weight_min, weight_max, weight_avg FROM cats WHERE id = ?',
                          (cat_id.lower(),))
            row = cursor.fetchone()
            if row:
                old_tolerance = (row['weight_max'] - row['weight_min']) / 2
                tolerance = old_tolerance
            else:
                tolerance = 0.3

        cursor.execute('''
            UPDATE cats
            SET weight_min = ?, weight_max = ?, weight_avg = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (new_weight - tolerance, new_weight + tolerance, new_weight, cat_id.lower()))

        conn.commit()
        success = cursor.rowcount > 0
        conn.close()

        if success:
            logger.info(f"Cat {cat_id} weight updated to {new_weight}kg")
        return success

    def set_cat_target_weight(self, cat_id: str, target_weight: float) -> bool:
        """Imposta il peso forma di un gatto."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE cats SET weight_target = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (target_weight, cat_id.lower()))
        conn.commit()
        success = cursor.rowcount > 0
        conn.close()
        return success

    def set_cat_authorized(self, cat_id: str, authorized: bool) -> bool:
        """Imposta se un gatto è autorizzato a mangiare."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE cats SET authorized = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (authorized, cat_id.lower()))
        conn.commit()
        success = cursor.rowcount > 0
        conn.close()
        return success

    def set_cat_window_allowed(self, cat_id: str, allowed: bool) -> bool:
        """Imposta se un gatto può entrare dalla finestra."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE cats SET window_allowed = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (allowed, cat_id.lower()))
        conn.commit()
        success = cursor.rowcount > 0
        conn.close()
        return success

    def identify_cat_by_weight(self, weight: float) -> Optional[Dict[str, Any]]:
        """
        Identifica un gatto dal peso.

        Args:
            weight: Peso rilevato in kg

        Returns:
            Dict con dati gatto e confidence, o None se non identificato
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT *,
                   ABS(weight_avg - ?) as weight_diff
            FROM cats
            WHERE ? BETWEEN weight_min AND weight_max
            ORDER BY weight_diff ASC
            LIMIT 1
        ''', (weight, weight))
        row = cursor.fetchone()
        conn.close()

        if row:
            cat = dict(row)
            # Calcola confidence basata sulla distanza dal peso medio
            weight_range = cat['weight_max'] - cat['weight_min']
            weight_diff = abs(cat['weight_avg'] - weight)
            confidence = max(0, 1 - (weight_diff / (weight_range / 2)))
            cat['confidence'] = round(confidence, 2)
            logger.info(f"Cat identified: {cat['name']} (confidence: {confidence:.2f})")
            return cat

        logger.info(f"No cat identified for weight {weight}kg")
        return None

    # ==================== GESTIONE PESATE ====================

    def add_weight_reading(self, weight: float, cat_id: str = None,
                          confidence: float = None, photo_path: str = None,
                          food_dispensed: bool = None) -> int:
        """
        Registra una nuova pesata.

        Returns:
            ID della pesata inserita
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        identified = cat_id is not None
        authorized = None
        if cat_id:
            cat = self.get_cat(cat_id)
            authorized = cat['authorized'] if cat else None

        cursor.execute('''
            INSERT INTO weight_readings
            (weight, cat_id, confidence, photo_path, identified, authorized, food_dispensed)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (weight, cat_id, confidence, photo_path, identified, authorized, food_dispensed))

        reading_id = cursor.lastrowid
        conn.commit()
        conn.close()

        logger.info(f"Weight reading added: {weight}kg, cat={cat_id}, id={reading_id}")
        return reading_id

    def get_unidentified_readings(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Ottiene le pesate non ancora identificate."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM weight_readings
            WHERE identified = FALSE
            ORDER BY timestamp DESC
            LIMIT ?
        ''', (limit,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def assign_cat_to_reading(self, reading_id: int, cat_id: str) -> bool:
        """Assegna un gatto a una pesata esistente."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cat = self.get_cat(cat_id)
        if not cat:
            conn.close()
            return False

        cursor.execute('''
            UPDATE weight_readings
            SET cat_id = ?, identified = TRUE, authorized = ?
            WHERE id = ?
        ''', (cat_id.lower(), cat['authorized'], reading_id))

        conn.commit()
        success = cursor.rowcount > 0
        conn.close()
        return success

    def get_feeding_count_today(self, cat_id: str) -> int:
        """Conta quante volte un gatto ha mangiato oggi."""
        conn = self._get_connection()
        cursor = conn.cursor()
        today = datetime.now().strftime('%Y-%m-%d')
        cursor.execute('''
            SELECT COUNT(*) as count FROM weight_readings
            WHERE cat_id = ?
            AND food_dispensed = TRUE
            AND date(timestamp) = ?
        ''', (cat_id.lower(), today))
        row = cursor.fetchone()
        conn.close()
        return row['count'] if row else 0

    def get_daily_feeding_stats(self) -> List[Dict[str, Any]]:
        """Ottiene statistiche alimentazione giornaliera per tutti i gatti."""
        conn = self._get_connection()
        cursor = conn.cursor()
        today = datetime.now().strftime('%Y-%m-%d')
        cursor.execute('''
            SELECT c.id, c.name,
                   COUNT(w.id) as feeding_count,
                   MAX(w.timestamp) as last_fed
            FROM cats c
            LEFT JOIN weight_readings w ON c.id = w.cat_id
                AND w.food_dispensed = TRUE
                AND date(w.timestamp) = ?
            GROUP BY c.id, c.name
            ORDER BY feeding_count DESC
        ''', (today,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    # ==================== GESTIONE FOTO ====================

    def add_cat_photo(self, photo_path: str, source: str,
                      cat_id: str = None, weight: float = None,
                      verified: bool = False) -> int:
        """
        Aggiunge una foto di gatto per il training.

        Args:
            photo_path: Percorso del file foto
            source: Sorgente ('feeder', 'window', 'manual')
            cat_id: ID gatto se identificato
            weight: Peso associato
            verified: Se l'identità è stata verificata manualmente
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO cat_photos (photo_path, source, cat_id, weight, verified)
            VALUES (?, ?, ?, ?, ?)
        ''', (photo_path, source, cat_id, weight, verified))
        photo_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return photo_id

    def get_unverified_photos(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Ottiene foto non ancora verificate (per assegnazione via Telegram)."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM cat_photos
            WHERE verified = FALSE OR cat_id IS NULL
            ORDER BY timestamp DESC
            LIMIT ?
        ''', (limit,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def verify_photo(self, photo_id: int, cat_id: str) -> bool:
        """Verifica e assegna una foto a un gatto."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE cat_photos
            SET cat_id = ?, verified = TRUE
            WHERE id = ?
        ''', (cat_id.lower(), photo_id))
        conn.commit()
        success = cursor.rowcount > 0
        conn.close()
        return success

    def get_photos_for_cat(self, cat_id: str, verified_only: bool = True) -> List[Dict[str, Any]]:
        """Ottiene tutte le foto di un gatto (per training)."""
        conn = self._get_connection()
        cursor = conn.cursor()

        if verified_only:
            cursor.execute('''
                SELECT * FROM cat_photos
                WHERE cat_id = ? AND verified = TRUE
                ORDER BY timestamp DESC
            ''', (cat_id.lower(),))
        else:
            cursor.execute('''
                SELECT * FROM cat_photos
                WHERE cat_id = ?
                ORDER BY timestamp DESC
            ''', (cat_id.lower(),))

        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    # ==================== GESTIONE EVENTI ====================

    def log_event(self, event_type: str, source: str,
                  cat_id: str = None, details: Dict = None) -> int:
        """
        Registra un evento di sistema.

        Args:
            event_type: 'feeding', 'window', 'detection', 'error', 'config'
            source: 'esp32', 'rpi', 'telegram'
            cat_id: ID gatto coinvolto
            details: Dettagli evento (dict → JSON)
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        details_json = json.dumps(details) if details else None
        cursor.execute('''
            INSERT INTO system_events (event_type, source, cat_id, details)
            VALUES (?, ?, ?, ?)
        ''', (event_type, source, cat_id, details_json))
        event_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return event_id

    def get_recent_events(self, limit: int = 50,
                          event_type: str = None) -> List[Dict[str, Any]]:
        """Ottiene gli eventi recenti."""
        conn = self._get_connection()
        cursor = conn.cursor()

        if event_type:
            cursor.execute('''
                SELECT * FROM system_events
                WHERE event_type = ?
                ORDER BY timestamp DESC
                LIMIT ?
            ''', (event_type, limit))
        else:
            cursor.execute('''
                SELECT * FROM system_events
                ORDER BY timestamp DESC
                LIMIT ?
            ''', (limit,))

        rows = cursor.fetchall()
        conn.close()

        events = []
        for row in rows:
            event = dict(row)
            if event['details']:
                try:
                    event['details'] = json.loads(event['details'])
                except json.JSONDecodeError:
                    pass
            events.append(event)

        return events

    # ==================== EXPORT PER ESP32 ====================

    def get_cats_for_esp32(self) -> Dict[str, Any]:
        """
        Genera il JSON da inviare alla ESP32 come cache locale.
        Formato definito in cat_feeding_system_architecture.md
        """
        cats = self.get_all_cats()

        esp32_cats = []
        for cat in cats:
            esp32_cats.append({
                "id": cat['id'],
                "name": cat['name'],
                "weight_min": cat['weight_min'],
                "weight_max": cat['weight_max'],
                "authorized": bool(cat['authorized']),
                "last_fed": None  # TODO: recuperare ultimo feeding
            })

        return {
            "version": int(datetime.now().timestamp()),
            "updated": datetime.now().isoformat(),
            "cats": esp32_cats
        }


# Test del modulo
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Test database
    db = CatDatabase("/tmp/test_cats.db")

    # Aggiungi gatti di test
    db.add_cat("luna", "Luna", 4.2, tolerance=0.3)
    db.add_cat("codina", "Codina", 3.8, tolerance=0.25)
    db.add_cat("micio", "Micio", 5.1, tolerance=0.35)

    # Test identificazione
    cat = db.identify_cat_by_weight(4.15)
    print(f"Identified: {cat}")

    # Test pesata
    reading_id = db.add_weight_reading(4.15, cat_id="luna", confidence=0.95, food_dispensed=True)
    print(f"Reading ID: {reading_id}")

    # Test statistiche
    stats = db.get_daily_feeding_stats()
    print(f"Daily stats: {stats}")

    # Test export ESP32
    esp32_data = db.get_cats_for_esp32()
    print(f"ESP32 data: {json.dumps(esp32_data, indent=2)}")

    # Cleanup
    os.remove("/tmp/test_cats.db")
    print("Test completato!")
