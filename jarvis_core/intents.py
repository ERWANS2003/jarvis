"""Reponses instantanees et aiguillage, pour un Jarvis plus rapide.

Mesure (29/10/2026, modele gratuit) : ~5,3 s avant la premiere phrase avec
les 19 outils, ~3,1 s sans outils. Deux raccourcis en decoulent :

  * **commandes instantanees** : l'heure, la date, la meteo d'une ville,
    « ouvre YouTube »,
    « pause », « suivant », « monte le son », « cherche X sur YouTube »... sont
    reconnues ici et executees tout de suite, sans appeler le modele (< 1 s) ;
  * **outils a la demande** : une simple conversation (« raconte une
    blague ») est envoyee au modele sans la description des outils.

Les motifs sont volontairement stricts (phrase courte, commande seule) : une
demande plus riche (« ouvre YouTube et mets une musique calme ») part au
modele comme avant.
"""

from __future__ import annotations

import datetime as _dt
import re
import unicodedata

from . import pc, websites
from .briefing import DAYS, MONTHS, say_time

_POLITE = re.compile(
    r"^(?:jarvis|hey jarvis|ok jarvis|dis jarvis)?[ ,]*"
    r"(?:s'il te plait |s'il vous plait |please |est-ce que tu peux |peux-tu |tu peux |"
    r"pourrais-tu |can you |could you )*", re.I)

TIME = re.compile(r"^(?:quelle heure (?:est-il|il est)|il est quelle heure|l'heure|donne(?:-moi)? l'heure"
                  r"|what time is it|what's the time|tell me the time)$")
DATE = re.compile(r"^(?:on est quel jour|quel jour (?:on est|sommes-nous|est-on|nous sommes)|quelle"
                  r" (?:est la )?date(?: d'aujourd'hui)?(?: sommes-nous)?|on est le combien"
                  r"|what day is (?:it|today)|what's the date|what is the date(?: today)?)$")
OPEN = re.compile(r"^(?:ouvre|ouvrir|lance|lancer|demarre|demarrer|open|launch|start)(?:-moi)?\s+(?:l'application |le site |"
                  r"l'appli |the app |the site )?(?:le |la |les |l')?(.{2,40})$")
SEARCH = re.compile(r"^(?:cherche|recherche|trouve|search(?: for)?|look up|find)\s+(.{1,80}?)\s+"
                    r"(?:sur|on|dans|in)\s+(youtube|google|images|maps|google maps|wikipedia|amazon|"
                    r"spotify|github|netflix|twitch)$")
PLAY_PAUSE = re.compile(r"^(?:mets? (?:en )?pause|pause|stoppe la musique|reprends(?: la musique| la lecture)?"
                        r"|remets la musique|play|resume|pause (?:the )?music)$")
NEXT = re.compile(r"^(?:suivant|(?:musique|chanson|piste|morceau) suivante?|passe (?:a la suivante|la chanson)"
                  r"|next(?: song| track)?|skip)$")
PREVIOUS = re.compile(r"^(?:precedent|(?:musique|chanson|piste|morceau) precedente?|reviens en arriere"
                      r"|previous(?: song| track)?)$")
VOLUME_UP = re.compile(r"^(?:monte|augmente)(?: le)? (?:son|volume)|^plus fort$|^(?:turn )?(?:the )?volume up$"
                       r"|^louder$")
VOLUME_DOWN = re.compile(r"^(?:baisse|diminue)(?: le)? (?:son|volume)|^moins fort$"
                         r"|^(?:turn )?(?:the )?volume down$|^quieter$")
MUTE = re.compile(r"^(?:coupe le son|mets le son en sourdine|sourdine|mute|unmute|remets le son)$")
WEATHER = re.compile(r"^(?:(?:quelle est |c'est quoi )?la meteo|quel temps (?:fait-il|il fait|fera-t-il)"
                     r"|il fait quel temps|(?:what's|what is) the weather(?: like)?|weather)"
                     r" (?:a|au|aux|en|de|pour|sur|in|at|for) ([a-z' -]{2,40})$")
VOLUME_SET = re.compile(r"^(?:mets|regle|met|set)(?: le)? (?:son|volume) (?:a|to) (\d{1,3})(?: ?%| pour ?cent| percent)?$")

# Mots qui signalent qu'un outil peut servir (sinon : conversation simple).
# Compares a des mots entiers (« photo » ne doit pas viser « photosynthese ») ;
# un « * » final accepte les terminaisons (« rappel* » : rappelle, rappels...).
TOOL_WORDS = (
    "heure*", "date*", "jour*", "aujourd'hui", "demain", "hier", "semaine*", "meteo",
    "temps qu'il", "temperature*", "pleut", "pluie", "minuteur*", "chrono*", "timer*",
    "rappel*", "alarme*", "reveil*", "calcul*", "combien font", "combien fait", "ouvr*",
    "lanc*", "demarr*", "ferme*", "cherche*", "recherche*", "trouve*", "google", "youtube",
    "wikipedia", "internet", "web", "site*", "actualite*", "news", "infos", "volume", "son",
    "musique*", "chanson*", "pause", "suivant*", "precedent*", "capture*", "ecran*",
    "verrouill*", "copi*", "coll*", "presse-papiers", "fichier*", "dossier*", "document*",
    "pdf", "photo", "photos", "image", "images", "souviens", "souvenir*", "retiens", "oublie*",
    "memoire", "je t'ai dit", "application*", "appli*", "systeme", "disque*", "ordinateur*",
    "pc", "batterie", "ram", "cpu", "prix", "cours", "score*", "match*",
    "time", "today", "tomorrow", "weather", "remind*", "open*", "launch*", "search*",
    "look up", "find", "music", "song*", "screen*", "file*", "folder*", "remember",
    "forget", "clipboard", "copy", "calculat*", "latest", "current", "price*",
)
_TOOL_RE = re.compile(r"\b(?:" + "|".join(
    re.escape(word[:-1]) + r"\w*" if word.endswith("*") else re.escape(word) + r"\b"
    for word in TOOL_WORDS) + ")")
_MATH = re.compile(r"\d\s*(?:[x*+/^-]|fois|plus|moins|divise)\s*\d")


def normalize(text: str) -> str:
    """Minuscules, sans accents ni ponctuation finale, sans « Jarvis, peux-tu »."""
    text = unicodedata.normalize("NFKD", text or "").lower()
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.replace("’", "'").strip(" .!?;,")
    text = _POLITE.sub("", text).strip(" .!?;,")
    return " ".join(text.split())


def needs_tools(text: str) -> bool:
    """Vrai si la question peut demander un outil (heure, meteo, ouvrir...)."""
    low = normalize(text)
    return bool(_MATH.search(low) or _TOOL_RE.search(low))


def _today(now: _dt.datetime, lang: str) -> str:
    day, month = DAYS[lang][now.weekday()], MONTHS[lang][now.month - 1]
    if lang == "fr":
        return f"Nous sommes {day} {now.day} {month} {now.year}."
    return f"Today is {day}, {month} {now.day}, {now.year}."


def quick_answer(text: str, lang: str, strings: dict, allow_apps: dict | None = None,
                 now: _dt.datetime | None = None, opener=None,
                 weather_fn=None) -> str | None:
    """Execute une commande simple sans le modele. None si ce n'en est pas une."""
    from .tools import DEFAULT_APPS, open_application

    lang = lang if lang in DAYS else "en"
    fr = lang == "fr"
    low = normalize(text)
    if not low or len(low.split()) > 10:
        return None
    now = now or _dt.datetime.now()
    done = strings.get("pc_done", "Done.")

    if TIME.match(low):
        return f"Il est {say_time(now, lang)}." if fr else f"It is {say_time(now, lang)}."
    if DATE.match(low):
        return _today(now, lang)

    match = WEATHER.match(low)
    if match:
        from .tools import fetch_weather

        city = match.group(1).strip()
        try:
            return (weather_fn or fetch_weather)(city, lang, 6.0)
        except Exception:
            return None  # reseau coupe : le modele prendra le relais

    match = SEARCH.match(low)
    if match:
        query, site = match.group(1), match.group(2).replace("google maps", "maps")
        url = websites.search_url(site, query)
        if url and websites.open_url(url, opener):
            return strings.get("site_searched", "Searching {query} on {site}.").format(
                query=query, site=site.capitalize())
        return None

    match = OPEN.match(low)
    if match:
        name = match.group(1).strip()
        if " et " in f" {name} " or " and " in f" {name} ":
            return None  # demande composee : le modele s'en charge
        apps = allow_apps or DEFAULT_APPS
        url = websites.resolve(name)
        # Application connue (Spotify, Chrome...) d'abord, sinon le site web.
        if opener is None and (name in apps or url is None):
            opened = open_application(name, apps)
            if opened:
                return f"« {opened} » est ouvert." if fr else f"Opened {opened}."
        if url and websites.open_url(url, opener):
            return strings.get("site_opened", "Opening {site}.").format(site=name.capitalize())
        return None

    if PLAY_PAUSE.match(low):
        return done if pc.media("play_pause") else None
    if NEXT.match(low):
        return done if pc.media("next") else None
    if PREVIOUS.match(low):
        return done if pc.media("previous") else None
    match = VOLUME_SET.match(low)
    if match:
        percent = min(100, int(match.group(1)))
        if pc.volume("set", percent):
            return strings.get("volume_set", "Volume set to {percent}%.").format(percent=percent)
        return None
    if VOLUME_UP.search(low):
        return done if pc.volume("up") else None
    if VOLUME_DOWN.search(low):
        return done if pc.volume("down") else None
    if MUTE.match(low):
        return done if pc.volume("mute") else None
    return None


__all__ = ["quick_answer", "needs_tools", "normalize"]
