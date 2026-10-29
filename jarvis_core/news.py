"""Actualites du jour : « Jarvis, quelles sont les infos ? ».

Les titres viennent de flux RSS publics, sans cle : Le Monde (a la une) en
francais, Google Actualites pour l'anglais et pour un sujet precis
(« les infos sur le football »). Seuls les titres sont lus, pas les articles.
"""

from __future__ import annotations

import re
import urllib.request
import xml.etree.ElementTree as ET
from urllib.parse import quote_plus

FEEDS = {
    "fr": ("https://www.lemonde.fr/rss/une.xml",
           "https://news.google.com/rss?hl=fr&gl=FR&ceid=FR:fr"),
    "en": ("https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en",),
}
TOPIC_FEED = {
    "fr": "https://news.google.com/rss/search?q={q}&hl=fr&gl=FR&ceid=FR:fr",
    "en": "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en",
}
_SOURCE = re.compile(r"\s+[-–—]\s+[^-–—]{2,40}$")   # « Titre - Le Figaro » -> « Titre »


def parse_titles(xml: bytes, limit: int = 5) -> list[str]:
    """Titres d'un flux RSS, sans le nom du journal, sans doublons."""
    titles: list[str] = []
    for item in ET.fromstring(xml).iter("item"):
        title = " ".join((item.findtext("title") or "").split())
        title = _SOURCE.sub("", title).strip(" .")
        if title and title.lower() not in {t.lower() for t in titles}:
            titles.append(title)
        if len(titles) >= limit:
            break
    return titles


def _download(url: str, timeout: float) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 Jarvis"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(2_000_000)


def fetch_headlines(lang: str = "fr", topic: str = "", limit: int = 4,
                    timeout: float = 6.0, download=None) -> list[str]:
    """Les `limit` premiers titres (general ou sur `topic`). [] si tout echoue."""
    lang = "fr" if lang == "fr" else "en"
    download = download or _download
    topic = (topic or "").strip()
    urls = ((TOPIC_FEED[lang].format(q=quote_plus(topic)),) if topic else FEEDS[lang])
    for url in urls:
        try:
            titles = parse_titles(download(url, timeout), limit)
        except Exception:
            continue
        if titles:
            return titles
    return []


def say_headlines(titles: list[str], lang: str, topic: str = "") -> str:
    """Phrase a lire : « Voici les titres : un. Deux. Trois. »"""
    fr = lang == "fr"
    if not titles:
        return ("Je n'arrive pas à récupérer les actualités pour le moment." if fr
                else "I cannot get the news right now.")
    about = (f" sur {topic}" if fr else f" about {topic}") if topic else ""
    intro = f"Voici les titres{about} : " if fr else f"Here are the headlines{about}: "
    return intro + " ".join(t if t.endswith(("?", "!")) else t + "." for t in titles)


__all__ = ["fetch_headlines", "parse_titles", "say_headlines"]
