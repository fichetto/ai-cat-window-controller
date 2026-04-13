#!/usr/bin/env python3
import sys
import json
from pymodbus.client import ModbusSerialClient
import time

def set_window_angle(client, angle):
    """
    Imposta l'angolo della finestra e attende il completamento del movimento

    Args:
        client: client Modbus
        angle: angolo desiderato (45-135 gradi)
    """
    angle_reg = int(round(angle * 10))

    try:
        print(f"Invio setpoint finestra {angle}°...")
        result = client.write_register(address=0, value=angle_reg, slave=1)
        if result is None:
            raise Exception("Nessuna risposta dal dispositivo")
    except Exception as e:
        print(f"Errore scrittura: {e}")
        return False

    print("Setpoint finestra inviato correttamente")

    print("Movimento finestra in corso...")
    timeout = 30
    start_time = time.time()
    last_value = None

    while True:
        if (time.time() - start_time) > timeout:
            print("Timeout movimento finestra")
            return False

        try:
            result = client.read_holding_registers(address=1, count=1, slave=1)
            if result is None:
                print("Nessuna risposta durante la lettura")
                time.sleep(0.5)
                continue

            current_angle = float(result.registers[0]) / 10.0

            if current_angle != last_value:
                print(f"Posizione attuale finestra: {current_angle:.1f}°")
                last_value = current_angle

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
    """
    angle_reg = int(round(angle * 10))

    try:
        print(f"Invio setpoint serratura {angle}°...")
        result = client.write_register(address=2, value=angle_reg, slave=1)
        if result is None:
            raise Exception("Nessuna risposta dal dispositivo")
    except Exception as e:
        print(f"Errore scrittura serratura: {e}")
        return False

    print("Setpoint serratura inviato correttamente")

    print("Impostazione serratura in corso...")
    time.sleep(1)

    try:
        result = client.read_holding_registers(address=3, count=1, slave=1)
        if result is None:
            print("Nessuna risposta durante la lettura serratura")
            return False

        current_angle = float(result.registers[0]) / 10.0
        print(f"Posizione attuale serratura: {current_angle:.1f}°")

        if abs(current_angle - angle) <= 5.0:
            print(f"Posizione serratura impostata: {angle}°")
            return True
        else:
            print(f"Errore: la serratura non ha raggiunto la posizione richiesta")
            return False

    except Exception as e:
        print(f"Errore lettura serratura: {e}")
        return False

def read_angles(client):
    """
    Legge gli angoli attuali di finestra e serratura dai registri Modbus.

    Returns:
        dict: {"window": float, "lock": float} oppure None in caso di errore
    """
    try:
        result_w = client.read_holding_registers(address=1, count=1, slave=1)
        result_l = client.read_holding_registers(address=3, count=1, slave=1)
        if result_w is None or result_l is None:
            print("Nessuna risposta durante la lettura angoli")
            return None
        window_angle = float(result_w.registers[0]) / 10.0
        lock_angle = float(result_l.registers[0]) / 10.0
        return {"window": window_angle, "lock": lock_angle}
    except Exception as e:
        print(f"Errore lettura angoli: {e}")
        return None


def ramp_window_to_angle(client, target, step=2.0, delay=0.3):
    """
    Muove la finestra verso il target con rampa graduale lato Python.
    Invia step intermedi e verifica la posizione dopo ciascuno.

    Args:
        client: client Modbus
        target: angolo target
        step: gradi per ogni step intermedio (default 2.0)
        delay: pausa in secondi tra ogni step (default 0.3)

    Returns:
        (bool, float): (successo, angolo finale letto)
    """
    angles = read_angles(client)
    if angles is None:
        print("Impossibile leggere posizione attuale per la rampa")
        return False, -1

    current = angles["window"]
    print(f"Rampa finestra: {current:.1f}° → {target:.1f}° (step {step}°)")

    if abs(current - target) <= step:
        # Già abbastanza vicino, manda direttamente il target
        angle_reg = int(round(target * 10))
        try:
            client.write_register(address=0, value=angle_reg, slave=1)
        except Exception as e:
            print(f"Errore scrittura setpoint: {e}")
            return False, current
        time.sleep(delay + 0.2)
        angles = read_angles(client)
        final = angles["window"] if angles else target
        print(f"Rampa completata: {final:.1f}°")
        return True, final

    # Calcola direzione
    direction = 1.0 if target > current else -1.0
    pos = current

    while abs(pos - target) > step:
        pos += direction * step
        angle_reg = int(round(pos * 10))
        try:
            client.write_register(address=0, value=angle_reg, slave=1)
        except Exception as e:
            print(f"Errore scrittura step {pos:.1f}°: {e}")
            return False, pos - direction * step

        time.sleep(delay)

        # Verifica posizione
        angles = read_angles(client)
        if angles is None:
            print(f"Errore lettura durante rampa a {pos:.1f}°")
            return False, pos

        actual = angles["window"]
        diff = abs(actual - pos)
        print(f"  Step: target={pos:.1f}° actual={actual:.1f}° (diff={diff:.1f}°)")

        # Se la differenza è troppo grande, il servo potrebbe essere bloccato
        if diff > step * 3:
            print(f"ATTENZIONE: servo non segue il setpoint (diff={diff:.1f}°), fermata!")
            return False, actual

    # Step finale al target esatto
    angle_reg = int(round(target * 10))
    try:
        client.write_register(address=0, value=angle_reg, slave=1)
    except Exception as e:
        print(f"Errore scrittura target finale: {e}")
        return False, pos

    time.sleep(delay + 0.2)
    angles = read_angles(client)
    final = angles["window"] if angles else target
    print(f"Rampa completata: {final:.1f}°")
    return True, final


def lock_window(client):
    """Blocca la finestra (serratura a 0°)"""
    return set_lock_angle(client, 0)

def unlock_window(client):
    """Sblocca la finestra (serratura a 90°)"""
    return set_lock_angle(client, 90)

def open_window(client):
    """Sblocca e apre completamente la finestra (con rampa)"""
    if not unlock_window(client):
        print("Errore durante lo sblocco della finestra")
        return False

    success, final_angle = ramp_window_to_angle(client, 120)
    if not success:
        print(f"Errore durante l'apertura della finestra (fermata a {final_angle:.1f}°)")
        return False

    return True

def close_window(client):
    """Chiude e blocca la finestra (con rampa)"""
    success, final_angle = ramp_window_to_angle(client, 77)
    if not success:
        print(f"Errore durante la chiusura della finestra (fermata a {final_angle:.1f}°)")
        return False

    time.sleep(1)

    if not lock_window(client):
        print("Errore durante il blocco della finestra")
        return False

    return True

def reset_pca9685(client):
    """
    Reset soft del PCA9685 via registro Modbus (registro 4).
    Reinizializza il driver PWM senza resettare l'Arduino.
    Utile quando il servo va in protezione.
    """
    try:
        print("Reset PCA9685 via Modbus...")
        result = client.write_register(address=4, value=1, slave=1)
        if result is None:
            raise Exception("Nessuna risposta dal dispositivo")
        time.sleep(1)
        print("Reset PCA9685 completato")
        return True
    except Exception as e:
        print(f"Errore reset PCA9685: {e}")
        return False

def reset_arduino_dtr():
    """
    Reset dell'Arduino tramite toggle della linea DTR.
    Equivale a premere il pulsante reset sull'Arduino.
    """
    import serial
    try:
        print("Reset Arduino via DTR...")
        ser = serial.Serial('/dev/ttyCAT', 115200)
        ser.setDTR(False)
        time.sleep(0.1)
        ser.setDTR(True)
        ser.close()
        time.sleep(3)
        print("Reset Arduino completato")
        return True
    except Exception as e:
        print(f"Errore reset DTR: {e}")
        return False

def reset_usb_device():
    """Resetta la porta USB per forzare la riconnessione dell'Arduino"""
    import os
    import subprocess

    try:
        print("Resettando porta USB...")
        result = subprocess.run(
            ["readlink", "-f", "/sys/class/tty/ttyUSB0/device"],
            capture_output=True, text=True
        )

        if result.returncode == 0:
            device_path = result.stdout.strip()
            usb_device = device_path.split('/usb')[0] + '/usb' + device_path.split('/usb')[1].split('/')[0]

            subprocess.run(
                ["sudo", "sh", "-c", f"echo '{usb_device.split('/')[-1]}' > /sys/bus/usb/drivers/usb/unbind"],
                stderr=subprocess.DEVNULL
            )
            time.sleep(1)

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
    """Tenta di connettersi alla porta seriale con retry automatici"""
    import os

    for attempt in range(max_retries):
        try:
            if attempt > 0:
                print(f"Tentativo {attempt + 1}/{max_retries}...")
                try:
                    os.system("fuser -k /dev/ttyCAT 2>/dev/null")
                    time.sleep(0.5)
                except:
                    pass
                if attempt % 2 == 1:
                    reset_usb_device()

            client = ModbusSerialClient(
                port='/dev/ttyCAT',
                baudrate=115200, bytesize=8, parity='N', stopbits=1,
                timeout=2, retries=3
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
        print("  apri       - Sblocca e apre la finestra (con rampa)")
        print("  chiudi     - Chiude e blocca la finestra (con rampa)")
        print("  finestra <angolo>   - Angolo finestra (77-135)")
        print("  serratura <angolo>  - Angolo serratura (0-90)")
        print("  sblocca    - Sblocca la serratura (90°)")
        print("  blocca     - Blocca la serratura (0°)")
        print("  leggi      - Legge angoli attuali (JSON)")
        print("  reset      - Reset soft PCA9685 via Modbus")
        print("  hardreset  - Reset Arduino via DTR")
        print("  usbreset   - Reset porta USB (più aggressivo)")
        sys.exit(1)

    comando = sys.argv[1].lower()

    # Comandi che non richiedono connessione Modbus
    if comando == "hardreset":
        if not reset_arduino_dtr():
            print("Reset Arduino fallito")
            sys.exit(1)
        print("Arduino resettato. Attendere qualche secondo.")
        sys.exit(0)

    if comando == "usbreset":
        if not reset_usb_device():
            print("Reset USB fallito")
            sys.exit(1)
        print("USB resettata. Attendere qualche secondo.")
        sys.exit(0)

    # Connessione con retry automatici
    client = connect_with_retry(max_retries=5, retry_delay=2)

    if client is None:
        print("Errore: impossibile stabilire connessione Modbus")
        sys.exit(1)

    try:
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

        elif comando == "leggi":
            angles = read_angles(client)
            if angles is None:
                print(json.dumps({"error": "Impossibile leggere angoli"}))
                sys.exit(1)
            print(json.dumps(angles))

        elif comando == "reset":
            if not reset_pca9685(client):
                print("Reset PCA9685 fallito")
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
