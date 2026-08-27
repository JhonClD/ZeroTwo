"""
anime_handler.py - Manejador del comando /anime
Fuentes: AniList (principal) → MyAnimeList/Jikan (fallback)
Imagen: cascada multi-fuente con verificación de tamaño (≥500KB preferido)
Doblaje: Crunchyroll Latinoamérica (temporada Primavera 2026 + historial)
"""

import json
import re
import logging
import subprocess
import tempfile
import os
import html
import unicodedata
from pathlib import Path
from pyrogram import filters, enums
from pyrogram.types import Message

logger = logging.getLogger(__name__)


def _normalizar_consulta(texto: str) -> str:
    """Limpia espacios y caracteres de control sin alterar el título buscado."""
    texto = re.sub(r"[\x00-\x1f\x7f]", " ", texto or "")
    return re.sub(r"\s+", " ", texto).strip()[:100]


def _sin_acentos(texto: str) -> str:
    """Genera una variante útil para títulos escritos sin tildes."""
    return "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )


def _escapar(texto) -> str:
    """Escapa valores externos antes de insertarlos en mensajes HTML."""
    return html.escape(str(texto if texto is not None else ""), quote=False)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Lista de animes con doblaje latino confirmado en Crunchyroll
# Fuente: Crunchyroll Latinoamérica — Primavera 2026 + temporadas previas
# 🟢 = tiene doblaje latino en Crunchyroll  |  🔴 = sin doblaje
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CRUNCHYROLL_DUBS = {
    # ── Primavera 2026 (confirmados 24 mar 2026) ──────────────────────────
    "agents of the four seasons: dance of spring": True,
    "the beginning after the end": True,
    "classroom of the elite": True,
    "classroom of the elite season 4": True,
    "i want to end this love game": True,
    "dr. stone: science future": True,
    "dr stone science future": True,
    "that time i got reincarnated as a slime": True,
    "that time i got reincarnated as a slime season 4": True,
    "tensura": True,
    "ascendance of a bookworm": True,
    "daemons of the shadow realm": True,
    "mistress kanan is devilishly easy": True,
    "welcome to demon school! iruma-kun": True,
    "iruma-kun": True,
    "mairimashita! iruma-kun": True,
    "one piece": True,
    "liar game": True,
    "an observation log of my fiancee who calls herself a villainess": True,
    "witch hat atelier": True,
    "atelier of witch hat": True,
    "i made friends with the second prettiest girl in my class": True,
    "marriagetoxin": True,
    "rent a girlfriend": True,
    "rent a girlfriend season 5": True,
    "kanojo okarishimasu": True,
    "re:zero": True,
    "re:zero - starting life in another world": True,
    "re:zero season 4": True,
    "the warrior princess and the barbaric king": True,
    "drops of god": True,
    "wistoria: wand and sword": True,
    "wistoria wand and sword": True,
    "wistoria: wand and sword season 2": True,
    # ── Invierno 2026 ──────────────────────────────────────────────────────
    "jujutsu kaisen": True,
    "jujutsu kaisen season 3": True,
    "frieren: beyond journey's end": True,
    "frieren beyond journey's end": True,
    "sousou no frieren": True,
    "fire force": True,
    "enen no shouboutai": True,
    "you and i are polar opposites": True,
    # ── Títulos populares con doblaje histórico en Crunchyroll ────────────
    "naruto": True,
    "naruto shippuden": True,
    "boruto": True,
    "boruto: naruto next generations": True,
    "dragon ball super": True,
    "dragon ball z": True,
    "bleach": True,
    "bleach: thousand-year blood war": True,
    "attack on titan": True,
    "shingeki no kyojin": True,
    "demon slayer": True,
    "kimetsu no yaiba": True,
    "my hero academia": True,
    "boku no hero academia": True,
    "black clover": True,
    "fairy tail": True,
    "overlord": True,
    "sword art online": True,
    "sword art online: alicization": True,
    "the rising of the shield hero": True,
    "tate no yuusha no nariagari": True,
    "konosuba": True,
    "kono subarashii sekai ni shukufuku wo!": True,
    "tensura diary": True,
    "mushoku tensei": True,
    "mushoku tensei: jobless reincarnation": True,
    "jobless reincarnation": True,
    "reincarnated as a sword": True,
    "tensei shitara ken deshita": True,
    "the eminence in shadow": True,
    "kage no jitsuryokusha ni naritakute": True,
    "solo leveling": True,
    "ore dake level up na ken": True,
    "chainsaw man": True,
    "spy x family": True,
    "tokyo revengers": True,
    "hunter x hunter": True,
    "fullmetal alchemist: brotherhood": True,
    "made in abyss": True,
    "vinland saga": True,
    "dr. stone": True,
    "dr stone": True,
    "tower of god": True,
    "the god of high school": True,
    "noblesse": True,
    "classroom of the elite season 2": True,
    "classroom of the elite season 3": True,
    "rent-a-girlfriend": True,
    "that time i got reincarnated as a slime season 2": True,
    "that time i got reincarnated as a slime season 3": True,
    "dorohedoro": True,
    "dorohedoro season 2": True,
    "one punch man": True,
    "mob psycho 100": True,
    "death note": True,
    "tokyo ghoul": True,
    "no game no life": True,
    "is it wrong to try to pick up girls in a dungeon?": True,
    "danmachi": True,
    "re:zero season 2": True,
    "re:zero season 3": True,
    "that time i got reincarnated as a slime: trinity in tempest": True,
    "welcome to demon school! iruma-kun season 2": True,
    "welcome to demon school! iruma-kun season 3": True,
}

# Alias habituales en español y variantes que pueden devolver las APIs.
# Se mantienen separados de CRUNCHYROLL_DUBS para que la lista principal sea fácil de actualizar.
DUB_ALIASES = {
    "guardianes de la noche": "kimetsu no yaiba",
    "demon slayer": "kimetsu no yaiba",
    "mi academia de heroes": "boku no hero academia",
    "mi hero academia": "boku no hero academia",
    "ataque de los titanes": "shingeki no kyojin",
    "ataque a los titanes": "shingeki no kyojin",
    "la eminencia en la sombra": "kage no jitsuryokusha ni naritakute",
    "nivelacion en solitario": "solo leveling",
    "isekai slime": "tensura",
    "re zero": "re:zero",
    "rezero": "re:zero",
    "jujutsu kaisen": "jujutsu kaisen",
}


def _normalizar_titulo_doblaje(titulo: str) -> str:
    """Normaliza un título para comparar alias sin depender de formato o tildes."""
    titulo = _sin_acentos(titulo or "").lower()
    titulo = titulo.replace("&", " and ")
    titulo = re.sub(r"[’'`´]", "", titulo)
    titulo = re.sub(r"[^a-z0-9]+", " ", titulo)
    return re.sub(r"\s+", " ", titulo).strip()


def _clave_doblaje(titulo: str) -> str:
    """Resuelve alias y elimina sufijos comunes de temporada o parte."""
    titulo = _normalizar_titulo_doblaje(titulo)
    titulo = DUB_ALIASES.get(titulo, titulo)
    titulo = re.sub(
        r"(?:\s+(?:season|temporada|parte|part|cour)\s*\d+|\s+s\d+)$",
        "",
        titulo,
        flags=re.IGNORECASE,
    ).strip()
    return DUB_ALIASES.get(titulo, titulo)


def _tiene_doblaje(titulo_romaji: str, titulo_english: str, titulo_native: str) -> bool:
    """Verifica el doblaje con títulos normalizados y coincidencia por palabras completas."""
    claves = {_clave_doblaje(t) for t in (titulo_romaji, titulo_english, titulo_native) if t}
    claves.discard("")
    disponibles = {_clave_doblaje(t) for t in CRUNCHYROLL_DUBS}

    for clave in claves:
        if clave in disponibles:
            return True
        # Permite reconocer una temporada concreta a partir de su serie base,
        # pero evita coincidencias arbitrarias como "art" dentro de otro título.
        for disponible in disponibles:
            if len(disponible) >= 5 and (
                clave.startswith(disponible + " ")
                or disponible.startswith(clave + " ")
            ):
                return True
    return False


def _curl_post_json(url: str, payload: dict, timeout: int = 15) -> dict | None:
    """Hace POST JSON con curl usando archivo temporal (evita problemas de escapado)."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as tmp:
        json.dump(payload, tmp, ensure_ascii=False)
        tmp_path = tmp.name

    try:
        cmd = [
            'curl', '-s', '-X', 'POST', url,
            '-H', 'Content-Type: application/json',
            '-H', 'Accept: application/json',
            '-d', f'@{tmp_path}'
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            return None
        return json.loads(result.stdout)
    except Exception as e:
        logger.error(f"curl POST error: {e}")
        return None
    finally:
        os.unlink(tmp_path)


def _curl_get(url: str, timeout: int = 15) -> dict | None:
    """Hace GET con curl y devuelve JSON parseado."""
    try:
        cmd = ['curl', '-s', '-L', url,
               '-H', 'Accept: application/json',
               '-H', 'User-Agent: Mozilla/5.0']
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            return None
        return json.loads(result.stdout)
    except Exception as e:
        logger.error(f"curl GET error: {e}")
        return None







def _buscar_anilist(anime_name: str) -> dict | None:
    """Busca en AniList con la consulta original y una variante sin tildes."""
    query = """
    query ($search: String) {
        Media (search: $search, type: ANIME) {
            id
            title { romaji english native }
            studios(isMain: true) { nodes { name } }
            startDate { year month day }
            seasonYear
            episodes
            genres
            duration
            format
            season
            status
            source
            siteUrl
            averageScore
            popularity
            description
            bannerImage
            coverImage { extraLarge large medium }
        }
    }
    """
    consultas = [_normalizar_consulta(anime_name)]
    sin_acentos = _sin_acentos(consultas[0])
    if sin_acentos and sin_acentos.lower() != consultas[0].lower():
        consultas.append(sin_acentos)

    for consulta in consultas:
        data = _curl_post_json(
            'https://graphql.anilist.co',
            {'query': query, 'variables': {'search': consulta}}
        )
        if data and not data.get('errors'):
            resultado = data.get('data', {}).get('Media')
            if resultado:
                return resultado

    logger.info(f"AniList: no encontrado → {anime_name}")
    return None


def _buscar_mal(anime_name: str) -> dict | None:
    """
    Fallback: busca en MyAnimeList via Jikan API v4.
    Devuelve un dict normalizado con los mismos campos que AniList.
    """
    import urllib.parse
    consulta = _normalizar_consulta(anime_name)
    query_enc = urllib.parse.quote(consulta)
    data = _curl_get(f'https://api.jikan.moe/v4/anime?q={query_enc}&limit=5')
    if not data or not data.get('data'):
        return None

    # Jikan puede devolver coincidencias parciales; priorizamos la de mayor puntuación.
    candidatos = data['data'][:5]
    mal = max(candidatos, key=lambda item: item.get('score') or 0)


    return {
        '_source': 'mal',
        'title': {
            'romaji': mal.get('title'),
            'english': mal.get('title_english') or mal.get('title'),
            'native': mal.get('title_japanese') or '',
        },
        'studios': {
            'nodes': [{'name': s['name']} for s in mal.get('studios', [])]
        },
        'startDate': {
            'year':  mal.get('aired', {}).get('prop', {}).get('from', {}).get('year'),
            'month': mal.get('aired', {}).get('prop', {}).get('from', {}).get('month'),
            'day':   mal.get('aired', {}).get('prop', {}).get('from', {}).get('day'),
        },
        'seasonYear': mal.get('aired', {}).get('prop', {}).get('from', {}).get('year'),
        'episodes': mal.get('episodes'),
        'genres': [g['name'] for g in mal.get('genres', [])],
        'duration': None,
        'format': _mal_type(mal.get('type')),
        'season': None,
        'status': _mal_status(mal.get('status')),
        'source': _mal_source(mal.get('source')),
        'description': mal.get('synopsis') or 'No disponible',
        'bannerImage': None,
        'coverImage': {
            'extraLarge': mal.get('images', {}).get('jpg', {}).get('large_image_url'),
            'large': mal.get('images', {}).get('jpg', {}).get('image_url'),
        },
        'mal_url': mal.get('url'),
        'score': mal.get('score'),
        'popularity': mal.get('popularity'),
        'siteUrl': mal.get('url'),
    }


def _mal_type(t: str | None) -> str:
    mapping = {'TV': 'TV', 'Movie': 'MOVIE', 'Special': 'SPECIAL',
               'OVA': 'OVA', 'ONA': 'ONA', 'Music': 'MUSIC'}
    return mapping.get(t or '', t or 'TV')


def _mal_status(s: str | None) -> str:
    mapping = {
        'Finished Airing': 'FINISHED',
        'Currently Airing': 'RELEASING',
        'Not yet aired': 'NOT_YET_RELEASED',
    }
    return mapping.get(s or '', s or '')


def _mal_source(s: str | None) -> str:
    """Normaliza el campo source de MAL al formato de AniList."""
    mapping = {
        'Manga': 'MANGA',
        'Light novel': 'LIGHT_NOVEL',
        'Visual novel': 'VISUAL_NOVEL',
        'Web manga': 'WEB_MANGA',
        'Novel': 'NOVEL',
        'Original': 'ORIGINAL',
        'Game': 'VIDEO_GAME',
        'Other': 'OTHER',
        'Music': 'MUSIC',
        'Comic book': 'COMIC',
        '4-koma manga': 'MANGA',
        'Web novel': 'NOVEL',
        'Card game': 'OTHER',
        'Book': 'NOVEL',
        'Picture book': 'OTHER',
        'Radio': 'OTHER',
    }
    return mapping.get(s or '', 'OTHER' if s else '')


def _traducir(texto: str) -> str:
    """Traduce al español usando MyMemory (max 500 chars)."""
    try:
        cmd = [
            'curl', '-s', '-G',
            'https://api.mymemory.translated.net/get',
            '--data-urlencode', f'q={texto[:500]}',
            '--data-urlencode', 'langpair=en|es'
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            d = json.loads(r.stdout)
            if d.get('responseStatus') == 200:
                return d['responseData']['translatedText']
    except Exception:
        pass
    return texto


def register(app, user_states, work_dir):
    """Registra el handler del comando /anime."""

    ESTADOS = {
        'FINISHED': 'Finalizado', 'RELEASING': 'En emisión',
        'NOT_YET_RELEASED': 'Próximamente', 'CANCELLED': 'Cancelado', 'HIATUS': 'En pausa'
    }
    TEMPORADAS = {
        'WINTER': 'Invierno', 'SPRING': 'Primavera',
        'SUMMER': 'Verano', 'FALL': 'Otoño'
    }
    FORMATOS = {
        'TV': 'Serie de TV', 'MOVIE': 'Película', 'SPECIAL': 'Especial',
        'OVA': 'OVA', 'ONA': 'ONA', 'MUSIC': 'Musical', 'TV_SHORT': 'Serie Corta'
    }
    GENEROS_TRAD = {
        'Action': 'Acción', 'Adventure': 'Aventura', 'Comedy': 'Comedia',
        'Drama': 'Drama', 'Ecchi': 'Ecchi', 'Fantasy': 'Fantasía',
        'Horror': 'Terror', 'Mahou Shoujo': 'Magical Girls', 'Mecha': 'Mecha',
        'Music': 'Música', 'Mystery': 'Misterio', 'Psychological': 'Psicológico',
        'Romance': 'Romance', 'Sci-Fi': 'Ciencia Ficción',
        'Slice of Life': 'Recuentos de la vida', 'Sports': 'Deportes',
        'Supernatural': 'Sobrenatural', 'Thriller': 'Suspenso',
        'Shounen': 'Shōnen', 'Shoujo': 'Shōjo', 'Seinen': 'Seinen',
        'Josei': 'Josei', 'Isekai': 'Isekai', 'Harem': 'Harem',
        'School': 'Escolar', 'Magic': 'Magia', 'Super Power': 'Superpoderes',
        'Martial Arts': 'Artes Marciales', 'Historical': 'Histórico',
        'Military': 'Militar', 'Space': 'Espacial', 'Game': 'Juegos',
        'Vampire': 'Vampiros', 'Demons': 'Demonios', 'Police': 'Policía',
        'Cars': 'Autos', 'Kids': 'Infantil', 'Parody': 'Parodia',
        'Samurai': 'Samurái', 'Award Winning': 'Premiado',
        'Suspense': 'Suspenso', 'Gourmet': 'Gastronomía',
        'Boys Love': 'Boys Love', 'Girls Love': 'Girls Love',
    }

    @app.on_message(filters.command("anime"))
    async def anime_command(client, message: Message):
        """Comando /anime — busca info de anime (AniList + MAL fallback)."""

        args = message.text.split(maxsplit=1)

        if len(args) < 2:
            await message.reply_text(
                "🈺 <b>Búsqueda de Anime</b>\n\n"
                "Por favor ingresa el nombre del anime:\n"
                "<code>/anime Nombre del anime</code>\n\n"
                "Ejemplos:\n"
                "<code>/anime One Piece</code>\n"
                "<code>/anime Solo Leveling</code>",
                parse_mode=enums.ParseMode.HTML
            )
            return

        anime_name = _normalizar_consulta(args[1])
        if len(anime_name) < 2:
            await message.reply_text(
                "❌ Escribe al menos 2 caracteres para realizar la búsqueda.",
                parse_mode=enums.ParseMode.HTML
            )
            return
        logger.info(f"🈺 Buscando anime: {anime_name}")

        status_msg = await message.reply_text("⏳ Buscando información del anime...")

        try:
            # ── 1. Buscar en AniList ──────────────────────────────────────
            anime = _buscar_anilist(anime_name)
            fuente = "AniList"

            # ── 2. Fallback a MyAnimeList/Jikan ──────────────────────────
            if not anime:
                logger.info(f"AniList sin resultados, probando MAL para: {anime_name}")
                await status_msg.edit_text("⏳ Buscando en MyAnimeList...")
                anime = _buscar_mal(anime_name)
                fuente = "MyAnimeList"

            if not anime:
                await status_msg.edit_text(
                    f"❌ No se encontró el anime: <b>{anime_name}</b>\n\n"
                    "Intenta con el título en japonés o inglés.",
                    parse_mode=enums.ParseMode.HTML
                )
                return

            # ── 3. Procesar campos ────────────────────────────────────────
            titulo = (
                anime.get('title', {}).get('romaji')
                or anime.get('title', {}).get('english')
                or anime.get('title', {}).get('native')
                or 'Desconocido'
            )
            titulo_ingles = anime.get('title', {}).get('english') or ''
            titulo_nativo = anime.get('title', {}).get('native') or ''

            estudios_nodes = anime.get('studios', {}).get('nodes', [])
            estudios = ', '.join([s.get('name', '') for s in estudios_nodes if s.get('name')]) if estudios_nodes else 'Desconocido'
            estudios = _escapar(estudios)

            generos_raw = anime.get('genres') or []
            generos = ', '.join([GENEROS_TRAD.get(g, g) for g in generos_raw]) if generos_raw else 'N/A'
            generos = _escapar(generos)

            sinopsis = anime.get('description') or 'No disponible'
            if sinopsis not in ('No disponible', '', None):
                sinopsis = re.sub(r'<[^>]+>', '', sinopsis).strip()
                # Quitar líneas de fuente/nota que AniList agrega al final
                sinopsis = re.sub(r'\n?\(Fuente:[^)]*\)', '', sinopsis, flags=re.IGNORECASE).strip()
                sinopsis = re.sub(r'\n?Nota:.*', '', sinopsis, flags=re.IGNORECASE | re.DOTALL).strip()
                sinopsis = re.sub(r'\n?\[Escrito por.*?\]', '', sinopsis, flags=re.IGNORECASE).strip()
                sinopsis = _traducir(sinopsis)
            sinopsis = _escapar(sinopsis[:1800]) or 'No disponible'

            episodios = anime.get('episodes') or 'En emisión'
            duracion  = anime.get('duration')
            duracion_txt = f"{duracion} min" if duracion else 'N/A'
            anio      = anime.get('seasonYear') or 'N/A'
            formato   = FORMATOS.get(anime.get('format'), anime.get('format') or 'N/A')
            temporada = TEMPORADAS.get(anime.get('season'), 'N/A')
            estado    = ESTADOS.get(anime.get('status'), anime.get('status') or 'N/A')

            # Puntuación normalizada: AniList usa 0-100 y Jikan/MAL usa 0-10.
            puntuacion_raw = anime.get('averageScore')
            if puntuacion_raw is not None:
                puntuacion_txt = f"{float(puntuacion_raw) / 10:.1f}/10"
            elif anime.get('score') is not None:
                puntuacion_txt = f"{float(anime['score']):.1f}/10"
            else:
                puntuacion_txt = 'N/A'
            ficha_url = anime.get('siteUrl') or anime.get('mal_url')
            ficha_txt = ''
            if isinstance(ficha_url, str) and ficha_url.startswith(('https://', 'http://')):
                ficha_txt = f'\n<a href="{_escapar(ficha_url)}">🔗 Ver ficha y más información</a>'

            # Fecha de estreno completa (día/mes/año)
            sd = anime.get('startDate') or {}
            sd_year  = sd.get('year')
            sd_month = sd.get('month')
            sd_day   = sd.get('day')
            MESES = {
                1: 'enero', 2: 'febrero', 3: 'marzo', 4: 'abril',
                5: 'mayo', 6: 'junio', 7: 'julio', 8: 'agosto',
                9: 'septiembre', 10: 'octubre', 11: 'noviembre', 12: 'diciembre'
            }
            if sd_year and sd_month and sd_day:
                estreno_txt = f"{sd_day} de {MESES[sd_month]} de {sd_year}"
            elif sd_year and sd_month:
                estreno_txt = f"{MESES[sd_month].capitalize()} de {sd_year}"
            elif sd_year:
                estreno_txt = str(sd_year)
            else:
                estreno_txt = 'N/A'

            # Fuente/origen con emoji
            FUENTES = {
                'ORIGINAL':      ('📝', 'Original'),
                'MANGA':         ('📚', 'Manga'),
                'LIGHT_NOVEL':   ('📖', 'Novela ligera'),
                'NOVEL':         ('📕', 'Novela'),
                'VISUAL_NOVEL':  ('🎮', 'Novela visual'),
                'WEB_MANGA':     ('🌐', 'Web manga'),
                'WEB_NOVEL':     ('🌐', 'Web novel'),
                'VIDEO_GAME':    ('🕹', 'Videojuego'),
                'GAME':          ('🕹', 'Juego'),
                'COMIC':         ('📓', 'Cómic'),
                'CARD_GAME':     ('🃏', 'Juego de cartas'),
                'MUSIC':         ('🎵', 'Música'),
                'OTHER':         ('📦', 'Otro'),
                '':              ('❓', 'Desconocido'),
            }
            source_raw = anime.get('source') or ''
            src_emoji, src_label = FUENTES.get(source_raw, ('📦', source_raw or 'Desconocido'))

            # ── 4. Doblaje Crunchyroll ────────────────────────────────────
            titulo_original = titulo
            tiene_dub = _tiene_doblaje(titulo_original, titulo_ingles, titulo_nativo)
            doblaje_txt = "🟢 Disponible en Crunchyroll" if tiene_dub else "🔴 No disponible"

            # ── 5. Bloques opcionales de título ───────────────────────────
            titulo = _escapar(titulo)
            titulo_ingles = _escapar(titulo_ingles)
            titulo_nativo = _escapar(titulo_nativo)
            titulo_bloque = ""
            if titulo_ingles and titulo_ingles.strip() != titulo.strip():
                titulo_bloque += f"\n<b>🔤 Título inglés:</b> <b>{titulo_ingles}</b>"
            if titulo_nativo and titulo_nativo.strip() != titulo.strip():
                titulo_bloque += f"\n<b>🈯 Título nativo:</b> <b>{titulo_nativo}</b>"

            info = (
                f"<b>✨ INFORMACIÓN DEL ANIME ✨</b>\n\n"
                f"<b>🈺 Título:</b> <b>{titulo}</b>"
                f"{titulo_bloque}\n"
                f"<b>🏦 Estudio:</b> <b>{estudios}</b>\n"
                f"<b>{src_emoji} Fuente:</b> <b>{src_label}</b>\n"
                f"<b>📅 Estreno:</b> <b>{estreno_txt}</b>\n"
                f"<b>🗂 Episodios:</b> <b>{episodios}</b>\n"
                f"<b>🎙 Doblaje latino:</b> <b>{doblaje_txt}</b>\n"
                f"<b>🏷 Géneros:</b> <b>{generos}</b>\n"
                f"<b>⏱ Duración:</b> <b>{duracion_txt}</b>\n"
                f"<b>💽 Formato:</b> <b>{formato}</b>\n"
                f"<b>🔅 Temporada:</b> <b>{temporada}</b>\n"
                f"<b>⏳ Estado:</b> <b>{estado}</b>\n"
                f"<b>⭐ Puntuación:</b> <b>{puntuacion_txt}</b>\n"
                f"<b>📜 Sinopsis:</b>\n"
                f"<blockquote><b>{sinopsis}</b></blockquote>"
                f"{ficha_txt}"
            )

            # ── 6. Imagen de portada — AniList exclusivamente ─────────────
            # Cuando el fallback es MyAnimeList/Jikan no se muestra su imagen:
            # así se evita mezclar la portada de otra fuente con los datos del resultado.
            cover = anime.get('coverImage') or {} if anime.get('_source') != 'mal' else {}
            image_candidates = [
                cover.get('extraLarge'),
                cover.get('large'),
                cover.get('medium'),
            ]
            image_candidates = [url for url in image_candidates if url]

            # Intentar cada candidato hasta obtener imagen válida (>10KB)
            img_bytes = None
            for candidate in image_candidates:
                try:
                    r = subprocess.run(
                        ['curl', '-s', '-L', candidate],
                        capture_output=True, timeout=30
                    )
                    if r.returncode == 0 and len(r.stdout) > 10_000:
                        img_bytes = r.stdout
                        logger.info(f"🖼 Imagen OK: {len(r.stdout)//1024}KB → {candidate[:80]}")
                        break
                    else:
                        logger.info(f"🖼 Imagen inválida ({len(r.stdout)} bytes) → {candidate[:80]}")
                except Exception as e:
                    logger.warning(f"🖼 Error descargando {candidate}: {e}")

            if img_bytes:
                temp_img = work_dir / f"anime_{message.from_user.id}.jpg"
                temp_img.write_bytes(img_bytes)

                if len(info) > 1024:
                    await message.reply_photo(photo=str(temp_img))
                    await message.reply_text(info, parse_mode=enums.ParseMode.HTML)
                else:
                    await message.reply_photo(
                        photo=str(temp_img),
                        caption=info,
                        parse_mode=enums.ParseMode.HTML
                    )
                await status_msg.delete()
                temp_img.unlink(missing_ok=True)
                return

            # Sin imagen → solo texto
            await status_msg.edit_text(info, parse_mode=enums.ParseMode.HTML)

        except Exception as e:
            logger.error(f"❌ Error en /anime: {e}", exc_info=True)
            await status_msg.edit_text(
                f"❌ <b>Error interno</b>\n\n<code>{str(e)[:200]}</code>",
                parse_mode=enums.ParseMode.HTML
            )
