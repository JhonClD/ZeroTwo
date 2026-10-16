# Instalación de ZeroTwo en hosting Linux

Esta guía sirve para un VPS Ubuntu/Debian o un panel de hosting que ejecute procesos Python de forma continua. Los nombres de menús cambian según el proveedor. ZeroTwo usa Pyrogram con conexión saliente a Telegram y permanece ejecutándose; no es una aplicación web ni necesita un puerto HTTP/webhook.

> El panel debe permitir mantener un proceso en ejecución y tener disponibles Python 3.9+, FFmpeg/FFprobe y utilidades de descarga. Si `megadl` no está instalado, ZeroTwo puede descargar un build portable de Megatools al primer uso de MEGA. Si falta `aria2c`, puede descargar un build portable de aria2 al primer uso de `/torrent`. Ambos funcionan sin permisos root.

Las descargas de YouTube se solicitan a Loader.to; no requieren Node.js, Deno ni credenciales de Google. El bot busca metadatos públicos en YouTube y luego pide a Loader.to el MP3 o video (hasta 720p). FFmpeg/FFprobe se utilizan para validar el audio/video y convertir notas de voz. El servicio externo puede limitar o rechazar solicitudes desde algunas redes de hosting.

## 1. Preparar el entorno

En un VPS Ubuntu/Debian con acceso SSH y permisos `sudo`:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip ffmpeg megatools wget curl aria2
```

Comprueba que las herramientas estén instaladas:

```bash
python3 --version
ffmpeg -version
ffprobe -version
megadl --version
wget --version
curl --version
aria2c --version
```

En un panel como BotKeep, selecciona el runtime Python requerido. El fallback portable de Megatools está preparado para Linux `x86_64` y `aarch64`; en el primer enlace MEGA descarga el ejecutable oficial, verifica sus hashes y lo guarda bajo `.runtime/` dentro del proyecto. Requiere conexión HTTPS saliente a `xff.cz`, permiso de escritura en el directorio del proyecto y unos 10 MB de espacio adicional.

Para torrents, si `aria2c` no existe en el sistema, ZeroTwo descarga automáticamente aria2 1.37.0 estático para Linux `x86_64`, `aarch64` o `ARMv7` desde el [release comunitario aria2-static-build](https://github.com/abcfy2/aria2-static-build/releases/tag/1.37.0). Comprueba SHA-256 tanto del ZIP como del ejecutable y lo guarda en `.runtime/aria2-*`; requiere HTTPS saliente a GitHub, espacio temporal de unos 20 MB y permiso para ejecutar binarios del proyecto. No necesita `apt`, `pkg` ni root. Si el panel bloquea descargas externas o ejecución de binarios, pide al proveedor que habilite `aria2c`.

El notificador de Crunchyroll consulta metadatos del catálogo en modo anónimo y publica enlaces oficiales; no descarga videos ni requiere una cuenta. El endpoint de catálogo no está documentado públicamente y puede cambiar. Los comandos `/crset`, `/crrem`, `/crstatus`, `/crlist` y `/crnotify` requieren que el ID del propietario esté en `CRUNCHYROLL_OWNER_IDS` o en la variable existente `TIOANIME_OWNER_IDS` (lista de IDs separados por comas). `CR_MINUTES` controla el intervalo en minutos y por defecto es 5. No envíes contraseñas, cookies ni tokens de Crunchyroll al bot.

MediaFire puede usar `aria2c`, `wget` o `curl` si están instalados. Si no hay ninguno, ZeroTwo usa `requests` de Python, incluido en `requirements.txt`; no requiere instalar otro ejecutable. Si MediaFire devuelve HTTP 403 desde el hosting, el sitio/CDN está rechazando esa solicitud y el fallback no puede quitar ese bloqueo.

## 2. Descargar el proyecto e instalar Python

Desde la terminal del servidor o la consola del panel, sitúate en el directorio persistente del bot y ejecuta:

```bash
git clone https://github.com/JhonClD/ZeroTwo.git
cd ZeroTwo
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Si ya clonaste el repositorio, entra en su carpeta y continúa desde la creación del entorno virtual. En paneles sin `venv`, instala `requirements.txt` usando la opción de dependencias Python del panel o el comando de instalación que indique el proveedor.

## 3. Configurar el token de Telegram

Crea un bot con [@BotFather](https://t.me/BotFather) y copia su token. No lo subas a GitHub ni lo compartas en capturas, registros o mensajes.

ZeroTwo lee el token desde `~/.telegram_bot_token` de la cuenta que ejecuta el proceso. En una terminal del servidor:

```bash
printf '%s\n' 'PEGA_AQUI_EL_TOKEN' > "$HOME/.telegram_bot_token"
chmod 600 "$HOME/.telegram_bot_token"
```

En un panel, asegúrate de que el archivo quede en el directorio personal de la misma cuenta/contendor donde arrancará el bot. Si el proveedor ofrece una consola de archivos, crea `.telegram_bot_token` en ese directorio y guarda solo el token en una línea. No añadas comillas al contenido del archivo.

## 4. Configurar el comando de inicio del panel

Usa el directorio del repositorio como directorio de trabajo y configura este comando de inicio:

```bash
./.venv/bin/python main.py
```

Si el panel exige un comando para instalar dependencias al crear o reconstruir el servidor, usa:

```bash
python3 -m venv .venv && ./.venv/bin/python -m pip install -r requirements.txt
```

No ejecutes el bot dos veces a la vez con el mismo token. En un VPS sin panel, puedes iniciarlo en primer plano dentro de `tmux` o configurarlo como servicio `systemd`; el panel normalmente se encarga de mantener y reiniciar su proceso.

## 5. Verificar que está funcionando

Inicia el servidor desde el panel. En los registros deberías ver el mensaje de conexión establecida y bot operativo. Después, abre Telegram y envía `/start` al bot.

Los archivos de trabajo y descargas se guardan por defecto en `~/telegram_bot_files` y `~/telegram_downloads`. Asegúrate de que el plan tenga espacio suficiente, especialmente al procesar vídeos, y de que estas carpetas estén en almacenamiento persistente si el proveedor reemplaza contenedores al reiniciarlos.

## Actualizar

Detén el proceso desde el panel antes de actualizar. Luego, desde la carpeta del repositorio:

```bash
git pull
./.venv/bin/python -m pip install -r requirements.txt
```

Vuelve a iniciar el proceso desde el panel.

## Solución de problemas

- **No se encontró `~/.telegram_bot_token`:** crea el archivo en el directorio `HOME` efectivo del proceso del panel. Comprueba que el usuario del panel pueda leerlo.
- **MEGA no puede preparar Megatools portable:** el primer uso requiere acceso HTTPS a `xff.cz`, escritura dentro de `.runtime/` y permiso para ejecutar archivos del proyecto. Si BotKeep bloquea cualquiera de estos pasos, solicita al proveedor que incluya Megatools/`megadl` en el runtime. En un VPS Ubuntu/Debian, instala el paquete del sistema con `sudo apt update && sudo apt install -y megatools`.
- **MediaFire no descarga:** tras actualizar, el bot puede recurrir a `requests` si faltan `aria2c`, `wget` y `curl`. Si el registro indica HTTP 403, el hosting está recibiendo una denegación de MediaFire/CDN; confirma si funciona desde otra red y consulta al proveedor por la conexión saliente.
- **`/torrent` no puede preparar aria2 portable:** comprueba que el hosting permita HTTPS saliente a GitHub y ejecución de `.runtime/aria2-*/aria2c`. Si el mensaje menciona tráfico o conexión torrent, el proveedor podría bloquear DHT, UDP o conexiones salientes de pares; el binario portable no puede eludir esas restricciones. Pide al proveedor habilitar BitTorrent o `aria2c` en el runtime.
- **`ffmpeg` o `ffprobe` no aparecen:** el entorno no incluye las herramientas de procesamiento requeridas. Pide habilitarlas al proveedor o usa un VPS/imagen que las permita instalar.
- **El bot se apaga al cerrar la consola:** usa el gestor de procesos del panel, no una sesión interactiva temporal.
- **El panel reinicia el bot repetidamente:** revisa los registros y confirma token, dependencias, permisos y conectividad saliente a Telegram.
- **Falta espacio o se pierden archivos al reiniciar:** revisa límites y persistencia del almacenamiento del proveedor.

La interfaz y los campos del panel dependen del proveedor. Si el panel usa Docker, prepara una imagen con las dependencias del sistema y configura un volumen persistente para los datos y el token; no asumas que una plantilla genérica de Python ya incluye FFmpeg o Megatools.
