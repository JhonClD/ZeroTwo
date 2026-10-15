"""
drive_downloader.py - Descargas públicas de Drive y subidas OAuth con progreso.
Las dependencias de Google OAuth/API solo se requieren para subir archivos.
"""

import asyncio
import logging
import mimetypes
import re
import subprocess
from email.message import Message as EmailMessage
from pathlib import Path

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)
DRIVE_DOWNLOAD_URL = 'https://drive.google.com/uc'
DRIVE_HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36'}

# ── Importación opcional de las librerías de Google ───────────────────────────
try:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    GOOGLE_AVAILABLE = True
except ImportError:
    GOOGLE_AVAILABLE = False
    logger.debug("Dependencias de Google ausentes; OAuth solo se necesita para subir a Drive.")

SCOPES = ['https://www.googleapis.com/auth/drive']

# Ruta del token y credenciales (junto al módulo)
_BASE = Path(__file__).parent
TOKEN_PATH  = _BASE / 'drive_token.json'
CREDS_PATH  = _BASE / 'drive_credentials.json'


def _get_service():
    """Devuelve un cliente autenticado de Google Drive API v3."""
    if not GOOGLE_AVAILABLE:
        raise RuntimeError("Instala: pip install google-auth-oauthlib google-api-python-client")
    if not CREDS_PATH.exists():
        raise FileNotFoundError(
            f"No se encontró {CREDS_PATH}.\n"
            "Descarga tu credentials.json desde Google Cloud Console y renómbralo."
        )

    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_PATH), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_PATH.write_text(creds.to_json())

    return build('drive', 'v3', credentials=creds)


def _extract_file_id(url_or_id: str) -> str:
    """Extrae el ID de archivo de una URL de Drive o lo devuelve tal cual."""
    import re
    patterns = [
        r'/(?:file|document|spreadsheets|presentation)/d/([a-zA-Z0-9_-]+)',
        r'id=([a-zA-Z0-9_-]+)',
        r'^([a-zA-Z0-9_-]{25,})$',
    ]
    for pat in patterns:
        m = re.search(pat, url_or_id)
        if m:
            return m.group(1)
    return url_or_id


def _open_public_drive_response(session: requests.Session, file_id: str):
    """Abre la descarga de un archivo compartido públicamente, sin OAuth/API."""
    params = {'export': 'download', 'id': file_id}
    response = session.get(
        DRIVE_DOWNLOAD_URL, params=params, headers=DRIVE_HEADERS,
        stream=True, timeout=(20, 60), allow_redirects=True,
    )
    if response.status_code == 403:
        response.close()
        raise requests.HTTPError('Google Drive respondió HTTP 403; revisa que el archivo sea público.', response=response)
    response.raise_for_status()

    content_type = response.headers.get('Content-Type', '').lower()
    # Los archivos HTML compartidos también pueden ser descargables; la página
    # intermedia de confirmación/permisos normalmente no trae Content-Disposition.
    if 'text/html' in content_type and not response.headers.get('Content-Disposition'):
        html = response.text
        token = next(
            (value for key, value in session.cookies.items() if key.startswith('download_warning')),
            None,
        )
        if not token:
            soup = BeautifulSoup(html, 'html.parser')
            confirm = soup.select_one('input[name="confirm"][value]')
            token = confirm.get('value') if confirm else None
        if not token:
            match = re.search(r'[?&]confirm=([\w-]+)', html)
            token = match.group(1) if match else None
        response.close()
        if not token:
            raise PermissionError(
                'No se pudo descargar el archivo sin iniciar sesión. '
                'En Google Drive, compártelo como «Cualquier persona con el enlace». '
                'Los documentos de Google (Docs/Sheets) requieren exportación.'
            )

        params['confirm'] = token
        response = session.get(
            DRIVE_DOWNLOAD_URL, params=params, headers=DRIVE_HEADERS,
            stream=True, timeout=(20, 60), allow_redirects=True,
        )
        if response.status_code == 403:
            response.close()
            raise requests.HTTPError('Google Drive respondió HTTP 403 al confirmar la descarga.', response=response)
        response.raise_for_status()
        if ('text/html' in response.headers.get('Content-Type', '').lower()
                and not response.headers.get('Content-Disposition')):
            response.close()
            raise PermissionError(
                'Google Drive no entregó el archivo. Comprueba que el enlace sea público '
                'y que permita descargarlo.'
            )
    return response


def _drive_filename(response, file_id: str) -> str:
    disposition = response.headers.get('Content-Disposition', '')
    filename = None
    if disposition:
        header = EmailMessage()
        header['Content-Disposition'] = disposition
        filename = header.get_filename()
    if not filename:
        filename = f'drive_file_{file_id}'
        extension = mimetypes.guess_extension(
            response.headers.get('Content-Type', '').split(';', 1)[0].strip()
        )
        if extension:
            filename += extension
    filename = Path(filename).name
    filename = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '_', filename).strip(' .')
    return filename or f'drive_file_{file_id}'


def _download_public_drive_file(file_id: str, output_dir: Path, progress_update=None) -> Path:
    """Descarga un enlace público de Drive por HTTP y guarda el nombre real."""
    session = requests.Session()
    response = _open_public_drive_response(session, file_id)
    output_path = output_dir / _drive_filename(response, file_id)
    total = int(response.headers.get('Content-Length') or 0)
    downloaded = 0
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        with output_path.open('wb') as output:
            for chunk in response.iter_content(chunk_size=8 * 1024 * 1024):
                if not chunk:
                    continue
                output.write(chunk)
                downloaded += len(chunk)
                if progress_update:
                    progress_update(downloaded, total)
        if downloaded == 0:
            raise ValueError('Google Drive devolvió un archivo vacío.')
        return output_path
    except Exception:
        output_path.unlink(missing_ok=True)
        raise
    finally:
        response.close()


def _take_screenshot(video_path: Path, timestamp: str, output_path: Path) -> bool:
    """Captura un fotograma del video en el timestamp indicado."""
    try:
        cmd = [
            'ffmpeg', '-y',
            '-ss', timestamp,
            '-i', str(video_path),
            '-vframes', '1',
            '-q:v', '2',
            str(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=30)
        return result.returncode == 0 and output_path.exists()
    except Exception as e:
        logger.warning(f"⚠️ Screenshot en {timestamp} falló: {e}")
        return False


def _get_video_duration(video_path: Path) -> float:
    """Devuelve la duración en segundos del video, o 0.0 si falla."""
    try:
        cmd = [
            'ffprobe', '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            str(video_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return float(result.stdout.strip())
    except Exception:
        return 0.0


def _seconds_to_ts(seconds: float) -> str:
    """Convierte segundos a HH:MM:SS.mmm para ffmpeg."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


async def take_video_screenshots(video_path: Path, work_dir: Path, prefix: str = "shot") -> list[Path]:
    """
    Captura 5 screenshots del video en:
      inicio(5%), cuarto(25%), mitad(50%), tres cuartos(75%), casi final(95%)
    Devuelve lista de paths generados.
    """
    duration = _get_video_duration(video_path)
    if duration < 5:
        logger.warning("⚠️ Video demasiado corto para screenshots")
        return []

    positions = {
        "inicio":      0.05,
        "cuarto":      0.25,
        "mitad":       0.50,
        "tres_cuartos":0.75,
        "final":       0.95,
    }

    shots = []
    for name, ratio in positions.items():
        ts = _seconds_to_ts(duration * ratio)
        out = work_dir / f"{prefix}_{name}.jpg"
        if _take_screenshot(video_path, ts, out):
            shots.append(out)
            logger.info(f"📸 Screenshot '{name}' en {ts}: OK")
        else:
            logger.warning(f"⚠️ Screenshot '{name}' en {ts}: falló")

    return shots


class DriveDownloader:
    """Descarga archivos desde Google Drive con barra de progreso."""

    @staticmethod
    def is_drive_url(url: str) -> bool:
        import re
        return bool(re.search(r'drive\.google\.com|docs\.google\.com', url, re.IGNORECASE))

    @staticmethod
    async def get_file_info(url_or_id: str) -> dict | None:
        """Retorna metadatos básicos de un archivo público, sin usar la API."""
        response = None
        try:
            file_id = _extract_file_id(url_or_id)
            session = requests.Session()
            response = await asyncio.to_thread(_open_public_drive_response, session, file_id)
            return {
                'id': file_id,
                'name': _drive_filename(response, file_id),
                'mimeType': response.headers.get('Content-Type', '').split(';', 1)[0],
                'size': response.headers.get('Content-Length'),
                'webViewLink': f'https://drive.google.com/file/d/{file_id}/view',
            }
        except Exception as e:
            logger.error(f"❌ Error obteniendo info de Drive: {e}")
            return None
        finally:
            if response is not None:
                response.close()

    @staticmethod
    async def download(url_or_id: str, output_dir: Path, progress_callback=None) -> tuple[bool, Path | None, str | None]:
        """
        Descarga un archivo de Google Drive.

        progress_callback(text) → actualiza el mensaje de Telegram.
        Retorna (success, file_path, error_msg).
        """
        try:
            file_id = _extract_file_id(url_or_id)
            output_dir.mkdir(parents=True, exist_ok=True)
            progress_state = [0, 0]
            if progress_callback:
                try:
                    await progress_callback(
                        "📥 <b>Descargando enlace público de Drive</b>\n"
                        "🔓 No se requiere API para archivos compartidos públicamente.\n"
                        "⏳ Iniciando…"
                    )
                except Exception:
                    pass

            def progress_update(downloaded, total):
                progress_state[:] = [downloaded, total]

            task = asyncio.create_task(asyncio.to_thread(
                _download_public_drive_file, file_id, output_dir, progress_update
            ))
            last_reported = -10
            while not task.done():
                await asyncio.sleep(0.5)
                downloaded, total = progress_state
                if total > 0:
                    pct = min(100, int(downloaded * 100 / total))
                    if pct - last_reported >= 10 and progress_callback:
                        downloaded_mb = downloaded / (1024 * 1024)
                        total_mb = total / (1024 * 1024)
                        logger.info(f"📥 Drive {pct}% — {downloaded_mb:.1f}/{total_mb:.1f} MB")
                        try:
                            await progress_callback(
                                f"📥 <b>Descargando de Drive</b>\n"
                                f"{_progress_bar(pct)} {pct}%\n"
                                f"💾 {downloaded_mb:.1f} / {total_mb:.1f} MB"
                            )
                        except Exception:
                            pass
                        last_reported = pct

            output_path = await task
            file_size = output_path.stat().st_size / (1024 * 1024)
            logger.info(f"✅ Drive descargado: {output_path.name} ({file_size:.1f} MB)")
            if progress_callback:
                try:
                    await progress_callback(
                        f"✅ <b>Drive descargado</b>\n📄 {output_path.name}\n📦 {file_size:.1f} MB"
                    )
                except Exception:
                    pass
            return True, output_path, None

        except Exception as e:
            logger.error(f"❌ Error descargando de Drive: {e}", exc_info=True)
            return False, None, str(e)


class DriveUploader:
    """Sube archivos a Google Drive con barra de progreso."""

    @staticmethod
    async def upload(
        file_path: Path,
        folder_id: str | None = None,
        mime_type: str = 'application/octet-stream',
        progress_callback=None,
    ) -> tuple[bool, dict | None, str | None]:
        """
        Sube un archivo a Google Drive.

        progress_callback(text) → actualiza el mensaje de Telegram.
        Retorna (success, file_info_dict, error_msg).
        """
        try:
            service   = _get_service()
            filename  = file_path.name
            total_mb  = file_path.stat().st_size / (1024 * 1024)

            logger.info(f"📤 Drive: subiendo '{filename}' ({total_mb:.1f} MB)")
            if progress_callback:
                await progress_callback(
                    f"📤 <b>Subiendo a Drive</b>\n"
                    f"📄 {filename}\n"
                    f"📦 {total_mb:.1f} MB\n"
                    f"⏳ Iniciando..."
                )

            metadata = {'name': filename}
            if folder_id:
                metadata['parents'] = [folder_id]

            media = MediaFileUpload(
                str(file_path),
                mimetype=mime_type,
                resumable=True,
                chunksize=8 * 1024 * 1024,
            )

            request = service.files().create(
                body=metadata,
                media_body=media,
                fields='id,name,webViewLink',
            )

            last_reported = -10
            response = None
            while response is None:
                status, response = request.next_chunk()
                if status:
                    pct = int(status.progress() * 100)
                    uploaded_mb = (status.resumable_progress or 0) / (1024 * 1024)

                    logger.info(f"📤 Drive {pct}% — {uploaded_mb:.1f}/{total_mb:.1f} MB")

                    if pct - last_reported >= 10 and progress_callback:
                        bar = _progress_bar(pct)
                        await progress_callback(
                            f"📤 <b>Subiendo a Drive</b>\n"
                            f"📄 {filename}\n"
                            f"{bar} {pct}%\n"
                            f"💾 {uploaded_mb:.1f} / {total_mb:.1f} MB"
                        )
                        last_reported = pct

            logger.info(f"✅ Drive subida completa: {response.get('webViewLink', '')}")
            return True, response, None

        except Exception as e:
            logger.error(f"❌ Error subiendo a Drive: {e}", exc_info=True)
            return False, None, str(e)


# ── Utilidad compartida ────────────────────────────────────────────────────────

def _progress_bar(pct: int, width: int = 10) -> str:
    """Genera una barra de progreso visual con emojis."""
    filled = int(width * pct / 100)
    empty  = width - filled
    return '▓' * filled + '░' * empty
