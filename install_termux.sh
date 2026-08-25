#!/bin/bash
# Script de instalación automática para Rikka Bot en Termux

echo "╔══════════════════════════════════════════╗"
echo "║  🤖 RIKKA BOT - INSTALADOR AUTOMÁTICO  ║"
echo "╔══════════════════════════════════════════╗"
echo ""

# Colores
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}📦 Paso 1/5: Actualizando paquetes...${NC}"
pkg update -y && pkg upgrade -y

echo ""
echo -e "${BLUE}📦 Paso 2/5: Instalando dependencias del sistema...${NC}"
pkg install -y git python ffmpeg megatools wget curl aria2

echo ""
echo -e "${BLUE}📦 Paso 3/5: Instalando dependencias Python...${NC}"
pip install --upgrade pip
pip install -r requirements.txt

echo ""
echo -e "${BLUE}📦 Paso 4/5: Configuración del bot...${NC}"

# Verificar si ya existe el token
if [ -f "$HOME/.telegram_bot_token" ]; then
    echo -e "${YELLOW}⚠️  Ya existe un token configurado${NC}"
    read -p "¿Deseas cambiarlo? (s/N): " change_token
    if [[ $change_token == "s" || $change_token == "S" ]]; then
        read -p "Ingresa el token del bot: " BOT_TOKEN
        echo "$BOT_TOKEN" > ~/.telegram_bot_token
        echo -e "${GREEN}✅ Token actualizado${NC}"
    fi
else
    read -p "Ingresa el token del bot (obtener en @BotFather): " BOT_TOKEN
    echo "$BOT_TOKEN" > ~/.telegram_bot_token
    echo -e "${GREEN}✅ Token configurado${NC}"
fi

echo ""
echo -e "${BLUE}📦 Paso 5/5: Verificando instalación...${NC}"

# Verificar herramientas
tools=("python" "ffmpeg" "megadl" "wget" "curl" "aria2c")
all_ok=true

for tool in "${tools[@]}"; do
    if command -v $tool &> /dev/null; then
        echo -e "${GREEN}✅ $tool instalado${NC}"
    else
        echo -e "${RED}❌ $tool NO instalado${NC}"
        all_ok=false
    fi
done

echo ""
if [ "$all_ok" = true ]; then
    echo -e "${GREEN}╔══════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║    ✅ INSTALACIÓN COMPLETADA CON ÉXITO  ║${NC}"
    echo -e "${GREEN}╚══════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${BLUE}🚀 Para iniciar el bot, ejecuta:${NC}"
    echo -e "${YELLOW}   python main.py${NC}"
    echo ""
else
    echo -e "${RED}╔══════════════════════════════════════════╗${NC}"
    echo -e "${RED}║  ⚠️  INSTALACIÓN CON ERRORES            ║${NC}"
    echo -e "${RED}╚══════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${YELLOW}Por favor, revisa los errores arriba${NC}"
fi
