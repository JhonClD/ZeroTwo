"""
Rikka Bot - Bot de Telegram para procesamiento de videos
Autor: @MINORURAKUEN
GitHub: https://github.com/MINORURAKUEN/Rikka-Bot
"""

import os
import asyncio
import logging
import shutil
from pathlib import Path

# Parche de compatibilidad: Python 3.12+ (incluido Termux) ya no crea
# automáticamente un event loop en el hilo principal. Pyrogram lo necesita
# antes de importarse, así que lo creamos aquí manualmente.
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

from pyrogram import Client


# ─────────────────────────────────────────────────────────────────────────────
# Logging: consola limpia + archivo detallado
# ─────────────────────────────────────────────────────────────────────────────
class ConsoleFormatter(logging.Formatter):
    """Formato breve y legible para Termux, sin perder el detalle en bot.log."""

    LEVELS = {
        logging.DEBUG: ("DBG", "\033[90m"),
        logging.INFO: ("INFO", "\033[36m"),
        logging.WARNING: ("WARN", "\033[33m"),
        logging.ERROR: ("ERROR", "\033[31m"),
        logging.CRITICAL: ("FATAL", "\033[1;31m"),
    }

    def format(self, record):
        label, color = self.LEVELS.get(record.levelno, (record.levelname, ""))
        reset = "\033[0m"
        message = record.getMessage()
        timestamp = self.formatTime(record, "%H:%M:%S")
        return f"{color}{timestamp}  {label:<5}{reset} {message}"


console_handler = logging.StreamHandler()
console_handler.setFormatter(ConsoleFormatter("%(asctime)s"))

file_handler = logging.FileHandler("bot.log", encoding="utf-8")
file_handler.setFormatter(logging.Formatter(
    "%(asctime)s | %(name)s | %(levelname)s | %(message)s"
))

logging.basicConfig(
    level=logging.INFO,
    handlers=[console_handler, file_handler],
    force=True,
)

# Pyrogram puede emitir muchos mensajes internos; los errores siguen visibles,
# pero la consola queda centrada en los eventos útiles del bot.
for noisy_logger in ("pyrogram", "asyncio", "httpx", "httpcore"):
    logging.getLogger(noisy_logger).setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


def print_section(title):
    """Dibuja una sección consistente y compacta en la consola."""
    line = "─" * 58
    logger.info(line)
    logger.info("  %s", title)
    logger.info(line)


def print_status(label, value, ok=True):
    """Muestra una fila de estado alineada."""
    icon = "✓" if ok else "✗"
    logger.info("  %s %-16s %s", icon, label, value)


# Configuración del bot
API_ID = 30368923
API_HASH = "c77e78f4666683cb542fe4a2f7fd9045"

# Leer token del bot
token_file = Path.home() / ".telegram_bot_token"
if not token_file.exists():
    logger.error("No se encontró el archivo ~/.telegram_bot_token")
    logger.error("Créalo con: echo 'TU_BOT_TOKEN' > ~/.telegram_bot_token")
    raise SystemExit(1)

BOT_TOKEN = token_file.read_text().strip()

# Directorios de trabajo
WORK_DIR = Path.home() / "telegram_bot_files"
DOWNLOAD_DIR = Path.home() / "telegram_downloads"
# Carpeta predeterminada de Google Drive. Puede quedar vacía para usar Mi unidad.
GOOGLE_DRIVE_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "").strip() or None
WORK_DIR.mkdir(exist_ok=True)
DOWNLOAD_DIR.mkdir(exist_ok=True)

# Crear cliente de Pyrogram
app = Client(
    "video_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
)

# Estado de usuarios (DEFINIR ANTES DE IMPORTAR HANDLERS)
user_states = {}

# Importar handlers
from handlers import (
    start_handler,
    help_handler,
    download_handler,
    anime_handler,
    youtube_handler,
    facebook_handler,
    twitter_handler,
    tiktok_handler,
    url_handler,
    drive_handler,
    enhance_handler,
    tioanime_notify_handler,
    animeav1_notify_handler,
    animedbs_notify_handler,
    monoschinos_notify_handler,
    jkanime_notify_handler,
)

# Registrar handlers
start_handler.register(app)
help_handler.register(app)
download_handler.register(app)
anime_handler.register(app, user_states, WORK_DIR)
youtube_handler.register(app, DOWNLOAD_DIR)
facebook_handler.register(app, DOWNLOAD_DIR)
twitter_handler.register(app, DOWNLOAD_DIR)
tiktok_handler.register(app, DOWNLOAD_DIR)
url_handler.register(app, DOWNLOAD_DIR)
drive_handler.register(
    app,
    user_states,
    DOWNLOAD_DIR,
    default_folder_id=GOOGLE_DRIVE_FOLDER_ID,
)
enhance_handler.register(app, user_states, WORK_DIR)
tioanime_notify_handler.register(app, WORK_DIR)
animeav1_notify_handler.register(app, WORK_DIR)
animedbs_notify_handler.register(app, WORK_DIR)
monoschinos_notify_handler.register(app, WORK_DIR)
jkanime_notify_handler.register(app, WORK_DIR)


if __name__ == "__main__":
    print_section("ZERO TWO  ·  TELEGRAM VIDEO BOT")
    print_status("Versión", "Pyrogram · sin límite de tamaño")
    print_status("Trabajo", str(WORK_DIR))
    print_status("Descargas", str(DOWNLOAD_DIR))
    print_status("Registro", "bot.log")

    print_section("COMPROBACIÓN DEL SISTEMA")
    tools = {
        "FFmpeg": "ffmpeg",
        "FFprobe": "ffprobe",
        "Megatools": "megadl",
        "Wget": "wget",
    }
    for name, command in tools.items():
        available = shutil.which(command) is not None
        version = "disponible" if available else "no disponible"
        print_status(name, version, ok=available)

    print_section("ESTADO")
    logger.info("  ✓ Bot iniciado correctamente")
    logger.info("  · Carpeta Drive: %s", GOOGLE_DRIVE_FOLDER_ID or "Mi unidad")
    logger.info("  · Pulsa Ctrl+C para detenerlo")
    logger.info("─" * 58)

    async def main():
        await app.start()
        logger.info("Conexión establecida · bot operativo")

        from pyrogram import idle
        await idle()
        await app.stop()

    try:
        app.loop.run_until_complete(main())
    except KeyboardInterrupt:
        logger.info("Bot detenido por el usuario")
    except Exception as error:
        logger.error("Error fatal: %s", error, exc_info=True)
        raise
