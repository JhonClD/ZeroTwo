"""
facebook_handler.py - Manejador de descargas de Facebook
Usa múltiples APIs con sistema de fallback
"""

import asyncio
import json
import logging
import subprocess
import re
from pathlib import Path
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup
from pyrogram import filters, enums
from pyrogram.types import Message
from utils import VideoProcessor

logger = logging.getLogger(__name__)


PUBLIC_FB_APIS = (
    "https://eliasar-yt-api.vercel.app/api/facebookdl?link={url}",
    "https://api.vreden.my.id/api/facebook?url={url}",
)


def _scrape_facebook_page(fb_link):
    """Extrae video y título desde metadatos públicos de una página de Facebook."""
    response = requests.get(
        fb_link,
        headers={"User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36"},
        timeout=25,
        allow_redirects=True,
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    video_url = None
    for prop in ("og:video", "og:video:url", "og:video:secure_url"):
        tag = soup.find("meta", property=prop)
        if tag and tag.get("content", "").startswith("http"):
            video_url = tag["content"]
            break
    title_tag = soup.find("meta", property="og:title")
    title = title_tag.get("content") if title_tag else None
    return video_url, title


def _extract_public_api_url(api_data):
    """Busca recursivamente una URL de video en respuestas públicas variables."""
    if isinstance(api_data, dict):
        for key in ("url", "download", "hd", "sd", "video"):
            value = api_data.get(key)
            if isinstance(value, dict):
                found = _extract_public_api_url(value)
                if found:
                    return found, api_data.get("title") or api_data.get("name")
            elif isinstance(value, str) and value.startswith("http"):
                return value, api_data.get("title") or api_data.get("name")
        for value in api_data.values():
            found = _extract_public_api_url(value)
            if found:
                return found
    elif isinstance(api_data, list):
        for value in api_data:
            found = _extract_public_api_url(value)
            if found:
                return found
    return None, None


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

            # Primera opción: scraping de metadatos públicos de Facebook.
            try:
                logger.info("🔎 Scrapeando metadatos públicos de Facebook...")
                video_url, video_title = await asyncio.to_thread(_scrape_facebook_page, fb_link)
                if video_url:
                    logger.info("✅ Video encontrado mediante scraping")
            except requests.RequestException as error:
                logger.warning(f"⚠️ Scraping de Facebook falló: {error}")

            # APIs públicas de respaldo.
            if not video_url:
                encoded_url = quote(fb_link, safe="")
                for i, api_template in enumerate(PUBLIC_FB_APIS, 1):
                    try:
                        api = api_template.format(url=encoded_url)
                        logger.info(f"🔄 Intentando API pública #{i}...")
                        result = requests.get(
                            api,
                            headers={"User-Agent": "ZeroTwoBot/1.0"},
                            timeout=30,
                        )
                        result.raise_for_status()
                        video_url, video_title = _extract_public_api_url(result.json())
                        if video_url:
                            logger.info(f"✅ API pública #{i} exitosa")
                            break
                    except (requests.RequestException, ValueError, json.JSONDecodeError) as error:
                        logger.warning(f"⚠️ API pública #{i} falló: {error}")

            if not video_url:
                raise Exception("No se pudo extraer el video mediante scraping ni APIs públicas.")
            
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
