# Instalación de ZeroTwo en hosting Linux

Esta guía sirve para un VPS Ubuntu/Debian o un panel de hosting que ejecute procesos Python de forma continua. Los nombres de menús cambian según el proveedor. ZeroTwo usa Pyrogram con conexión saliente a Telegram y permanece ejecutándose; no es una aplicación web ni necesita un puerto HTTP/webhook.

> El panel debe permitir mantener un proceso en ejecución y tener disponibles Python 3, FFmpeg/FFprobe, Megatools y utilidades de descarga. Si el panel no permite instalar paquetes del sistema, pide al proveedor una imagen/entorno que incluya estas herramientas o utiliza un VPS/Docker compatible.

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

En un panel, instala o selecciona Python 3.8 o superior. Si no hay acceso al sistema para instalar FFmpeg, Megatools, wget, curl y aria2, confirma con el proveedor cuáles están preinstalados. Algunas funciones de descargas o procesamiento pueden no funcionar si faltan.

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

### FlareSolverr opcional

ZeroTwo puede intentar resolver un desafío de Cloudflare si el servidor de descarga devuelve una respuesta bloqueada. Este paso es opcional y solo se activa al definir `FLARESOLVERR_URL`. Instala/ejecuta FlareSolverr aparte según la [documentación oficial](https://github.com/FlareSolverr/FlareSolverr) y configura ZeroTwo con la URL privada del servicio, por ejemplo:

```bash
export FLARESOLVERR_URL="http://127.0.0.1:8191"
./.venv/bin/python main.py
```

En un panel Docker, usa el nombre del servicio FlareSolverr y su puerto dentro de la red privada compartida, no `127.0.0.1`. El bot y FlareSolverr deben poder salir por la misma IP pública para reutilizar las cookies de Cloudflare. No expongas el puerto 8191 directamente a Internet. Sin `FLARESOLVERR_URL`, ZeroTwo conserva su flujo habitual y reporta el error si detecta un bloqueo.

Si el panel tiene una sección de variables de entorno, agrega `FLARESOLVERR_URL` con el valor de la URL privada. Si el panel solo permite comandos de inicio, expórtala antes de ejecutar Python:

```bash
export FLARESOLVERR_URL="http://127.0.0.1:8191"
exec ./.venv/bin/python main.py
```

FlareSolverr requiere recursos adicionales y no garantiza que todos los sitios puedan desbloquearse. Úsalo solo donde tengas autorización para acceder al contenido.

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

Una vez instalado este cambio, el propietario puede enviar `/gitpull` al bot para ejecutar una actualización segura de `origin/main` sin abrir la consola. El comando está limitado al ID configurado en `handlers/gitpull_handler.py` y solo acepta avances directos (`--ff-only`). Después de una actualización exitosa, reinicia el bot desde el panel para que el proceso cargue los archivos nuevos. Si el hosting no conserva una copia Git (por ejemplo, despliega desde un ZIP), el comando no podrá actualizarla.

## Solución de problemas

- **No se encontró `~/.telegram_bot_token`:** crea el archivo en el directorio `HOME` efectivo del proceso del panel. Comprueba que el usuario del panel pueda leerlo.
- **`ffmpeg`, `ffprobe` o `megadl` no aparecen:** el entorno no incluye herramientas del sistema requeridas. Pide habilitarlas al proveedor o usa un VPS/imagen que las permita instalar.
- **El bot se apaga al cerrar la consola:** usa el gestor de procesos del panel, no una sesión interactiva temporal.
- **El panel reinicia el bot repetidamente:** revisa los registros y confirma token, dependencias, permisos y conectividad saliente a Telegram.
- **Se detecta un desafío de Cloudflare:** configura `FLARESOLVERR_URL` y confirma que el servicio está accesible desde el bot por la red privada. La integración no resuelve errores de proveedor, URL vencidas ni archivos multimedia corruptos que no provengan de un desafío.
- **Falta espacio o se pierden archivos al reiniciar:** revisa límites y persistencia del almacenamiento del proveedor.

La interfaz y los campos del panel dependen del proveedor. Si el panel usa Docker, prepara una imagen con las dependencias del sistema y configura un volumen persistente para los datos y el token; no asumas que una plantilla genérica de Python ya incluye FFmpeg o Megatools.
