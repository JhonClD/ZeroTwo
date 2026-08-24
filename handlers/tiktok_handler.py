"""
tiktok_handler.py - Manejador de descargas de TikTok
Soporta videos con/sin marca de agua, en alta calidad (HD)
"""

import json
import logging
import subprocess
import re
import urllib.request
import urllib.parse
from pathlib import Path
from pyrogram import filters, enums
from pyrogram.types import Message

logger = logging.getLogger(__name__)

# ─── Regex para validar URLs de TikTok ────────────────────────────────────────
TIKTOK_REGEX = re.compile(
    r'(?:https?://)?(?:www\.|vm\.|vt\.|t\.)?tiktok\.com/[^\s&]+',
    re.IGNORECASE
)

# ─── APIs de fallback ─────────────────────────────────────────────────────────
FALLBACK_APIS = [
    "https://www.tikwm.com/api/?url={url}&hd=1",
    "https://api.vreden.my.id/api/tiktok?url={url}",
    "https://luminai.my.id/api/download/tiktok?url={url}",
]


def register(app, download_dir):
    """Registra el handler de TikTok"""

    @app.on_message(filters.command(["tiktok", "ttdl", "tt", "tiktoknowm", "ttnowm"]))
    async def tiktok_command(client, message: Message):
        """Comando para descargar videos de TikTok en alta calidad"""

        # ── Obtener URL ───────────────────────────────────────────────────────
        args = message.text.split(maxsplit=1)

        if len(args) < 2:
            await message.reply_text(
                "🎵 <b>TikTok Downloader</b>\n\n"
                "Envía el enlace del video de TikTok.\n\n"
                "<b>Comandos:</b>\n"
                "/tiktok &lt;url&gt; — Descargar video HD\n"
                "/ttdl &lt;url&gt; — Alias rápido\n\n"
                "<b>Ejemplo:</b>\n"
                "<code>/tiktok https://vt.tiktok.com/ZS12345/</code>",
                parse_mode=enums.ParseMode.HTML
            )
            return

        tiktok_url = args[1].strip()

        # ── Validar URL ───────────────────────────────────────────────────────
        if not TIKTOK_REGEX.search(tiktok_url):
            await message.reply_text(
                "❌ <b>URL inválida</b>\n\n"
                "Asegúrate de enviar un enlace válido de TikTok.\n"
                "<b>Ejemplo:</b> <code>https://vt.tiktok.com/ZS12345/</code>",
                parse_mode=enums.ParseMode.HTML
            )
            return

        logger.info(f"🎵 TikTok - URL: {tiktok_url[:80]}")

        status_msg = await message.reply_text("⏳ Obteniendo enlace de descarga...")

        try:
            # ── INTENTO 1: Scraping instatiktok.com ───────────────────────────
            video_url = await _fetch_from_instatiktok(tiktok_url)

            if video_url:
                logger.info(f"✅ URL obtenida vía instatiktok: {video_url[:60]}...")
            else:
                logger.info("⚠️ instatiktok falló, probando APIs de fallback...")

            # ── INTENTO 2: APIs de fallback ───────────────────────────────────
            if not video_url:
                video_url = await _fetch_from_apis(tiktok_url)

            if not video_url:
                raise Exception("No se pudo obtener el enlace de descarga del video.")

            # ── Descargar y enviar ────────────────────────────────────────────
            await status_msg.edit_text("📥 Descargando video en alta calidad...")

            tmp_video = download_dir / f"tt_{message.from_user.id}.mp4"

            try:
                dl_cmd = f'curl -s -L -o "{tmp_video}" "{video_url}"'
                result = subprocess.run(dl_cmd, shell=True, timeout=120)

                if not tmp_video.exists() or tmp_video.stat().st_size < 10_000:
                    raise Exception("El archivo descargado está vacío o es inválido.")

                file_size_mb = tmp_video.stat().st_size / (1024 * 1024)
                logger.info(f"✅ Descarga completada: {file_size_mb:.2f} MB")

                await status_msg.edit_text("📤 Enviando video...")

                await message.reply_video(
                    video=str(tmp_video),
                    caption=(
                        "✅ <b>TikTok descargado en alta calidad</b>\n\n"
                        f"📦 Tamaño: {file_size_mb:.2f} MB"
                    ),
                    parse_mode=enums.ParseMode.HTML,
                    supports_streaming=True,
                )

                await status_msg.delete()
                logger.info("✅ Video de TikTok enviado exitosamente")

            finally:
                tmp_video.unlink(missing_ok=True)
                logger.info("🗑️ Archivo temporal eliminado")

        except subprocess.TimeoutExpired:
            logger.error("⏱️ Timeout en descarga de TikTok")
            await status_msg.edit_text(
                "⏱️ La descarga tardó demasiado. Intenta de nuevo o prueba con otro enlace."
            )

        except Exception as e:
            logger.error(f"❌ Error TikTok: {e}", exc_info=True)
            await status_msg.edit_text(
                f"❌ <b>Error descargando el video</b>\n\n{str(e)[:200]}",
                parse_mode=enums.ParseMode.HTML
            )


# ─── Funciones auxiliares ──────────────────────────────────────────────────────

async def _fetch_from_instatiktok(url: str):
    """Intenta obtener el enlace de descarga desde instatiktok.com"""
    try:
        SITE_URL = "https://instatiktok.com/"
        form_data = urllib.parse.urlencode({
            "url": url,
            "platform": "tiktok"
        }).encode()

        req = urllib.request.Request(
            f"{SITE_URL}api",
            data=form_data,
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Origin": SITE_URL,
                "Referer": SITE_URL,
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "X-Requested-With": "XMLHttpRequest",
            }
        )

        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode()

        data = json.loads(raw)
        if data.get("status") != "success" or not data.get("html"):
            return None

        html = data["html"]

        # Extraer todos los href de los botones de descarga
        links = re.findall(r'href=["\']?(https?://[^"\'>\s]+)["\']?', html)

        if not links:
            return None

        # Priorizar hdplay > download > cualquier otro
        hd = next((l for l in links if "hdplay" in l.lower()), None)
        dl = next((l for l in links if "download" in l.lower()), None)
        return hd or dl or links[0]

    except Exception as e:
        logger.warning(f"[instatiktok] Error: {e}")
        return None


async def _fetch_from_apis(url: str) -> str | None:
    """Prueba una lista de APIs de fallback y devuelve la primera URL válida"""
    encoded = urllib.parse.quote(url, safe="")

    for api_template in FALLBACK_APIS:
        api_url = api_template.format(url=encoded)
        try:
            req = urllib.request.Request(
                api_url,
                headers={"User-Agent": "Mozilla/5.0"}
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode()

            data = json.loads(raw)

            # Intentar múltiples rutas en la respuesta JSON
            video_url = (
                _safe_get(data, "data", "hdplay") or
                _safe_get(data, "data", "play") or
                _safe_get(data, "data", "url") or
                _safe_get(data, "result", "url") or
                (data["data"][0]["url"] if isinstance(data.get("data"), list) else None)
            )

            if video_url:
                logger.info(f"✅ URL obtenida vía API fallback: {api_url[:60]}")
                return video_url

        except Exception as e:
            logger.warning(f"[API fallback] {api_url[:60]} → {e}")
            continue

    return None


def _safe_get(d: dict, *keys):
    """Navegación segura en dicts anidados"""
    for k in keys:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d if isinstance(d, str) and d.startswith("http") else None
