#!/bin/bash

# Colori per i messaggi
GREEN='\033[0;32m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}Configurazione porta seriale per controllo finestra gatti${NC}"

# Verifica che l'utente sia root
if [ "$EUID" -ne 0 ]; then 
  echo -e "${RED}Questo script deve essere eseguito come root${NC}"
  exit 1
fi

# Crea regola udev per la porta seriale
echo "Creo la regola udev per CH341..."
cat > /etc/udev/rules.d/99-cat-window.rules << 'EOL'
SUBSYSTEM=="tty", ATTRS{idVendor}=="1a86", ATTRS{idProduct}=="7523", SYMLINK+="ttyCAT", MODE="0666", RUN+="/bin/stty -F /dev/%k -hupcl"
EOL

# Ricarica le regole udev
echo "Ricarico le regole udev..."
udevadm control --reload-rules
udevadm trigger

# Attendi che la porta venga creata
echo "Attendo la creazione della porta..."
sleep 2

# Verifica che la porta esista
if [ -e "/dev/ttyCAT" ]; then
    echo -e "${GREEN}Porta /dev/ttyCAT creata correttamente${NC}"
else
    echo -e "${RED}Errore: /dev/ttyCAT non trovata${NC}"
    echo "Provo a ricollegare il dispositivo..."
    echo "Per favore, scollega e ricollega fisicamente l'adattatore USB"
    echo "Premi Enter quando hai finito"
    read
    sleep 2
    if [ -e "/dev/ttyCAT" ]; then
        echo -e "${GREEN}Porta /dev/ttyCAT creata correttamente${NC}"
    else
        echo -e "${RED}Errore: /dev/ttyCAT non trovata${NC}"
        exit 1
    fi
fi

# Configura la porta
echo "Configuro la porta seriale..."
stty -F /dev/ttyCAT 115200 -hupcl -echo raw

# Verifica la configurazione
echo "Verifica configurazione:"
stty -F /dev/ttyCAT -a

# Imposta permessi corretti
echo "Imposto i permessi..."
chown root:dialout /dev/ttyCAT
chmod 666 /dev/ttyCAT

echo -e "${GREEN}Configurazione completata${NC}"
echo "La porta seriale è ora configurata per evitare il reset DTR"
echo "Permessi porta:"
ls -l /dev/ttyCAT
