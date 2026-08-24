"""Notificador independiente de episodios de MonosChinos para Zero Two.

Este módulo no modifica ni importa tioanime_notify_handler.py. Mantiene su
propia cola, estado persistente y comandos para que MonosChinos pueda editarse o
desactivarse por separado.

Comandos:
  /mchosstart [min]  /mchosstop  /mchosstatus  /mchoscheck
  /mchosqueue        /mchosflush /mchosunblock /mchosinterval <min>
  /mchosexample [N]

La descarga reutiliza los descargadores compartidos de Mega y MediaFire.
"""

import asyncio
import json
import logging
import os
import re
import time
import subprocess
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from pyrogram import enums, filters
from pyrogram.types import Message

from downloaders import MEGADownloader, MediaFireDownloader

logger = logging.getLogger(__name__)

MONOSCHINOS_URL = 'https://monoschinos.st'
CHECK_INTERVAL_DEFAULT = 10
QUEUE_DELAY = 90
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'es-419,es;q=0.9,en;q=0.8',
}

_owner_env = os.environ.get('TIOANIME_OWNER_IDS', '')
OWNER_IDS = {int(x) for x in _owner_env.split(',') if x.strip().isdigit()}

_client = None
_loop = None
_active = {}
_intervals = {}
_queue = []
_queue_running = False
_queue_task = None
SEEN_FILE = None
STATE_FILE = None


def _create_task(coro):
    loop = _loop
    if loop is None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.get_event_loop()
    return loop.create_task(coro)


def _load(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return {}


def _save(path, data):
    try:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
    except Exception:
        logger.exception('[monoschinos-notify] No se pudo guardar %s', path)


async def _get(url, **kwargs):
    kwargs.setdefault('headers', HEADERS)
    kwargs.setdefault('timeout', 20)
    return await asyncio.to_thread(requests.get, url, **kwargs)


def _safe_file(value):
    return re.sub(r'\s+', ' ', re.sub(r'[/\\:*?"<>|]', '_', value)).strip()


def _episode_id(slug, number):
    return f'monoschinos-{slug.lower()}-{number}'


async def _video_metadata(video_path: Path, temp_dir: Path):
    """Devuelve duración/resolución y genera una miniatura pequeña para Telegram."""
    duration = width = height = 0
    try:
        probe = await asyncio.to_thread(
            subprocess.run,
            ['ffprobe', '-v', 'error', '-show_entries',
             'format=duration:stream=codec_type,duration,width,height',
             '-of', 'json', str(video_path)],
            capture_output=True, text=True, timeout=30,
        )
        if probe.returncode == 0:
            data = json.loads(probe.stdout or '{}')
            stream = next((item for item in data.get('streams', [])
                           if item.get('codec_type') == 'video'), {})
            width = int(float(stream.get('width') or 0))
            height = int(float(stream.get('height') or 0))
            raw_duration = data.get('format', {}).get('duration') or stream.get('duration') or 0
            duration = max(0, int(round(float(raw_duration))))
    except (OSError, ValueError, TypeError, json.JSONDecodeError, subprocess.TimeoutExpired) as error:
        logger.warning('[monoschinos-notify] No se pudieron leer metadatos de %s: %s', video_path, error)

    thumb_path = temp_dir / 'monoschinos_thumb.jpg'
    scale = 'scale=320:-2' if width >= height else 'scale=-2:320'
    seek = max(1, duration // 2) if duration else 1
    for quality in (5, 10, 16, 23):
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                ['ffmpeg', '-y', '-v', 'error', '-ss', str(seek), '-i', str(video_path),
                 '-frames:v', '1', '-vf', scale, '-q:v', str(quality),
                 '-f', 'image2', '-pix_fmt', 'yuvj420p', str(thumb_path)],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0 and thumb_path.exists() and thumb_path.stat().st_size <= 200 * 1024:
                return duration, width, height, thumb_path
        except (OSError, subprocess.TimeoutExpired) as error:
            logger.warning('[monoschinos-notify] No se pudo crear miniatura: %s', error)
            break
    return duration, width, height, None


def _is_owner(message):
    if not OWNER_IDS:
        return True
    sender = getattr(message, 'from_user', None)
    return bool(sender and sender.id in OWNER_IDS)


async def fetch_latest_episodes() -> list[dict]:
    """Obtiene las tarjetas de episodios en el orden publicado por MonosChinos."""
    response = await _get( MONOSCHINOS_URL + '/')
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')
    domain = urlparse(MONOSCHINOS_URL).netloc
    result, ids = [], set()

    for anchor in soup.select('a[href]'):
        page_url = urljoin(MONOSCHINOS_URL + '/', anchor.get('href', '').strip())
        parsed = urlparse(page_url)
        if parsed.netloc != domain or '/ver/' not in parsed.path:
            continue
        episode_path = parsed.path.rstrip('/').split('/ver/', 1)[1]
        match = re.search(r'^(.+?)-(?:episodio|capitulo)-(\d+)(?:-[^/]*)?$', episode_path, re.I)
        if not match:
            continue
        slug, number_text = match.groups()
        number = int(number_text)
        item_id = _episode_id(slug, number)
        if item_id in ids:
            continue

        raw_title = anchor.get('title') or anchor.get_text(' ', strip=True)
        if raw_title.strip().lower() in ('ver ahora', 'más info'):
            continue
        card = anchor
        image = None
        for _ in range(5):
            card = card.parent or card
            image = card.select_one('img') if hasattr(card, 'select_one') else None
            if image:
                break
        image_src = ''
        if image:
            image_src = (image.get('data-src') or image.get('data-lazy') or
                         image.get('data-original') or image.get('src') or '').strip()
        image_url = '' if not image_src or image_src.startswith('data:') else urljoin(page_url, image_src)
        title = re.sub(r'^EP\s*\d+\s+', '', raw_title, flags=re.I).strip()
        title = re.sub(r'\s+(?:episodio|capitulo)\s+\d+.*$', '', title, flags=re.I).strip()
        title = title or slug.replace('-', ' ')

        ids.add(item_id)
        result.append({
            'id': item_id, 'slug': slug, 'titulo': title, 'epNum': number,
            'epUrl': page_url, 'imgUrl': image_url, 'fuente': 'monoschinos',
        })

    logger.info('[monoschinos-notify] %s episodios en portada', len(result))
    return result


async def scrape_servers(ep_url: str) -> list[dict]:
    """Extrae downloads/embeds.SUB del estado JavaScript de MonosChinos."""
    response = await _get(ep_url, headers={**HEADERS, 'Referer': MONOSCHINOS_URL})
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')
    servers, seen = [], set()

    def add(name, url, direct):
        name, url = name.lower().strip(), url.strip()
        if url.startswith('http') and url not in seen:
            seen.add(url)
            servers.append({'nombre': name, 'url': url, 'directo': direct})

    provider_domains = {
        'mega': 'mega.nz', 'mediafire': 'mediafire.com', 'gofile': 'gofile.io',
        'filemoon': 'filemoon', 'savefiles': 'savefiles', 'doodstream': 'doodstream',
        'voe': 'voe.', 'mxdrop': 'mxdrop', 'lulu': 'lulu', 'mp4upload': 'mp4upload',
    }
    for anchor in soup.select('a[href]'):
        url = anchor.get('href', '').strip()
        text = anchor.get_text(' ', strip=True).lower()
        name = next((key for key, domain_name in provider_domains.items() if domain_name in url.lower()), None)
        if not name:
            name = next((key for key in provider_domains if key in text), None)
        if name:
            add(name, url, name in ('mega', 'mediafire'))

    for frame in soup.select('iframe[src], iframe[data-src]'):
        url = (frame.get('src') or frame.get('data-src') or '').strip()
        if url.startswith('http'):
            add('embed', url, False)
    return servers


def _ordered_servers(servers):
    priority = {'mediafire': 0, 'mega': 1}
    return sorted(servers, key=lambda item: (not item.get('directo', False), priority.get(item['nombre'], 99)))


async def _send_episode(chat_id, episode, client):
    title, number = episode['titulo'], episode['epNum']
    work_dir = STATE_FILE.parent.parent / 'temp_videos'
    work_dir.mkdir(parents=True, exist_ok=True)
    temp_dir = work_dir / f'monoschinos_{int(time.time() * 1000)}'
    temp_dir.mkdir(parents=True, exist_ok=True)
    caption = (
        '<b>✨ Nuevo Episodio MonosChinos ✨</b>\n'
        '━━━━━━━━━━━━━━━━━━━━━\n'
        f'🇪🇸 <b>{title}</b>\n'
        f'🆕 Capítulo: <b>{number}</b>\n'
        f'🌐 Ver online: {episode["epUrl"]}\n'
        '📡 Fuente: <b>MonosChinos</b>\n'
        '━━━━━━━━━━━━━━━━━━━━━\n'
        '✅ <i>INICIANDO DESCARGA...</i>'
    )
    try:
        if episode.get('imgUrl'):
            try:
                await client.send_photo(chat_id, episode['imgUrl'], caption=caption, parse_mode=enums.ParseMode.HTML)
            except Exception:
                await client.send_message(chat_id, caption, parse_mode=enums.ParseMode.HTML)
        else:
            await client.send_message(chat_id, caption, parse_mode=enums.ParseMode.HTML)

        servers = await scrape_servers(episode['epUrl'])
        video = None
        for server in _ordered_servers(servers)[:6]:
            if server['nombre'] not in ('mega', 'mediafire') or not server.get('directo'):
                continue
            try:
                downloader = MEGADownloader if server['nombre'] == 'mega' else MediaFireDownloader
                ok, path, error = await downloader.download(server['url'], temp_dir)
                if ok and path:
                    video = path
                    break
                logger.warning('[monoschinos-notify] %s falló: %s', server['nombre'], error)
            except Exception as error:
                logger.warning('[monoschinos-notify] %s falló: %s', server['nombre'], error)

        if not video:
            raise RuntimeError('No se pudo descargar desde Mega o MediaFire')

        duration, width, height, thumb = await _video_metadata(video, temp_dir)
        send_kwargs = {
            'caption': f'🇪🇸 <b>{title}</b> — Episodio {number}',
            'parse_mode': enums.ParseMode.HTML,
            'supports_streaming': True,
        }
        if duration:
            send_kwargs['duration'] = duration
        if width:
            send_kwargs['width'] = width
        if height:
            send_kwargs['height'] = height
        if thumb:
            send_kwargs['thumb'] = str(thumb)
        await client.send_video(chat_id, str(video), **send_kwargs)
    finally:
        for item in temp_dir.glob('*'):
            try:
                item.unlink()
            except OSError:
                pass
        try:
            temp_dir.rmdir()
        except OSError:
            pass


async def _process_queue():
    global _queue_running
    if _queue_running:
        return
    _queue_running = True
    try:
        while _queue:
            item = _queue.pop(0)
            try:
                await _send_episode(item['chat_id'], item['ep'], _client)
            except Exception as error:
                logger.exception('[monoschinos-notify] Error enviando episodio: %s', error)
                try:
                    await _client.send_message(item['chat_id'], f'❌ MonosChinos no pudo enviar {item["ep"]["titulo"]} ep {item["ep"]["epNum"]}: {error}')
                except Exception:
                    pass
            if _queue:
                await asyncio.sleep(QUEUE_DELAY)
    finally:
        _queue_running = False


async def check_new(chat_id, client):
    global _client
    _client = client
    episodes = await fetch_latest_episodes()
    seen = _load(SEEN_FILE)
    chat_seen = seen.setdefault(str(chat_id), [])
    new = [ep for ep in episodes if ep['id'] not in chat_seen]
    if not new:
        return 0
    chat_seen.extend(ep['id'] for ep in new)
    seen[str(chat_id)] = chat_seen[-500:]
    _save(SEEN_FILE, seen)
    _queue.extend({'chat_id': chat_id, 'ep': ep} for ep in new)
    _create_task(_process_queue())
    return len(new)


async def _notifier_loop(chat_id, minutes):
    try:
        while True:
            await asyncio.sleep(minutes * 60)
            if _client:
                try:
                    await check_new(chat_id, _client)
                except Exception:
                    logger.exception('[monoschinos-notify] Error comprobando episodios')
    except asyncio.CancelledError:
        pass


def _start(chat_id, client, minutes=CHECK_INTERVAL_DEFAULT):
    global _client
    _client = client
    previous = _active.get(chat_id)
    if previous:
        previous.cancel()
    _active[chat_id] = _create_task(_notifier_loop(chat_id, minutes))
    _intervals[chat_id] = minutes
    state = _load(STATE_FILE)
    old = state.get(str(chat_id), {})
    state[str(chat_id)] = {'intervalMin': minutes, 'startedAt': old.get('startedAt', int(time.time() * 1000))}
    _save(STATE_FILE, state)
    return previous is not None


def _stop(chat_id):
    task = _active.pop(chat_id, None)
    _intervals.pop(chat_id, None)
    if task:
        task.cancel()
    state = _load(STATE_FILE)
    state.pop(str(chat_id), None)
    _save(STATE_FILE, state)


def _restore(client):
    global _client
    _client = client
    for chat, config in _load(STATE_FILE).items():
        chat_id = int(chat)
        if chat_id not in _active:
            _start(chat_id, client, config.get('intervalMin', CHECK_INTERVAL_DEFAULT))


def register(app, work_dir: Path):
    """Registra exclusivamente los comandos y tareas de MonosChinos."""
    global _client, _loop, SEEN_FILE, STATE_FILE
    _client, _loop = app, getattr(app, 'loop', None)
    database = Path(work_dir) / 'database'
    database.mkdir(parents=True, exist_ok=True)
    SEEN_FILE = database / 'monoschinos_seen.json'
    STATE_FILE = database / 'monoschinos_state.json'

    @app.on_message(filters.all, group=-2)
    async def _bootstrap(client, message: Message):
        _restore(client)

    @app.on_message(filters.command('mchosstart'))
    async def start_cmd(client, message: Message):
        if not _is_owner(message):
            await message.reply_text('⛔ Solo el owner puede usar este comando.')
            return
        try:
            minutes = int(message.text.split(maxsplit=1)[1]) if len(message.text.split()) > 1 else CHECK_INTERVAL_DEFAULT
        except ValueError:
            minutes = 0
        if not 5 <= minutes <= 60:
            await message.reply_text('❌ Usa un intervalo entre 5 y 60 minutos. Ej: /mchosstart 15')
            return
        already = _start(message.chat.id, client, minutes)
        await message.reply_text(f'✅ Notificador MonosChinos {"actualizado" if already else "activado"} cada {minutes} minutos.')
        if not already:
            try:
                episodes = await fetch_latest_episodes()
                seen = _load(SEEN_FILE)
                seen[str(message.chat.id)] = [ep['id'] for ep in episodes][-500:]
                _save(SEEN_FILE, seen)
                await message.reply_text(f'📋 {len(episodes)} episodios de MonosChinos registrados como base. Solo se enviarán los nuevos.')
            except Exception as error:
                await message.reply_text(f'⚠️ No se pudo crear la base inicial: {error}')

    @app.on_message(filters.command('mchosstop'))
    async def stop_cmd(client, message: Message):
        if not _is_owner(message):
            await message.reply_text('⛔ Solo el owner puede usar este comando.')
            return
        _stop(message.chat.id)
        before = len(_queue)
        _queue[:] = [item for item in _queue if item['chat_id'] != message.chat.id]
        await message.reply_text(f'🛑 Notificador MonosChinos detenido. Episodios cancelados: {before - len(_queue)}.')

    @app.on_message(filters.command('mchosstatus'))
    async def status_cmd(client, message: Message):
        pending = sum(1 for item in _queue if item['chat_id'] == message.chat.id)
        await message.reply_text(f'📡 MonosChinos: {"activo" if message.chat.id in _active else "inactivo"}\nCola: {pending}\nProcesando: {"sí" if _queue_running else "no"}\nVistos: {len(_load(SEEN_FILE).get(str(message.chat.id), []))}')

    @app.on_message(filters.command('mchoscheck'))
    async def check_cmd(client, message: Message):
        await message.reply_text('🔍 Comprobando MonosChinos...')
        count = await check_new(message.chat.id, client)
        await message.reply_text(f'✅ {count} episodio(s) nuevo(s).' if count else '✅ Sin episodios nuevos.')

    @app.on_message(filters.command('mchosexample'))
    async def example_cmd(client, message: Message):
        try:
            count = min(max(int(message.text.split(maxsplit=1)[1]), 1), 10)
        except (IndexError, ValueError):
            count = 1
        episodes = await fetch_latest_episodes()
        for episode in episodes[:count]:
            _queue.append({'chat_id': message.chat.id, 'ep': episode})
        _create_task(_process_queue())
        await message.reply_text(f'📋 {min(count, len(episodes))} episodio(s) de MonosChinos añadido(s) a la cola.')

    @app.on_message(filters.command('mchosqueue'))
    async def queue_cmd(client, message: Message):
        own = [item for item in _queue if item['chat_id'] == message.chat.id]
        text = '✅ Cola MonosChinos vacía.' if not own else '📋 Cola MonosChinos:\n' + '\n'.join(f'{i + 1}. {x["ep"]["titulo"]} ep {x["ep"]["epNum"]}' for i, x in enumerate(own))
        await message.reply_text(text)

    @app.on_message(filters.command('mchosflush'))
    async def flush_cmd(client, message: Message):
        if not _is_owner(message):
            await message.reply_text('⛔ Solo el owner puede usar este comando.')
            return
        before = len(_queue)
        _queue[:] = [item for item in _queue if item['chat_id'] != message.chat.id]
        await message.reply_text(f'🗑️ {before - len(_queue)} episodio(s) eliminado(s) de la cola MonosChinos.')

    @app.on_message(filters.command('mchosunblock'))
    async def unblock_cmd(client, message: Message):
        global _queue_running
        if not _is_owner(message):
            await message.reply_text('⛔ Solo el owner puede usar este comando.')
            return
        _queue_running = False
        _create_task(_process_queue())
        await message.reply_text('🔓 Cola MonosChinos desbloqueada y reanudada.')

    @app.on_message(filters.command('mchosinterval'))
    async def interval_cmd(client, message: Message):
        if not _is_owner(message):
            await message.reply_text('⛔ Solo el owner puede usar este comando.')
            return
        try:
            minutes = int(message.text.split(maxsplit=1)[1])
        except (IndexError, ValueError):
            minutes = 0
        if not 5 <= minutes <= 60:
            await message.reply_text('❌ Usa un intervalo entre 5 y 60 minutos.')
            return
        if message.chat.id not in _active:
            await message.reply_text('⚠️ Usa /mchosstart primero.')
            return
        _start(message.chat.id, client, minutes)
        await message.reply_text(f'⏱️ Intervalo MonosChinos actualizado a {minutes} minutos.')

    logger.info('[monoschinos-notify] Handler independiente registrado (comandos mchos*)')
