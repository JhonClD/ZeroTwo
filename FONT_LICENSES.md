# Fuentes incluidas en ZeroTwo

Estas fuentes se distribuyen dentro del repositorio para que FFmpeg/libass pueda renderizar subtítulos de forma consistente, incluso en Termux o en un servidor sin fuentes instaladas.

| Archivo | Familia | Licencia | Fuente original |
|---|---|---|---|
| `Roboto-Regular.ttf` | Roboto Regular | Apache License 2.0 | [googlefonts/roboto-2](https://github.com/googlefonts/roboto-2) |
| `Roboto-Bold.ttf` | Roboto Bold | Apache License 2.0 | [googlefonts/roboto-2](https://github.com/googlefonts/roboto-2) |
| `NotoSans-Regular.ttf` | Noto Sans Regular | SIL Open Font License 1.1 | [openmaptiles/fonts](https://github.com/openmaptiles/fonts) |
| `Montserrat-Variable.ttf` | Montserrat | SIL Open Font License 1.1 | [google/fonts](https://github.com/google/fonts/tree/main/ofl/montserrat) |
| `Oswald-Variable.ttf` | Oswald | SIL Open Font License 1.1 | [google/fonts](https://github.com/google/fonts/tree/main/ofl/oswald) |
| `MPLUS1p-Bold.ttf` | M PLUS 1p Bold | SIL Open Font License 1.1 | [google/fonts](https://github.com/google/fonts/tree/main/ofl/mplus1p) |
| `Rosario-Variable.ttf` | Rosario (incluye peso Bold) | SIL Open Font License 1.1 | [google/fonts](https://github.com/google/fonts/tree/main/ofl/rosario) |

El bot configura FFmpeg con `fontsdir=fonts/`, por lo que no es necesario instalar estas fuentes globalmente en el sistema. Las copias de la licencia OFL de las nuevas familias se conservan en `licenses/fonts/` para que libass no intente interpretarlas como fuentes. Para añadir otra fuente, coloca el archivo `.ttf` u `.otf` en esta carpeta, actualiza el mapa de familias en `utils/subtitle_tools.py` y conserva el archivo de licencia correspondiente fuera de `fonts/`.

**Comic Sans MS no se redistribuye** porque es una fuente propietaria de Microsoft. ZeroTwo sí ofrece la opción `Comic Sans MS — sistema`, que funciona si la fuente ya está instalada en el sistema operativo; de lo contrario, FFmpeg/libass utilizará una fuente de sustitución.
