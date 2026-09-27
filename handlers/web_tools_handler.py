"""Herramientas web migradas desde get-http.js y ssweb.js."""
from __future__ import annotations

import asyncio
import html
import mimetypes
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests
from pyrogram import enums, filters
from pyrogram.types import Message

MAX_BUFFER = 200 * 1024 * 1024


def _valid_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _filename(url: str, content_type: str) -> str:
    name = unquote(Path(urlparse(url).path).name) or "archivo"
    if "." not in name:
        name += mimetypes.guess_extension(content_type.split(";", 1)[0]) or ".bin"
    return re.sub(r'[\\/:*?"<>|]+', "_", name)[:180]


def register(app, download_dir):
    @app.on_message(filters.command(["get", "fetch"]))
    async def get_url(client, message: Message):
        args = message.text.split(maxsplit=1)
        if len(args) < 2 or not _valid_url(args[1].strip()):
            await message.reply_text("Uso: <code>/get https://sitio.com/archivo</code>", parse_mode=enums.ParseMode.HTML)
            return
        url = args[1].strip()
        status = await message.reply_text("📥 Descargando recurso…")
        path = None
        try:
            def download():
                response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=45, stream=True)
                response.raise_for_status()
                content_type = response.headers.get("content-type", "application/octet-stream")
                filename = _filename(url, content_type)
                target = download_dir / f"web_{message.from_user.id}_{message.id}_{filename}"
                total = 0
                with target.open("wb") as output:
                    for chunk in response.iter_content(1024 * 1024):
                        total += len(chunk)
                        if total > MAX_BUFFER:
                            raise ValueError("El archivo supera el límite de 200 MB")
                        output.write(chunk)
                return target, content_type
            path, content_type = await asyncio.to_thread(download)
            await status.edit_text(f"✅ <b>Recurso descargado</b>\n📄 {html.escape(path.name)}", parse_mode=enums.ParseMode.HTML)
            if content_type.startswith("image/"):
                await message.reply_photo(str(path), caption=path.name)
            elif content_type.startswith("video/"):
                await message.reply_video(str(path), caption=path.name, supports_streaming=True)
            elif content_type.startswith("audio/"):
                await message.reply_audio(str(path), caption=path.name)
            else:
                await message.reply_document(str(path), caption=path.name)
            await status.delete()
        except Exception as error:
            await status.edit_text(f"❌ Error: {html.escape(str(error)[:300])}", parse_mode=enums.ParseMode.HTML)
        finally:
            if path:
                path.unlink(missing_ok=True)

    @app.on_message(filters.command(["ss", "ssweb"]))
    async def screenshot(client, message: Message):
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            await message.reply_text("Uso: <code>/ss https://sitio.com</code>", parse_mode=enums.ParseMode.HTML)
            return
        url = args[1].strip()
        if not _valid_url(url):
            await message.reply_text("❌ URL inválida.")
            return
        status = await message.reply_text("📸 Generando captura…")
        try:
            screenshot_url = f"https://image.thum.io/get/width/1200/noAnimate/fullpage/{url}"
            await message.reply_photo(screenshot_url, caption=f"📸 Captura de: {url}")
            await status.delete()
        except Exception as error:
            await status.edit_text(f"❌ No se pudo generar la captura: {html.escape(str(error)[:200])}", parse_mode=enums.ParseMode.HTML)
