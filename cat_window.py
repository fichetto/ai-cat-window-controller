#!/usr/bin/env python3
import sys
from pymodbus.client import ModbusSerialClient
import time

def set_window_angle(client, angle):
    """
    Imposta l'angolo della finestra e attende il completamento del movimento
    
    Args:
        client: client Modbus
        angle: angolo desiderato (45-135 gradi)
    """
    # Converti l'angolo direttamente in formato registro (x10)
    angle_reg = int(round(angle * 10))
    
    # Scrivi setpoint
    try:
        print(f"Invio setpoint finestra {angle}°...")
        result = client.write_register(
            address=0,
            value=angle_reg,
            slave=1
        )
        if result is None:
            raise Exception("Nessuna risposta dal dispositivo")
    except Exception as e:
        print(f"Errore scrittura: {e}")
        return False

    print("Setpoint finestra inviato correttamente")
    
    # Attendi completamento movimento
    print("Movimento finestra in corso...")
    timeout = 30  # secondi
    start_time = time.time()
    last_value = None
    
    while True:
        if (time.time() - start_time) > timeout:
            print("Timeout movimento finestra")
            return False
            
        try:
            result = client.read_holding_registers(
                address=1,
                count=1,
                slave=1
            )
            if result is None:
                print("Nessuna risposta durante la lettura")
                time.sleep(0.5)
                continue
                
            # Leggi l'angolo attuale (già in gradi x10)
            current_angle = float(result.registers[0]) / 10.0
            
            if current_angle != last_value:
                print(f"Posizione attuale finestra: {current_angle:.1f}°")
                last_value = current_angle
            
            # Verifica se abbiamo raggiunto la posizione con tolleranza di 0.1 gradi
            if abs(current_angle - angle) <= 0.1:
                print(f"Posizione finestra raggiunta: {angle}°")
                return True
                
        except Exception as e:
            print(f"Errore lettura: {e}")
            time.sleep(0.5)
            continue
            
        time.sleep(0.1)

def set_lock_angle(client, angle):
    """
    Imposta l'angolo della serratura
    
    Args:
        client: client Modbus
        angle: angolo desiderato (0-90 gradi)
    
    Returns:
        bool: True se l'operazione è riuscita, False altrimenti
    """
    # Converti l'angolo direttamente in formato registro (x10)
    angle_reg = int(round(angle * 10))
    
    # Scrivi setpoint
    try:
        print(f"Invio setpoint serratura {angle}°...")
        result = client.write_register(
            address=2,  # Registro per il servo serratura
            value=angle_reg,
            slave=1
        )
        if result is None:
            raise Exception("Nessuna risposta dal dispositivo")
    except Exception as e:
        print(f"Errore scrittura serratura: {e}")
        return False

    print("Setpoint serratura inviato correttamente")
    
    # Attendi breve conferma
    print("Impostazione serratura in corso...")
    time.sleep(1)  # Breve attesa
    
    try:
        result = client.read_holding_registers(
            address=3,  # Registro stato serratura
            count=1,
            slave=1
        )
        if result is None:
            print("Nessuna risposta durante la lettura serratura")
            return False
            
        # Leggi l'angolo attuale (già in gradi x10)
        current_angle = float(result.registers[0]) / 10.0
        print(f"Posizione attuale serratura: {current_angle:.1f}°")
        
        # Verifica con tolleranza maggiore per la serratura
        if abs(current_angle - angle) <= 5.0:
            print(f"Posizione serratura impostata: {angle}°")
            return True
        else:
            print(f"Errore: la serratura non ha raggiunto la posizione richiesta")
            return False
                
    except Exception as e:
        print(f"Errore lettura serratura: {e}")
        return False

def lock_window(client):
    """
    Blocca la finestra (serratura a 0°)
    
    Args:
        client: client Modbus
    
    Returns:
        bool: True se l'operazione è riuscita
    """
    return set_lock_angle(client, 0)

def unlock_window(client):
    """
    Sblocca la finestra (serratura a 90°)
    
    Args:
        client: client Modbus
    
    Returns:
        bool: True se l'operazione è riuscita
    """
    return set_lock_angle(client, 90)

def open_window(client):
    """
    Sblocca e apre completamente la finestra
    
    Args:
        client: client Modbus
    
    Returns:
        bool: True se l'operazione è riuscita
    """
    # Prima sblocca
    if not unlock_window(client):
        print("Errore durante lo sblocco della finestra")
        return False
    
    # Poi apri
    if not set_window_angle(client, 120):
        print("Errore durante l'apertura della finestra")
        return False
    
    return True

def close_window(client):
    """
    Chiude e blocca la finestra
    
    Args:
        client: client Modbus
    
    Returns:
        bool: True se l'operazione è riuscita
    """
    # Prima chiudi
    if not set_window_angle(client, 77):
        print("Errore durante la chiusura della finestra")
        return False
    
    # Breve attesa per assicurarsi che la finestra sia completamente chiusa
    time.sleep(1)
    
    # Poi blocca
    if not lock_window(client):
        print("Errore durante il blocco della finestra")
        return False
    
    return True

def reset_usb_device():
    """
    Resetta la porta USB per forzare la riconnessione dell'Arduino
    """
    import os
    import subprocess

    try:
        print("Resettando porta USB...")
        # Trova il dispositivo USB ttyUSB0
        result = subprocess.run(
            ["readlink", "-f", "/sys/class/tty/ttyUSB0/device"],
            capture_output=True,
            text=True
        )

        if result.returncode == 0:
            device_path = result.stdout.strip()
            # Risale al device USB
            usb_device = device_path.split('/usb')[0] + '/usb' + device_path.split('/usb')[1].split('/')[0]

            # Unbind
            subprocess.run(
                ["sudo", "sh", "-c", f"echo '{usb_device.split('/')[-1]}' > /sys/bus/usb/drivers/usb/unbind"],
                stderr=subprocess.DEVNULL
            )
            time.sleep(1)

            # Bind
            subprocess.run(
                ["sudo", "sh", "-c", f"echo '{usb_device.split('/')[-1]}' > /sys/bus/usb/drivers/usb/bind"],
                stderr=subprocess.DEVNULL
            )
            time.sleep(2)
            print("Reset USB completato")
            return True
    except Exception as e:
        print(f"Errore durante il reset USB: {e}")

    return False

def connect_with_retry(max_retries=5, retry_delay=2):
    """
    Tenta di connettersi alla porta seriale con retry automatici

    Args:
        max_retries: Numero massimo di tentativi
        retry_delay: Secondi di attesa tra i tentativi

    Returns:
        ModbusSerialClient connesso o None se fallisce
    """
    import os

    for attempt in range(max_retries):
        try:
            # Prima prova a resettare la porta se non è il primo tentativo
            if attempt > 0:
                print(f"Tentativo {attempt + 1}/{max_retries}...")

                # Prova a chiudere eventuali connessioni esistenti
                try:
                    os.system("fuser -k /dev/ttyCAT 2>/dev/null")
                    time.sleep(0.5)
                except:
                    pass

                # Ogni 2 tentativi, prova a resettare l'USB
                if attempt % 2 == 1:
                    reset_usb_device()

            # Crea client Modbus
            client = ModbusSerialClient(
                port='/dev/ttyCAT',
                baudrate=115200,
                bytesize=8,
                parity='N',
                stopbits=1,
                timeout=2,
                retries=3
            )

            if client.connect():
                print("Connessione Modbus stabilita")
                return client
            else:
                print(f"Connessione fallita al tentativo {attempt + 1}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)

        except Exception as e:
            print(f"Errore durante la connessione (tentativo {attempt + 1}): {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)

    print("Impossibile connettersi dopo tutti i tentativi")
    return None

def main():
    if len(sys.argv) < 2:
        print("Uso: python3 cat_window.py <comando>")
        print("Comandi disponibili:")
        print("  apri - Sblocca e apre completamente la finestra")
        print("  chiudi - Chiude e blocca la finestra")
        print("  finestra <angolo> - Imposta solo l'angolo della finestra (77-135 gradi)")
        print("  serratura <angolo> - Imposta solo l'angolo della serratura (0-90 gradi)")
        print("  sblocca - Sblocca la finestra (serratura a 90°)")
        print("  blocca - Blocca la finestra (serratura a 0°)")
        sys.exit(1)

    comando = sys.argv[1].lower()

    # Connessione con retry automatici
    client = connect_with_retry(max_retries=5, retry_delay=2)

    if client is None:
        print("Errore: impossibile stabilire connessione Modbus")
        sys.exit(1)

    try:
        
        # Gestisci i vari comandi
        if comando == "finestra" and len(sys.argv) == 3:
            try:
                angle = float(sys.argv[2])
                if not (77 <= angle <= 135):
                    raise ValueError("Angolo finestra fuori range (77-135)")
                
                if not set_window_angle(client, angle):
                    print("Operazione fallita")
                    sys.exit(1)
            except ValueError as e:
                print(f"Errore: {e}")
                sys.exit(1)
                
        elif comando == "serratura" and len(sys.argv) == 3:
            try:
                angle = float(sys.argv[2])
                if not (0 <= angle <= 90):
                    raise ValueError("Angolo serratura fuori range (0-90)")
                
                if not set_lock_angle(client, angle):
                    print("Operazione fallita")
                    sys.exit(1)
            except ValueError as e:
                print(f"Errore: {e}")
                sys.exit(1)
                
        elif comando == "apri":
            if not open_window(client):
                print("Operazione apertura fallita")
                sys.exit(1)
                
        elif comando == "chiudi":
            if not close_window(client):
                print("Operazione chiusura fallita")
                sys.exit(1)
                
        elif comando == "sblocca":
            if not unlock_window(client):
                print("Operazione sblocco fallita")
                sys.exit(1)
                
        elif comando == "blocca":
            if not lock_window(client):
                print("Operazione blocco fallita")
                sys.exit(1)
                
        else:
            print(f"Comando non riconosciuto: {comando}")
            sys.exit(1)
            
    except Exception as e:
        print(f"Errore: {e}")
        sys.exit(1)
    finally:
        client.close()

if __name__ == "__main__":
    main()
