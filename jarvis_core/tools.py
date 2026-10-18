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
import operator
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from langchain_core.tools import BaseTool, tool

from .memory import FACT, MemoryStore

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
            if isinstance(node.op, ast.Pow) and abs(right) > 100:
                raise ValueError("exposant trop grand")
            return _ALLOWED_BINOPS[type(node.op)](left, right)
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

    def list_timers(self) -> list[dict]:
        with self._lock:
            return [
                {k: v for k, v in entry.items() if k != "handle"}
                for entry in self._timers.values()
            ]

    def cancel(self, timer_id: int | None = None) -> int:
        cancelled = 0
        with self._lock:
            targets = (
                [self._timers[timer_id]] if timer_id in self._timers
                else list(self._timers.values())
            )
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
        """Search the web for recent information."""
        try:
            return fetch_web_search(query, ctx.timeout)
        except Exception as exc:
            return (ctx.string("tool_error") or "The tool failed.") + f" ({exc})"

    registry = TimerRegistry(speak=ctx.speak)

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
