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
📥 <b>DESCARGAS</b>
━━━━━━━━━━━━━━━━━━━━

<b>1️⃣ YouTube</b>
├ /play &lt;nombre&gt; — Audio MP3
├ /play2 &lt;nombre&gt; — Video MP4
├ /playaudio &lt;nombre&gt; — Nota de voz
├ /ytmp3 &lt;url&gt; — Audio desde URL
└ /ytmp4 &lt;url&gt; — Video desde URL

<b>2️⃣ Facebook</b>
├ /fb &lt;url&gt;
└ Ejemplo: /fb https://facebook.com/watch/?v=12345

<b>3️⃣ Twitter / X</b>
├ /x &lt;url&gt;
└ Descarga videos y fotos

<b>4️⃣ TikTok</b>
├ /tiktok &lt;url&gt; — Sin marca de agua, calidad HD
└ Alias: /ttdl /tt /tiktoknowm

<b>5️⃣ MEGA / MediaFire / Google Drive</b>
├ Pega el enlace directamente o usa:
├ 🔷 MEGA — mega.nz
├ 🔶 MediaFire — mediafire.com
├ ☁️ /gdrive &lt;url_o_id&gt; — Descargar de Drive
└ 📤 /gdrive_upload [folder_id] — Subir a Drive

━━━━━━━━━━━━━━━━━━━━
🤖 <b>HERRAMIENTAS IA</b>
━━━━━━━━━━━━━━━━━━━━

<b>6️⃣ Mejorar Imagen con IA</b>
├ /enhance, /hd o /remini
├ Envía la foto con el comando como caption
├ O responde a una foto con el comando
├ O escribe /hd y luego envía la foto
└ ✨ Upscale 4x — mejora resolución y nitidez

━━━━━━━━━━━━━━━━━━━━
🔔 <b>NOTIFICACIONES DE ANIME</b>
━━━━━━━━━━━━━━━━━━━━

<b>7️⃣ Notificaciones de Streaming</b>
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

<b>8️⃣ Buscar Anime</b>
├ /anime &lt;nombre&gt;
├ Info completa: estudio, géneros, sinopsis traducida
└ Ejemplo: /anime Berserk

━━━━━━━━━━━━━━━━━━━━
⚠️ <b>NOTA</b>
━━━━━━━━━━━━━━━━━━━━
Los archivos se descargan y se envían sin compresión ni edición multimedia.

<b>⚠️ Límite Telegram:</b> 2GB por archivo"""

        await message.reply_text(help_text, parse_mode=enums.ParseMode.HTML)
