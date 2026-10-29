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


__all__ = ["SITES", "SEARCH", "resolve", "search_url", "open_url"]
