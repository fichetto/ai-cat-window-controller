#!/usr/bin/env python3
"""
Modulo generico per il processamento delle detection AI.
Fornisce un'interfaccia pulita per estrarre rilevamenti da qualsiasi sorgente frame.
"""

import hailo
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class Detection:
    """Singolo rilevamento con tutte le informazioni geometriche."""
    label: str
    confidence: float
    # Bounding box normalizzato (0-1)
    xmin: float
    ymin: float
    xmax: float
    ymax: float
    # Posizione relativa calcolata
    center_x: float  # 0.0 = sinistra, 1.0 = destra
    center_y: float  # 0.0 = alto, 1.0 = basso
    width: float     # larghezza bbox normalizzata
    height: float    # altezza bbox normalizzata

    @property
    def is_left(self) -> bool:
        """True se l'oggetto è nella metà sinistra dell'immagine."""
        return self.center_x < 0.5

    @property
    def is_right(self) -> bool:
        """True se l'oggetto è nella metà destra dell'immagine."""
        return self.center_x >= 0.5

    @property
    def position_str(self) -> str:
        """Stringa descrittiva della posizione."""
        h_pos = "sinistra" if self.is_left else "destra"
        v_pos = "alto" if self.center_y < 0.5 else "basso"
        return f"{h_pos}-{v_pos}"


@dataclass
class DetectionResult:
    """Risultato completo dell'elaborazione di un frame."""
    # Conteggi
    total_count: int
    filtered_count: int  # Dopo applicazione filtri (classi, confidence)

    # Lista detections filtrate
    detections: List[Detection] = field(default_factory=list)

    # Metadata sorgente
    source: str = 'unknown'  # 'usb', 'rtsp', o nome camera
    timestamp: datetime = field(default_factory=datetime.now)

    # Aggregazioni utili
    def count_by_label(self) -> Dict[str, int]:
        """Conta rilevamenti per classe."""
        counts = {}
        for det in self.detections:
            counts[det.label] = counts.get(det.label, 0) + 1
        return counts

    def get_by_label(self, label: str) -> List[Detection]:
        """Filtra rilevamenti per classe."""
        return [d for d in self.detections if d.label == label]

    def get_left(self) -> List[Detection]:
        """Rilevamenti nella metà sinistra."""
        return [d for d in self.detections if d.is_left]

    def get_right(self) -> List[Detection]:
        """Rilevamenti nella metà destra."""
        return [d for d in self.detections if d.is_right]

    def best_by_confidence(self, label: Optional[str] = None) -> Optional[Detection]:
        """Rilevamento con confidence maggiore, opzionalmente filtrato per label."""
        candidates = self.get_by_label(label) if label else self.detections
        if not candidates:
            return None
        return max(candidates, key=lambda d: d.confidence)

    @property
    def has_detections(self) -> bool:
        return len(self.detections) > 0


class DetectionProcessor:
    """
    Processore generico per estrarre detection da buffer Hailo.

    Uso:
        processor = DetectionProcessor()
        result = processor.process(buffer,
                                   detect_classes=['cat', 'person'],
                                   min_confidence=0.7,
                                   source='usb')

        # Accesso risultati
        print(f"Trovati {result.filtered_count} oggetti")
        for det in result.detections:
            print(f"  {det.label}: {det.confidence:.2f} @ {det.position_str}")
    """

    def __init__(self):
        """Inizializza il processore."""
        self.frame_count = 0

    def process(self,
                buffer,
                detect_classes: Optional[List[str]] = None,
                min_confidence: float = 0.5,
                source: str = 'unknown') -> DetectionResult:
        """
        Processa un buffer GStreamer ed estrae i rilevamenti.

        Args:
            buffer: GstBuffer con ROI Hailo
            detect_classes: Lista classi da rilevare (None = tutte)
            min_confidence: Soglia minima di confidenza
            source: Identificativo sorgente ('usb', nome camera, etc.)

        Returns:
            DetectionResult con tutti i rilevamenti filtrati
        """
        self.frame_count += 1

        # Estrai ROI dal buffer
        try:
            roi = hailo.get_roi_from_buffer(buffer)
            all_detections = roi.get_objects_typed(hailo.HAILO_DETECTION)
        except Exception as e:
            logger.error(f"Error extracting detections from buffer: {e}")
            return DetectionResult(
                total_count=0,
                filtered_count=0,
                source=source
            )

        total_count = len(all_detections)
        filtered_detections = []

        for det in all_detections:
            label = det.get_label()
            confidence = det.get_confidence()

            # Filtra per classe
            if detect_classes and label not in detect_classes:
                continue

            # Filtra per confidence
            if confidence < min_confidence:
                continue

            # Estrai bounding box
            bbox = det.get_bbox()
            xmin = float(bbox.xmin())
            ymin = float(bbox.ymin())
            xmax = float(bbox.xmax())
            ymax = float(bbox.ymax())

            # Calcola posizione relativa
            center_x = (xmin + xmax) / 2
            center_y = (ymin + ymax) / 2
            width = xmax - xmin
            height = ymax - ymin

            detection = Detection(
                label=label,
                confidence=confidence,
                xmin=xmin,
                ymin=ymin,
                xmax=xmax,
                ymax=ymax,
                center_x=center_x,
                center_y=center_y,
                width=width,
                height=height
            )

            filtered_detections.append(detection)

        return DetectionResult(
            total_count=total_count,
            filtered_count=len(filtered_detections),
            detections=filtered_detections,
            source=source,
            timestamp=datetime.now()
        )

    def process_for_cats(self,
                         buffer,
                         min_confidence: float = 0.7,
                         source: str = 'usb') -> DetectionResult:
        """
        Shortcut per processare solo gatti.

        Args:
            buffer: GstBuffer
            min_confidence: Soglia minima
            source: Sorgente

        Returns:
            DetectionResult con solo gatti
        """
        return self.process(buffer,
                           detect_classes=['cat'],
                           min_confidence=min_confidence,
                           source=source)

    def process_for_security(self,
                             buffer,
                             min_confidence: float = 0.6,
                             source: str = 'rtsp') -> DetectionResult:
        """
        Shortcut per monitoraggio sicurezza (persone, auto).

        Args:
            buffer: GstBuffer
            min_confidence: Soglia minima
            source: Sorgente

        Returns:
            DetectionResult con persone e veicoli
        """
        return self.process(buffer,
                           detect_classes=['person', 'car', 'truck', 'motorcycle'],
                           min_confidence=min_confidence,
                           source=source)
