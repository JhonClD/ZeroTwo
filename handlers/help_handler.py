"""
help_handler.py - Manejador del comando /help
"""

from pyrogram import enums, filters
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

<b>5️⃣ Descargas del ZIP migradas</b>
├ /animedl &lt;url&gt; — Episodio de anime
├ /animedl &lt;nombre&gt; &lt;episodio&gt; — Buscar episodio
├ /ani o /anidl &lt;url&gt; — AniDL local (solo propietario)
├ /hdl &lt;nombre&gt; &lt;episodio&gt; — HentaiLA
├ /get &lt;url&gt; — Descargar recurso
└ /ssweb &lt;url&gt; — Captura de página
<b>6️⃣ YouTube</b>
├ /play &lt;nombre&gt; — MP3 por Loader.to con carátula si está disponible
├ /play2 &lt;nombre&gt; — Video hasta 720p por Loader.to
├ /playaudio &lt;nombre&gt; — Nota de voz
├ /ytmp3 &lt;url&gt; — Audio desde URL
└ /ytmp4 &lt;url&gt; — Video desde URL

<b>7️⃣ Facebook</b>
├ /fb &lt;url&gt;
└ Ejemplo: /fb https://facebook.com/watch/?v=12345

<b>🎞 Procesamiento de video</b>
├ Responde a un video con /process para elegir una operación
├ /compress — Perfiles de compresión; /compress 700 intenta un tamaño aproximado en MB
├ /subtitles o /sub — Quemar una pista del video o enviar .srt/.ass/.vtt
├ /processstatus — Ver tu trabajo pendiente o activo
└ /cancelprocess — Cancelar y limpiar archivos temporales

<b>🛠 Administración</b>
└ /updatezero — Actualizar desde GitHub (alias: /uptadezero; solo propietarios autorizados)

<b>🖼 Portada de video</b>
├ Envía una foto; reemplaza la miniatura anterior (solo se usa una)
├ Al enviar un video, se reenviará con esa miniatura
├ /thumon — Activar aplicación automática
├ /thumoff — Desactivarla temporalmente
├ /show_cover — Ver tu portada guardada
├ /del_cover — Eliminarla
└ Video normal: sin descargarlo; como documento puede requerir descarga y reenvío

<b>8️⃣ Twitter / X</b>
├ /x &lt;url&gt;
└ Descarga videos y fotos

<b>9️⃣ TikTok</b>
├ /tiktok &lt;url&gt; — Sin marca de agua, calidad HD
└ Alias: /ttdl /tt /tiktoknowm

<b>🔟 MEGA / MediaFire / Google Drive / Drime / GoFile</b>
├ Pega el enlace directamente o usa:
├ 🔷 MEGA — mega.nz
├ 🔶 MediaFire — mediafire.com
├ ☁️ /gdrive &lt;url_o_id&gt; — Descargar de Drive
├ Carpeta pública: elegir archivo o descargar todo; requiere GOOGLE_DRIVE_API_KEY
├ 📤 /gdrive_upload [folder_id] — Subir usando API de Drive
├ ☁️ Drime — pega un enlace público; si es carpeta, elige un archivo
├ Drime requiere que el enlace permita descargar; no pide token de cuenta
├ ☁️ GoFile — pega un enlace público https://gofile.io/d/ID
└ Si es carpeta, elige el archivo; no requiere una cuenta personal

├ 📁 /drive_sync — Guardar para sincronización Android
└ Después envía un documento, foto, video o audio

<b>1️⃣1️⃣ Torrents</b>
├ Pega un enlace magnet directamente
├ Responde a un archivo .torrent con /torrent
└ Requiere aria2 instalado en Termux

<b>📦 Archivos RAR</b>
├ Envía un .rar como documento y responde con /unrar
├ O usa /unrar nombre_archivo.rar si ya está en tus descargas
├ Los archivos protegidos solicitan la contraseña en el chat
└ /cancel ID — Cancelar una extracción activa

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
<b>1️⃣2️⃣ Avisos de Crunchyroll</b>
├ /crset — Suscribir este chat (solo propietario)
├ /crrem — Quitar este chat
├ /crstatus — Ver estado del monitor
├ /crlist — Mostrar los 10 episodios recientes con miniatura disponible
└ /crnotify — Revisar avisos nuevos (con imagen si está disponible)

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
• <b>Imagen:</b> JPG, PNG

<b>⚠️ Límite Telegram:</b> 2GB por archivo

La compresión usa FFmpeg. Quemar subtítulos requiere una build con el filtro subtitles/libass. En hosting, el tamaño de entrada y los procesos simultáneos tienen límites configurables.
La miniatura se adjunta al video en Telegram; no altera ni inserta la imagen dentro de los fotogramas del archivo.

<b>💡 Tip:</b> Todos los videos descargados muestran un preview con screenshots automáticos 📸"""

        await message.reply_text(help_text, parse_mode=enums.ParseMode.HTML)
