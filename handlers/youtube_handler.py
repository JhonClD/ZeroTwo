"""Manejador de descargas de YouTube con yt-dlp."""
from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from html import escape
from pathlib import Path

from pyrogram import enums, filters
from pyrogram.types import Message

from downloaders.youtube_downloader import YouTubeDownloadError, YouTubeDownloader
from utils import VideoProcessor
from utils.media_download import MediaDownloadError

logger = logging.getLogger(__name__)


def _validate_audio_file(audio_path: Path) -> None:
    """Rechaza respuestas HTML, archivos incompletos y medios sin audio."""
    if not audio_path.exists() or audio_path.stat().st_size < 1024:
        raise MediaDownloadError("yt-dlp no produjo un archivo de audio válido.")

    probe = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "a:0",
            "-show_entries", "stream=codec_name", "-show_entries", "format=duration",
            "-of", "json", str(audio_path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    try:
        metadata = json.loads(probe.stdout) if probe.returncode == 0 else {}
        duration = float(metadata.get("format", {}).get("duration", 0))
        has_audio = bool(metadata.get("streams"))
    except (ValueError, TypeError, AttributeError):
        duration, has_audio = 0, False
    if not has_audio or duration <= 0:
        raise MediaDownloadError("El archivo descargado no contiene una pista de audio reproducible.")


def _convert_to_voice_note(source: Path, destination: Path) -> None:
    """Convierte un MP3 a OGG/Opus para enviarlo como nota de voz."""
    result = subprocess.run(
        [
            "ffmpeg", "-v", "error", "-i", str(source), "-vn",
            "-c:a", "libopus", "-b:a", "48k", "-vbr", "on",
            "-compression_level", "10", "-application", "voip",
            "-y", str(destination),
        ],
        capture_output=True,
        timeout=60,
    )
    if result.returncode != 0 or not destination.exists() or destination.stat().st_size < 1024:
        detail = result.stderr.decode(errors="replace")[-300:]
        raise RuntimeError(f"No se pudo convertir el audio a nota de voz. {detail}")


async def safe_react(message: Message, emoji: str) -> None:
    """Envía una reacción sin interrumpir la descarga si Telegram la rechaza."""
    try:
        await message.react(emoji)
    except Exception:
        logger.warning("No se pudo reaccionar con %s", emoji)


def register(app, download_dir: Path) -> None:
    """Registra los comandos de descarga de YouTube."""

    @app.on_message(filters.command(["play", "play2", "ytmp3", "ytmp4", "playaudio"]))
    async def youtube_command(client, message: Message) -> None:
        args = (message.text or "").split(maxsplit=1)
        command = (message.command[0] if message.command else "play").lower()
        if len(args) < 2:
            await message.reply_text(
                "🎵 <b>YouTube Downloader</b>\n\n"
                "Escribe el nombre o la URL de un video público de YouTube:\n\n"
                "/play &lt;búsqueda&gt; — Descargar audio MP3\n"
                "/play2 &lt;búsqueda&gt; — Descargar video hasta 720p\n"
                "/playaudio &lt;búsqueda&gt; — Enviar como nota de voz\n"
                "/ytmp3 &lt;URL&gt; — Descargar audio\n"
                "/ytmp4 &lt;URL&gt; — Descargar video\n\n"
                "Ejemplo: <code>/play Linkin Park Numb</code>",
                parse_mode=enums.ParseMode.HTML,
            )
            return

        query = args[1].strip()
        is_video = command in {"play2", "ytmp4"}
        is_voice_note = command == "playaudio"
        logger.info("YouTube | consulta=%s | comando=%s", query[:80], command)

        status_msg = await message.reply_text("🔎 Buscando y descargando con yt-dlp…")
        chat_id = message.chat.id if message.chat else 0
        output_base = Path(download_dir) / f"yt_{chat_id}_{message.id}"
        thumbnail_path = Path(f"{output_base}_thumb.jpg")
        voice_path = Path(f"{output_base}_voice.ogg")
        success = False

        try:
            downloaded = await asyncio.to_thread(
                YouTubeDownloader.download,
                query,
                output_base,
                is_video,
            )
            title = downloaded.title[:300]
            channel = downloaded.channel[:150]
            media_type = "VIDEO" if is_video else "AUDIO"
            caption_info = (
                f"╭━━━〔 🎵 YOUTUBE {media_type} 〕━━━⬣\n"
                f"┃ 📌 <b>Título:</b> {escape(title)}\n"
                f"┃ 👤 <b>Canal:</b> {escape(channel)}\n"
                f"┃ 🔗 <a href=\"{escape(downloaded.url, quote=True)}\">Ver en YouTube</a>\n"
                "╰━━━━━━━━━━━━━━━━⬣"
            )

            if downloaded.thumbnail:
                try:
                    await message.reply_photo(
                        photo=downloaded.thumbnail,
                        caption=caption_info,
                        parse_mode=enums.ParseMode.HTML,
                    )
                except Exception as error:
                    logger.info("No se pudo enviar la miniatura de YouTube: %s", error)
                    await status_msg.edit_text(caption_info, parse_mode=enums.ParseMode.HTML)
            else:
                await status_msg.edit_text(caption_info, parse_mode=enums.ParseMode.HTML)

            await safe_react(message, "⚡")

            if is_video:
                duration, thumb = await asyncio.to_thread(
                    VideoProcessor.get_video_meta,
                    downloaded.path,
                    thumbnail_path,
                )
                if not duration:
                    raise MediaDownloadError(
                        "yt-dlp terminó, pero FFprobe no pudo reconocer el video descargado."
                    )
                caption = f"🎬 <b>{escape(title)}</b>"
                if downloaded.path.suffix.lower() == ".mp4":
                    await message.reply_video(
                        video=str(downloaded.path),
                        caption=caption,
                        parse_mode=enums.ParseMode.HTML,
                        supports_streaming=True,
                        duration=duration,
                        thumb=thumb,
                    )
                else:
                    await message.reply_document(
                        document=str(downloaded.path),
                        caption=f"🎬 {escape(title)} (formato {downloaded.path.suffix.lower()})",
                        parse_mode=enums.ParseMode.HTML,
                        thumb=thumb,
                    )
            elif is_voice_note:
                await asyncio.to_thread(_validate_audio_file, downloaded.path)
                await asyncio.to_thread(_convert_to_voice_note, downloaded.path, voice_path)
                await message.reply_voice(voice=str(voice_path))
            else:
                await asyncio.to_thread(_validate_audio_file, downloaded.path)
                await message.reply_audio(
                    audio=str(downloaded.path),
                    title=title[:64] or "Audio de YouTube",
                    performer=channel[:64] or "YouTube",
                )

            await safe_react(message, "👍")
            success = True
        except subprocess.TimeoutExpired:
            logger.error("Timeout durante la descarga/procesamiento de YouTube")
            await safe_react(message, "👎")
            await message.reply_text("⏱️ La operación tardó demasiado. Intenta con un video más corto.")
        except (YouTubeDownloadError, MediaDownloadError) as error:
            logger.warning("Descarga de YouTube fallida: %s", error)
            await safe_react(message, "👎")
            await message.reply_text(
                f"❌ <b>Error de YouTube:</b> {escape(str(error)[:700])}",
                parse_mode=enums.ParseMode.HTML,
            )
        except Exception as error:
            logger.error("Error en la descarga de YouTube: %s", error, exc_info=True)
            await safe_react(message, "👎")
            await message.reply_text(
                f"❌ <b>Error:</b> {escape(str(error)[:700])}",
                parse_mode=enums.ParseMode.HTML,
            )
        finally:
            YouTubeDownloader.cleanup(output_base)
            thumbnail_path.unlink(missing_ok=True)
            voice_path.unlink(missing_ok=True)
            if success:
                try:
                    await status_msg.delete()
                except Exception:
                    pass
