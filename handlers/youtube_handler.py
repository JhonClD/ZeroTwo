"""Manejador de YouTube: búsqueda por requests y descarga mediante Loader.to."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import subprocess
from html import escape
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests
from pyrogram import enums, filters
from pyrogram.types import Message

from utils import VideoProcessor
from utils.loader_to import LoaderToError, download_url as loader_download_url
from utils.media_download import MediaDownloadError, download_file

logger = logging.getLogger(__name__)

_YOUTUBE_HOSTS = {
    "youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com",
    "youtu.be", "www.youtu.be",
}
_YOUTUBE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-419,es;q=0.9,en;q=0.7",
}


def _video_id(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.hostname in {"youtu.be", "www.youtu.be"}:
        candidate = parsed.path.strip("/").split("/", 1)[0]
    else:
        candidate = parse_qs(parsed.query).get("v", [None])[0]
        if not candidate and parsed.path.startswith("/shorts/"):
            candidate = parsed.path.split("/", 2)[2].split("/", 1)[0]
    return candidate if candidate and re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate) else None


def _extract_balanced_json(page: str) -> dict | None:
    """Extrae ytInitialData respetando llaves dentro de strings JSON."""
    markers = ("var ytInitialData =", "let ytInitialData =", 'window["ytInitialData"] =')
    for marker in markers:
        marker_pos = page.find(marker)
        if marker_pos < 0:
            continue
        start = page.find("{", marker_pos + len(marker))
        if start < 0:
            continue
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(page)):
            char = page[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    try:
                        value = json.loads(page[start:index + 1])
                    except ValueError:
                        break
                    return value if isinstance(value, dict) else None
    return None


def _iter_video_renderers(value):
    if isinstance(value, dict):
        renderer = value.get("videoRenderer")
        if isinstance(renderer, dict):
            yield renderer
        for child in value.values():
            yield from _iter_video_renderers(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_video_renderers(child)


def _text_value(value) -> str:
    if not isinstance(value, dict):
        return ""
    if isinstance(value.get("simpleText"), str):
        return value["simpleText"].strip()
    runs = value.get("runs")
    if isinstance(runs, list):
        return "".join(str(run.get("text", "")) for run in runs if isinstance(run, dict)).strip()
    return ""


def _oembed_info(video_url: str) -> dict:
    """Obtiene título/canal/miniatura sin API key; si falla, conserva la URL."""
    info = {
        "url": video_url,
        "title": "Video de YouTube",
        "channel": "YouTube",
        "thumbnail": None,
    }
    video_id = _video_id(video_url)
    if video_id:
        info["thumbnail"] = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
    try:
        response = requests.get(
            "https://www.youtube.com/oembed",
            params={"url": video_url, "format": "json"},
            headers=_YOUTUBE_HEADERS,
            timeout=(8, 15),
        )
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict):
            info["title"] = str(data.get("title") or info["title"])
            info["channel"] = str(data.get("author_name") or info["channel"])
            info["thumbnail"] = data.get("thumbnail_url") or info["thumbnail"]
    except (requests.RequestException, ValueError) as error:
        logger.info("No se pudieron consultar metadatos oEmbed de YouTube: %s", error)
    return info


def _resolve_video(query: str) -> dict:
    """Resuelve una URL o busca el primer video público en YouTube."""
    parsed = urlparse(query)
    if parsed.scheme.lower() in {"http", "https"}:
        if (parsed.hostname or "").lower() not in _YOUTUBE_HOSTS:
            raise LoaderToError("El enlace debe pertenecer a YouTube o youtu.be.")
        return _oembed_info(query)

    try:
        response = requests.get(
            "https://www.youtube.com/results",
            params={"search_query": query},
            headers=_YOUTUBE_HEADERS,
            timeout=(10, 20),
        )
        response.raise_for_status()
        page = response.text
    except requests.RequestException as error:
        raise LoaderToError(
            "No se pudo buscar en YouTube desde el hosting. Prueba enviando el enlace directo del video."
        ) from error

    initial_data = _extract_balanced_json(page)
    renderer = next(_iter_video_renderers(initial_data), None) if initial_data else None
    video_id = renderer.get("videoId") if renderer else None
    if not video_id:
        match = re.search(r'"videoId"\s*:\s*"([A-Za-z0-9_-]{11})"', page)
        video_id = match.group(1) if match else None

    if not video_id or not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise LoaderToError(
            "YouTube no devolvió resultados de búsqueda. Intenta con otra consulta o pega la URL del video."
        )

    video_url = f"https://www.youtube.com/watch?v={video_id}"
    result = {
        "url": video_url,
        "title": _text_value(renderer.get("title")) if renderer else "",
        "channel": "",
        "thumbnail": None,
    }
    if renderer:
        result["channel"] = (
            _text_value(renderer.get("ownerText"))
            or _text_value(renderer.get("longBylineText"))
            or _text_value(renderer.get("shortBylineText"))
        )
        thumbnails = renderer.get("thumbnail", {}).get("thumbnails", [])
        if thumbnails and isinstance(thumbnails[-1], dict):
            result["thumbnail"] = thumbnails[-1].get("url")
    fallback_info = _oembed_info(video_url)
    result["title"] = result["title"] or fallback_info["title"]
    result["channel"] = result["channel"] or fallback_info["channel"]
    result["thumbnail"] = result["thumbnail"] or fallback_info["thumbnail"]
    return result


def _validate_audio_file(audio_path: Path) -> None:
    """Rechaza páginas HTML, archivos parciales y audio no reproducible."""
    if not audio_path.exists() or audio_path.stat().st_size < 1024:
        raise MediaDownloadError("Loader.to no produjo un archivo de audio válido.")
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
        raise MediaDownloadError(
            "Loader.to devolvió un archivo sin una pista de audio reproducible."
        )


def _convert_to_voice_note(source: Path, destination: Path) -> None:
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


def _prepare_audio_thumbnail(thumbnail_url: str, destination: Path) -> bool:
    """Descarga y normaliza una miniatura de YouTube para adjuntarla al MP3."""
    parsed = urlparse(thumbnail_url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme.lower() != "https" or not (
        host == "ytimg.com" or host.endswith(".ytimg.com")
        or host == "youtube.com" or host.endswith(".youtube.com")
    ):
        return False

    source_path = destination.with_name(f"{destination.stem}_source")
    response = None
    try:
        response = requests.get(
            thumbnail_url,
            headers=_YOUTUBE_HEADERS,
            stream=True,
            timeout=(8, 15),
        )
        response.raise_for_status()
        content_type = str(response.headers.get("Content-Type", "")).lower()
        if not content_type.startswith("image/"):
            return False

        size = 0
        with source_path.open("wb") as source_file:
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                size += len(chunk)
                if size > 5 * 1024 * 1024:
                    raise ValueError("La miniatura supera el límite de tamaño.")
                source_file.write(chunk)
        if size < 256:
            return False

        destination.parent.mkdir(parents=True, exist_ok=True)
        for quality in (5, 8):
            result = subprocess.run(
                [
                    "ffmpeg", "-v", "error", "-i", str(source_path),
                    "-vf", "scale=320:320:force_original_aspect_ratio=decrease,pad=320:320:(ow-iw)/2:(oh-ih)/2",
                    "-frames:v", "1", "-q:v", str(quality), "-y", str(destination),
                ],
                capture_output=True,
                timeout=30,
            )
            if result.returncode == 0 and destination.exists():
                output_size = destination.stat().st_size
                if 1024 <= output_size <= 200 * 1024:
                    return True
        destination.unlink(missing_ok=True)
        return False
    except (requests.RequestException, OSError, ValueError, subprocess.TimeoutExpired) as error:
        logger.info("No se pudo preparar la miniatura del audio: %s", error)
        destination.unlink(missing_ok=True)
        return False
    finally:
        if response is not None:
            response.close()
        source_path.unlink(missing_ok=True)


async def safe_react(message: Message, emoji: str) -> None:
    try:
        await message.react(emoji)
    except Exception:
        logger.warning("No se pudo reaccionar con %s", emoji)


def register(app, download_dir: Path) -> None:
    @app.on_message(filters.command(["play", "play2", "ytmp3", "ytmp4", "playaudio"]))
    async def youtube_command(client, message: Message) -> None:
        args = (message.text or "").split(maxsplit=1)
        command = (message.command[0] if message.command else "play").lower()
        if len(args) < 2:
            await message.reply_text(
                "🎵 <b>YouTube Downloader</b>\n\n"
                "Escribe el nombre o la URL de un video público de YouTube:\n\n"
                "/play &lt;búsqueda&gt; — Audio MP3 mediante Loader.to\n"
                "/play2 &lt;búsqueda&gt; — Video hasta 720p\n"
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
        status_msg = await message.reply_text("🔎 Buscando video en YouTube…")
        chat_id = message.chat.id if message.chat else 0
        output_base = Path(download_dir) / f"yt_{chat_id}_{message.id}"
        extension = ".mp4" if is_video else ".mp3"
        media_path = Path(f"{output_base}{extension}")
        thumbnail_path = Path(f"{output_base}_thumb.jpg")
        voice_path = Path(f"{output_base}_voice.ogg")

        try:
            info = await asyncio.to_thread(_resolve_video, query)
            video_url = info["url"]
            title = str(info.get("title") or "Video de YouTube")
            channel = str(info.get("channel") or "YouTube")
            media_format = "720" if is_video else "mp3"
            logger.info(
                "🎵 YouTube seleccionado: %s | canal: %s",
                title.replace("\n", " ")[:160],
                channel.replace("\n", " ")[:100],
            )
            logger.info("📥 Solicitando %s a Loader.to", "video 720p" if is_video else "audio MP3")
            caption_info = (
                f"╭━━━〔 🎵 YOUTUBE {'VIDEO' if is_video else 'AUDIO'} 〕━━━⬣\n"
                f"┃ 📌 <b>Título:</b> {escape(title[:300])}\n"
                f"┃ 👤 <b>Canal:</b> {escape(channel[:150])}\n"
                f"┃ 🔗 <a href=\"{escape(video_url, quote=True)}\">Ver en YouTube</a>\n"
                "╰━━━━━━━━━━━━━━━━⬣"
            )
            if info.get("thumbnail"):
                try:
                    await message.reply_photo(
                        photo=info["thumbnail"],
                        caption=caption_info,
                        parse_mode=enums.ParseMode.HTML,
                    )
                except Exception as error:
                    logger.info("No se pudo enviar la miniatura de YouTube: %s", error)
                    try:
                        await message.reply_text(caption_info, parse_mode=enums.ParseMode.HTML)
                    except Exception:
                        logger.info("No se pudo enviar la tarjeta de información de YouTube")
            else:
                try:
                    await message.reply_text(caption_info, parse_mode=enums.ParseMode.HTML)
                except Exception:
                    logger.info("No se pudo enviar la tarjeta de información de YouTube")

            await status_msg.edit_text("⬇️ Descargando con Loader.to…")
            direct_url, loader_title = await loader_download_url(video_url, media_format)
            title = loader_title or title
            await safe_react(message, "⚡")
            timeout = (20, 180) if is_video else (15, 120)
            await asyncio.to_thread(download_file, direct_url, media_path, timeout)

            if is_video:
                duration, thumb = await asyncio.to_thread(
                    VideoProcessor.get_video_meta,
                    media_path,
                    thumbnail_path,
                )
                if not duration:
                    raise MediaDownloadError(
                        "Loader.to terminó la descarga, pero FFprobe no reconoció un video válido."
                    )
                await message.reply_video(
                    video=str(media_path),
                    caption=f"🎬 <b>{escape(title[:300])}</b>",
                    parse_mode=enums.ParseMode.HTML,
                    supports_streaming=True,
                    duration=duration,
                    thumb=thumb,
                )
            elif is_voice_note:
                await asyncio.to_thread(_validate_audio_file, media_path)
                await asyncio.to_thread(_convert_to_voice_note, media_path, voice_path)
                await message.reply_voice(voice=str(voice_path))
            else:
                await asyncio.to_thread(_validate_audio_file, media_path)
                has_thumbnail = False
                if info.get("thumbnail"):
                    has_thumbnail = await asyncio.to_thread(
                        _prepare_audio_thumbnail,
                        info["thumbnail"],
                        thumbnail_path,
                    )
                await message.reply_audio(
                    audio=str(media_path),
                    title=title[:64] or "Audio de YouTube",
                    performer=channel[:64] or "YouTube",
                    thumb=str(thumbnail_path) if has_thumbnail else None,
                )
            await safe_react(message, "👍")
        except subprocess.TimeoutExpired:
            logger.error("Timeout durante la descarga/procesamiento de YouTube")
            await safe_react(message, "👎")
            await message.reply_text("⏱️ La operación tardó demasiado. Prueba un video más corto o una URL directa.")
        except (LoaderToError, MediaDownloadError) as error:
            logger.warning("Descarga de YouTube con Loader.to fallida: %s", error)
            await safe_react(message, "👎")
            await message.reply_text(
                f"❌ <b>Error de descarga:</b> {escape(str(error)[:700])}",
                parse_mode=enums.ParseMode.HTML,
            )
        except Exception as error:
            logger.error("Error en descarga de YouTube con Loader.to: %s", error, exc_info=True)
            await safe_react(message, "👎")
            await message.reply_text(
                f"❌ <b>Error:</b> {escape(str(error)[:700])}",
                parse_mode=enums.ParseMode.HTML,
            )
        finally:
            media_path.unlink(missing_ok=True)
            thumbnail_path.unlink(missing_ok=True)
            voice_path.unlink(missing_ok=True)
            try:
                await status_msg.delete()
            except Exception:
                pass
