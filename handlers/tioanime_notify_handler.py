"""
tioanime_notify_handler.py — Notificador automático de nuevos episodios
TioAnime (SUB) + LatAnime (LAT/ESP) para Zero Two (Pyrogram / Telegram).

Puerto de plugins/tioanime-notify.js (WhatsApp/Baileys) → hace lo mismo que
el plugin original: scrapea portadas, detecta episodios nuevos, los encola,
descarga desde el primer servidor soportado (MEGA → MediaFire, igual que el
JS) y los envía al chat como documento/video.

Descarga: reutiliza downloaders.MEGADownloader y downloaders.MediaFireDownloader
(los mismos dos servicios que soportaba el JS — mega + mediafire; los demás
servidores/embeds se detectan pero se saltan, igual que en el original).

Comandos (mismos nombres que el JS):
  /tiostart [min]   /tiostop     /tiostatus   /tiocheck
  /tioqueue         /tioflush    /tiounblock  /tiointerval <min>
  /tioexample [N]   /latexample [N]

Comandos "owner-only" (tiostart, tiostop, tiointerval, tioflush, tiounblock):
  Restringidos vía la lista OWNER_IDS (variable de entorno TIOANIME_OWNER_IDS,
  IDs de Telegram separados por coma). Si no se configura ninguno, no se
  restringe (comportamiento abierto, ya que Zero Two no tiene un concepto de
  "owner" global como el bot de WhatsApp).
"""

import os
import re
import json
import time
import asyncio
import logging
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from pyrogram import filters, enums
from pyrogram.types import Message

from downloaders import MEGADownloader, MediaFireDownloader

logger = logging.getLogger(__name__)

# ─── Constantes ─────────────────────────────────────────────────────────────

TIOANIME_URL = 'https://tioanime.com'
LATANIME_URL = 'https://latanime.org'

CHECK_INTERVAL_DEFAULT = 10      # minutos
QUEUE_DELAY            = 90      # segundos entre ítems de la cola
MAX_REINTENTOS         = 3
ESPERA_REINTENTO       = 3 * 60  # segundos
ESPERA_REQUEUE         = 5 * 60  # segundos

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
HEADERS = {
    'User-Agent': UA,
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'es-419,es;q=0.9,en;q=0.8',
}

PREFS_EMBED = ['mp4upload', 'filemoon', 'streamwish', 'streamtape', 'doodstream', 'voe', 'vidhide', 'okru', 'mixdrop']

# Comandos restringidos a "owner" (igual que COMANDOS_OWNER en el JS)
COMANDOS_OWNER = {'tiostart', 'tiostop', 'tiointerval', 'tioflush', 'tiounblock'}
_owner_env = os.environ.get('TIOANIME_OWNER_IDS', '')
OWNER_IDS = {int(x) for x in _owner_env.split(',') if x.strip().isdigit()}


def _is_owner(user_id: int) -> bool:
    # Si no se configuró TIOANIME_OWNER_IDS, no se restringe (ver docstring).
    return (not OWNER_IDS) or (user_id in OWNER_IDS)


# ─── Estado global (equivalente a los global.tio* del JS) ───────────────────

_client            = None                 # referencia al Client de Pyrogram (equivalente a global.tioConn)
_loop              = None                 # event loop del bot (puede no estar corriendo aún al llamar register())
_active_notifiers  = {}                   # chat_id -> asyncio.Task
_notifier_interval = {}                   # chat_id -> intervalMin (para /tiostatus)
_episode_queue     = []                   # lista de {"chat_id": int, "ep": dict}
_queue_running     = False
_queue_task        = None

SEEN_FILE  = None
STATE_FILE = None


def _create_task(coro):
    """Crea una Task de forma segura tanto si el loop ya está corriendo
    (dentro de un handler async) como si todavía no arrancó (register() se
    llama en main.py antes de app.loop.run_until_complete(...))."""
    loop = _loop
    if loop is None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.get_event_loop()
    return loop.create_task(coro)


# ─── Persistencia ────────────────────────────────────────────────────────────

def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return {}


def _save_json(path: Path, data: dict) -> None:
    try:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
    except Exception:
        pass


def load_seen() -> dict:  return _load_json(SEEN_FILE)
def save_seen(d):         _save_json(SEEN_FILE, d)
def load_state() -> dict: return _load_json(STATE_FILE)
def save_state(d):        _save_json(STATE_FILE, d)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def zero_pad(n) -> str:
    return str(n).zfill(2)


def safe_file(s: str) -> str:
    s = re.sub(r'[/\\:*?"<>|]', '_', s)
    return re.sub(r'\s+', ' ', s).strip()


def build_file_name(titulo: str, ep_num) -> str:
    return f"{zero_pad(ep_num)} {safe_file(titulo)}.mp4"


def fmt_bytes(b) -> str:
    if not b or b <= 0:
        return '0 KB'
    if b >= 1073741824:
        return f"{b / 1073741824:.2f} GB"
    if b >= 1048576:
        return f"{b / 1048576:.2f} MB"
    return f"{b / 1024:.2f} KB"


def _progress_bar(pct: int, width: int = 10) -> str:
    filled = int(width * pct / 100)
    return '▓' * filled + '░' * (width - filled)


async def _get(url: str, **kwargs) -> requests.Response:
    """GET no bloqueante (requests corre en un hilo aparte)."""
    kwargs.setdefault('headers', HEADERS)
    kwargs.setdefault('timeout', 15)
    return await asyncio.to_thread(requests.get, url, **kwargs)


async def _video_meta(video_path: Path, tmp_dir: Path) -> tuple:
    """Duración (seg), thumbnail (jpg) y resolución real del video.

    Telegram exige que el thumb sea JPEG, con el lado mayor <= 320px y
    < 200 KB (https://docs.pyrogram.org/api/methods/send_video) — si no,
    lo descarta en silencio y el cliente muestra un cuadro negro con 0:00,
    que es justo lo que pasaba al generar la miniatura a resolución completa.
    Por eso acá se escala con ffmpeg y se reintenta con más compresión si
    el archivo sigue pesando de más.
    """
    import subprocess as _sp

    duration = width = height = 0
    try:
        r = await asyncio.to_thread(
            _sp.run,
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height:format=duration",
             "-of", "json", str(video_path)],
            capture_output=True, text=True, timeout=15
        )
        data = json.loads(r.stdout or '{}')
        streams = data.get('streams') or [{}]
        width = int(streams[0].get('width') or 0)
        height = int(streams[0].get('height') or 0)
        duration = int(float(data.get('format', {}).get('duration') or 0))
    except Exception:
        pass

    if width and width >= height:
        scale = 'scale=320:-2'
    elif width:
        scale = 'scale=-2:320'
    else:
        scale = "scale='min(320,iw)':-2"

    mid = max(1, duration // 2) if duration else 5
    thumb_path = tmp_dir / 'thumb.jpg'
    thumb = None

    for quality in (4, 8, 14, 20):  # sube compresión si el jpg sigue pesando > 200KB
        try:
            await asyncio.to_thread(
                _sp.run,
                ["ffmpeg", "-y", "-ss", str(mid), "-i", str(video_path),
                 "-vframes", "1", "-vf", scale, "-q:v", str(quality),
                 str(thumb_path)],
                capture_output=True, timeout=20
            )
        except Exception:
            continue
        if thumb_path.exists() and thumb_path.stat().st_size > 0:
            if thumb_path.stat().st_size <= 200 * 1024:
                thumb = str(thumb_path)
                break
    if not thumb and thumb_path.exists() and thumb_path.stat().st_size > 0:
        # último recurso: usarlo aunque supere levemente los 200 KB
        thumb = str(thumb_path)

    return duration, thumb, width, height


def detectar_serv_nombre(url: str) -> str:
    u = url.lower()
    if 'mediafire' in u:  return 'mediafire'
    if 'mega.nz' in u:    return 'mega'
    if 'voe' in u:        return 'voe'
    if 'filemoon' in u:   return 'filemoon'
    if 'mp4upload' in u:  return 'mp4upload'
    if 'streamwish' in u: return 'streamwish'
    if 'streamtape' in u: return 'streamtape'
    if 'dood' in u:       return 'doodstream'
    if 'ok.ru' in u:      return 'okru'
    return 'embed'


# ─── Scraping — TioAnime ──────────────────────────────────────────────────────

async def fetch_latest_episodes() -> list[dict]:
    res = await _get(TIOANIME_URL)
    soup = BeautifulSoup(res.text, 'html.parser')
    lista: list[dict] = []
    ids = set()

    candidatos = soup.select(
        'ul.episodes-list li, .episodes-list li, article.episode, '
        '.episode-item, .anime-item, [class*="episode"], [class*="item"]'
    )

    def _parse(a_tag, contenedor):
        href = a_tag.get('href', '') if a_tag else ''
        if not href:
            return None
        m = re.search(r'/ver/(.+?)[-_](\d+)/?$', href)
        if not m:
            return None
        slug, ep_num = m.group(1), int(m.group(2))
        titulo_el = contenedor.select_one('h3, h2, .title, .anime-title, p') if contenedor else None
        titulo = (titulo_el.get_text(strip=True) if titulo_el else '') \
            or a_tag.get('title', '') or slug.replace('-', ' ')
        titulo = titulo.strip()
        img_el = contenedor.select_one('img') if contenedor else None
        img_src = (img_el.get('src') or img_el.get('data-src') or img_el.get('data-lazy-src') or '') if img_el else ''
        if img_src.startswith('http'):
            img_url = img_src
        elif img_src.startswith('//'):
            img_url = 'https:' + img_src
        elif img_src:
            img_url = TIOANIME_URL + img_src
        else:
            img_url = ''
        ep_url = href if href.startswith('http') else TIOANIME_URL + href
        norm_slug = re.sub(r'-(?:sub|hd|fhd|1080p|720p|480p)$', '', slug, flags=re.IGNORECASE).lower()
        eid = f"{norm_slug}-{ep_num}"
        return {'id': eid, 'slug': norm_slug, 'titulo': titulo, 'epNum': ep_num, 'epUrl': ep_url, 'imgUrl': img_url}

    for el in candidatos:
        a_tag = el.find('a')
        item = _parse(a_tag, el)
        if item and item['id'] not in ids:
            ids.add(item['id'])
            lista.append(item)

    if not lista:
        for a_tag in soup.select('a[href*="/ver/"]'):
            href = a_tag.get('href', '')
            m = re.search(r'/ver/(.+?)[-_](\d+)/?$', href)
            if not m:
                continue
            slug, ep_num = m.group(1), int(m.group(2))
            titulo = (a_tag.get('title') or a_tag.get_text(strip=True) or slug.replace('-', ' ')).strip()
            ep_url = href if href.startswith('http') else TIOANIME_URL + href
            norm_slug = re.sub(r'-(?:sub|hd|fhd|1080p|720p|480p)$', '', slug, flags=re.IGNORECASE).lower()
            eid = f"{norm_slug}-{ep_num}"
            if eid not in ids:
                ids.add(eid)
                lista.append({'id': eid, 'slug': norm_slug, 'titulo': titulo, 'epNum': ep_num, 'epUrl': ep_url, 'imgUrl': ''})

    logger.info(f"[tioanime-notify] {len(lista)} episodios en portada")
    return lista


async def scrape_servidores(ep_url: str) -> list[dict]:
    res = await _get(ep_url, headers={**HEADERS, 'Referer': TIOANIME_URL})
    soup = BeautifulSoup(res.text, 'html.parser')
    srvs: list[dict] = []
    urls_vistos = set()

    m_slug = re.search(r'/ver/(.+)$', ep_url)
    ep_slug = m_slug.group(1).rstrip('/') if m_slug else ''

    def _push(nombre, url, directo):
        if url in urls_vistos:
            return
        urls_vistos.add(url)
        srvs.append({'nombre': nombre, 'url': url, 'directo': directo})

    if ep_slug:
        try:
            api_url = f"{TIOANIME_URL}/api/download?episode={ep_slug}"
            api_res = await _get(api_url, headers={**HEADERS, 'Referer': ep_url, 'X-Requested-With': 'XMLHttpRequest'}, timeout=12)
            data = api_res.json()
            descargas = data if isinstance(data, list) else (data.get('downloads') or data.get('data') or [])
            for d in descargas:
                url = d.get('url') or d.get('link') or d.get('href') or ''
                nombre = (d.get('server') or d.get('name') or d.get('label') or '').lower()
                if not url.startswith('http') or url in urls_vistos:
                    continue
                if 'hqq.tv' in url or 'netu.tv' in url or 'netu.ac' in url:
                    continue
                es_mega = 'mega.nz' in url or 'mega.co.nz' in url
                es_mediafire = 'mediafire.com' in url
                _push('mega' if es_mega else 'mediafire' if es_mediafire else nombre, url, es_mega or es_mediafire)
        except Exception:
            pass

    for a_tag in soup.select('a[href]'):
        href = a_tag.get('href', '')
        if not href.startswith('http') or href in urls_vistos:
            continue
        es_mega = 'mega.nz' in href or 'mega.co.nz' in href
        es_mediafire = 'mediafire.com' in href
        es_otro = 'gofile.io' in href or '1fichier' in href or 'pixeldrain' in href
        sin_soporte = 'hqq.tv' in href or 'netu.tv' in href
        if sin_soporte or not (es_mega or es_mediafire or es_otro):
            continue
        label = a_tag.get_text(strip=True).lower()
        _push('mega' if es_mega else 'mediafire' if es_mediafire else (label or 'descarga'), href, True)

    for script in soup.find_all('script'):
        code = script.string or script.get_text() or ''
        if 'var videos' not in code:
            continue
        m = re.search(r'var\s+videos\s*=\s*(\[\s*\[[\s\S]*?\]\s*\])\s*[;,]?', code)
        if m:
            try:
                for item in json.loads(m.group(1)):
                    if not isinstance(item, list) or not str(item[1]).startswith('http'):
                        continue
                    url = item[1]
                    if url in urls_vistos:
                        continue
                    if 'hqq.tv' in url or 'netu.tv' in url or 'netu.ac' in url:
                        continue
                    es_mega = 'mega.nz' in url or 'mega.co.nz' in url
                    es_mediafire = 'mediafire.com' in url
                    _push('mega' if es_mega else 'mediafire' if es_mediafire else str(item[0]).lower(), url, es_mega or es_mediafire)
            except Exception:
                pass
        m_arr = re.search(r'var\s+videos\s*=\s*(\[[\s\S]*?\]);', code)
        if m_arr and not any(not s['directo'] for s in srvs):
            try:
                for item in json.loads(m_arr.group(1)):
                    url = (item or {}).get('url') or (item or {}).get('file') or (item or {}).get('code') or ''
                    nom = ((item or {}).get('title') or (item or {}).get('label') or (item or {}).get('server') or '').lower()
                    if not url.startswith('http') or url in urls_vistos:
                        continue
                    if 'hqq.tv' in url or 'netu.tv' in url or 'netu.ac' in url:
                        continue
                    es_mega = 'mega.nz' in url
                    _push('mega' if es_mega else (nom or url), url, es_mega)
            except Exception:
                pass

    if not srvs:
        for iframe in soup.select('iframe[src]'):
            src = iframe.get('src', '')
            if src.startswith('http'):
                _push('iframe', src, False)

    return srvs


# ─── Scraping — LatAnime ──────────────────────────────────────────────────────

async def fetch_latest_episodes_latanime() -> list[dict]:
    res = await _get(LATANIME_URL)
    soup = BeautifulSoup(res.text, 'html.parser')
    lista: list[dict] = []
    ids = set()

    for a_tag in soup.select('a[href*="/ver/"]'):
        href = a_tag.get('href', '')
        m = re.search(r'/ver/(.+?)[-_](\d+)(?:-[a-z]+)?(?:/|$)', href)
        if not m:
            continue
        slug, ep_num = m.group(1), int(m.group(2))
        t_attr = (a_tag.get('title') or '').strip()
        t_find_el = a_tag.select_one('h3, h2, p, span, [class*="title"], [class*="name"]')
        t_find = t_find_el.get_text(strip=True) if t_find_el else ''
        t_slug = re.sub(r'-episodio$', '', slug, flags=re.IGNORECASE).replace('-', ' ').strip()
        titulo = t_attr or t_find or t_slug
        img_el = a_tag.select_one('img')
        img_src = ''
        if img_el:
            img_src = (img_el.get('data-src') or img_el.get('data-lazy') or img_el.get('data-original')
                       or img_el.get('data-lazy-src') or img_el.get('src') or '')
        if not img_src or img_src.startswith('data:'):
            img_url = ''
        elif img_src.startswith('http'):
            img_url = img_src
        else:
            img_url = LATANIME_URL + img_src
        ep_url = href if href.startswith('http') else LATANIME_URL + href
        norm_slug = re.sub(r'-episodio$', '', slug, flags=re.IGNORECASE)
        norm_slug = re.sub(r'-(?:castellano|latino|espanol|español|esp|sub|dub|hd)$', '', norm_slug, flags=re.IGNORECASE)
        norm_slug = re.sub(r'-episodio$', '', norm_slug, flags=re.IGNORECASE).lower()
        eid = f"lat-{norm_slug}-{ep_num}"
        idioma = 'castellano' if 'castellano' in href.lower() else 'latino'
        if eid not in ids:
            ids.add(eid)
            lista.append({'id': eid, 'slug': slug, 'titulo': titulo, 'epNum': ep_num, 'epUrl': ep_url,
                           'imgUrl': img_url, 'fuente': 'latanime', 'idioma': idioma})
    return lista


async def scrape_servidores_latanime(ep_url: str) -> list[dict]:
    res = await _get(ep_url, headers={**HEADERS, 'Referer': LATANIME_URL})
    soup = BeautifulSoup(res.text, 'html.parser')
    srvs: list[dict] = []
    urls_vistos = set()

    for a_tag in soup.select('a[href]'):
        href = a_tag.get('href', '')
        label = a_tag.get_text(strip=True).lower()
        if not href.startswith('http') or href in urls_vistos:
            continue

        es_mega = 'mega.nz' in href
        es_mediafire = 'mediafire.com' in href
        es_otro = any(d in href for d in ['voe.sx', 'streamtape', 'filemoon', 'mp4upload', 'streamwish',
                                           'dood', 'upstream', 'ok.ru', 'vidhide', 'mixdrop', 'savefiles',
                                           'gofile.io', 'byse'])
        es_redirector = ('latanime.org' not in href and 'javascript' not in href and '#' not in href
                          and len(href) > 20 and not re.search(r'\.(jpg|png|gif|css|js)$', href))

        urls_vistos.add(href)
        if es_mega or es_mediafire:
            srvs.append({'nombre': 'mega' if es_mega else 'mediafire', 'url': href, 'directo': True})
        elif es_otro:
            srvs.append({'nombre': label or detectar_serv_nombre(href), 'url': href, 'directo': False})
        elif es_redirector:
            srvs.append({'nombre': label or 'redir', 'url': href, 'directo': False, 'esRedirector': True})

    dominios = ['mega.nz', 'mediafire.com', 'voe.sx', 'streamtape', 'filemoon', 'mp4upload',
                'streamwish', 'dood', 'ok.ru']
    for r in [s for s in srvs if s.get('esRedirector')]:
        try:
            resp = await asyncio.to_thread(
                requests.get, r['url'], headers={'User-Agent': UA, 'Referer': LATANIME_URL},
                allow_redirects=True, timeout=10
            )
            body = resp.text if isinstance(resp.text, str) else ''
            final_url = resp.url or ''
            url_real = None
            for d in dominios:
                m = re.search(rf'https?://[^"\'\s]*{re.escape(d)}[^"\'\s]*', body)
                if m:
                    url_real = m.group(0)
                    break
            if not url_real and final_url and any(d in final_url for d in dominios):
                url_real = final_url
            idx = next((i for i, s in enumerate(srvs) if s['url'] == r['url']), -1)
            if url_real and idx != -1:
                srvs[idx]['url'] = url_real
                srvs[idx]['nombre'] = 'mediafire' if 'mediafire' in url_real else 'mega' if 'mega.nz' in url_real else detectar_serv_nombre(url_real)
                srvs[idx]['directo'] = 'mega.nz' in url_real or 'mediafire.com' in url_real
                srvs[idx].pop('esRedirector', None)
            elif idx != -1:
                srvs.pop(idx)
        except Exception:
            idx = next((i for i, s in enumerate(srvs) if s['url'] == r['url']), -1)
            if idx != -1:
                srvs.pop(idx)

    for el in soup.select('[data-src], [data-player], [data-url], iframe[src]'):
        raw = el.get('data-src') or el.get('data-player') or el.get('data-url') or el.get('src') or ''
        embed_url = raw
        try:
            import base64
            decoded = base64.b64decode(raw).decode('utf-8', errors='ignore')
            if decoded.startswith('http'):
                embed_url = decoded
        except Exception:
            pass
        if embed_url.startswith('http') and not any(s['url'] == embed_url for s in srvs):
            srvs.append({'nombre': detectar_serv_nombre(embed_url), 'url': embed_url, 'directo': False})

    return srvs


def ordenar_servidores(srvs: list[dict], fuente: str = 'tioanime') -> list[dict]:
    mega = [s for s in srvs if s['nombre'] == 'mega']
    mediafire = [s for s in srvs if s['nombre'] == 'mediafire']
    otros = [s for s in srvs if s['directo'] and s['nombre'] not in ('mega', 'mediafire')]

    def _pref_idx(s):
        for i, p in enumerate(PREFS_EMBED):
            if p in s['nombre'] or p in s['url']:
                return i
        return 99

    embeds = sorted([s for s in srvs if not s['directo']], key=_pref_idx)

    if fuente == 'latanime':
        return mediafire + mega + otros + embeds
    return mega + mediafire + otros + embeds


# ─── Envío de episodio ────────────────────────────────────────────────────────

async def enviar_episodio(chat_id: int, ep: dict, client) -> None:
    titulo   = ep['titulo']
    ep_num   = ep['epNum']
    ep_url   = ep['epUrl']
    img_url  = ep.get('imgUrl', '')
    fuente   = ep.get('fuente', 'tioanime')
    idioma   = ep.get('idioma', 'latino')
    file_name = build_file_name(titulo, ep_num)

    work_dir = STATE_FILE.parent.parent / 'temp_videos'
    work_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = work_dir / f"tio_{int(time.time() * 1000)}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    bandera  = ('🇪🇸' if idioma == 'castellano' else '🇲🇽') if fuente == 'latanime' else '🇯🇵'
    etiqueta = f"LatAnime {bandera}" if fuente == 'latanime' else 'TioAnime 🇯🇵'

    try:
        ahora = time.strftime('%I:%M %p')
        caption = (
            f"<b>✨ Nuevo Episodio ✨</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"{bandera} <b>{titulo}</b>\n"
            f"🆕 Capítulo: <b>{ep_num}</b>\n"
            f"🕐 Publicado: <b>{ahora}</b>\n"
            f"🌐 Ver online: {ep_url}\n"
            f"📡 Fuente: <b>{etiqueta}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ <i>INICIANDO DESCARGA...</i>"
        )

        if img_url:
            try:
                await client.send_photo(chat_id, img_url, caption=caption, parse_mode=enums.ParseMode.HTML)
            except Exception:
                await client.send_message(chat_id, caption, parse_mode=enums.ParseMode.HTML)
        else:
            await client.send_message(chat_id, caption, parse_mode=enums.ParseMode.HTML)

        logger.info(f"[tioanime-notify] Buscando servidores para \"{titulo}\" ep {ep_num}...")
        srvs = (await scrape_servidores_latanime(ep_url)) if fuente == 'latanime' else (await scrape_servidores(ep_url))
        if not srvs:
            raise RuntimeError('No se encontraron servidores')

        await asyncio.sleep(15)
        orden = ordenar_servidores(srvs, fuente)[:5]
        video_path = None

        for srv in orden:
            nombre_servidor = (srv.get('nombre') or 'servidor').upper()
            # Igual que el JS: solo mega y mediafire tienen soporte de descarga.
            if srv['nombre'] not in ('mega', 'mediafire'):
                continue
            try:
                logger.info(f"[tioanime-notify] Conectando con [ {nombre_servidor} ]...")
                if srv['nombre'] == 'mega':
                    ok, fpath, err = await MEGADownloader.download(srv['url'], tmp_dir)
                else:
                    ok, fpath, err = await MediaFireDownloader.download(srv['url'], tmp_dir)

                if ok and fpath:
                    video_path = fpath
                    break
                else:
                    logger.info(f"[tioanime-notify] [ {nombre_servidor} ] falló: {err}")
            except Exception as e:
                logger.info(f"[tioanime-notify] [ {nombre_servidor} ] falló: {e}")

            for f in tmp_dir.glob('*'):
                if f.name != 'cover.jpg':
                    try:
                        f.unlink()
                    except Exception:
                        pass

        if not video_path:
            raise RuntimeError('Todos los servidores fallaron')

        size_mb = video_path.stat().st_size / 1024 / 1024
        logger.info(f"[tioanime-notify] Descarga completa: {file_name} ({size_mb:.1f} MB) — subiendo a Telegram...")

        final_caption = f"✅ <b>{titulo}</b>\n📌 Episodio {zero_pad(ep_num)}\n📦 {size_mb:.1f} MB · {etiqueta}"
        video_exts = {'.mp4', '.mkv', '.avi', '.mov', '.webm'}
        if video_path.suffix.lower() in video_exts:
            # Generar duración + miniatura real con ffprobe/ffmpeg (si no,
            # Telegram muestra 0:00 y sin thumbnail, como pasaba antes).
            duration, thumb, width, height = await _video_meta(video_path, tmp_dir)
            await client.send_video(
                chat_id, str(video_path), caption=final_caption,
                parse_mode=enums.ParseMode.HTML, supports_streaming=True,
                file_name=file_name,
                duration=duration or 0,
                thumb=thumb,
                width=width or 0,
                height=height or 0,
            )
        else:
            await client.send_document(chat_id, str(video_path), caption=final_caption,
                                        parse_mode=enums.ParseMode.HTML, file_name=file_name)

        logger.info(f"[tioanime-notify] Enviado: {file_name}")

    finally:
        try:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass


# ─── Cola ─────────────────────────────────────────────────────────────────────

async def procesar_cola() -> None:
    global _queue_running
    if _queue_running or not _episode_queue:
        return
    _queue_running = True

    try:
        while _episode_queue:
            item = _episode_queue[0]
            chat_id, ep = item['chat_id'], item['ep']
            intentos, exito = 0, False

            while intentos < MAX_REINTENTOS and not exito:
                intentos += 1
                client = _client
                if not client:
                    await asyncio.sleep(ESPERA_REINTENTO)
                    continue
                try:
                    await enviar_episodio(chat_id, ep, client)
                    exito = True
                    _episode_queue.pop(0)
                except Exception as err:
                    msg = str(err).lower()
                    es_conexion = any(s in msg for s in [
                        'connection closed', 'stream errored', 'timed out', 'econnreset',
                        'socket hang up', 'precondition required'])
                    if es_conexion and intentos < MAX_REINTENTOS:
                        await asyncio.sleep(ESPERA_REINTENTO * intentos)
                    elif es_conexion:
                        _episode_queue.pop(0)
                        _episode_queue.append({'chat_id': chat_id, 'ep': ep})
                        await asyncio.sleep(ESPERA_REQUEUE)
                        break
                    else:
                        _episode_queue.pop(0)
                        try:
                            if _client:
                                await _client.send_message(
                                    chat_id,
                                    f"❌ Error enviando <b>{ep['titulo']}</b> ep <b>{zero_pad(ep['epNum'])}</b>:\n{err}",
                                    parse_mode=enums.ParseMode.HTML
                                )
                        except Exception:
                            pass
            if _episode_queue:
                await asyncio.sleep(QUEUE_DELAY)
    finally:
        _queue_running = False


async def check_nuevos_episodios(chat_id: int, client) -> None:
    lista = []
    try:
        lista += await fetch_latest_episodes()
    except Exception:
        pass
    try:
        lista += await fetch_latest_episodes_latanime()
    except Exception:
        pass
    if not lista:
        return

    seen = load_seen()
    vistos_chat = seen.setdefault(str(chat_id), [])
    nuevos = [e for e in lista if e['id'] not in vistos_chat]
    if not nuevos:
        return

    for e in nuevos:
        vistos_chat.append(e['id'])
    if len(vistos_chat) > 500:
        seen[str(chat_id)] = vistos_chat[-500:]
    save_seen(seen)

    if len(nuevos) > 1:
        try:
            texto = f"📋 <b>{len(nuevos)} episodios nuevos detectados</b>\n\n" + \
                "\n".join(f"{i + 1}. <b>{e['titulo']}</b> — Ep {zero_pad(e['epNum'])}" for i, e in enumerate(nuevos)) + \
                "\n\n⏳ <i>Se enviarán de uno en uno...</i>"
            await client.send_message(chat_id, texto, parse_mode=enums.ParseMode.HTML)
        except Exception:
            pass

    for e in nuevos:
        _episode_queue.append({'chat_id': chat_id, 'ep': e})
    _create_task(procesar_cola())


# ─── Notificador periódico por chat (reemplaza setInterval del JS) ───────────

async def _notifier_loop(chat_id: int, interval_min: int) -> None:
    try:
        while True:
            await asyncio.sleep(interval_min * 60)
            client = _client
            if not client:
                continue
            try:
                await check_nuevos_episodios(chat_id, client)
            except Exception:
                pass
    except asyncio.CancelledError:
        pass


def iniciar_notificador(chat_id: int, client, interval_min: int = CHECK_INTERVAL_DEFAULT) -> None:
    global _client
    if client:
        _client = client
    prev = _active_notifiers.get(chat_id)
    if prev:
        prev.cancel()
    _active_notifiers[chat_id] = _create_task(_notifier_loop(chat_id, interval_min))
    _notifier_interval[chat_id] = interval_min

    state = load_state()
    state[str(chat_id)] = {'intervalMin': interval_min, 'startedAt': int(time.time() * 1000)}
    save_state(state)


def detener_notificador(chat_id: int) -> None:
    task = _active_notifiers.pop(chat_id, None)
    _notifier_interval.pop(chat_id, None)
    if task:
        task.cancel()
    state = load_state()
    state.pop(str(chat_id), None)
    save_state(state)


def restaurar_notificadores(client) -> None:
    global _client
    if client:
        _client = client
    state = load_state()
    for chat_id_str, cfg in state.items():
        chat_id = int(chat_id_str)
        if chat_id not in _active_notifiers:
            iniciar_notificador(chat_id, client, cfg.get('intervalMin', CHECK_INTERVAL_DEFAULT))


# ─── Registro de comandos (Pyrogram) ─────────────────────────────────────────

def register(app, work_dir: Path):
    """Registra los comandos tio*/lat* en el bot. work_dir es el mismo Path que
    usan otros handlers de Zero Two (ver main.py)."""
    global SEEN_FILE, STATE_FILE, _client, _loop
    _client = app
    _loop = getattr(app, 'loop', None)

    db_dir = Path(work_dir) / 'database'
    db_dir.mkdir(parents=True, exist_ok=True)
    SEEN_FILE = db_dir / 'tioanime_seen.json'
    STATE_FILE = db_dir / 'tioanime_state.json'

    # NOTA: no llamamos restaurar_notificadores() acá directamente, porque
    # register() se ejecuta ANTES de que arranque el loop de asyncio
    # (main.py llama app.loop.run_until_complete(...) recién al final).
    # asyncio.create_task()/loop.create_task() en ese punto puede fallar
    # ("no running event loop") según la versión de Python/Pyrogram.
    # En vez de eso, restauramos los notificadores en cada update entrante
    # (igual que el handler.before del plugin original de WhatsApp);
    # iniciar_notificador() ya evita duplicar tasks si el chat ya está activo.
    @app.on_message(filters.all, group=-1)
    async def _tio_bootstrap(client, message: Message):
        try:
            restaurar_notificadores(client)
        except Exception as e:
            logger.error(f"[tioanime-notify] Error restaurando notificadores: {e}")

    async def _guard_owner(message: Message, command: str) -> bool:
        if command in COMANDOS_OWNER and not _is_owner(message.from_user.id):
            await message.reply_text("⛔ Solo el <b>owner</b> puede usar este comando.", parse_mode=enums.ParseMode.HTML)
            return False
        return True

    @app.on_message(filters.command('tiostart'))
    async def tiostart_cmd(client, message: Message):
        if not await _guard_owner(message, 'tiostart'):
            return
        args = message.text.split(maxsplit=1)
        try:
            mn = int(args[1].strip()) if len(args) > 1 else None
        except ValueError:
            mn = None
        interval_min = mn if (mn is not None and 5 <= mn <= 60) else CHECK_INTERVAL_DEFAULT
        iniciar_notificador(message.chat.id, client, interval_min)
        await message.reply_text(
            f"✅ <b>Notificador TioAnime + LatAnime activado</b>\n\n"
            f"╭━━━━━━〔 📡 〕━━━━━━\n"
            f"┃ ⏱️ Intervalo: <b>{interval_min} min</b>\n"
            f"┃ 🇯🇵 TioAnime — Sub japonés\n"
            f"┃ 🇲🇽🇪🇸 LatAnime — Latino / Castellano\n"
            f"┃ 💬 Chat registrado\n"
            f"╰━━━━━━━━━━━━━━━━━━\n\n"
            f"<i>Usa /tiostop para detener.</i>",
            parse_mode=enums.ParseMode.HTML
        )
        try:
            tio = await fetch_latest_episodes()
            lat = await fetch_latest_episodes_latanime()
            lista = tio + lat
            seen = load_seen()
            vistos = seen.setdefault(str(message.chat.id), [])
            for e in lista:
                if e['id'] not in vistos:
                    vistos.append(e['id'])
            if len(vistos) > 500:
                seen[str(message.chat.id)] = vistos[-500:]
            save_seen(seen)
            await message.reply_text(
                f"📋 <b>{len(tio)}</b> ep TioAnime + <b>{len(lat)}</b> ep LatAnime registrados como base.\n"
                f"<i>Solo los nuevos se enviarán.</i>",
                parse_mode=enums.ParseMode.HTML
            )
        except Exception:
            pass

    @app.on_message(filters.command('tiostop'))
    async def tiostop_cmd(client, message: Message):
        if not await _guard_owner(message, 'tiostop'):
            return
        if message.chat.id not in _active_notifiers:
            await message.reply_text("ℹ️ El notificador no estaba activo.")
            return
        detener_notificador(message.chat.id)
        await message.reply_text("🛑 <b>Notificador detenido.</b>\n<i>Usa /tiostart para reactivar.</i>", parse_mode=enums.ParseMode.HTML)

    @app.on_message(filters.command('tiostatus'))
    async def tiostatus_cmd(client, message: Message):
        activo = message.chat.id in _active_notifiers
        interval_min = _notifier_interval.get(message.chat.id)
        cola = [i for i in _episode_queue if i['chat_id'] == message.chat.id]
        vistos = len(load_seen().get(str(message.chat.id), []))
        txt = "📡 <b>Estado TioAnime</b>\n\n"
        txt += f"✅ <b>Activo</b> — cada {interval_min} min\n" if activo else "🔴 <b>Inactivo</b>\n"
        txt += f"📋 Cola: <b>{len(cola)}</b> pendiente(s)\n"
        txt += f"🔵 Procesando: <b>{'Sí' if _queue_running else 'No'}</b>\n"
        txt += f"👁️ Vistos: <b>{vistos}</b>"
        if cola:
            txt += "\n\n<b>En cola:</b>\n" + "\n".join(
                f"  {n + 1}. {i['ep']['titulo']} ep {zero_pad(i['ep']['epNum'])}" for n, i in enumerate(cola[:5])
            )
        await message.reply_text(txt, parse_mode=enums.ParseMode.HTML)

    @app.on_message(filters.command('tioqueue'))
    async def tioqueue_cmd(client, message: Message):
        if not _episode_queue:
            await message.reply_text("✅ Cola vacía.")
            return
        txt = f"📋 <b>Cola ({len(_episode_queue)}):</b>\n\n" + "\n".join(
            f"{n + 1}. <b>{i['ep']['titulo']}</b> ep {zero_pad(i['ep']['epNum'])} "
            f"[{'este chat' if i['chat_id'] == message.chat.id else 'otro chat'}]"
            for n, i in enumerate(_episode_queue)
        )
        await message.reply_text(txt, parse_mode=enums.ParseMode.HTML)

    @app.on_message(filters.command('tioflush'))
    async def tioflush_cmd(client, message: Message):
        if not await _guard_owner(message, 'tioflush'):
            return
        antes = len(_episode_queue)
        _episode_queue[:] = [i for i in _episode_queue if i['chat_id'] != message.chat.id]
        await message.reply_text(f"🗑️ <b>{antes - len(_episode_queue)}</b> episodio(s) eliminado(s).", parse_mode=enums.ParseMode.HTML)

    @app.on_message(filters.command('tiounblock'))
    async def tiounblock_cmd(client, message: Message):
        global _queue_running
        if not await _guard_owner(message, 'tiounblock'):
            return
        estaba = _queue_running
        _queue_running = False
        if _episode_queue:
            await message.reply_text(
                f"🔓 Cola desbloqueada{' (estaba trabada)' if estaba else ''}.\n"
                f"▶️ Reanudando {len(_episode_queue)} episodio(s)...",
                parse_mode=enums.ParseMode.HTML
            )
            _create_task(procesar_cola())
        else:
            await message.reply_text(
                f"🔓 Cola desbloqueada{' (estaba trabada)' if estaba else ''}.\nℹ️ No hay episodios pendientes.",
                parse_mode=enums.ParseMode.HTML
            )

    @app.on_message(filters.command('tiocheck'))
    async def tiocheck_cmd(client, message: Message):
        await message.reply_text("🔍 Chequeando TioAnime...")
        try:
            await check_nuevos_episodios(message.chat.id, client)
            if not any(i['chat_id'] == message.chat.id for i in _episode_queue):
                await message.reply_text("✅ Sin episodios nuevos.")
        except Exception as e:
            await message.reply_text(f"❌ Error: {e}")

    @app.on_message(filters.command('tiointerval'))
    async def tiointerval_cmd(client, message: Message):
        if not await _guard_owner(message, 'tiointerval'):
            return
        args = message.text.split(maxsplit=1)
        try:
            mn = int(args[1].strip()) if len(args) > 1 else None
        except ValueError:
            mn = None
        if mn is None or not (5 <= mn <= 60):
            await message.reply_text("❌ Número entre <b>5</b> y <b>60</b>.\nEj: <code>/tiointerval 15</code>", parse_mode=enums.ParseMode.HTML)
            return
        if message.chat.id not in _active_notifiers:
            await message.reply_text("⚠️ Usa <b>/tiostart</b> primero.", parse_mode=enums.ParseMode.HTML)
            return
        iniciar_notificador(message.chat.id, client, mn)
        await message.reply_text(f"⏱️ Intervalo actualizado a <b>{mn} minutos</b>.", parse_mode=enums.ParseMode.HTML)

    @app.on_message(filters.command('tioexample'))
    async def tioexample_cmd(client, message: Message):
        args = message.text.split(maxsplit=1)
        try:
            cantidad = min(max(int(args[1].strip()), 1), 10) if len(args) > 1 else 1
        except ValueError:
            cantidad = 1
        await message.reply_text(f"🔍 Obteniendo los <b>{cantidad}</b> episodio(s) más reciente(s) de <b>TioAnime</b>...", parse_mode=enums.ParseMode.HTML)
        try:
            lista = await fetch_latest_episodes()
            if not lista:
                await message.reply_text("❌ Sin episodios de TioAnime disponibles. Intenta más tarde.")
                return
        except Exception as e:
            await message.reply_text(f"❌ Error: {e}")
            return

        seleccion = lista[:cantidad]
        if len(seleccion) > 1:
            txt = f"📋 <b>{len(seleccion)} episodios seleccionados (TioAnime):</b>\n\n" + \
                "\n".join(f"{i + 1}. <b>{e['titulo']}</b> — Ep {zero_pad(e['epNum'])}" for i, e in enumerate(seleccion)) + \
                "\n\n⏳ <i>Se enviarán de uno en uno...</i>"
            await message.reply_text(txt, parse_mode=enums.ParseMode.HTML)

        for e in seleccion:
            _episode_queue.append({'chat_id': message.chat.id, 'ep': e})
        _create_task(procesar_cola())

    @app.on_message(filters.command('latexample'))
    async def latexample_cmd(client, message: Message):
        args = message.text.split(maxsplit=1)
        try:
            cantidad = min(max(int(args[1].strip()), 1), 10) if len(args) > 1 else 1
        except ValueError:
            cantidad = 1
        await message.reply_text(f"🔍 Obteniendo los <b>{cantidad}</b> episodio(s) más reciente(s) de <b>LatAnime</b>...", parse_mode=enums.ParseMode.HTML)
        try:
            lista = await fetch_latest_episodes_latanime()
            if not lista:
                await message.reply_text("❌ Sin episodios de LatAnime disponibles. Intenta más tarde.")
                return
        except Exception as e:
            await message.reply_text(f"❌ Error: {e}")
            return

        seleccion = lista[:cantidad]
        if len(seleccion) > 1:
            txt = f"📋 <b>{len(seleccion)} episodios seleccionados (LatAnime):</b>\n\n" + \
                "\n".join(f"{i + 1}. <b>{e['titulo']}</b> — Ep {zero_pad(e['epNum'])}" for i, e in enumerate(seleccion)) + \
                "\n\n⏳ <i>Se enviarán de uno en uno...</i>"
            await message.reply_text(txt, parse_mode=enums.ParseMode.HTML)

        for e in seleccion:
            _episode_queue.append({'chat_id': message.chat.id, 'ep': e})
        _create_task(procesar_cola())

    logger.info("[tioanime-notify] Handler registrado (comandos tio*/latexample)")
