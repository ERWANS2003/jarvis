"""Briefing de demarrage : « Bonjour Erwan, il est 9 h 12... ».

Compose en local, sans appel au modele (donc instantane et gratuit) :
salutation selon l'heure, prenom et ville tires du profil memorise, date et
heure, meteo de la ville (Open-Meteo, avec un delai court) et rappels du
jour. Ce qui manque est simplement omis.
"""

from __future__ import annotations

import datetime as _dt

DAYS = {"fr": ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"],
        "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday",
               "Sunday"]}
MONTHS = {"fr": ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
                 "août", "septembre", "octobre", "novembre", "décembre"],
          "en": ["January", "February", "March", "April", "May", "June", "July",
                 "August", "September", "October", "November", "December"]}


def salutation(hour: int, lang: str) -> str:
    if lang == "fr":
        if 5 <= hour < 12:
            return "Bonjour"
        if 12 <= hour < 18:
            return "Bon après-midi"
        return "Bonsoir"
    if 5 <= hour < 12:
        return "Good morning"
    if 12 <= hour < 18:
        return "Good afternoon"
    return "Good evening"


def say_time(moment: _dt.datetime, lang: str) -> str:
    if lang == "fr":
        return f"{moment.hour} h {moment.minute:02d}" if moment.minute else f"{moment.hour} h"
    return moment.strftime("%I:%M %p").lstrip("0")


def profile_facts(memory) -> dict:
    """{'name': ..., 'location': ...} depuis le profil memorise (le plus recent)."""
    facts: dict = {}
    if memory is None:
        return facts
    try:
        entries = memory.all(kind="profile", limit=50)
    except Exception:
        return facts
    for entry in entries:  # du plus recent au plus ancien
        label, _, value = entry.text.partition(":")
        label, value = label.strip().lower(), value.strip()
        if label in ("name", "location") and value and label not in facts:
            facts[label] = value
    return facts


def compose(lang: str, now: _dt.datetime, name: str | None = None,
            weather: str | None = None, reminders: list[dict] | None = None) -> str:
    """Assemble le texte du briefing (fonction pure, facile a tester)."""
    fr = lang == "fr"
    parts = [f"{salutation(now.hour, lang)}{', ' + name if name else ''}."]
    day, month = DAYS[lang][now.weekday()], MONTHS[lang][now.month - 1]
    if fr:
        parts.append(f"Il est {say_time(now, lang)}, nous sommes {day} {now.day} {month}.")
    else:
        parts.append(f"It is {say_time(now, lang)}, {day}, {month} {now.day}.")
    if weather:
        parts.append(weather.strip())
    today = sorted((r for r in reminders or []
                    if _dt.datetime.fromisoformat(r["when"]).date() == now.date()
                    and _dt.datetime.fromisoformat(r["when"]) >= now),
                   key=lambda r: r["when"])
    if today:
        first = today[0]
        at = say_time(_dt.datetime.fromisoformat(first["when"]), lang)
        if fr:
            parts.append(f"Un rappel aujourd'hui, à {at} : {first['text']}." if len(today) == 1
                         else f"Vous avez {len(today)} rappels aujourd'hui, le prochain "
                              f"à {at} : {first['text']}.")
        else:
            parts.append(f"One reminder today, at {at}: {first['text']}." if len(today) == 1
                         else f"You have {len(today)} reminders today, the next one "
                              f"at {at}: {first['text']}.")
    parts.append("Que puis-je faire pour vous ?" if fr else "What can I do for you?")
    return " ".join(parts)


def gather(lang: str, memory=None, reminders=None, now: _dt.datetime | None = None,
           weather_fn=None, timeout: float = 4.0) -> str:
    """Rassemble profil, meteo et rappels, puis compose le briefing."""
    now = now or _dt.datetime.now()
    facts = profile_facts(memory)
    weather = None
    city = facts.get("location")
    if city:
        if weather_fn is None:
            from .tools import fetch_weather as weather_fn
        try:
            weather = weather_fn(city, lang, timeout)
        except Exception:
            weather = None
    items = []
    if reminders is not None:
        try:
            items = reminders.list()
        except Exception:
            items = []
    return compose(lang, now, facts.get("name"), weather, items)


__all__ = ["compose", "gather", "profile_facts", "salutation", "say_time"]
