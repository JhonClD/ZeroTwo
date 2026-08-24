"""
start_handler.py - Manejador del comando /start
"""

from pyrogram import filters, enums
from pyrogram.types import Message


def register(app):
    """Registra el handler del comando /start"""

    @app.on_message(filters.command("start"))
    async def start_command(client, message: Message):
        """Comando /start - Mensaje de bienvenida"""

        welcome_message = """🎌 <b>Bienvenido a Zero Two Bot</b>

Puedo ayudarte con todo esto:

━━━━━━━━━━━━━━━━━━━━
🎬 <b>PROCESAMIENTO DE VIDEO</b>
━━━━━━━━━━━━━━━━━━━━
/extract_audio  — Extraer audio MP3

━━━━━━━━━━━━━━━━━━━━
📥 <b>DESCARGAS</b>
━━━━━━━━━━━━━━━━━━━━
/play           — YouTube audio
/play2          — YouTube video
/fb             — Facebook video
/x              — Twitter/X video
/tiktok         — TikTok sin marca de agua
/gdrive         — Descargar de Google Drive
/gdrive_upload  — Subir a Google Drive
Pega un enlace de MEGA o MediaFire directamente

━━━━━━━━━━━━━━━━━━━━
🤖 <b>HERRAMIENTAS IA</b>
━━━━━━━━━━━━━━━━━━━━
/hd             — Mejorar imagen con IA (upscale 4x)
/enhance        — Alias de /hd
/remini         — Alias de /hd

━━━━━━━━━━━━━━━━━━━━
🔔 <b>NOTIFICACIONES</b>
━━━━━━━━━━━━━━━━━━━━
/notify on      — Activar avisos de estrenos
/notify add     — Suscribirse a un anime
/notify list    — Ver suscripciones
📡 Fuente: LiveChart.me · revisión cada 10 min

━━━━━━━━━━━━━━━━━━━━
🔍 <b>BÚSQUEDA</b>
━━━━━━━━━━━━━━━━━━━━
/anime          — Info completa de cualquier anime

━━━━━━━━━━━━━━━━━━━━

/help — Ver ayuda detallada de todos los comandos"""

        await message.reply_text(welcome_message, parse_mode=enums.ParseMode.HTML)
        
