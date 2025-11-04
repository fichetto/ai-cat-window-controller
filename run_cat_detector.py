#!/usr/bin/env python3
"""
Script di avvio per il sistema di rilevamento gatti e controllo finestra.
"""

import argparse
import logging
import os
import sys
import time
import signal
from cat_detector import CatDetectorApp

# Configurazione logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("cat_detector.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def parse_args():
    """Analizza gli argomenti da linea di comando."""
    parser = argparse.ArgumentParser(description='Sistema di rilevamento gatti e controllo finestra')
    parser.add_argument('--input', '-i', default='/dev/video0',
                      help='Sorgente input (default: /dev/video0)')
    parser.add_argument('--hef-path', default='/home/pi/hailo-rpi5-examples/resources/yolov8m.hef',
                       help='Path to HEF file')
    parser.add_argument('--post-process-so', default='/usr/lib/aarch64-linux-gnu/hailo/tappas/post_processes/libyolo_hailortpp_postprocess.so',
                       help='Path to post-processing SO file')
    parser.add_argument('--daemon', '-d', action='store_true',
                      help='Avvia in modalità daemon')
    parser.add_argument('--restart-on-error', '-r', action='store_true',
                      help='Riavvia automaticamente in caso di errore')
    parser.add_argument('--debug', action='store_true',
                      help='Attiva modalità debug con log più dettagliati')
    return parser.parse_args()

def setup_signal_handlers(detector):
    """Configura i gestori dei segnali."""
    def signal_handler(sig, frame):
        logger.info(f"Received signal {sig}, shutting down...")
        detector.stop()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)   # Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler)  # kill/systemd
    
    logger.info("Signal handlers configured")

def main():
    """Funzione principale."""
    args = parse_args()
    
    # Configura livello di log
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.info("Debug mode activated")
    
    # Se modalità daemon, scollega dal terminale
    if args.daemon:
        logger.info("Starting in daemon mode")
        if os.fork():
            sys.exit(0)
    
    # Verifica che i percorsi esistano
    for path, name in [(args.hef_path, "HEF"), (args.post_process_so, "Post-process SO")]:
        if not os.path.exists(path):
            logger.error(f"{name} file not found: {path}")
            logger.error(f"Looking in current directory and parent directories...")
            
            # Cerca nei percorsi comuni
            base_dir = os.path.dirname(os.path.abspath(__file__))
            parent_dir = os.path.dirname(base_dir)
            grandparent_dir = os.path.dirname(parent_dir)
            
            possible_paths = [
                os.path.join(base_dir, os.path.basename(path)),
                os.path.join(parent_dir, os.path.basename(path)),
                os.path.join(parent_dir, "resources", os.path.basename(path)),
                os.path.join(grandparent_dir, "resources", os.path.basename(path)),
                # Percorsi di sistema per i file SO
                os.path.join("/usr/lib/aarch64-linux-gnu", os.path.basename(path)),
                os.path.join("/usr/lib/aarch64-linux-gnu/hailo/tappas/post_processes", os.path.basename(path))
            ]
            
            found = False
            for possible_path in possible_paths:
                if os.path.exists(possible_path):
                    logger.info(f"Found {name} at: {possible_path}")
                    if name == "HEF":
                        args.hef_path = possible_path
                    else:
                        args.post_process_so = possible_path
                    found = True
                    break
            
            if not found:
                logger.error(f"Could not find {name} file. Please specify the path correctly.")
                sys.exit(1)
    
    logger.info(f"Starting cat detector with input: {args.input}")
    logger.info(f"HEF path: {args.hef_path}")
    logger.info(f"Post-process SO path: {args.post_process_so}")
    
    # Crea il rilevatore di gatti
    detector = None
    max_retry_count = 3
    retry_count = 0
    
    while retry_count < max_retry_count:
        try:
            detector = CatDetectorApp(
                input_source=args.input,
                hef_path=args.hef_path,
                post_process_so=args.post_process_so
            )
            
            # Configura i gestori dei segnali
            setup_signal_handlers(detector)
            
            # Avvia il rilevatore
            detector.start()
            
            # Il mainloop sta già girando
            break
            
        except KeyboardInterrupt:
            logger.info("Application stopped by user")
            break
            
        except Exception as e:
            retry_count += 1
            logger.error(f"Application error: {e}", exc_info=True)
            
            if detector:
                detector.stop()
                
            if args.restart_on_error and retry_count < max_retry_count:
                logger.info(f"Restarting in 10 seconds (attempt {retry_count}/{max_retry_count})...")
                time.sleep(10)
            else:
                logger.error("Max retry count reached or auto-restart disabled. Exiting.")
                sys.exit(1)
    
    logger.info("Application terminated")

if __name__ == "__main__":
    main()
