"""Recherche qui lit vraiment ses sources, et les cite.

Avant, Jarvis ne voyait que des extraits de deux lignes. Ici, trois sources
ouvertes et sans cle sont interrogees en parallele :

  * **Wikipedia** (API officielle) : les articles les plus pertinents sont
    lus (introduction complete), dans la langue de l'utilisateur ;
  * **Google Actualites** (flux RSS public) : titres datés et nom du journal,
    pour les faits recents (resultats, nominations, sorties...) ;
  * les extraits du moteur web habituel (`tools.fetch_web_search`), s'il repond.

Chaque passage est etiquete par sa source (« [1] Wikipédia — Prix Nobel de
physique ») pour que Jarvis puisse la citer, et le tout est borne pour tenir
dans le contexte du modele.
"""

from __future__ import annotations

import re
import threading
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

ARTICLE_CHARS = 900       # 2 articles + les titres tiennent dans ~3 500 caracteres
TIMEOUT = 6.0
DEADLINE = 3.5        # on repond avec les sources arrivees, sans attendre la plus lente
_session = None


def _http():
    """Session partagee : connexions gardees ouvertes d'une recherche a l'autre."""
    global _session
    if _session is None:
        import requests

        _session = requests.Session()
        _session.headers["User-Agent"] = "jarvis-assistant/2.1 (projet etudiant)"
    return _session


def _json(url: str, params: dict, timeout: float):
    response = _http().get(url, params=params, timeout=timeout)
    response.raise_for_status()
    return response.json()


def _bytes(url: str, timeout: float) -> bytes:
    response = _http().get(url, timeout=timeout)
    response.raise_for_status()
    return response.content


def wikipedia(query: str, lang: str = "fr", limit: int = 2, timeout: float = TIMEOUT,
              get_json=None) -> list[tuple[str, str]]:
    """[(titre, introduction)] des articles Wikipedia les plus pertinents."""
    get_json = get_json or _json
    api = f"https://{lang}.wikipedia.org/w/api.php"
    # Recherche ET lecture des introductions en un seul appel (2,5 s au lieu de 5).
    data = get_json(api, {"action": "query", "generator": "search", "gsrsearch": query,
                          "gsrlimit": limit, "prop": "extracts", "exintro": 1,
                          "explaintext": 1, "redirects": 1, "format": "json"}, timeout)
    pages = sorted(data.get("query", {}).get("pages", {}).values(),
                   key=lambda page: page.get("index", 99))
    found = []
    for page in pages[:limit]:
        extract = " ".join((page.get("extract") or "").split())
        if extract:
            found.append((page.get("title", ""), extract[:ARTICLE_CHARS]))
    return found


def news(query: str, lang: str = "fr", limit: int = 5, timeout: float = TIMEOUT,
         download=None) -> list[str]:
    """Titres d'actualite dates : « 12/10/2026 — Titre (Journal) »."""
    download = download or _bytes
    if lang == "fr":
        url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=fr&gl=FR&ceid=FR:fr"
    else:
        url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"
    lines = []
    for item in ET.fromstring(download(url, timeout)).iter("item"):
        title = " ".join((item.findtext("title") or "").split())
        source = item.findtext("source") or ""
        try:
            when = parsedate_to_datetime(item.findtext("pubDate") or "").strftime("%d/%m/%Y")
        except Exception:
            when = ""
        if source and title.endswith(" - " + source):
            title = title[: -len(" - " + source)]
        if title:
            lines.append(f"{when} — {title}" + (f" ({source})" if source else ""))
        if len(lines) >= limit:
            break
    return lines


_RECENT = re.compile(r"\b(?:20[2-9]\d|aujourd'hui|hier|cette (?:semaine|annee)|dernier|derniere|"
                     r"actuel|actuelle|en ce moment|recent|nouveau|nouvelle|resultat|score|"
                     r"today|yesterday|latest|current|recent|new|result)\b", re.I)


def research(query: str, lang: str = "fr", timeout: float = TIMEOUT, sources=None) -> str:
    """Interroge les sources en parallele ; texte pret pour le modele, avec sources."""
    lang = "fr" if lang == "fr" else "en"
    sources = sources or {}
    wiki_fn = sources.get("wikipedia", wikipedia)
    news_fn = sources.get("news", news)
    web_fn = sources.get("web")
    if web_fn is None:
        from .tools import fetch_web_search as web_fn
    results: dict[str, object] = {}

    def run(name: str, fn) -> None:
        try:
            results[name] = fn()
        except Exception:
            results[name] = None

    jobs = {"wiki": lambda: wiki_fn(query, lang, 2, timeout),
            "news": lambda: news_fn(query, lang, 5, timeout),
            "web": lambda: web_fn(query, timeout)}
    import time

    workers = [threading.Thread(target=run, args=item, daemon=True) for item in jobs.items()]
    for worker in workers:
        worker.start()
    limit = time.monotonic() + min(DEADLINE, timeout)
    for worker in workers:                     # une seule echeance pour toutes les sources
        worker.join(max(0.0, limit - time.monotonic()))
    if not any(results.get(name) for name in jobs):          # rien a temps : on patiente
        for worker in workers:
            worker.join(max(0.0, timeout + 1.0 - (time.monotonic() - limit + DEADLINE)))

    blocks, index = [], 1
    recent = bool(_RECENT.search(query))
    news_lines = results.get("news") or []
    if recent and news_lines:                              # l'actualite d'abord si c'est recent
        blocks.append(f"[{index}] Actualités (Google Actualités)\n" + "\n".join(news_lines))
        index += 1
    for title, extract in results.get("wiki") or []:
        blocks.append(f"[{index}] Wikipédia — {title}\n{extract}")
        index += 1
    if not recent and news_lines:
        blocks.append(f"[{index}] Actualités (Google Actualités)\n" + "\n".join(news_lines[:3]))
        index += 1
    web = results.get("web")
    if isinstance(web, str) and web.strip() and not web.startswith(("Aucun", "No result")):
        blocks.append(f"[{index}] Web (extraits)\n{web.strip()}")
    if not blocks:
        return ""
    head = ("SOURCES — appuie-toi dessus et cite la source par son nom (« d'après Wikipédia », "
            "« selon Le Monde »). Si elles se contredisent, préfère la plus récente.")
    return head + "\n\n" + "\n\n".join(blocks)


__all__ = ["research", "wikipedia", "news"]
