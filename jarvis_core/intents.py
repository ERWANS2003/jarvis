"""Reponses instantanees et aiguillage, pour un Jarvis plus rapide.

Mesure (29/10/2026, modele gratuit) : ~5,3 s avant la premiere phrase avec
les 19 outils, ~3,1 s sans outils. Deux raccourcis en decoulent :

  * **commandes instantanees** : l'heure, la date, la meteo d'une ville,
    « ouvre YouTube », « minuteur de 5 minutes », « rappelle-moi dans 10 min de... »,
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
                     r"|il fait quel temps|(?:il )?fait combien(?: de degres)?|(?:il )?fait quelle temperature"
                     r"|(?:il fait )?combien de degres(?: fait-il| il fait)?"
                     r"|quelle (?:est la )?temperature(?: fait-il| il fait)?"
                     r"|(?:what's|what is) the (?:weather|temperature)(?: like)?|weather)"
                     r" (?:a|au|aux|en|de|pour|sur|in|at|for) ([a-z' -]{2,40}?)"
                     r"(?: en ce moment| maintenant| aujourd'hui| right now| today)?$")
VOLUME_SET = re.compile(r"^(?:mets|regle|met|set)(?: le)? (?:son|volume) (?:a|to) (\d{1,3})(?: ?%| pour ?cent| percent)?$")

# Durees parlees : « 10 minutes », « une demi-heure », « 1 h 30 », « 2 minutes et 30 secondes ».
_NUMBERS = {
    "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6, "sept": 7,
    "huit": 8, "neuf": 9, "dix": 10, "onze": 11, "douze": 12, "quinze": 15, "vingt": 20,
    "trente": 30, "quarante": 40, "quarante-cinq": 45, "cinquante": 50, "soixante": 60,
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "ten": 10,
    "fifteen": 15, "twenty": 20, "thirty": 30, "forty-five": 45, "sixty": 60,
}
_UNITS = (("seconde", 1), ("second", 1), ("sec", 1), ("s", 1), ("minute", 60), ("min", 60),
          ("mn", 60), ("heure", 3600), ("hour", 3600), ("h", 3600))
_PART = re.compile(r"\b(\d+|" + "|".join(sorted(_NUMBERS, key=len, reverse=True)) + r")\s*"
                   r"(secondes?|seconds?|sec|s|minutes?|min|mn|heures?|hours?|h)\b")
_SPECIAL = {"une demi-heure": 1800, "une demi heure": 1800, "half an hour": 1800,
            "un quart d'heure": 900, "a quarter of an hour": 900, "trois quarts d'heure": 2700}
DURATION = (r"((?:\d+|[a-z-]+)\s*(?:secondes?|seconds?|sec|s|minutes?|min|mn|heures?|hours?|h)"
            r"(?:\s*(?:et\s+|and\s+)?(?:\d+|[a-z-]+)(?:\s*(?:secondes?|seconds?|sec|s|minutes?|min|mn))?"
            r"(?: et demie)?)?|une demi-heure|une demi heure|half an hour|un quart d'heure"
            r"|a quarter of an hour|trois quarts d'heure)")
TIMER = re.compile(r"^(?:(?:mets|met|lance|demarre|programme|regle|set|start)(?: moi)? )?(?:un |une |a )?"
                   r"(?:minuteur|minuterie|chrono|compte a rebours|timer)(?: de| pour| dans| for| of)? "
                   + DURATION + r"$")
REMIND_IN = re.compile(r"^(?:rappelle(?:-| )moi|previens(?:-| )moi|remind me) (?:dans|in) " + DURATION
                       + r",? (?:de |d'|qu'il faut |que |to |about )(.{2,120})$")
REMIND_AT = re.compile(r"^(?:rappelle(?:-| )moi|previens(?:-| )moi|remind me) (demain |tomorrow )?"
                       r"(?:a|vers|at) (\d{1,2})(?: ?h ?| ?: ?)?(\d{2})?(?: ?(am|pm))?,? "
                       r"(?:de |d'|qu'il faut |que |to |about )(.{2,120})$")

# « joue Daft Punk », « mets la chanson Bohemian Rhapsody », « ecoute du jazz sur Spotify ».
_MUSIC_TAIL = r"(.{2,60}?)(?: (?:sur|on) (youtube|spotify))?$"
MUSIC = re.compile(r"^(?:joue(?:-moi)?|jouer|ecoute|ecouter|play)\s+(?:de la musique |la musique |"
                   r"la chanson |le morceau |le son |l'album |la playlist |un peu de |une chanson de |"
                   r"du |de la |des |some |music by |the song )?" + _MUSIC_TAIL)
MUSIC_PUT = re.compile(r"^(?:mets(?:-moi)?|met|lance(?:-moi)?|demarre)\s+(?:de la musique |la musique |"
                       r"la chanson |le morceau |le son |l'album |la playlist |un peu de |"
                       r"une chanson de |du |de la |des )" + _MUSIC_TAIL)
MUSIC_ANY = re.compile(r"^(?:mets|met|lance|joue|demarre)(?:-moi)? (?:de la|un peu de|la) musique$"
                       r"|^play (?:some )?music$")

NEWS = re.compile(r"^(?:(?:quelles sont|c'est quoi|donne(?:-moi)?|dis(?:-moi)?|lis(?:-moi)?|quoi de neuf dans) )?"
                  r"(?:les |des |le )?(?:infos|informations|actualites|actus|nouvelles|titres|monde|news"
                  r"|headlines)(?: du jour| d'aujourd'hui| de ce matin| today)?"
                  r"(?: (?:sur|a propos de|concernant|about|on) (.{2,40}))?$"
                  r"|^what(?:'s| is| are) the (?:news|headlines)(?: today)?(?: (?:about|on) (.{2,40}))?$")

READ_SELECTION = re.compile(r"^(?:lis|lit|relis|lire)(?:-moi| moi)? (?:ca|ceci|cela|ce texte|ce passage|"
                            r"la selection|le texte selectionne|ce que j'ai (?:selectionne|copie)|"
                            r"le presse-papiers?|ce que j'ai surligne)(?: a voix haute)?$"
                            r"|^read (?:this|that|it|the selection|what i selected)(?: out loud| aloud)?$")
WRITE = re.compile(r"^(?:ecris|ecrit|tape|ecrire|type|write)(?:-moi| moi)?(?: :| que| this)? (.{1,400})$")


def parse_duration(text: str) -> int | None:
    """« 1 h 30 » -> 5400 secondes. None si la duree est illisible."""
    text = " ".join(text.split())
    if text in _SPECIAL:
        return _SPECIAL[text]
    total, last_unit = 0, None
    rest = text
    for match in _PART.finditer(text):
        raw, unit = match.groups()
        value = int(raw) if raw.isdigit() else _NUMBERS.get(raw)
        if value is None:
            return None
        seconds = next(size for name, size in _UNITS if unit.startswith(name))
        total += value * seconds
        last_unit = seconds
        rest = rest.replace(match.group(0), " ", 1)
    rest = " ".join(rest.replace(" et ", " ").replace(" and ", " ").split())
    if rest == "et demie" or rest == "demie":
        total += (last_unit or 0) // 2
    elif rest.isdigit() and last_unit in (3600, 60):   # « 1 h 30 », « 2 minutes 30 »
        total += int(rest) * last_unit // 60
    elif rest:
        return None
    return total or None


def say_duration(seconds: int, lang: str) -> str:
    """5400 -> « 1 heure 30 minutes »."""
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    names = (("heure", "minute", "seconde") if lang == "fr" else ("hour", "minute", "second"))
    parts = [f"{value} {name}{'s' if value > 1 else ''}"
             for value, name in zip((hours, minutes, secs), names) if value]
    return " ".join(parts)


def _original_tail(text: str, words: int) -> str:
    """Les `words` derniers mots du texte d'origine (accents conserves)."""
    tail = " ".join((text or "").replace("’", "'").strip(" .!?;,").split()[-words:])
    return re.sub(r"^(?:d'|qu')", "", tail, flags=re.I)


def _when_phrase(when: _dt.datetime, now: _dt.datetime, lang: str) -> str:
    if when.date() == now.date():
        prefix = "à " if lang == "fr" else "at "
    elif when.date() == (now + _dt.timedelta(days=1)).date():
        prefix = "demain à " if lang == "fr" else "tomorrow at "
    else:
        prefix = when.strftime("%d/%m ") + ("à " if lang == "fr" else "at ")
    return prefix + say_time(when, lang)


def _reminder(low: str, text: str, lang: str, strings: dict, now: _dt.datetime,
              reminders) -> str | None:
    """« rappelle-moi dans 10 minutes de sortir le linge » -> rappel enregistre."""
    match = REMIND_IN.match(low)
    if match:
        seconds = parse_duration(match.group(1))
        if not seconds or seconds > 7 * 86400:
            return None
        when = now + _dt.timedelta(seconds=seconds)
        what = match.group(2)
    else:
        match = REMIND_AT.match(low)
        if not match:
            return None
        tomorrow, hour, minute, ampm, what = match.groups()
        hour, minute = int(hour), int(minute or 0)
        if ampm == "pm" and hour < 12:
            hour += 12
        if hour > 23 or minute > 59:
            return None
        when = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if tomorrow or when <= now:
            when += _dt.timedelta(days=1)
    what = _original_tail(text, len(what.split()))
    reminders.add(when, what)
    return strings.get("reminder_noted", "Noted, I will remind you {when}.").format(
        when=_when_phrase(when, now, lang))

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
    "erreur*", "bug*", "plant*", "crash*", "error*", "exception*", "lis", "ecris", "redige*",
    "colle*", "selection*", "selectionn*", "actu*", "nouvelles", "joue*", "ecoute*",
    "quiz*", "interroge*", "revis*", "write", "type", "paste", "selected", "read",
    "qui est", "qui a", "qui sont", "qui etait", "quand", "combien", "en quelle annee",
    "president*", "ministre*", "population", "record*", "dernier*", "derniere*", "resultat*",
    "gagne*", "vainqueur*", "sorti*", "sortie", "cette annee", "en ce moment", "actuel*",
    "classement*", "taux", "bourse", "action*", "who is", "who won", "when", "how many",
    "how much", "president", "population", "result*", "released", "this year", "currently",
)
_TOOL_RE = re.compile(r"\b(?:" + "|".join(
    re.escape(word[:-1]) + r"\w*" if word.endswith("*") else re.escape(word) + r"\b"
    for word in TOOL_WORDS) + ")")
_RECENT_YEAR = re.compile(r"\b20[2-9]\d\b")   # « le Nobel 2026 » : fait recent, outils
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
    return bool(_MATH.search(low) or _TOOL_RE.search(low) or _RECENT_YEAR.search(low))


REPEAT = re.compile(r"^(?:repete|repetes|repeter|tu peux repeter|peux-tu repeter|redis(?:-le)?|"
                    r"redis-moi|qu'est-ce que tu as dit|qu'as-tu dit|t'as dit quoi|tu as dit quoi|"
                    r"pardon|comment|hein|j'ai pas (?:bien )?(?:entendu|compris)|"
                    r"je n'ai pas (?:bien )?(?:entendu|compris)|repeat(?: that)?|say (?:it|that) again|"
                    r"what did you say|sorry|pardon me)(?: s'il te plait| please)?$")


_SLOWER = re.compile(r"^(?:parle(?:s)?|parlez) (?:un peu )?(?:plus lentement|moins vite)$|^ralentis$|"
                     r"^moins vite$|^plus lentement$|^(?:speak|talk) (?:more )?slow(?:er|ly)$|^slow down$")
_FASTER = re.compile(r"^(?:parle(?:s)?|parlez) (?:un peu )?(?:plus vite|plus rapidement)$|^accelere$|"
                     r"^plus vite$|^(?:speak|talk) faster$|^speed up$")
PACE_STEP = 1.15


def pace_request(text: str) -> float | None:
    """« Parle plus lentement » -> 1/1,15 ; « plus vite » -> 1,15 ; sinon None."""
    low = normalize(text)
    if _SLOWER.match(low):
        return 1 / PACE_STEP
    if _FASTER.match(low):
        return PACE_STEP
    return None


def last_reply(history) -> str:
    """Derniere reponse prononcee de Jarvis (sans la partie detaillee affichee)."""
    for message in reversed(history or []):
        if getattr(message, "type", "") == "ai":
            content = message.content if isinstance(message.content, str) else ""
            content = content.split("---DETAIL---", 1)[0].strip()
            if content:
                return content
    return ""


def repeat_request(text: str) -> bool:
    return bool(REPEAT.match(normalize(text)))


def selection_for(ctx):
    """Module de lecture/ecriture de texte, si les outils sont actifs (Windows)."""
    from . import selection

    return selection if ctx is not None and selection.supported() else None


def _today(now: _dt.datetime, lang: str) -> str:
    day, month = DAYS[lang][now.weekday()], MONTHS[lang][now.month - 1]
    if lang == "fr":
        return f"Nous sommes {day} {now.day} {month} {now.year}."
    return f"Today is {day}, {month} {now.day}, {now.year}."


def quick_answer(text: str, lang: str, strings: dict, allow_apps: dict | None = None,
                 now: _dt.datetime | None = None, opener=None,
                 weather_fn=None, timers=None, reminders=None,
                 music_finder=None, news_fn=None, selection_api=None) -> str | None:
    """Execute une commande simple sans le modele. None si ce n'en est pas une."""
    from .tools import DEFAULT_APPS, open_application

    lang = lang if lang in DAYS else "en"
    fr = lang == "fr"
    low = normalize(text)
    now = now or _dt.datetime.now()
    if low and reminders is not None and len(low.split()) <= 30:
        answer = _reminder(low, text, lang, strings, now, reminders)
        if answer:
            return answer
    match = WRITE.match(low)
    if match and selection_api is not None:
        words = len(match.group(1).split())
        if words <= 80 and selection_api.paste_text(_original_tail(text, words)):
            return strings.get("typed_done", "Done, it is written.")
        return None
    if READ_SELECTION.match(low) and selection_api is not None:
        content, _origin = selection_api.selection_or_clipboard()
        if not content.strip():
            return strings.get("nothing_selected", "Select a text first.")
        return selection_api.for_speech(content, lang)
    if not low or len(low.split()) > 10:
        return None
    done = strings.get("pc_done", "Done.")

    match = TIMER.match(low)
    if match and timers is not None:
        seconds = parse_duration(match.group(1))
        if not seconds or seconds > 86400:
            return None
        duration = say_duration(seconds, lang)
        timers.set_timer(seconds, strings.get("timer_label", "{duration} timer done.").format(
            duration=duration))
        return strings.get("timer_started", "Timer set for {duration}.").format(duration=duration)

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

    match = NEWS.match(low)
    if match:
        from . import news

        topic = (match.group(1) or match.group(2) or "").strip()
        titles = (news_fn or news.fetch_headlines)(lang, topic)
        return news.say_headlines(titles, lang, topic) if titles else None

    if MUSIC_ANY.match(low):
        url = websites.play_music("musique du moment playlist", opener=opener, finder=music_finder)
        return strings.get("music_playing", "Playing {query}.").format(
            query="de la musique" if fr else "some music") if url else None
    match = MUSIC.match(low) or MUSIC_PUT.match(low)
    if match and match.group(1).strip() not in {"pause", "la pause", "le son"}:
        query, service = match.group(1).strip(), match.group(2) or "youtube"
        words = len(query.split()) + (2 if match.group(2) else 0)
        original = _original_tail(text, words).split()[:len(query.split())]
        query = " ".join(original) or query
        if websites.play_music(query, service, opener=opener, finder=music_finder):
            return strings.get("music_playing", "Playing {query}.").format(query=query)
        return None

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


__all__ = ["quick_answer", "needs_tools", "normalize", "parse_duration", "selection_for",
           "repeat_request", "last_reply", "pace_request"]
