"""
youtube_handler.py - Manejador de descargas de YouTube
Corregido: Manejo robusto de reacciones para evitar REACTION_INVALID
"""

import json
import logging
import subprocess
import re
from pathlib import Path
from pyrogram import filters, enums
from pyrogram.types import Message
from utils import VideoProcessor
from utils.loader_to import LoaderToError, download_url as loader_download_url

logger = logging.getLogger(__name__)

async def safe_react(message: Message, emoji: str):
    """Envía una reacción de forma segura sin romper el flujo si falla"""
    try:
        await message.react(emoji)
    except Exception:
        # Si falla la reacción (emoji inválido o permisos), solo logueamos y seguimos
        logger.warning(f"No se pudo reaccionar con {emoji}")

def register(app, download_dir):
    """Registra el handler de YouTube"""
    
    @app.on_message(filters.command(["play", "play2", "ytmp3", "ytmp4", "playaudio"]))
    async def youtube_command(client, message: Message):
        """Comando para descargar de YouTube (Audio/Video/Nota de Voz)"""
        
        # Obtener query
        args = message.text.split(maxsplit=1)
        command = message.command[0].lower()
        
        if len(args) < 2:
            await message.reply_text(
                "🎵 <b>YouTube Downloader</b>\n\n"
                "Escribe el nombre o URL del video:\n\n"
                "<b>Comandos:</b>\n"
                "/play <nombre> - Buscar y descargar audio\n"
                "/play2 <nombre> - Buscar y descargar video\n"
                "/playaudio <nombre> - Audio como nota de voz\n"
                "/ytmp3 <url> - Descargar audio directo\n"
                "/ytmp4 <url> - Descargar video directo\n\n"
                "<b>Ejemplo:</b>\n"
                "<code>/play Linkin Park Numb</code>",
                parse_mode=enums.ParseMode.HTML
            )
            return
        
        query = args[1].strip()
        
        # Determinar tipo de descarga
        is_video = command in ['play2', 'ytmp4']
        is_voice_note = command == 'playaudio'
        
        logger.info(f"🎵 YouTube request - Query: {query[:50]}... | Comando: {command}")
        
        status_msg = await message.reply_text("🔍 Buscando en YouTube...")
        
        try:
            # ==========================================
            # BUSCAR VIDEO EN YOUTUBE
            # ==========================================
            video_url = None
            video_title = None
            video_channel = None
            video_thumbnail = None
            
            # Si es URL directa
            if query.startswith('http'):
                video_url = query
                logger.info(f"📹 URL directa proporcionada")
                
                # Obtener info del video
                info_cmd = f'curl -s "https://www.youtube.com/oembed?url={video_url}&format=json"'
                result = subprocess.run(info_cmd, shell=True, capture_output=True, text=True, timeout=10)
                
                if result.returncode == 0 and result.stdout:
                    try:
                        info = json.loads(result.stdout)
                        video_title = info.get('title', 'Video de YouTube')
                        video_channel = info.get('author_name', 'Desconocido')
                        video_thumbnail = info.get('thumbnail_url', '')
                    except:
                        video_title = 'Video de YouTube'
                        video_channel = 'Desconocido'
            else:
                # Buscar en YouTube
                logger.info(f"🔍 Buscando: {query}")
                
                search_cmd = f'curl -s "https://www.youtube.com/results?search_query={query.replace(" ", "+")}"'
                result = subprocess.run(search_cmd, shell=True, capture_output=True, text=True, timeout=15)
                
                if result.returncode == 0 and result.stdout:
                    # Extraer primer video ID
                    video_id_match = re.search(r'"videoId":"([^"]+)"', result.stdout)
                    
                    if video_id_match:
                        video_id = video_id_match.group(1)
                        video_url = f"https://www.youtube.com/watch?v={video_id}"
                        
                        # Extraer título
                        title_match = re.search(r'"title":{"runs":\[{"text":"([^"]+)"', result.stdout)
                        if title_match:
                            video_title = title_match.group(1)
                        
                        # Extraer canal
                        channel_match = re.search(r'"ownerText":{"runs":\[{"text":"([^"]+)"', result.stdout)
                        if channel_match:
                            video_channel = channel_match.group(1)
                        
                        # Thumbnail
                        video_thumbnail = f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"
                        
                        logger.info(f"✅ Video encontrado: {video_title}")
                    else:
                        await status_msg.edit_text("❌ No se encontró ningún video")
                        return
                else:
                    await status_msg.edit_text("❌ Error buscando en YouTube")
                    return
            
            if not video_url:
                await status_msg.edit_text("❌ No se pudo obtener la URL del video")
                return
            
            # ==========================================
            # MOSTRAR INFORMACIÓN DEL VIDEO
            # ==========================================
            media_type = 'VIDEO' if is_video else 'AUDIO'
            
            caption_info = f"""╭━━━〔 🎵 YOUTUBE {media_type} 〕━━━⬣
┃ 📌 <b>Título:</b> {video_title or 'Desconocido'}
┃ 👤 <b>Canal:</b> {video_channel or 'Desconocido'}
┃ 🔗 <b>Link:</b> {video_url[:50]}...
╰━━━━━━━━━━━━━━━━⬣"""
            
            # Enviar thumbnail con info
            if video_thumbnail:
                try:
                    await message.reply_photo(
                        photo=video_thumbnail,
                        caption=caption_info,
                        parse_mode=enums.ParseMode.HTML
                    )
                except:
                    await status_msg.edit_text(caption_info, parse_mode=enums.ParseMode.HTML)
            else:
                await status_msg.edit_text(caption_info, parse_mode=enums.ParseMode.HTML)
            
            # Reaccionar de forma segura
            await safe_react(message, "⚡")
            
            # ==========================================
            # DESCARGAR PRIORIZANDO LOADER.TO
            # ==========================================
            media_format = '720' if is_video else 'mp3'
            logger.info(f"📥 Solicitando {media_format} a loader.to...")
            try:
                download_url, loader_title = await loader_download_url(video_url, media_format)
                if loader_title and not video_title:
                    video_title = loader_title
                logger.info(f"✅ loader.to devolvió una URL de descarga")
            except LoaderToError as error:
                raise Exception(f"loader.to no pudo procesar el video: {error}") from error
            
            # ==========================================
            # LÓGICA DE ENVÍO
            # ==========================================
            
            if is_video:
                # ========== ENVIAR COMO VIDEO ==========
                logger.info("📹 Descargando y enviando video...")
                tmp_video = download_dir / f"yt_{message.from_user.id}_{message.id}.mp4"
                
                tmp_thumb = download_dir / f"yt_{message.from_user.id}_{message.id}_thumb.jpg"
                try:
                    dl_cmd = f'curl -sS -L --fail -o "{tmp_video}" "{download_url}"'
                    result = subprocess.run(dl_cmd, shell=True, timeout=180)
                    if result.returncode != 0 or not tmp_video.exists() or tmp_video.stat().st_size < 10_000:
                        raise Exception("Error descargando video")

                    duration, thumb = VideoProcessor.get_video_meta(tmp_video, tmp_thumb)
                    await message.reply_video(
                        video=str(tmp_video),
                        caption=f"🎬 <b>{video_title}</b>",
                        parse_mode=enums.ParseMode.HTML,
                        supports_streaming=True,
                        duration=duration or None,
                        thumb=thumb,
                    )
                finally:
                    tmp_video.unlink(missing_ok=True)
                    tmp_thumb.unlink(missing_ok=True)
                
            elif is_voice_note:
                # ========== ENVIAR COMO NOTA DE VOZ ==========
                logger.info("🎤 Convirtiendo a nota de voz...")
                tmp_mp3 = download_dir / f"tmp_{message.from_user.id}_{message.id}.mp3"
                tmp_ogg = download_dir / f"tmp_{message.from_user.id}_{message.id}.ogg"
                
                try:
                    dl_cmd = f'curl -s -L -o "{tmp_mp3}" "{download_url}"'
                    subprocess.run(dl_cmd, shell=True, timeout=120)
                    
                    convert_cmd = [
                        'ffmpeg', '-i', str(tmp_mp3),
                        '-c:a', 'libopus', '-b:a', '48k',
                        '-vbr', 'on', '-compression_level', '10',
                        '-application', 'voip', '-y', str(tmp_ogg)
                    ]
                    subprocess.run(convert_cmd, capture_output=True, timeout=60)
                    
                    if not tmp_ogg.exists():
                        raise Exception("Error convirtiendo a nota de voz")
                    
                    await message.reply_voice(voice=str(tmp_ogg))
                finally:
                    tmp_mp3.unlink(missing_ok=True)
                    tmp_ogg.unlink(missing_ok=True)
                    
            else:
                # ========== ENVIAR COMO AUDIO NORMAL ==========
                logger.info("🎵 Descargando y enviando audio...")
                tmp_audio = download_dir / f"yt_{message.from_user.id}_{message.id}.mp3"
                
                try:
                    dl_cmd = f'curl -s -L -o "{tmp_audio}" "{download_url}"'
                    subprocess.run(dl_cmd, shell=True, timeout=120)
                    
                    await message.reply_audio(
                        audio=str(tmp_audio),
                        title=video_title or 'Audio de YouTube',
                        performer=video_channel or 'YouTube'
                    )
                finally:
                    tmp_audio.unlink(missing_ok=True)
            
            # Reaccionar con éxito
            await safe_react(message, "👍")
            
        except subprocess.TimeoutExpired:
            logger.error("⏱️ Timeout en la operación")
            await safe_react(message, "👎")
            await message.reply_text("⏱️ La operación tardó demasiado. Intenta con un video más corto.")
            
        except Exception as e:
            logger.error(f"❌ Error: {e}", exc_info=True)
            await safe_react(message, "👎")
            await message.reply_text(f"❌ <b>Error:</b> {str(e)}", parse_mode=enums.ParseMode.HTML)
        
