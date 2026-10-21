"""
start_handler.py - Manejador del comando /start
"""

from pyrogram import enums, filters
from pyrogram.types import Message


def register(app):
    """Registra el handler del comando /start"""

    @app.on_message(filters.command("start"))
    async def start_command(client, message: Message):
        """Comando /start - Mensaje de bienvenida"""

        welcome_message = """🎌 <b>Bienvenido a Zero Two Bot</b>

Puedo ayudarte con todo esto:

━━━━━━━━━━━━━━━━━━━━
📥 <b>DESCARGAS</b>
━━━━━━━━━━━━━━━━━━━━
/play           — YouTube audio
/animedl        — Descargar episodios de anime
/hdl            — Descargar HentaiLA
/get            — Descargar un recurso por URL
/ssweb          — Captura de una página web
/play2          — YouTube video
/fb             — Facebook video
/x              — Twitter/X video
/tiktok         — TikTok sin marca de agua
/gdrive         — Descargar de Google Drive
                 Carpetas públicas: elegir archivo o descargar todo (requiere GOOGLE_DRIVE_API_KEY)
/gdrive_upload  — Subir directamente usando API
/drive_sync     — Guardar para sincronización Android
                 Luego envía el archivo
Pega un enlace de MEGA o MediaFire directamente

━━━━━━━━━━━━━━━━━━━━
🎞 <b>PROCESAMIENTO DE VIDEO</b>
━━━━━━━━━━━━━━━━━━━━
/process        — Elegir compresión o quemar subtítulos
/compress       — Comprimir con perfil o tamaño objetivo
/subtitles      — Quemar subtítulos internos o externos
/processstatus  — Ver estado · /cancelprocess para cancelar

🖼 <b>PORTADA DE VIDEO</b>
Envía una foto para guardarla como miniatura de tus videos.
/thumon         — Activar · /thumoff para desactivar
/show_cover     — Ver tu portada · /del_cover para borrarla

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
        
