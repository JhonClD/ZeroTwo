"""
help_handler.py - Manejador del comando /help
"""

from pyrogram import filters, enums
from pyrogram.types import Message


def register(app):
    """Registra el handler del comando /help"""

    @app.on_message(filters.command("help"))
    async def help_command(client, message: Message):
        """Comando /help - Ayuda detallada"""

        help_text = """📖 <b>Ayuda Detallada</b>

━━━━━━━━━━━━━━━━━━━━
🎬 <b>PROCESAMIENTO DE VIDEOS</b>
━━━━━━━━━━━━━━━━━━━━

━━━━━━━━━━━━━━━━━━━━
📥 <b>DESCARGAS</b>
━━━━━━━━━━━━━━━━━━━━

<b>5️⃣ YouTube</b>
├ /play &lt;nombre&gt; — Audio MP3
├ /play2 &lt;nombre&gt; — Video MP4
├ /playaudio &lt;nombre&gt; — Nota de voz
├ /ytmp3 &lt;url&gt; — Audio desde URL
└ /ytmp4 &lt;url&gt; — Video desde URL

<b>6️⃣ Facebook</b>
├ /fb &lt;url&gt;
└ Ejemplo: /fb https://facebook.com/watch/?v=12345

<b>7️⃣ Twitter / X</b>
├ /x &lt;url&gt;
└ Descarga videos y fotos

<b>8️⃣ TikTok</b>
├ /tiktok &lt;url&gt; — Sin marca de agua, calidad HD
└ Alias: /ttdl /tt /tiktoknowm

<b>9️⃣ MEGA / MediaFire / Google Drive</b>
├ Pega el enlace directamente o usa:
├ 🔷 MEGA — mega.nz
├ 🔶 MediaFire — mediafire.com
├ ☁️ /gdrive &lt;url_o_id&gt; — Descargar de Drive
└ 📤 /gdrive_upload [folder_id] — Subir a Drive

━━━━━━━━━━━━━━━━━━━━
🤖 <b>HERRAMIENTAS IA</b>
━━━━━━━━━━━━━━━━━━━━

<b>🔟 Mejorar Imagen con IA</b>
├ /enhance, /hd o /remini
├ Envía la foto con el comando como caption
├ O responde a una foto con el comando
├ O escribe /hd y luego envía la foto
└ ✨ Upscale 4x — mejora resolución y nitidez

━━━━━━━━━━━━━━━━━━━━
🔔 <b>NOTIFICACIONES DE ANIME</b>
━━━━━━━━━━━━━━━━━━━━

<b>1️⃣1️⃣ Notificaciones de Streaming</b>
├ /notify on           — Activar notificaciones
├ /notify off          — Desactivar
├ /notify status       — Ver estado actual
├ /notify add &lt;anime&gt;  — Suscribirse a un anime
├ /notify list         — Ver suscripciones
├ /notify remove &lt;n&gt;  — Eliminar suscripción
├ /notify now          — Revisar episodios ahora
├ 📡 Fuente: LiveChart.me
└ ⏱ Revisión automática cada 10 minutos

━━━━━━━━━━━━━━━━━━━━
🔍 <b>BÚSQUEDA</b>
━━━━━━━━━━━━━━━━━━━━

<b>1️⃣2️⃣ Buscar Anime</b>
├ /anime &lt;nombre&gt;
├ Info completa: estudio, géneros, sinopsis traducida
└ Ejemplo: /anime Berserk

━━━━━━━━━━━━━━━━━━━━
📋 <b>FORMATOS SOPORTADOS</b>
━━━━━━━━━━━━━━━━━━━━
• <b>Video:</b> MP4, MKV, AVI, MOV, WEBM
• <b>Audio:</b> MP3, M4A, WAV, OGG, FLAC
• <b>Subtítulos:</b> SRT, ASS, VTT
• <b>Imagen:</b> JPG, PNG

<b>⚠️ Límite Telegram:</b> 2GB por archivo

<b>💡 Tip:</b> Todos los videos descargados muestran un preview con screenshots automáticos 📸"""

        await message.reply_text(help_text, parse_mode=enums.ParseMode.HTML)
