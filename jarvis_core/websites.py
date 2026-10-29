"""Horizon 3 - ouvrir des sites web : « Jarvis, ouvre YouTube ».

Deux outils :

  * ouvrir un site connu (YouTube, Gmail, Netflix...) ou une adresse ;
  * chercher directement sur un site (« cherche des tutos Python sur YouTube »).

Securite : seules des adresses http(s) sont ouvertes, dans le navigateur par
defaut. Jamais de commande, de fichier local ou de schema exotique
(`file:`, `javascript:`...).
"""

from __future__ import annotations

import re
import unicodedata
import webbrowser
from urllib.parse import quote_plus, urlparse

SITES = {
    "youtube": "https://www.youtube.com",
    "youtube music": "https://music.youtube.com",
    "google": "https://www.google.com",
    "gmail": "https://mail.google.com",
    "google drive": "https://drive.google.com",
    "drive": "https://drive.google.com",
    "google maps": "https://www.google.com/maps",
    "maps": "https://www.google.com/maps",
    "google docs": "https://docs.google.com",
    "agenda": "https://calendar.google.com",
    "calendar": "https://calendar.google.com",
    "outlook": "https://outlook.live.com",
    "netflix": "https://www.netflix.com",
    "spotify": "https://open.spotify.com",
    "deezer": "https://www.deezer.com",
    "twitch": "https://www.twitch.tv",
    "facebook": "https://www.facebook.com",
    "instagram": "https://www.instagram.com",
    "x": "https://x.com",
    "twitter": "https://x.com",
    "linkedin": "https://www.linkedin.com",
    "tiktok": "https://www.tiktok.com",
    "whatsapp": "https://web.whatsapp.com",
    "github": "https://github.com",
    "chatgpt": "https://chatgpt.com",
    "claude": "https://claude.ai",
    "wikipedia": "https://fr.wikipedia.org",
    "wikipedia en": "https://en.wikipedia.org",
    "amazon": "https://www.amazon.fr",
    "le monde": "https://www.lemonde.fr",
    "meteo": "https://meteofrance.com",
    "traduction": "https://translate.google.com",
    "translate": "https://translate.google.com",
}

SEARCH = {
    "youtube": "https://www.youtube.com/results?search_query={q}",
    "google": "https://www.google.com/search?q={q}",
    "images": "https://www.google.com/search?tbm=isch&q={q}",
    "maps": "https://www.google.com/maps/search/{q}",
    "wikipedia": "https://fr.wikipedia.org/w/index.php?search={q}",
    "amazon": "https://www.amazon.fr/s?k={q}",
    "spotify": "https://open.spotify.com/search/{q}",
    "github": "https://github.com/search?q={q}",
    "netflix": "https://www.netflix.com/search?q={q}",
    "twitch": "https://www.twitch.tv/search?term={q}",
    "traduction": "https://translate.google.com/?sl=auto&tl=fr&text={q}",
}
ALIASES = {"you tube": "youtube", "yt": "youtube", "mail": "gmail", "e-mail": "gmail",
           "email": "gmail", "google map": "maps", "carte": "maps", "cartes": "maps",
           "wiki": "wikipedia", "wikipedia fr": "wikipedia", "images google": "images",
           "translate": "traduction", "traducteur": "traduction"}

_DOMAIN = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}(?:[/?#].*)?$", re.I)


def _key(name: str) -> str:
    text = unicodedata.normalize("NFKD", name or "").lower()
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"^(?:le |la |les |l'|site |sur )+", "", text.strip(" .!?"))
    return ALIASES.get(text, text)


def resolve(target: str) -> str | None:
    """Nom de site ou adresse -> URL http(s), ou None si refuse/inconnu."""
    key = _key(target)
    if not key:
        return None
    if key in SITES:
        return SITES[key]
    raw = target.strip()
    if "://" in raw:
        parsed = urlparse(raw)
        return raw if parsed.scheme in ("http", "https") and parsed.netloc else None
    compact = raw.replace(" ", "")
    if _DOMAIN.match(compact):
        return "https://" + compact
    return None


def search_url(site: str, query: str) -> str | None:
    key = _key(site) or "google"
    template = SEARCH.get(key)
    if template is None or not (query or "").strip():
        return None
    return template.format(q=quote_plus(query.strip()))


def open_url(url: str, opener=None) -> bool:
    """Ouvre une adresse http(s) dans le navigateur par defaut."""
    parsed = urlparse(url or "")
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return False
    try:
        return bool((opener or webbrowser.open)(url))
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# Musique par nom : « joue Daft Punk » lance directement la premiere video.
# --------------------------------------------------------------------------- #
_VIDEO_ID = re.compile(r'"videoId":"([\w-]{11})"')
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")


def first_youtube_video(query: str, timeout: float = 4.0) -> str | None:
    """Identifiant de la premiere video YouTube pour `query` (None si echec).

    Le delai est strict : une resolution DNS en echec ignore le `timeout`
    d'urllib (11 s mesurees), d'ou le fil d'arriere-plan.
    """
    import threading
    import urllib.request

    url = SEARCH["youtube"].format(q=quote_plus(query.strip()))
    request = urllib.request.Request(url, headers={"User-Agent": _UA,
                                                   "Accept-Language": "fr-FR,fr;q=0.9"})
    found: list[str] = []

    def fetch() -> None:
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                page = response.read(800_000).decode("utf-8", "ignore")
        except Exception:
            return
        match = _VIDEO_ID.search(page)
        if match:
            found.append(match.group(1))

    worker = threading.Thread(target=fetch, name="jarvis-youtube", daemon=True)
    worker.start()
    worker.join(timeout)
    return found[0] if found else None


def play_music(query: str, service: str = "youtube", opener=None, finder=None) -> str | None:
    """Lance `query` : 1re video YouTube (lecture auto) ou recherche Spotify.

    Renvoie l'adresse ouverte, ou None en cas d'echec.
    """
    query = " ".join((query or "").split())
    if not query:
        return None
    if (service or "").lower().startswith("spot"):
        url = "https://open.spotify.com/search/" + quote_plus(query).replace("+", "%20")
    else:
        video = (finder or first_youtube_video)(query)
        url = (f"https://www.youtube.com/watch?v={video}" if video
               else SEARCH["youtube"].format(q=quote_plus(query)))
    return url if open_url(url, opener) else None


__all__ = ["SITES", "SEARCH", "resolve", "search_url", "open_url",
           "first_youtube_video", "play_music"]
