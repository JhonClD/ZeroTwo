"""
drive_downloader.py - Descargas públicas de Drive y subidas OAuth con progreso.
Las dependencias de Google OAuth/API solo se requieren para subir archivos.
"""

import asyncio
import logging
import mimetypes
import os
import random
import re
import subprocess
from email.message import Message as EmailMessage
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from utils.transfer_status import TransferProgress, format_file_info, render_transfer_status

logger = logging.getLogger(__name__)
DRIVE_DOWNLOAD_URL = 'https://drive.google.com/uc'
DRIVE_HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36'}
PUBLIC_LINK_HELP = (
    'La descarga pública de Drive no pudo acceder al archivo. Puede estar privado, '
    'el enlace/ID puede ser incorrecto o el propietario puede haber bloqueado la descarga. '
    'En Drive abre ⋮ > Administrar acceso > Acceso general > '
    'Cualquier persona con el enlace (Lector), guarda y copia el enlace nuevo.'
)
DRIVE_API_FILES_URL = 'https://www.googleapis.com/drive/v3/files'


class DriveFolderError(Exception):
    """Error al enumerar una carpeta pública de Google Drive."""

# ── Importación opcional de las librerías de Google ───────────────────────────
try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
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
        r'/(?:drive/)?(?:u/\d+/)?folders/([a-zA-Z0-9_-]+)',
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
    if response.status_code in (400, 403, 404):
        status_code = response.status_code
        response.close()
        raise PermissionError(f'Google Drive respondió HTTP {status_code}. {PUBLIC_LINK_HELP}')
    response.raise_for_status()

    content_type = response.headers.get('Content-Type', '').lower()
    # Los archivos HTML compartidos también pueden ser descargables; la página
    # intermedia de confirmación/permisos normalmente no trae Content-Disposition.
    if 'text/html' in content_type and not response.headers.get('Content-Disposition'):
        html = response.text
        soup = BeautifulSoup(html, 'html.parser')
        form = soup.find('form', action=True)
        form_params = {}
        form_url = DRIVE_DOWNLOAD_URL
        if form:
            form_params = {
                field.get('name'): field.get('value', '')
                for field in form.find_all(['input', 'button'])
                if field.get('name')
            }
            candidate_url = urljoin(response.url, form.get('action', ''))
            candidate_host = (urlparse(candidate_url).hostname or '').lower()
            if candidate_host in {'drive.google.com', 'drive.usercontent.google.com'}:
                form_url = candidate_url

        token = next(
            (value for key, value in session.cookies.items() if key.startswith('download_warning')),
            None,
        )
        if not token:
            token = form_params.get('confirm')
        if not token:
            confirm = soup.select_one('input[name="confirm"][value]')
            token = confirm.get('value') if confirm else None
        if not token:
            match = re.search(r'[?&]confirm=([\w-]+)', html)
            token = match.group(1) if match else None
        response.close()
        if not token:
            raise PermissionError(
                f'Google Drive mostró una página web en vez del archivo. {PUBLIC_LINK_HELP} '
                'Los documentos nativos de Google (Docs/Sheets/Slides) requieren exportación.'
            )

        params.update(form_params)
        params['id'] = file_id
        params['export'] = 'download'
        params['confirm'] = token
        response = session.get(
            form_url, params=params, headers=DRIVE_HEADERS,
            stream=True, timeout=(20, 60), allow_redirects=True,
        )
        if response.status_code in (400, 403, 404):
            status_code = response.status_code
            response.close()
            raise PermissionError(
                f'Google Drive respondió HTTP {status_code} al confirmar la descarga. '
                f'{PUBLIC_LINK_HELP}'
            )
        response.raise_for_status()
        if ('text/html' in response.headers.get('Content-Type', '').lower()
                and not response.headers.get('Content-Disposition')):
            response.close()
            raise PermissionError(
                f'Google Drive siguió mostrando una página web, no el archivo. {PUBLIC_LINK_HELP}'
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


def _download_public_drive_file(
    file_id: str, output_dir: Path, progress_update=None, max_bytes: int | None = None
) -> Path:
    """Descarga un enlace público de Drive por HTTP y guarda el nombre real."""
    session = requests.Session()
    response = _open_public_drive_response(session, file_id)
    output_path = output_dir / _drive_filename(response, file_id)
    try:
        total = max(0, int(response.headers.get('Content-Length') or 0))
    except (TypeError, ValueError):
        total = 0
    if max_bytes and total > max_bytes:
        response.close()
        raise ValueError(f'El archivo supera el límite configurado de {max_bytes // (1024 * 1024)} MB.')
    downloaded = 0
    partial_path = output_path.with_name(output_path.name + '.part')
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        with partial_path.open('wb') as output:
            for chunk in response.iter_content(chunk_size=8 * 1024 * 1024):
                if not chunk:
                    continue
                if max_bytes and downloaded + len(chunk) > max_bytes:
                    raise ValueError(
                        f'La descarga superó el límite configurado de {max_bytes // (1024 * 1024)} MB.'
                    )
                output.write(chunk)
                downloaded += len(chunk)
                if progress_update:
                    progress_update(downloaded, total, output_path.name)
        if downloaded == 0:
            raise ValueError('Google Drive devolvió un archivo vacío.')
        partial_path.replace(output_path)
        return output_path
    except Exception:
        partial_path.unlink(missing_ok=True)
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


def format_preview_timestamp(seconds: float) -> str:
    """Convierte segundos a una posición legible para la leyenda del preview."""
    total_seconds = max(0, int(round(seconds)))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


async def take_video_screenshots(
    video_path: Path, work_dir: Path, prefix: str = "shot"
) -> list[tuple[Path, float]]:
    """
    Captura 10 screenshots en posiciones aleatorias del video.

    El video se divide en diez tramos iguales y se escoge un instante
    aleatorio dentro de cada tramo. Así los previews cambian en cada
    descarga, pero siguen cubriendo toda la duración y no se agrupan en una
    sola zona del video. Se devuelven en orden cronológico junto con los
    segundos exactos de cada captura para rotular cada imagen en Telegram.
    """
    duration = _get_video_duration(video_path)
    if duration <= 0:
        logger.warning("⚠️ No se pudo obtener una duración válida para screenshots")
        return []

    preview_count = 10
    # Dejamos un pequeño margen en los extremos para evitar frames negros o
    # incompletos. Cada tramo recibe una posición distinta y aleatoria.
    start_ratio, end_ratio = 0.05, 0.95
    tramo = (end_ratio - start_ratio) / preview_count
    positions = [
        random.uniform(
            start_ratio + index * tramo,
            start_ratio + (index + 1) * tramo,
        )
        for index in range(preview_count)
    ]

    shots = []
    for index, ratio in enumerate(positions, start=1):
        ts = _seconds_to_ts(duration * ratio)
        preview_seconds = duration * ratio
        out = work_dir / f"{prefix}_{index:02d}.jpg"
        if _take_screenshot(video_path, ts, out):
            shots.append((out, preview_seconds))
            logger.info(f"📸 Screenshot {index}/{preview_count} en {ts}: OK")
        else:
            logger.warning(f"⚠️ Screenshot {index}/{preview_count} en {ts}: falló")

    return shots


class DriveDownloader:
    """Descarga archivos desde Google Drive con barra de progreso."""

    @staticmethod
    def is_drive_url(url: str) -> bool:
        import re
        return bool(re.search(r'drive\.google\.com|docs\.google\.com', url, re.IGNORECASE))

    @staticmethod
    def is_drive_folder_url(url: str) -> bool:
        """Reconoce enlaces de carpeta; los enlaces de archivos siguen su ruta habitual."""
        try:
            parsed = urlparse(url)
        except (TypeError, ValueError):
            return False
        host = (parsed.hostname or '').lower()
        if host not in {'drive.google.com', 'www.drive.google.com'}:
            return False
        return bool(re.search(r'/(?:drive/)?(?:u/\d+/)?folders/[a-zA-Z0-9_-]+(?:/|$)', parsed.path))

    @staticmethod
    def _folder_id(url_or_id: str) -> str:
        match = re.search(r'/(?:drive/)?(?:u/\d+/)?folders/([a-zA-Z0-9_-]+)', url_or_id)
        folder_id = match.group(1) if match else url_or_id.strip()
        if not re.fullmatch(r'[a-zA-Z0-9_-]{10,200}', folder_id):
            raise DriveFolderError('No pude extraer el ID de la carpeta de Drive.')
        return folder_id

    @staticmethod
    def _api_request(url: str, params: dict) -> dict:
        try:
            response = requests.get(url, params=params, headers=DRIVE_HEADERS, timeout=(10, 35))
        except requests.RequestException as error:
            raise DriveFolderError(
                'No pude conectar con la API de Google Drive. Revisa la conexión saliente del hosting.'
            ) from error
        try:
            payload = response.json()
        except ValueError as error:
            raise DriveFolderError(
                f'Google Drive devolvió una respuesta inválida (HTTP {response.status_code}).'
            ) from error
        if not isinstance(payload, dict):
            raise DriveFolderError('Google Drive devolvió datos de carpeta con formato inesperado.')
        if response.status_code >= 400 or payload.get('error'):
            error = payload.get('error') or {}
            message = str(error.get('message') or '') if isinstance(error, dict) else ''
            if response.status_code in (401, 403):
                raise DriveFolderError(
                    'Google rechazó la API key o el acceso público a la carpeta. '
                    'Verifica que Drive API esté habilitada y que el enlace sea público.'
                )
            if response.status_code == 404:
                raise DriveFolderError('La carpeta no existe o no es accesible públicamente.')
            detail = f' Detalle: {message[:180]}' if message else ''
            raise DriveFolderError(f'La API de Drive respondió HTTP {response.status_code}.{detail}')
        return payload

    @classmethod
    def list_public_folder_files(
        cls, url_or_id: str, api_key: str | None = None, max_files: int = 100, max_depth: int = 5
    ) -> dict:
        """Enumera archivos descargables bajo una carpeta pública usando una API key."""
        folder_id = cls._folder_id(url_or_id)
        api_key = (api_key or os.getenv('GOOGLE_DRIVE_API_KEY') or os.getenv('DRIVE_API_KEY') or '').strip()
        if not api_key:
            raise DriveFolderError(
                'Para listar una carpeta pública de Drive, configura GOOGLE_DRIVE_API_KEY en el panel. '
                'No necesitas API key para descargar un archivo individual.'
            )
        max_files = max(1, min(500, int(max_files)))
        max_depth = max(1, min(10, int(max_depth)))
        root = cls._api_request(
            f'{DRIVE_API_FILES_URL}/{folder_id}',
            {'key': api_key, 'fields': 'id,name,mimeType', 'supportsAllDrives': 'true'},
        )
        if root.get('mimeType') != 'application/vnd.google-apps.folder':
            raise DriveFolderError('El enlace de Drive no apunta a una carpeta.')

        files = []
        visited_folders = set()
        skipped_native = [0]
        truncated = [False]

        def add_file(item: dict, path_parts: list[str]):
            if len(files) >= max_files:
                truncated[0] = True
                return
            file_id = str(item.get('id') or '')
            name = str(item.get('name') or '').strip()
            if not file_id or not name:
                return
            try:
                size = max(0, int(item.get('size') or 0))
            except (TypeError, ValueError):
                size = 0
            relative_path = '/'.join(path_parts + [name])
            files.append({
                'id': file_id,
                'name': name,
                'size': size,
                'mimeType': str(item.get('mimeType') or 'application/octet-stream'),
                'folder_path': '/'.join(path_parts),
                'relative_path': relative_path,
                'webViewLink': item.get('webViewLink'),
            })

        def walk(current_folder_id: str, path_parts: list[str], depth: int):
            if len(files) >= max_files:
                truncated[0] = True
                return
            if depth > max_depth or current_folder_id in visited_folders:
                truncated[0] = True
                return
            visited_folders.add(current_folder_id)
            page_token = None
            while True:
                params = {
                    'key': api_key,
                    'q': f"'{current_folder_id}' in parents and trashed = false",
                    'pageSize': 1000,
                    'fields': 'nextPageToken,files(id,name,mimeType,size,webViewLink,shortcutDetails(targetId,targetMimeType))',
                    'supportsAllDrives': 'true',
                    'includeItemsFromAllDrives': 'true',
                    'orderBy': 'name',
                }
                if page_token:
                    params['pageToken'] = page_token
                result = cls._api_request(DRIVE_API_FILES_URL, params)
                for item in result.get('files') or []:
                    mime_type = str(item.get('mimeType') or '')
                    name = str(item.get('name') or '').strip()
                    if mime_type == 'application/vnd.google-apps.folder':
                        walk(str(item.get('id') or ''), path_parts + [name], depth + 1)
                    elif mime_type == 'application/vnd.google-apps.shortcut':
                        shortcut = item.get('shortcutDetails') or {}
                        target_id = str(shortcut.get('targetId') or '')
                        target_type = str(shortcut.get('targetMimeType') or '')
                        if target_id and target_type == 'application/vnd.google-apps.folder':
                            walk(target_id, path_parts + [name], depth + 1)
                        elif target_id and not target_type.startswith('application/vnd.google-apps.'):
                            target = dict(item)
                            target['id'] = target_id
                            target['mimeType'] = target_type or 'application/octet-stream'
                            add_file(target, path_parts)
                    elif mime_type.startswith('application/vnd.google-apps.'):
                        skipped_native[0] += 1
                    else:
                        add_file(item, path_parts)
                    if len(files) >= max_files:
                        truncated[0] = True
                        return
                page_token = result.get('nextPageToken')
                if not page_token:
                    break

        walk(folder_id, [], 0)
        if not files:
            suffix = ' Solo encontré documentos nativos de Google, que este descargador no exporta.' if skipped_native[0] else ''
            raise DriveFolderError('La carpeta no contiene archivos descargables.' + suffix)
        return {
            'folder_id': folder_id,
            'name': str(root.get('name') or 'Carpeta de Drive'),
            'files': files,
            'truncated': truncated[0],
            'skipped_native': skipped_native[0],
        }

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
    async def download(
        url_or_id: str, output_dir: Path, progress_callback=None, max_bytes: int | None = None
    ) -> tuple[bool, Path | None, str | None]:
        """
        Descarga un archivo de Google Drive.

        progress_callback(text) → actualiza el mensaje de Telegram.
        Retorna (success, file_path, error_msg).
        """
        try:
            file_id = _extract_file_id(url_or_id)
            output_dir.mkdir(parents=True, exist_ok=True)
            progress_state = [0, 0, ""]
            download_meter = TransferProgress()
            if progress_callback:
                try:
                    await progress_callback(
                        "📥 <b>Descargando enlace público de Drive</b>\n"
                        "🔓 No se requiere API para archivos compartidos públicamente.\n"
                        "⏳ Iniciando…"
                    )
                except Exception:
                    pass

            def progress_update(downloaded, total, filename=""):
                progress_state[:] = [downloaded, total, filename]

            task = asyncio.create_task(asyncio.to_thread(
                _download_public_drive_file, file_id, output_dir, progress_update, max_bytes
            ))
            last_reported = -10
            while not task.done():
                await asyncio.sleep(0.5)
                downloaded, total, filename = progress_state
                if total > 0:
                    pct = min(100, int(downloaded * 100 / total))
                    if pct - last_reported >= 10 and progress_callback:
                        logger.info(f"📥 Drive {pct}% — {downloaded}/{total} bytes")
                        try:
                            await progress_callback(
                                render_transfer_status(
                                    "Descargando", "Google Drive", filename or "archivo de Drive",
                                    downloaded, total, download_meter,
                                )
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
                        f"✅ <b>Descarga completada</b> · Google Drive\n{format_file_info(output_path, 'Google Drive')}"
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
            upload_meter = TransferProgress()

            logger.info(f"📤 Drive: subiendo '{filename}' ({total_mb:.1f} MB)")
            if progress_callback:
                await progress_callback(
                    render_transfer_status(
                        "Subiendo", "Google Drive", filename, 0,
                        file_path.stat().st_size, upload_meter,
                    )
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
                        await progress_callback(
                            render_transfer_status(
                                "Subiendo", "Google Drive", filename,
                                status.resumable_progress or 0, file_path.stat().st_size, upload_meter,
                            )
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
