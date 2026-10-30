"""Horizon 3 - outils et actions (function calling).

Tous les outils sont utilisables sans cle d'API (Open-Meteo, Wikipedia,
DuckDuckGo) et fonctionnent hors-ligne pour les plus simples (heure, calcul,
minuteurs, ouverture d'applications, memoire).

Securite :
  * ``calculate`` n'evalue qu'une grammaire AST blanche (pas d'eval()).
  * ``open_application`` n'ouvre que des noms presents dans une liste blanche.
"""

from __future__ import annotations

import ast
import datetime as _dt
import math
import operator
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from langchain_core.tools import BaseTool, tool

from . import files as files_mod
from . import pc
from . import websites
from .memory import FACT, MemoryStore
from .reminders import ReminderStore, parse_when
from .text import log

# --------------------------------------------------------------------------- #
# Contexte partage par les outils
# --------------------------------------------------------------------------- #
@dataclass
class ToolContext:
    lang: str = "en"
    strings: dict = field(default_factory=dict)
    memory: MemoryStore | None = None
    speak: Callable[[str], None] | None = None
    timeout: float = 8.0
    allow_apps: dict[str, str] = field(default_factory=dict)
    reminders: ReminderStore | None = None
    vision: Callable[[str], str] | None = None   # question -> reponse sur l'ecran
    timers: "TimerRegistry | None" = None        # partage avec les commandes rapides
    quiz: object | None = None                   # quiz.QuizSession (mode revision)
    lists: object | None = None                  # extras.ListStore (courses, taches...)

    def string(self, key: str, default: str = "") -> str:
        return self.strings.get(key, default)


# --------------------------------------------------------------------------- #
# Calculatrice sure (AST blanche)
# --------------------------------------------------------------------------- #
_ALLOWED_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_ALLOWED_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
MAX_DIGITS = 400  # au-dela, le resultat n'a aucun sens a l'oral


def safe_eval(expression: str) -> float:
    """Evalue une expression arithmetique simple, sans eval()."""
    expression = (expression or "").replace(",", ".").strip()
    if not expression or len(expression) > 200:
        raise ValueError("expression invalide")
    tree = ast.parse(expression, mode="eval")

    def walk(node):
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return node.value
            raise ValueError("constante non numerique")
        if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINOPS:
            left, right = walk(node.left), walk(node.right)
            if isinstance(node.op, ast.Pow):
                if abs(right) > 100:
                    raise ValueError("exposant trop grand")
                # (99**99)**99 : l'exposant est petit mais le resultat aurait
                # des millions de chiffres. On estime sa taille avant calcul.
                if abs(left) > 1 and right > 0 and \
                        right * math.log10(abs(left)) > MAX_DIGITS:
                    raise ValueError("resultat trop grand")
            value = _ALLOWED_BINOPS[type(node.op)](left, right)
            if isinstance(value, int) and value.bit_length() > MAX_DIGITS * 3.33:
                raise ValueError("resultat trop grand")
            return value
        if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARY:
            return _ALLOWED_UNARY[type(node.op)](walk(node.operand))
        raise ValueError("noeud non autorise")

    return walk(tree)


# --------------------------------------------------------------------------- #
# Meteo (Open-Meteo, sans cle)
# --------------------------------------------------------------------------- #
_WMO_EN = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "depositing rime fog", 51: "light drizzle",
    53: "moderate drizzle", 55: "dense drizzle", 61: "slight rain",
    63: "moderate rain", 65: "heavy rain", 66: "freezing rain",
    67: "heavy freezing rain", 71: "slight snow", 73: "moderate snow",
    75: "heavy snow", 77: "snow grains", 80: "slight rain showers",
    81: "moderate rain showers", 82: "violent rain showers",
    85: "slight snow showers", 86: "heavy snow showers",
    95: "thunderstorm", 96: "thunderstorm with slight hail",
    99: "thunderstorm with heavy hail",
}
_WMO_FR = {
    0: "ciel dégagé", 1: "ciel plutôt dégagé", 2: "partiellement nuageux",
    3: "couvert", 45: "brouillard", 48: "brouillard givrant",
    51: "bruine légère", 53: "bruine modérée", 55: "bruine dense",
    61: "pluie faible", 63: "pluie modérée", 65: "pluie forte",
    66: "pluie verglaçante", 67: "pluie verglaçante forte",
    71: "neige faible", 73: "neige modérée", 75: "neige forte",
    77: "grains de neige", 80: "averses faibles", 81: "averses modérées",
    82: "averses violentes", 85: "averses de neige faibles",
    86: "averses de neige fortes", 95: "orage",
    96: "orage avec grêle", 99: "orage avec forte grêle",
}


def describe_weather(code: int, lang: str = "en") -> str:
    table = _WMO_FR if lang == "fr" else _WMO_EN
    return table.get(int(code), "unknown" if lang != "fr" else "inconnu")


def _http_get_json(url: str, params: dict, timeout: float):
    import requests

    response = requests.get(
        url, params=params, timeout=timeout,
        headers={"User-Agent": "jarvis-assistant/2.0"},
    )
    response.raise_for_status()
    return response.json()


def fetch_weather(location: str, lang: str = "en", timeout: float = 8.0) -> str:
    """Meteo actuelle pour une ville (Open-Meteo). Leve une exception si echec."""
    geo = _http_get_json(
        "https://geocoding-api.open-meteo.com/v1/search",
        {"name": location, "count": 1, "language": lang, "format": "json"},
        timeout,
    )
    results = geo.get("results") or []
    if not results:
        return (f"Je ne trouve pas « {location} »." if lang == "fr"
                else f"I could not find '{location}'.")
    place = results[0]
    forecast = _http_get_json(
        "https://api.open-meteo.com/v1/forecast",
        {
            "latitude": place["latitude"],
            "longitude": place["longitude"],
            "current": "temperature_2m,weather_code,wind_speed_10m",
            "timezone": "auto",
        },
        timeout,
    )
    current = forecast.get("current") or {}
    temp = current.get("temperature_2m")
    code = current.get("weather_code", -1)
    wind = current.get("wind_speed_10m")
    city = place.get("name", location)
    desc = describe_weather(code, lang)
    if lang == "fr":
        return (f"À {city}, il fait {temp} °C, {desc}, "
                f"vent {wind} km/h.")
    return f"In {city}, it is {temp} °C, {desc}, wind {wind} km/h."


# --------------------------------------------------------------------------- #
# Wikipedia (sans cle)
# --------------------------------------------------------------------------- #
def fetch_wikipedia(query: str, lang: str = "en", timeout: float = 8.0) -> str:
    """Resume Wikipedia pour une requete. Leve une exception si echec."""
    import requests

    search = requests.get(
        f"https://{lang}.wikipedia.org/w/api.php",
        params={
            "action": "query", "list": "search", "srsearch": query,
            "format": "json", "srlimit": 1,
        },
        timeout=timeout,
        headers={"User-Agent": "jarvis-assistant/2.0"},
    )
    search.raise_for_status()
    hits = (search.json().get("query") or {}).get("search") or []
    if not hits:
        return ("Aucun résultat." if lang == "fr" else "No result.")
    title = hits[0]["title"]
    summary = requests.get(
        f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/"
        + requests.utils.quote(title.replace(" ", "_")),
        timeout=timeout,
        headers={"User-Agent": "jarvis-assistant/2.0"},
    )
    summary.raise_for_status()
    extract = (summary.json().get("extract") or "").strip()
    return extract or ("Aucun résumé." if lang == "fr" else "No summary.")


# --------------------------------------------------------------------------- #
# Recherche web (DuckDuckGo lite, sans cle)
# --------------------------------------------------------------------------- #
_TAG_RE = re.compile(r"<[^>]+>")


def fetch_web_search(query: str, timeout: float = 8.0, limit: int = 4) -> str:
    """Recherche web via DuckDuckGo (HTML lite). Leve une exception si echec."""
    import requests

    response = requests.get(
        "https://html.duckduckgo.com/html/",
        params={"q": query},
        timeout=timeout,
        headers={"User-Agent": "Mozilla/5.0 (compatible; jarvis-assistant/2.0)"},
    )
    response.raise_for_status()
    html = response.text
    snippets = re.findall(
        r'class="result__snippet"[^>]*>(.*?)</a>', html, re.DOTALL
    )
    titles = re.findall(r'class="result__a"[^>]*>(.*?)</a>', html, re.DOTALL)
    lines: list[str] = []
    for index, snippet in enumerate(snippets[:limit]):
        text = _TAG_RE.sub("", snippet)
        text = " ".join(text.split())
        title = _TAG_RE.sub("", titles[index]) if index < len(titles) else ""
        title = " ".join(title.split())
        if text:
            lines.append(f"- {title}: {text}" if title else f"- {text}")
    if not lines:
        return "Aucun résultat." if _is_french(query) else "No result."
    return "\n".join(lines)


def _is_french(text: str) -> bool:
    return bool(re.search(r"[éèêàçùôî]", text or ""))


# Groq gratuit : 8 000 jetons par minute. Une recherche de 7 000 caracteres (~2 000
# jetons) plus les descriptions d'outils suffisait a depasser : on s'en tient a 3 500.
SEARCH_CHARS = 3500


# --------------------------------------------------------------------------- #
# Minuteurs
# --------------------------------------------------------------------------- #
class TimerRegistry:
    """Minuteurs en memoire, avec rappel parle + bip."""

    def __init__(self, speak: Callable[[str], None] | None = None):
        self._timers: dict[int, dict] = {}
        self._next_id = 1
        self._lock = threading.Lock()
        self.speak = speak

    def set_timer(self, seconds: float, label: str = "") -> int:
        seconds = max(1.0, float(seconds))
        with self._lock:
            timer_id = self._next_id
            self._next_id += 1
            handle = threading.Timer(seconds, self._fire, args=(timer_id,))
            handle.daemon = True
            self._timers[timer_id] = {
                "id": timer_id, "label": label or f"timer {timer_id}",
                "seconds": seconds, "handle": handle, "done": False,
                "ends_at": time.monotonic() + seconds,
            }
            handle.start()
        return timer_id

    def _fire(self, timer_id: int) -> None:
        with self._lock:
            entry = self._timers.get(timer_id)
            if entry is None:
                return
            entry["done"] = True
            label = entry["label"]
        _beep()
        if self.speak:
            try:
                self.speak(label)
            except Exception:
                pass

    def remaining(self) -> list[float]:
        """Secondes restantes de chaque minuteur en cours (le plus proche d'abord)."""
        now = time.monotonic()
        with self._lock:
            left = [entry["ends_at"] - now for entry in self._timers.values()
                    if not entry["done"] and "ends_at" in entry]
        return sorted(max(0.0, value) for value in left)

    def list_timers(self) -> list[dict]:
        with self._lock:
            return [
                {k: v for k, v in entry.items() if k != "handle"}
                for entry in self._timers.values()
            ]

    def cancel(self, timer_id: int | None = None) -> int:
        """Annule un minuteur, ou tous si `timer_id` vaut None (id inconnu -> 0)."""
        cancelled = 0
        with self._lock:
            if timer_id is None:
                targets = list(self._timers.values())
            elif timer_id in self._timers:
                targets = [self._timers[timer_id]]
            else:
                targets = []
            for entry in targets:
                if not entry["done"]:
                    entry["handle"].cancel()
                self._timers.pop(entry["id"], None)
                cancelled += 1
        return cancelled


def _beep() -> None:
    try:
        if sys.platform == "win32":
            import winsound

            winsound.Beep(880, 400)
        else:
            sys.stdout.write("\a")
            sys.stdout.flush()
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# Ouverture d'applications (liste blanche)
# --------------------------------------------------------------------------- #
DEFAULT_APPS = {
    "notepad": "notepad",
    "bloc-notes": "notepad",
    "calculator": "calc",
    "calculatrice": "calc",
    "explorer": "explorer",
    "files": "explorer",
    "fichiers": "explorer",
    "browser": "start https://www.google.com",
    "navigateur": "start https://www.google.com",
    "paint": "mspaint",
    "terminal": "cmd",
    "cmd": "cmd",
    "task manager": "taskmgr",
    "gestionnaire des taches": "taskmgr",
    "gestionnaire des tâches": "taskmgr",
    # navigateurs
    "chrome": "start chrome",
    "google chrome": "start chrome",
    "edge": "start msedge",
    "microsoft edge": "start msedge",
    "firefox": "start firefox",
    "brave": "start brave",
    "opera": "start opera",
    "vivaldi": "start vivaldi",
    # bureautique/dev
    "vscode": "start code",
    "visual studio code": "start code",
    "code": "start code",
    "notepad++": "start notepad++",
    "github desktop": "start githubdesktop",
    # multimédia
    "vlc": "start vlc",
    "spotify": "start spotify:",
    "groove music": "start mswindowsmusic:",
    "windows media player": "start wmplayer",
    "mpv": "start mpv",
    # comms/jeux
    "discord": "start discord:",
    "whatsapp": "start whatsapp:",
    "telegram": "start telegram:",
    "teams": "start msteams:",
    "microsoft teams": "start msteams:",
    "steam": "start steam:",
    "epic games launcher": "start com.epicgames.launcher:",
    "epic games": "start com.epicgames.launcher:",
    "epic": "start com.epicgames.launcher:",
    "league of legends": "start leagueclient:",
    "riot client": "start riotclient:",
    # utilitaires
    "powershell": "start powershell",
    "windows terminal": "start wt",
    "wt": "start wt",
    "files explorer": "explorer",
    "settings": "start ms-settings:",
    "parametres": "start ms-settings:",
    "paramètres": "start ms-settings:",
}


def open_application(name: str, allow: dict[str, str] | None = None) -> str:
    """Ouvre une application de la liste blanche (jamais de commande libre)."""
    allow = allow or DEFAULT_APPS
    key = (name or "").strip().lower()
    if not key:
        return ""
    if key not in allow:
        for known in allow:
            if len(known) >= 3 and (known in key or key in known):
                key = known
                break
    if key not in allow:
        return ""
    command = allow[key]
    try:
        if sys.platform == "win32":
            if command.startswith("start "):
                subprocess.Popen(command, shell=True)
            else:
                subprocess.Popen([command], shell=False)
        else:
            subprocess.Popen(command.split(), shell=False)
    except Exception:
        return ""
    return key


# --------------------------------------------------------------------------- #
# Construction des outils LangChain
# --------------------------------------------------------------------------- #
def build_tools(ctx: ToolContext) -> list[BaseTool]:
    """Retourne la liste d'outils LangChain pour le graphe ReAct."""
    lang = ctx.lang
    fr = lang == "fr"
    tools: list[BaseTool] = []

    @tool
    def get_current_datetime() -> str:
        """Return the current local date and time."""
        now = _dt.datetime.now()
        return now.strftime("%A %d %B %Y, %H:%M")

    @tool
    def calculate(expression: str) -> str:
        """Evaluate a simple arithmetic expression (e.g. '12 * (3 + 4)')."""
        try:
            value = safe_eval(expression)
        except Exception:
            return ("Calcul impossible." if fr else "Cannot compute that.")
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        return str(value)

    @tool
    def get_weather(location: str) -> str:
        """Get the current weather for a city name."""
        try:
            return fetch_weather(location, lang, ctx.timeout)
        except Exception as exc:
            return (ctx.string("tool_error") or "The tool failed.") + f" ({exc})"

    @tool
    def search_wikipedia(query: str) -> str:
        """Look up a factual summary on Wikipedia."""
        try:
            return fetch_wikipedia(query, lang, ctx.timeout)
        except Exception as exc:
            return (ctx.string("tool_error") or "The tool failed.") + f" ({exc})"

    @tool
    def web_search(query: str) -> str:
        """Search the web and READ the top pages, for recent or precise facts
        (news, figures, dates, prices, results, who holds a position). Returns
        page excerpts labelled by source: base your answer on them and name
        the source briefly."""
        from . import websearch

        try:
            found = websearch.research(query, ctx.lang, ctx.timeout)
            if found:
                return found[:SEARCH_CHARS]
        except Exception as exc:
            log(f"[web] lecture des pages impossible : {exc}")
        try:
            return fetch_web_search(query, ctx.timeout)
        except Exception as exc:
            return (ctx.string("tool_error") or "The tool failed.") + f" ({exc})"

    registry = ctx.timers or TimerRegistry(speak=ctx.speak)
    ctx.timers = registry

    @tool
    def set_timer(seconds: float, label: str = "") -> str:
        """Start a countdown timer. `seconds` is the delay, `label` a name."""
        try:
            seconds = float(seconds)
        except Exception:
            return "Durée invalide." if fr else "Invalid duration."
        if seconds > 86400:
            seconds = 86400.0
        timer_id = registry.set_timer(seconds, label)
        if fr:
            return f"Minuteur {timer_id} lancé pour {int(seconds)} secondes."
        return f"Timer {timer_id} started for {int(seconds)} seconds."

    @tool
    def list_timers() -> str:
        """List the running timers."""
        entries = registry.list_timers()
        if not entries:
            return ctx.string("no_timers") or "No timer is running."
        lines = []
        running = ctx.string("timer_state_running") or "running"
        done = ctx.string("timer_state_done") or "done"
        for entry in entries:
            status = done if entry["done"] else running
            lines.append(f"{entry['id']}: {entry['label']} ({status})")
        return "\n".join(lines)

    @tool
    def cancel_timer(timer_id: int = 0) -> str:
        """Cancel one timer by id, or all timers when id is 0."""
        count = registry.cancel(timer_id or None)
        template = ctx.string("cancelled_timers") or "{count} timer(s) cancelled."
        return template.format(count=count)

    @tool
    def open_application_tool(name: str) -> str:
        """Open an allowed application on the computer by name."""
        opened = open_application(name, ctx.allow_apps or DEFAULT_APPS)
        if not opened:
            return ctx.string("app_denied") or "I am not allowed to open that."
        return (f"« {opened} » est ouvert." if fr else f"Opened {opened}.")

    tools += [
        get_current_datetime, calculate, get_weather, search_wikipedia,
        web_search, set_timer, list_timers, cancel_timer, open_application_tool,
    ]

    # -- controle du PC (touches multimedia, Windows) ------------------------ #
    unsupported = ctx.string("pc_unsupported") or "Not available on this computer."

    @tool
    def control_volume(action: str, percent: int = 50) -> str:
        """Change the computer volume. `action` is 'up', 'down', 'mute' (toggle)
        or 'set' (then `percent` is the target level, 0-100)."""
        try:
            done = pc.volume(action, percent)
        except ValueError:
            return "Action inconnue." if fr else "Unknown action."
        if not done:
            return unsupported
        if action.strip().lower() == "set":
            return ctx.string("volume_set", "Volume set to {percent}%.").format(
                percent=min(max(int(percent), 0), 100))
        return ctx.string("pc_done") or "Done."

    @tool
    def control_media(action: str) -> str:
        """Control the music or video playing on the computer (Spotify,
        YouTube...). `action` is 'play_pause', 'next', 'previous' or 'stop'."""
        try:
            done = pc.media(action)
        except ValueError:
            return "Action inconnue." if fr else "Unknown action."
        return (ctx.string("pc_done") or "Done.") if done else unsupported

    @tool
    def lock_screen() -> str:
        """Lock the computer screen. Only when the user explicitly asks."""
        return (ctx.string("screen_locked") or "Screen locked.") if pc.lock_screen() \
            else unsupported

    @tool
    def take_screenshot() -> str:
        """Take a screenshot of the whole screen and save it as a PNG file."""
        path = pc.screenshot()
        if path is None:
            return ctx.string("tool_error") or "The tool failed."
        return ctx.string("screenshot_saved", "Screenshot saved: {path}").format(
            path=path)

    tools += [control_volume, control_media, lock_screen, take_screenshot]

    # -- presse-papiers et fichiers ------------------------------------------ #
    @tool
    def read_clipboard() -> str:
        """Read the text the user selected in their window (or, failing that,
        copied), e.g. to summarise, translate, explain or correct it. Use it
        for 'this text', 'this page', 'what I selected', 'what I copied'."""
        from . import selection

        if not selection.supported():
            return unsupported
        text, _origin = selection.selection_or_clipboard()
        text = text.strip()
        if not text:
            return ctx.string("clipboard_empty") or "The clipboard is empty."
        return text[:6000]

    @tool
    def type_text(text: str) -> str:
        """Write `text` into the window the user is working in (an e-mail,
        a document, a chat), by pasting it. Use it when the user asks you to
        write, draft or type something for them ('rédige un mail...',
        'écris...', 'réponds-lui que...'): compose the full text yourself,
        then call this tool with it. Answer afterwards with a short sentence."""
        from . import selection

        if not selection.paste_text(text):
            return unsupported
        return ctx.string("typed_done") or "Done, it is written."

    @tool
    def copy_to_clipboard(text: str) -> str:
        """Copy a text to the clipboard so the user can paste it."""
        if not files_mod.write_clipboard(text):
            return unsupported
        return ctx.string("clipboard_copied") or "Copied."

    last_found: list = []

    def _describe(found) -> str:
        return "\n".join(f"{index}. {item.label()}"
                         for index, item in enumerate(found, start=1))

    @tool
    def find_files(query: str = "", kind: str = "") -> str:
        """Search the user's personal folders (Desktop, Documents, Downloads,
        Pictures...) for files whose name contains `query`, newest first.
        `kind` optionally filters: pdf, document, word, excel, presentation,
        image, music, video, archive. Then open one with open_file(number)."""
        found = files_mod.find_files(query, kind or None, limit=5)
        last_found[:] = found
        if not found:
            return ctx.string("files_none") or "No matching file."
        return _describe(found)

    @tool
    def open_file(choice: str) -> str:
        """Open a file with its usual application. `choice` is a number from
        the last find_files results, or a file name to search for (the most
        recent match is opened). For 'my latest PDF', call find_files with
        kind='pdf' first, then open number 1."""
        choice = (choice or "").strip()
        target = None
        if choice.isdigit() and 1 <= int(choice) <= len(last_found):
            target = last_found[int(choice) - 1]
        elif choice:
            found = files_mod.find_files(choice, limit=1)
            target = found[0] if found else None
        if target is None:
            return ctx.string("files_none") or "No matching file."
        if not files_mod.open_file(target.path):
            return ctx.string("file_denied") or "I cannot open that file."
        return ctx.string("file_opened", "Opening {name}.").format(name=target.path.name)

    tools += [read_clipboard, type_text, copy_to_clipboard, find_files, open_file]

    # -- sites web --------------------------------------------------------- #
    @tool
    def open_website(site: str) -> str:
        """Open a website in the browser: a known name (YouTube, Gmail, Netflix,
        Spotify, Google Maps, GitHub, ChatGPT, Wikipedia, Amazon, WhatsApp...)
        or an address such as 'lemonde.fr'. Prefer this over opening the
        browser application when the user names a site."""
        url = websites.resolve(site)
        if url is None:
            return ctx.string("site_unknown", "I do not know that site.")
        if not websites.open_url(url):
            return ctx.string("tool_error") or "The tool failed."
        return ctx.string("site_opened", "Opening {site}.").format(site=site.strip())

    @tool
    def search_on_site(query: str, site: str = "google") -> str:
        """Search `query` directly on a site and open the results: youtube,
        google, images, maps, wikipedia, amazon, spotify, github, netflix,
        twitch, or traduction (Google Translate)."""
        url = websites.search_url(site, query)
        if url is None:
            return ctx.string("site_unknown", "I do not know that site.")
        if not websites.open_url(url):
            return ctx.string("tool_error") or "The tool failed."
        return ctx.string("site_searched", "Searching {query} on {site}.").format(
            query=query.strip(), site=site.strip())

    @tool
    def play_music(query: str, service: str = "youtube") -> str:
        """Play music by name right away: an artist, a song, a genre or a
        playlist (e.g. 'Daft Punk', 'lofi to study'). `service` is 'youtube'
        (starts the first video automatically) or 'spotify'."""
        if not websites.play_music(query, service):
            return ctx.string("tool_error") or "The tool failed."
        return ctx.string("music_playing", "Playing {query}.").format(query=query.strip())

    @tool
    def get_news(topic: str = "") -> str:
        """Today's news headlines, in general or about `topic` (e.g. 'football',
        'intelligence artificielle'). Use it for any question about current
        events or the news."""
        from . import news

        titles = news.fetch_headlines(ctx.lang, topic, timeout=ctx.timeout)
        return news.say_headlines(titles, ctx.lang, topic.strip())

    tools += [open_website, search_on_site, play_music, get_news]

    # -- vision (capture d'ecran envoyee au modele : sur demande seulement) -- #
    if ctx.vision is not None:
        vision = ctx.vision

        @tool
        def look_at_screen(question: str = "") -> str:
            """Look at the user's screen (a screenshot is sent to a vision model)
            to answer `question`, e.g. read an error, describe a window,
            summarise a page. ONLY use it when the user explicitly asks you to
            look at, read or check their screen."""
            try:
                answer = vision(question)
            except Exception as exc:
                return (ctx.string("vision_error") or "I could not see the screen.") \
                    + f" ({type(exc).__name__})"
            return answer or (ctx.string("vision_error") or "I could not see the screen.")

        tools.append(look_at_screen)

    # -- aide au code : expliquer une erreur ---------------------------------- #
    @tool
    def explain_error() -> str:
        """Get the error message the user is looking at (selected text first,
        then the screen if vision is available) so you can explain it. Use it
        for 'c'est quoi cette erreur ?', 'pourquoi ça plante ?', 'aide-moi à
        corriger ça'. Then answer in 2-4 spoken sentences: the cause in plain
        words, then the concrete fix (command, line to change). No code blocks."""
        from . import selection

        text = ""
        if selection.supported():
            text, _origin = selection.selection_or_clipboard()
        if len(text.strip()) > 8:
            return "ERROR TEXT (selected by the user):\n" + text.strip()[:6000]
        if ctx.vision is None:
            return ctx.string("nothing_selected") or "Select the error text first."
        try:
            seen = ctx.vision("Recopie mot pour mot le message d'erreur visible (et le code ou "
                              "la commande juste autour), puis dis dans quel logiciel il apparait."
                              if fr else "Copy verbatim the visible error message (and the code "
                              "or command around it), then name the application showing it.")
        except Exception as exc:
            return (ctx.string("vision_error") or "I could not see the screen.") \
                + f" ({type(exc).__name__})"
        return "ERROR SEEN ON SCREEN:\n" + (seen or "")

    tools.append(explain_error)

    # -- mode revision (quiz oral) ---------------------------------------------- #
    from .quiz import QuizSession

    quiz = ctx.quiz or QuizSession(ctx.lang)
    ctx.quiz = quiz

    @tool
    def start_quiz(topic: str, questions: int = 5) -> str:
        """Start an oral quiz to help the user revise `topic` ('interroge-moi
        sur...', 'fais-moi réviser...', 'quiz me on...'), with `questions`
        questions (default 5). Then follow the returned rules."""
        return quiz.start(topic, questions)

    @tool
    def record_quiz_answer(correct: bool) -> str:
        """During a quiz, record whether the user's last answer was correct."""
        return quiz.record(bool(correct))

    @tool
    def stop_quiz() -> str:
        """Stop the running quiz and get the final score."""
        return quiz.stop()

    tools += [start_quiz, record_quiz_answer, stop_quiz]

    # -- rappels a date fixe (persistants) ----------------------------------- #
    if ctx.reminders is not None:
        reminders = ctx.reminders

        @tool
        def set_reminder(when: str, text: str) -> str:
            """Set a reminder for a precise date and time, kept even if Jarvis
            restarts. `when` must be 'YYYY-MM-DD HH:MM' in local time: call
            get_current_datetime first to resolve words like 'tomorrow'.
            `text` is what to remind the user about."""
            try:
                moment = parse_when(when)
            except ValueError:
                return ctx.string("reminder_bad_date") or "Invalid date."
            reminder_id = reminders.add(moment, text)
            return ctx.string("reminder_set", "Reminder {id} set for {when}.").format(
                id=reminder_id, when=moment.strftime("%d/%m/%Y %H:%M"))

        @tool
        def list_reminders() -> str:
            """List the upcoming reminders."""
            items = reminders.list()
            if not items:
                return ctx.string("no_reminders") or "No reminder."
            return "\n".join(
                f"{item['id']}: {item['when'].replace('T', ' ')} - {item['text']}"
                for item in items)

        @tool
        def cancel_reminder(reminder_id: int = 0) -> str:
            """Cancel one reminder by id, or all reminders when id is 0."""
            count = reminders.cancel(reminder_id or None)
            return ctx.string("cancelled_reminders", "{count} reminder(s) cancelled.") \
                .format(count=count)

        tools += [set_reminder, list_reminders, cancel_reminder]

    if ctx.memory is not None:
        store = ctx.memory

        @tool
        def remember_fact(text: str) -> str:
            """Store a durable fact about the user in long-term memory."""
            try:
                store.remember(text, kind=FACT, source="user")
            except Exception:
                return ctx.string("tool_error") or "The tool failed."
            return ctx.string("remembered") or "Okay, I will remember that."

        @tool
        def recall_memory(query: str) -> str:
            """Search long-term memory for facts matching a query."""
            hits = [m for m in store.search(query, k=5) if m.kind != "episode"]
            if not hits:
                return ctx.string("memory_empty") or "I do not know that yet."
            return "\n".join(f"- {m.text}" for m in hits)

        @tool
        def forget_memory(query: str) -> str:
            """Forget memories matching a query."""
            removed = store.forget_matching(query)
            if not removed:
                return ctx.string("nothing_to_forget") or "Nothing to forget."
            return ctx.string("forgotten") or "Forgotten."

        tools += [remember_fact, recall_memory, forget_memory]

    return tools


__all__ = [
    "ToolContext",
    "TimerRegistry",
    "DEFAULT_APPS",
    "build_tools",
    "safe_eval",
    "fetch_weather",
    "fetch_wikipedia",
    "fetch_web_search",
    "describe_weather",
    "open_application",
]
