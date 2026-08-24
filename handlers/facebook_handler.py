"""
facebook_handler.py - Manejador de descargas de Facebook
Usa múltiples APIs con sistema de fallback
"""

import json
import logging
import subprocess
import re
from pathlib import Path
from pyrogram import filters, enums
from pyrogram.types import Message
from utils.loader_to import LoaderToError, download_url as loader_download_url

logger = logging.getLogger(__name__)


def register(app, download_dir):
    """Registra el handler de Facebook"""
    
    @app.on_message(filters.command(["fb", "facebook", "fbdl"]))
    async def facebook_command(client, message: Message):
        """Comando para descargar videos de Facebook"""
        
        # Obtener URL
        args = message.text.split(maxsplit=1)
        
        if len(args) < 2:
            await message.reply_text(
                "📘 <b>Facebook Downloader</b>\n\n"
                "⚠️ Ingresa un enlace de Facebook.\n\n"
                "<b>Ejemplo:</b>\n"
                "<code>/fb https://www.facebook.com/watch/?v=12345</code>",
                parse_mode=enums.ParseMode.HTML
            )
            return
        
        fb_link = args[1].strip()
        
        # Validar que sea un enlace de Facebook
        if not re.search(r'facebook\.com|fb\.watch', fb_link):
            await message.reply_text("❌ El enlace no parece ser de Facebook.")
            return
        
        logger.info(f"📘 Facebook - URL: {fb_link[:60]}...")
        
        status_msg = await message.reply_text("⏳ Descargando video de Facebook...")
        
        try:
            video_url = None
            video_title = None

            # loader.to soporta Facebook y es la primera opción.
            try:
                logger.info("🔄 Intentando loader.to para Facebook...")
                video_url, video_title = await loader_download_url(fb_link, "720")
                logger.info("✅ loader.to devolvió una URL de Facebook")
            except LoaderToError as error:
                logger.warning(f"⚠️ loader.to no disponible: {error}")

            # APIs públicas de respaldo, sin depender de una sola plataforma.
            if not video_url:
                encoded_url = fb_link.replace('&', '%26').replace('=', '%3D').replace('?', '%3F')
                apis = [
                    f"https://eliasar-yt-api.vercel.app/api/facebookdl?link={encoded_url}",
                    f"https://api.vreden.my.id/api/facebook?url={encoded_url}",
                ]
                for i, api in enumerate(apis, 1):
                    try:
                        logger.info(f"🔄 Intentando API pública #{i}...")
                        result = subprocess.run(
                            ['curl', '-sS', '-L', '--max-time', '30', api],
                            capture_output=True, text=True, timeout=35,
                        )
                        if result.returncode != 0:
                            continue
                        api_data = json.loads(result.stdout)
                        candidates = [api_data]
                        if isinstance(api_data, dict):
                            candidates.extend([
                                api_data.get('data'), api_data.get('result'), api_data.get('resultado')
                            ])
                        for candidate in candidates:
                            if isinstance(candidate, list):
                                candidates.extend(candidate)
                            elif isinstance(candidate, dict):
                                candidate_url = candidate.get('url') or candidate.get('download')
                                if isinstance(candidate_url, dict):
                                    candidate_url = candidate_url.get('url')
                                if isinstance(candidate_url, str) and candidate_url.startswith('http'):
                                    video_url = candidate_url
                                    video_title = candidate.get('title') or candidate.get('name')
                                    break
                        if video_url:
                            logger.info(f"✅ API pública #{i} exitosa")
                            break
                    except (json.JSONDecodeError, subprocess.TimeoutExpired, Exception) as error:
                        logger.warning(f"⚠️ API pública #{i} falló: {error}")

            if not video_url:
                raise Exception("No se pudo extraer el video con loader.to ni APIs públicas.")
            
            logger.info(f"✅ URL de descarga obtenida: {video_url[:60]}...")
            
            # Descargar video primero (Telegram no puede acceder directo a algunas URLs)
            await status_msg.edit_text("📥 Descargando video...")
            
            output_file = download_dir / f"fb_{message.from_user.id}.mp4"
            
            logger.info("📥 Descargando video de Facebook...")
            dl_cmd = f'curl -s -L -o "{output_file}" "{video_url}"'
            dl_result = subprocess.run(dl_cmd, shell=True, timeout=180)
            
            if dl_result.returncode != 0 or not output_file.exists():
                raise Exception("Error descargando el video")
            
            file_size = output_file.stat().st_size / (1024 * 1024)
            logger.info(f"✅ Video descargado: {file_size:.2f} MB")
            
            # Enviar video desde archivo local
            await status_msg.edit_text("📤 Enviando video...")
            
            caption = f"✅ <b>Video de Facebook</b>"
            if video_title:
                caption = f"✅ <b>{video_title}</b>"
            
            # Función de progreso
            last_percent = [0]
            async def upload_progress(current, total):
                percent = int((current / total) * 100)
                if percent - last_percent[0] >= 10:
                    mb_current = current / (1024**2)
                    mb_total = total / (1024**2)
                    logger.info(f"📤 Subida: {percent}% ({mb_current:.1f}/{mb_total:.1f} MB)")
                    last_percent[0] = percent
            
            tmp_fb_thumb = download_dir / f"fb_{message.from_user.id}_thumb.jpg"
            fb_dur, fb_thumb = VideoProcessor.get_video_meta(output_file, tmp_fb_thumb)
            await message.reply_video(
                video=str(output_file),
                caption=caption,
                parse_mode=enums.ParseMode.HTML,
                supports_streaming=True,
                progress=upload_progress,
                duration=fb_dur,
                thumb=fb_thumb,
            )
            tmp_fb_thumb.unlink(missing_ok=True)
            
            # Limpiar archivo temporal
            output_file.unlink()
            logger.info("🗑️ Archivo temporal eliminado")
            
            await status_msg.delete()
            logger.info("✅ Video de Facebook enviado exitosamente")
            
        except subprocess.TimeoutExpired:
            logger.error("⏱️ Timeout en descarga de Facebook")
            await status_msg.edit_text("⏱️ La descarga tardó demasiado. Intenta de nuevo.")
            
        except Exception as e:
            logger.error(f"❌ Error: {e}", exc_info=True)
            await status_msg.edit_text(f"❌ <b>Error:</b> {str(e)}", parse_mode=enums.ParseMode.HTML)
