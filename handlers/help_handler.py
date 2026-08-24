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

<b>1️⃣ Compresión y encoding</b>
├ Envía un video o documento de video
├ Elige formato y resolución
├ Selecciona perfil: Pequeño, Equilibrado, Alta calidad o H.265/HEVC
└ FFmpeg procesa con duración, miniatura y progreso

<b>2️⃣ Subtítulos y pistas</b>
├ Responde a un video para gestionar audio/subtítulos internos
├ Compatible con SRT, ASS y VTT
└ Permite incrustar subtítulos mediante FFmpeg

<b>3️⃣ Extraer Audio</b>
├ /extract_audio
├ Envía el video
└ Recibe el audio en MP3 (192kbps)

━━━━━━━━━━━━━━━━━━━━
📥 <b>DESCARGAS</b>
━━━━━━━━━━━━━━━━━━━━

<b>6️⃣ YouTube</b>
├ /play &lt;nombre&gt; — Audio MP3
├ /play2 &lt;nombre&gt; — Video MP4
├ /playaudio &lt;nombre&gt; — Nota de voz
├ /ytmp3 &lt;url&gt; — Audio desde URL
└ /ytmp4 &lt;url&gt; — Video desde URL

<b>7️⃣ Facebook</b>
├ /fb &lt;url&gt;
└ Ejemplo: /fb https://facebook.com/watch/?v=12345

<b>8️⃣ Twitter / X</b>
├ /x &lt;url&gt;
└ Descarga videos y fotos

<b>9️⃣ TikTok</b>
├ /tiktok &lt;url&gt; — Sin marca de agua, calidad HD
└ Alias: /ttdl /tt /tiktoknowm

<b>🔟 MEGA / MediaFire / Google Drive</b>
├ Pega el enlace directamente o usa:
├ 🔷 MEGA — mega.nz
├ 🔶 MediaFire — mediafire.com
├ ☁️ /gdrive &lt;url_o_id&gt; — Descargar de Drive
└ 📤 /gdrive_upload [folder_id] — Subir a Drive

━━━━━━━━━━━━━━━━━━━━
🤖 <b>HERRAMIENTAS IA</b>
━━━━━━━━━━━━━━━━━━━━

<b>1️⃣1️⃣ Mejorar Imagen con IA</b>
├ /enhance, /hd o /remini
├ Envía la foto con el comando como caption
├ O responde a una foto con el comando
├ O escribe /hd y luego envía la foto
└ ✨ Upscale 4x — mejora resolución y nitidez

━━━━━━━━━━━━━━━━━━━━
🔔 <b>NOTIFICACIONES DE ANIME</b>
━━━━━━━━━━━━━━━━━━━━

<b>1️⃣2️⃣ Notificaciones de Streaming</b>
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

<b>1️⃣3️⃣ Buscar Anime</b>
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
