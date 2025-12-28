#!/bin/bash

# Colori per i messaggi
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}Pulizia del sistema di rilevamento gatti${NC}"
echo -e "${YELLOW}Questo script rimuoverà tutti i dati del sistema di rilevamento gatti.${NC}"
read -p "Sei sicuro di voler procedere? (s/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Ss]$ ]]
then
    echo -e "${BLUE}Operazione annullata${NC}"
    exit 1
fi

# Directory da eliminare
DIRS_TO_REMOVE=(
    "detected_cats"
    "named_cats"
    "dataset"
    "dataset/train"
    "dataset/val"
    "dataset/test"
)

# File da eliminare
FILES_TO_REMOVE=(
    "cats_database.json"
)

echo -e "\n${BLUE}Rimozione delle directory...${NC}"
for dir in "${DIRS_TO_REMOVE[@]}"; do
    if [ -d "$dir" ]; then
        echo -e "Rimozione di $dir..."
        rm -rf "$dir"
        if [ $? -eq 0 ]; then
            echo -e "${GREEN}✓ $dir rimossa con successo${NC}"
        else
            echo -e "${RED}✗ Errore durante la rimozione di $dir${NC}"
        fi
    else
        echo -e "${YELLOW}! $dir non esistente${NC}"
    fi
done

echo -e "\n${BLUE}Rimozione dei file...${NC}"
for file in "${FILES_TO_REMOVE[@]}"; do
    if [ -f "$file" ]; then
        echo -e "Rimozione di $file..."
        rm "$file"
        if [ $? -eq 0 ]; then
            echo -e "${GREEN}✓ $file rimosso con successo${NC}"
        else
            echo -e "${RED}✗ Errore durante la rimozione di $file${NC}"
        fi
    else
        echo -e "${YELLOW}! $file non esistente${NC}"
    fi
done

echo -e "\n${GREEN}Pulizia completata!${NC}"
echo -e "${BLUE}Ora puoi riavviare il sistema di rilevamento gatti.${NC}"
