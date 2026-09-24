# Fuentes incluidas en ZeroTwo

Estas fuentes se distribuyen dentro del repositorio para que FFmpeg/libass pueda renderizar subtítulos de forma consistente, incluso en Termux o en un servidor sin fuentes instaladas.

| Archivo | Familia | Licencia | Fuente original |
|---|---|---|---|
| `Roboto-Regular.ttf` | Roboto Regular | Apache License 2.0 | [googlefonts/roboto-2](https://github.com/googlefonts/roboto-2) |
| `Roboto-Bold.ttf` | Roboto Bold | Apache License 2.0 | [googlefonts/roboto-2](https://github.com/googlefonts/roboto-2) |
| `NotoSans-Regular.ttf` | Noto Sans Regular | SIL Open Font License 1.1 | [openmaptiles/fonts](https://github.com/openmaptiles/fonts) |

El bot configura FFmpeg con `fontsdir=fonts/`, por lo que no es necesario instalar estas fuentes globalmente en el sistema. Para añadir otra fuente, coloca el archivo `.ttf` u `.otf` en esta carpeta, actualiza el mapa de familias en `utils/subtitle_tools.py` y conserva el archivo de licencia correspondiente.
