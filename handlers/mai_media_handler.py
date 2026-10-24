"""Herramientas de anime adaptadas de mai.py al cliente y rutas de ZeroTwo."""

from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import shutil
import time
import uuid
from pathlib import Path

from pyrogram import enums, filters
from pyrogram.types import Message

from utils.mai_media import (
    EncodeOptions,
    ffmpeg_pass_one,
    ffmpeg_pass_two,
    parse_encode_options,
    safe_filename,
)

logger = logging.getLogger(__name__)
OWNER_ID = 7856571519


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        return max(minimum, min(maximum, int(os.getenv(name, str(default)))))
    except (TypeError, ValueError):
        logger.warning("Valor inválido en %s; se usará %s.", name, default)
        return default


def _bar(percent: float, width: int = 20) -> str:
    percent = max(0, min(100, percent))
    filled = round(width * percent / 100)
    return "[" + "█" * filled + "░" * (width - filled) + "]"


def _time_text(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


async def _run(command: list[str], *, cwd: Path, timeout: int) -> str:
    """Ejecuta un binario sin shell; incluye solo un fragmento acotado del error."""
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(cwd),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as error:
        raise RuntimeError(f"No se encontró {command[0]} en el hosting.") from error
    try:
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError as error:
        process.kill()
        await process.wait()
        raise RuntimeError("El proceso superó el tiempo límite configurado.") from error
    if process.returncode:
        detail = stderr.decode(errors="replace")[-900:].strip() if stderr else ""
        raise RuntimeError(detail or f"{command[0]} terminó con código {process.returncode}.")
    return ""


async def _probe(path: Path, timeout: int) -> dict:
    process = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=min(timeout, 180))
    except asyncio.TimeoutError as error:
        process.kill()
        await process.wait()
        raise RuntimeError("FFprobe tardó demasiado en analizar el video.") from error
    if process.returncode:
        raise RuntimeError(stderr.decode(errors="replace")[-500:] or "FFprobe no pudo leer el archivo.")
    try:
        return json.loads(stdout)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise RuntimeError("FFprobe devolvió metadatos inválidos.") from error


def _media_dimensions(metadata: dict) -> tuple[int, int, int]:
    streams = metadata.get("streams", [])
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
    try:
        duration = float(metadata.get("format", {}).get("duration") or video.get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0
    return int(duration), int(video.get("width") or 0), int(video.get("height") or 0)


async def _show_progress(status: Message, text: str) -> None:
    try:
        await status.edit_text(text[:3900], parse_mode=enums.ParseMode.HTML)
    except Exception:
        logger.debug("No se pudo actualizar la tarjeta de mai_media", exc_info=True)


def register(app, download_dir: Path | str) -> None:
    root = Path(download_dir) / "mai_tools"
    incoming = root / "anime"
    encoded = root / "encoded"
    jobs = root / "jobs"
    for directory in (incoming, encoded, jobs):
        directory.mkdir(parents=True, exist_ok=True)
    max_input_mb = _env_int("ZERO_TWO_MAI_MAX_MB", 1800, 20, 4096)
    timeout = _env_int("ZERO_TWO_MAI_TIMEOUT", 10800, 60, 21600)
    encode_lock = asyncio.Lock()

    def is_owner(message: Message) -> bool:
        return bool(message.from_user and message.from_user.id == OWNER_ID)

    async def deny(message: Message) -> bool:
        if is_owner(message):
            return False
        await message.reply_text("⛔ Solo el propietario puede usar estas herramientas.")
        return True

    def unique_destination(directory: Path, filename: str) -> Path:
        safe_name = safe_filename(filename)
        candidate = directory / safe_name
        if not candidate.exists() and not candidate.is_symlink():
            return candidate
        path = Path(safe_name)
        for suffix in range(1, 10000):
            candidate = directory / f"{path.stem}_{suffix}{path.suffix}"
            if not candidate.exists() and not candidate.is_symlink():
                return candidate
        raise RuntimeError("No se pudo crear un nombre de archivo único.")

    @app.on_message(filters.command("dw2"))
    async def download_replied_file(client, message: Message):
        if await deny(message):
            return
        source_message = message.reply_to_message
        media = None
        if source_message:
            media = source_message.document or source_message.video or source_message.audio
        if not source_message or not media:
            await message.reply_text("Responde a un documento, video o audio con /dw2.")
            return
        size = int(getattr(media, "file_size", 0) or 0)
        if size > max_input_mb * 1024 * 1024:
            await message.reply_text(f"El archivo supera el límite de {max_input_mb} MB.")
            return
        original_name = getattr(media, "file_name", None) or f"archivo_{getattr(media, 'file_unique_id', uuid.uuid4().hex)}"
        destination = unique_destination(incoming, original_name)
        status = await message.reply_text(f"📥 Preparando descarga: {html.escape(destination.name)}")
        user = message.from_user
        user_str = f"{user.first_name} ({user.id})" if user else "Desconocido"
        started = time.monotonic()
        last_update = [0.0]

        async def progress(current: int, total: int, *_):
            now = time.monotonic()
            if now - last_update[0] < 3 and current < total:
                return
            last_update[0] = now
            percent = current * 100 / total if total else 0
            elapsed = max(now - started, 0.1)
            speed = current / elapsed / (1024 * 1024)
            remaining = (total - current) / max(current / elapsed, 1) if total else 0
            await _show_progress(
                status,
                "┎〄 Descargando archivo\n"
                f"┠ 🗂 {html.escape(destination.name)}\n"
                f"┠ {_bar(percent)} {percent:.1f}%\n"
                f"┠ 💾 {current / 1048576:.2f} MB / {total / 1048576:.2f} MB\n"
                f"┠ ⚡ Velocidad: {speed:.2f} MB/s\n"
                f"┠ ⏳ Tiempo restante: {_time_text(remaining)}\n"
                f"┖〄 👤 Ejecutado por: {html.escape(user_str)}",
            )

        try:
            await source_message.download(
                file_name=str(destination), progress=progress,
            )
            if not destination.is_file() or destination.stat().st_size <= 0:
                raise RuntimeError("Telegram no entregó un archivo válido.")
            if destination.stat().st_size > max_input_mb * 1024 * 1024:
                raise RuntimeError(f"El archivo descargado supera {max_input_mb} MB.")
            await _show_progress(status, f"✅ Descargado en <code>{html.escape(str(destination))}</code>")
        except Exception as error:
            destination.unlink(missing_ok=True)
            await _show_progress(status, f"❌ No se pudo descargar: {html.escape(str(error)[:500])}")

    async def encode_files(message: Message, *, burn_subtitles: bool) -> None:
        if await deny(message):
            return
        text = message.text or message.caption or ""
        parts = text.split(maxsplit=1)
        try:
            options = parse_encode_options(parts[1] if len(parts) > 1 else "", burn_subtitles=burn_subtitles)
        except ValueError as error:
            suffix = " [-s índice]" if burn_subtitles else ""
            await message.reply_text(
                f"Opciones no válidas: {html.escape(str(error))}\n"
                f"Uso: /{'ed2' if burn_subtitles else 'ec2'}{suffix} [-a índice] [-vb 4800k] [-p superfast]"
            )
            return
        files = sorted(
            (path for path in incoming.iterdir() if path.is_file() and path.suffix.lower() == ".mkv" and not path.is_symlink()),
            key=lambda path: path.name.casefold(),
        )
        if not files:
            await message.reply_text(f"No hay archivos MKV en <code>{html.escape(str(incoming))}</code>.", parse_mode=enums.ParseMode.HTML)
            return
        if encode_lock.locked():
            await message.reply_text("Ya hay un encodeo mai activo. Espera a que termine.")
            return

        async with encode_lock:
            for source in files:
                await encode_one(message, source, options, burn_subtitles=burn_subtitles)

    async def encode_one(message: Message, source: Path, options: EncodeOptions, *, burn_subtitles: bool) -> None:
        job_id = uuid.uuid4().hex[:10]
        job_dir = jobs / job_id
        job_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
        command_name = "/ed2" if burn_subtitles else "/ec2"
        mode_title = "Codificando y quemando subtítulos" if burn_subtitles else "Codificando sin subtítulo interno"
        total_steps = 5 if burn_subtitles else 4
        encode_started = time.monotonic()
        status = await message.reply_text(f"⚙️ {mode_title}: {html.escape(source.name)}")
        output_name = f"{safe_filename(source.stem)}_{'sub' if burn_subtitles else 'encode'}_{job_id[:6]}.mp4"
        output = encoded / output_name

        async def step_template(step: int, label: str, *, completed: bool = False) -> None:
            elapsed = max(time.monotonic() - encode_started, 0)
            completed_steps = step if completed else step - 1
            percent = completed_steps * 100 / total_steps
            average = elapsed / max(completed_steps, 1)
            eta = max(0, total_steps - completed_steps) * average
            if completed:
                text = (
                    f"🔧 {mode_title}: {html.escape(source.name)}\n"
                    f"📍 Paso {step}/{total_steps}: {label}\n"
                    f"{_bar(percent)} {percent:.1f}%\n"
                    f"⏱️ Tiempo: {_time_text(elapsed)} / ETA: {_time_text(eta)}"
                )
            else:
                track_info = f"\n🎧 Audio: {options.audio_index}"
                if burn_subtitles:
                    track_info += f" · 📝 Subtítulo: {options.subtitle_index}"
                text = (
                    f"🔄 Paso {step}/{total_steps}: {label}\n"
                    f"🗂 {html.escape(source.name)}\n"
                    f"🛠 {command_name}{track_info}"
                )
            await _show_progress(status, text)

        try:
            await step_template(1, "Analizando pistas")
            metadata = await _probe(source, timeout)
            streams = metadata.get("streams", [])
            audio_count = sum(stream.get("codec_type") == "audio" for stream in streams)
            subtitle_count = sum(stream.get("codec_type") == "subtitle" for stream in streams)
            if audio_count == 0 or options.audio_index >= audio_count:
                raise RuntimeError(f"La pista de audio {options.audio_index} no existe; el video tiene {audio_count} pista(s).")
            await step_template(1, "Analizando pistas", completed=True)

            filters: list[str] = []
            if burn_subtitles:
                if options.subtitle_index >= subtitle_count:
                    raise RuntimeError(f"La pista de subtítulos {options.subtitle_index} no existe; el video tiene {subtitle_count} pista(s).")
                await step_template(2, f"Extrayendo subtítulo {options.subtitle_index}")
                embedded = job_dir / "embedded.ass"
                await _run(
                    ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-v", "error", "-i", str(source),
                     "-map", f"0:s:{options.subtitle_index}", str(embedded)],
                    cwd=job_dir, timeout=timeout,
                )
                filters.append("subtitles=filename='embedded.ass'")
                await step_template(2, f"Extrayendo subtítulo {options.subtitle_index}", completed=True)

            watermark_subs = root / "marca_bot.ass"
            if watermark_subs.is_file() and not watermark_subs.is_symlink():
                shutil.copyfile(watermark_subs, job_dir / "marca_bot.ass")
                filters.append("subtitles=filename='marca_bot.ass'")

            passlog = job_dir / "encode_pass"
            first_pass = 3 if burn_subtitles else 2
            await step_template(first_pass, "Primera pasada (video)")
            await _run(ffmpeg_pass_one(source, passlog, options, filters), cwd=job_dir, timeout=timeout)
            await step_template(first_pass, "Primera pasada (video)", completed=True)
            await step_template(first_pass + 1, "Segunda pasada (final)")
            await _run(ffmpeg_pass_two(source, output, passlog, options, filters), cwd=job_dir, timeout=timeout)
            await step_template(first_pass + 1, "Segunda pasada (final)", completed=True)
            if not output.is_file() or output.stat().st_size <= 0:
                raise RuntimeError("FFmpeg no generó un archivo de salida válido.")
            if output.stat().st_size > 1950 * 1024 * 1024:
                raise RuntimeError("El resultado supera 1950 MB, límite de envío de Telegram.")

            await step_template(total_steps, "Generando miniatura")
            thumb = await make_thumbnail(output, job_dir, root, timeout)
            await step_template(total_steps, "Generando miniatura", completed=True)
            upload_template = "📤 Subiendo resultado de /ed2" if burn_subtitles else "📤 Subiendo resultado de /ec2"
            await send_video(message, output, thumb, status, timeout, template_title=upload_template)
            await _show_progress(status, f"✅ {command_name} completado\n🗂 <code>{html.escape(output.name)}</code>")
            output.unlink(missing_ok=True)
            if thumb:
                thumb.unlink(missing_ok=True)
        except Exception as error:
            logger.exception("Falló mai_media con %s", source.name)
            await _show_progress(status, f"❌ Error con <code>{html.escape(source.name)}</code>\n{html.escape(str(error)[:900])}")
        finally:
            shutil.rmtree(job_dir, ignore_errors=True)

    async def make_thumbnail(output: Path, job_dir: Path, asset_root: Path, run_timeout: int) -> Path | None:
        base = job_dir / "thumb_base.jpg"
        thumb = job_dir / "thumb.jpg"
        try:
            await _run(
                ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-v", "error", "-ss", "10", "-i", str(output),
                 "-frames:v", "1", "-vf", "scale=320:180:force_original_aspect_ratio=decrease,pad=320:180:(ow-iw)/2:(oh-ih)/2", str(base)],
                cwd=job_dir, timeout=run_timeout,
            )
            logo = asset_root / "marca.png"
            if logo.is_file() and not logo.is_symlink():
                await _run(
                    ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-v", "error", "-i", str(base), "-i", str(logo),
                     "-filter_complex", "[1:v]scale=iw/2:-1[logo];[0:v][logo]overlay=W-w-10:H-h-10", "-frames:v", "1", str(thumb)],
                    cwd=job_dir, timeout=run_timeout,
                )
                base.unlink(missing_ok=True)
                return thumb if thumb.is_file() else None
            base.replace(thumb)
            return thumb
        except Exception:
            logger.info("No se pudo generar miniatura para %s", output.name, exc_info=True)
            return None

    async def send_video(
        message: Message,
        path: Path,
        thumb: Path | None,
        status: Message,
        run_timeout: int,
        *,
        template_title: str,
    ) -> None:
        metadata = await _probe(path, run_timeout)
        duration, width, height = _media_dimensions(metadata)
        started = time.monotonic()
        last_update = [0.0]

        async def progress(current: int, total: int, *_):
            now = time.monotonic()
            if now - last_update[0] < 3 and current < total:
                return
            last_update[0] = now
            percent = current * 100 / total if total else 0
            elapsed = max(now - started, 0.1)
            speed_bytes = current / elapsed if current else 1
            speed = speed_bytes / 1048576
            eta = (total - current) / speed_bytes if total else 0
            await _show_progress(
                status,
                f"{template_title}\n"
                f"🗂 {html.escape(path.name)}\n"
                f"{_bar(percent)} {percent:.1f}%\n"
                f"⚡ Velocidad: {speed:.2f} MB/s\n"
                f"⏱️ ETA: {_time_text(eta)}",
            )

        await _show_progress(status, f"{template_title}\n🗂 {html.escape(path.name)}\n📍 Destino: este chat")
        await message.reply_video(
            video=str(path),
            thumb=str(thumb) if thumb and thumb.is_file() else None,
            caption=html.escape(path.name[:900]),
            parse_mode=enums.ParseMode.HTML,
            duration=duration or None,
            width=width or None,
            height=height or None,
            supports_streaming=True,
            progress=progress,
        )

    @app.on_message(filters.command("ed2"))
    async def encode_with_subtitles(client, message: Message):
        await encode_files(message, burn_subtitles=True)

    @app.on_message(filters.command("ec2"))
    async def encode_without_source_subtitles(client, message: Message):
        await encode_files(message, burn_subtitles=False)

    @app.on_message(filters.command("up2"))
    async def upload_encoded(client, message: Message):
        if await deny(message):
            return
        files = sorted(
            (path for path in encoded.iterdir() if path.is_file() and path.suffix.lower() == ".mp4" and not path.is_symlink()),
            key=lambda path: path.name.casefold(),
        )
        if not files:
            await message.reply_text("No hay videos codificados pendientes en la carpeta de salida.")
            return
        for path in files:
            if path.stat().st_size > 1950 * 1024 * 1024:
                await message.reply_text(f"Se omite {html.escape(path.name)}: supera el límite de Telegram.")
                continue
            status = await message.reply_text(f"📦 /up2 · Pendiente\n🗂 {html.escape(path.name)}")
            try:
                await send_video(
                    message, path, None, status, timeout,
                    template_title="📤 /up2 · Subiendo video pendiente",
                )
                await _show_progress(status, f"✅ /up2 completado\n🗂 <code>{html.escape(path.name)}</code>")
                path.unlink(missing_ok=True)
            except Exception as error:
                logger.exception("No se pudo enviar %s", path.name)
                await _show_progress(status, f"❌ No se pudo enviar <code>{html.escape(path.name)}</code>: {html.escape(str(error)[:600])}")

    @app.on_message(filters.command("delete2"))
    async def delete_auxiliary(client, message: Message):
        if await deny(message):
            return
        deleted: list[str] = []
        protected = {"marca_bot.ass"}
        for path in incoming.iterdir():
            if path.is_file() and not path.is_symlink() and path.name not in protected and path.suffix.lower() in {".log", ".ass"}:
                try:
                    path.unlink()
                    deleted.append(path.name)
                except OSError:
                    logger.warning("No se pudo borrar %s", path, exc_info=True)
        await message.reply_text("🗑️ Archivos auxiliares borrados:\n" + "\n".join(map(html.escape, deleted)) if deleted else "No hay archivos .log o .ass que borrar.", parse_mode=enums.ParseMode.HTML)

    @app.on_message(filters.command("dele2"))
    async def delete_anime_media(client, message: Message):
        if await deny(message):
            return
        deleted: list[str] = []
        for path in incoming.iterdir():
            if path.is_file() and not path.is_symlink() and path.suffix.lower() in {".mkv", ".mp4"}:
                try:
                    path.unlink()
                    deleted.append(path.name)
                except OSError:
                    logger.warning("No se pudo borrar %s", path, exc_info=True)
        await message.reply_text("🗑️ Videos borrados de la carpeta mai_tools:\n" + "\n".join(map(html.escape, deleted)) if deleted else "No hay videos MKV o MP4 que borrar en mai_tools.", parse_mode=enums.ParseMode.HTML)
