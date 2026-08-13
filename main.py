#!/usr/bin/env python3
"""
Rikka Bot - Bot de Telegram para procesamiento de videos
Autor: @MINORURAKUEN
GitHub: https://github.com/MINORURAKUEN/Rikka-Bot
"""

import os
import asyncio
import logging
from pathlib import Path

# Parche de compatibilidad: Python 3.12+ (incluido Termux) ya no crea
# automáticamente un event loop en el hilo principal. Pyrogram lo necesita
# antes de importarse, así que lo creamos aquí manualmente.
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

from pyrogram import Client

# Configuración de logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bot.log')
    ]
)

logger = logging.getLogger(__name__)

# Configuración del bot
API_ID = 30368923
API_HASH = "c77e78f4666683cb542fe4a2f7fd9045"

# Leer token del bot
token_file = Path.home() / '.telegram_bot_token'
if not token_file.exists():
    logger.error("❌ No se encontró el archivo ~/.telegram_bot_token")
    logger.error("Crea el archivo con: echo 'TU_BOT_TOKEN' > ~/.telegram_bot_token")
    exit(1)

BOT_TOKEN = token_file.read_text().strip()

# Directorios de trabajo
WORK_DIR = Path.home() / 'telegram_bot_files'
DOWNLOAD_DIR = Path.home() / 'telegram_downloads'

WORK_DIR.mkdir(exist_ok=True)
DOWNLOAD_DIR.mkdir(exist_ok=True)

logger.info("📁 Directorio de trabajo: %s", WORK_DIR)
logger.info("📥 Directorio de descargas: %s", DOWNLOAD_DIR)

# Crear cliente de Pyrogram
app = Client(
    "video_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# Estado de usuarios (DEFINIR ANTES DE IMPORTAR HANDLERS)
user_states = {}

# Importar handlers
from handlers import (
    start_handler,
    help_handler,
    compress_handler,
    thumbnail_handler,
    subtitles_handler,
    extract_audio_handler,
    download_handler,
    anime_handler,
    youtube_handler,
    facebook_handler,
    twitter_handler,
    tiktok_handler,
    video_handler,
    photo_handler,
    document_handler,
    url_handler,
    button_callback_handler,
    drive_handler,
    enhance_handler,
    tioanime_notify_handler
)

# Registrar handlers
start_handler.register(app)
help_handler.register(app)
compress_handler.register(app, user_states)
thumbnail_handler.register(app, user_states, WORK_DIR)  # Fix: added WORK_DIR
subtitles_handler.register(app, user_states)
extract_audio_handler.register(app, user_states)
download_handler.register(app)
anime_handler.register(app, user_states, WORK_DIR)
youtube_handler.register(app, DOWNLOAD_DIR)
facebook_handler.register(app, DOWNLOAD_DIR)
twitter_handler.register(app, DOWNLOAD_DIR)
tiktok_handler.register(app, DOWNLOAD_DIR)
video_handler.register(app, user_states, WORK_DIR)
photo_handler.register(app, user_states, WORK_DIR)
document_handler.register(app, user_states, WORK_DIR)
url_handler.register(app, DOWNLOAD_DIR)
button_callback_handler.register(app, user_states, WORK_DIR)
drive_handler.register(app, user_states, DOWNLOAD_DIR)
enhance_handler.register(app, user_states, WORK_DIR)
tioanime_notify_handler.register(app, WORK_DIR)

if __name__ == '__main__':
    logger.info("=" * 60)
    logger.info("🤖 BOT DE TELEGRAM - PROCESAMIENTO DE VIDEOS")
    logger.info("=" * 60)
    logger.info("🔧 Versión: Pyrogram (Sin límite de tamaño)")
    logger.info("📁 Directorio de trabajo: %s", WORK_DIR)
    logger.info("📥 Directorio de descargas: %s", DOWNLOAD_DIR)
    logger.info("📝 Log guardado en: bot.log")
    logger.info("=" * 60)
    
    # Verificar herramientas
    logger.info("🔍 Verificando herramientas necesarias...")
    
    import subprocess
    tools = {
        'FFmpeg': 'ffmpeg',
        'FFprobe': 'ffprobe',
        'Megatools': 'megadl',
        'Wget': 'wget'
    }
    
    for name, cmd in tools.items():
        try:
            result = subprocess.run([cmd, '--version'], 
                                   capture_output=True, 
                                   timeout=5)
            if result.returncode == 0:
                logger.info(f"✅ {name}: Instalado")
            else:
                logger.warning(f"⚠️ {name}: No disponible")
        except:
            logger.warning(f"⚠️ {name}: No disponible")
    
    logger.info("=" * 60)
    logger.info("🚀 Bot iniciado correctamente")
    logger.info("⏸️ Presiona Ctrl+C para detener")
    logger.info("=" * 60)
    
    async def main():
        await app.start()
        logger.info("🚀 Bot iniciado correctamente")

        from pyrogram import idle
        await idle()
        await app.stop()

    try:
        import asyncio
        app.loop.run_until_complete(main())
    except KeyboardInterrupt:
        logger.info("\n👋 Bot detenido por el usuario")
    except Exception as e:
        logger.error(f"❌ Error fatal: {e}", exc_info=True)
