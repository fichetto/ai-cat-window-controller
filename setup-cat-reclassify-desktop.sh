#!/bin/bash

# Colori per i messaggi
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}Configurazione del collegamento desktop per Cat Reclassify${NC}"

# Verifica che la directory hailo-rpi5-examples esista
if [ ! -d ~/hailo-rpi5-examples ]; then
    echo "Error: Directory hailo-rpi5-examples non trovata!"
    exit 1
fi

# Crea lo script di avvio
echo -e "${BLUE}Creazione dello script di avvio...${NC}"
cat > ~/start_cat_reclassify.sh << 'EOL'
#!/bin/bash
cd ~/hailo-rpi5-examples
source venv_hailo_rpi5_examples/bin/activate
source setup_env.sh
python basic_pipelines/cat_reclassify.py
EOL

# Rendi lo script eseguibile
chmod +x ~/start_cat_reclassify.sh

# Crea la directory applications se non esiste
mkdir -p ~/.local/share/applications

# Crea il file .desktop
echo -e "${BLUE}Creazione del file .desktop...${NC}"
cat > ~/.local/share/applications/cat-reclassify.desktop << EOL
[Desktop Entry]
Version=1.0
Type=Application
Name=Cat Reclassify
Comment=Riclassificazione Gatti
Exec=/home/pi/start_cat_reclassify.sh
Icon=edit
Terminal=false
Categories=Application
EOL

# Rendi il file .desktop eseguibile
chmod +x ~/.local/share/applications/cat-reclassify.desktop

# Crea il collegamento sul desktop
echo -e "${BLUE}Creazione del collegamento sul desktop...${NC}"
ln -sf ~/.local/share/applications/cat-reclassify.desktop ~/Desktop/

# Rendi il collegamento sul desktop eseguibile
chmod +x ~/Desktop/cat-reclassify.desktop

echo -e "${GREEN}Configurazione completata!${NC}"
echo -e "${GREEN}Ora puoi trovare l'icona 'Cat Reclassify' sul desktop${NC}"