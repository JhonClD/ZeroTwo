"""
twitter_handler.py - Manejador de descargas de Twitter/X
Usa API de Tweeload
"""

import json
import logging
import subprocess
import re
from pyrogram import filters, enums
from pyrogram.types import Message

logger = logging.getLogger(__name__)


def register(app, download_dir):
    """Registra el handler de Twitter/X"""
    
    @app.on_message(filters.command(["x", "twitter", "xdl", "dlx", "twdl", "twt", "twitterdl"]))
    async def twitter_command(client, message: Message):
        """Comando para descargar videos/imágenes de Twitter/X"""
        
        # Obtener URL
        args = message.text.split(maxsplit=1)
        
        if len(args) < 2:
            await message.reply_text(
                "🐦 <b>Twitter/X Downloader</b>\n\n"
                "Ingresa un enlace de Twitter/X.\n\n"
                "<b>Ejemplo:</b>\n"
                "<code>/x https://x.com/username/status/123456789</code>",
                parse_mode=enums.ParseMode.HTML
            )
            return
        
        twitter_url = args[1].strip()
        
        logger.info(f"🐦 Twitter/X - URL: {twitter_url[:60]}...")
        
        status_msg = await message.reply_text("⏳ Descargando de Twitter/X...")
        
        try:
            # Extraer ID del tweet
            id_match = re.search(r'/([\d]+)', twitter_url)
            
            if not id_match:
                raise Exception("❌ URL inválida. Usa el formato: https://x.com/user/status/123456789")
            
            tweet_id = id_match.group(1)
            logger.info(f"📋 Tweet ID: {tweet_id}")
            
            # Obtener authorization token
            logger.info("🔑 Obteniendo token de autorización...")
            auth_cmd = 'curl -s "https://pastebin.com/raw/SnCfd4ru"'
            auth_result = subprocess.run(auth_cmd, shell=True, capture_output=True, text=True, timeout=10)
            
            if auth_result.returncode != 0:
                raise Exception("Error obteniendo token de autorización")
            
            authorization = auth_result.stdout.strip()
            
            # Llamar a la API de Tweeload
            api_url = f"https://info.tweeload.site/status/{tweet_id}.json"
            
            logger.info("📥 Llamando a API Tweeload...")
            
            api_cmd = f'''curl -s -H "Authorization: {authorization}" -H "user-agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_3) AppleWebKit/537.36" "{api_url}"'''
            
            api_result = subprocess.run(api_cmd, shell=True, capture_output=True, text=True, timeout=30)
            
            if api_result.returncode != 0:
                raise Exception("Error llamando a la API de Twitter")
            
            # Parsear respuesta
            api_data = json.loads(api_result.stdout)
            
            if api_data.get('code') != 200:
                raise Exception("El tweet no está disponible o es privado")
            
            # Extraer información del tweet
            tweet = api_data.get('tweet', {})
            author = tweet.get('author', {})
            media = tweet.get('media', {})
            
            author_username = author.get('screen_name', 'unknown')
            tweet_text = tweet.get('text', '')
            
            caption = f"🐦 <b>@{author_username}</b>\n\n{tweet_text}"
            
            logger.info(f"✅ Tweet de @{author_username} obtenido")
            
            # Determinar tipo de media
            if media.get('videos'):
                # Es video
                logger.info("📹 Media: Video")
                videos = media['videos']
                
                for video_data in videos:
                    video_urls = video_data.get('video_urls', [])
                    
                    if not video_urls:
                        continue
                    
                    # Obtener la mejor calidad (mayor bitrate)
                    best_video = max(video_urls, key=lambda x: x.get('bitrate', 0))
                    video_url = best_video.get('url')
                    
                    if not video_url:
                        continue
                    
                    logger.info("📹 Descargando y enviando video...")
                    
                    tmp_video = download_dir / f"tw_{message.from_user.id}.mp4"
                    
                    tmp_thumb = download_dir / f"tw_{message.from_user.id}_thumb.jpg"
                    try:
                        # Descargar video
                        dl_cmd = f'curl -s -L -o "{tmp_video}" "{video_url}"'
                        subprocess.run(dl_cmd, shell=True, timeout=120)

                        if not tmp_video.exists():
                            raise Exception("Error descargando video")

                        # Obtener duración con ffprobe
                        duration = 0
                        try:
                            probe = subprocess.run(
                                ['ffprobe', '-v', 'error',
                                 '-show_entries', 'format=duration',
                                 '-of', 'default=noprint_wrappers=1:nokey=1',
                                 str(tmp_video)],
                                capture_output=True, text=True, timeout=10
                            )
                            duration = int(float(probe.stdout.strip()))
                        except Exception:
                            pass

                        # Extraer miniatura del frame central
                        thumb_path = None
                        try:
                            mid = max(1, duration // 2)
                            subprocess.run(
                                ['ffmpeg', '-y', '-ss', str(mid),
                                 '-i', str(tmp_video),
                                 '-vframes', '1', '-q:v', '2',
                                 str(tmp_thumb)],
                                capture_output=True, timeout=15
                            )
                            if tmp_thumb.exists():
                                thumb_path = str(tmp_thumb)
                        except Exception:
                            pass

                        await message.reply_video(
                            video=str(tmp_video),
                            caption=caption,
                            parse_mode=enums.ParseMode.HTML,
                            supports_streaming=True,
                            duration=duration,
                            thumb=thumb_path,
                        )

                        logger.info("✅ Video enviado")

                    finally:
                        tmp_video.unlink(missing_ok=True)
                        tmp_thumb.unlink(missing_ok=True)
                
                await status_msg.delete()
                logger.info("✅ Video de Twitter enviado exitosamente")
                
            elif media.get('photos'):
                # Son fotos
                logger.info("🖼️ Media: Fotos")
                photos = media['photos']
                
                for photo in photos:
                    photo_url = photo.get('url')
                    
                    if not photo_url:
                        continue
                    
                    logger.info("🖼️ Enviando foto...")
                    
                    await message.reply_photo(
                        photo=photo_url,
                        caption=caption,
                        parse_mode=enums.ParseMode.HTML
                    )
                
                await status_msg.delete()
                logger.info("✅ Fotos de Twitter enviadas exitosamente")
                
            else:
                raise Exception("El tweet no contiene videos ni imágenes")
            
        except subprocess.TimeoutExpired:
            logger.error("⏱️ Timeout en descarga de Twitter")
            await status_msg.edit_text("⏱️ La operación tardó demasiado. Intenta de nuevo.")
            
        except json.JSONDecodeError:
            logger.error("❌ Error parseando respuesta JSON")
            await status_msg.edit_text("❌ Error procesando la respuesta de Twitter")
            
        except Exception as e:
            logger.error(f"❌ Error: {e}", exc_info=True)
            await status_msg.edit_text(f"❌ <b>Error:</b> {str(e)}", parse_mode=enums.ParseMode.HTML)
