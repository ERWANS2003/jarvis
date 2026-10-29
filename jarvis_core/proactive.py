"""Jarvis proactif : il prend la parole de lui-meme quand c'est utile.

Trois veilles, verifiees chaque minute, chacune avec sa propre retenue :

  * **batterie faible** (moins de 20 %, sur batterie) : une fois par decharge ;
  * **pluie dans l'heure** dans la ville du profil (« j'habite a Lyon ») :
    au plus une fois toutes les 3 heures, et seulement s'il ne pleut pas deja ;
  * **pause** : apres 2 heures d'activite continue au clavier ou a la souris
    (une absence de 10 minutes remet le compteur a zero).

La nuit (22 h - 8 h) les alertes sont seulement affichees, pas dites.
`--no-proactive` coupe tout.
"""

from __future__ import annotations

import datetime as _dt
import sys
import threading
import time

from .text import log

CHECK_EVERY = 60.0
BATTERY_LOW = 20
RAIN_PROBABILITY = 60          # %
RAIN_EVERY = 3 * 3600.0
WORK_LIMIT = 2 * 3600.0
BREAK_RESET = 10 * 60.0        # absence qui compte comme une pause
QUIET_HOURS = (22, 8)

MESSAGES = {
    "fr": {
        "battery": "Ta batterie est à {percent} %, pense à brancher le chargeur.",
        "rain": "Il risque de pleuvoir dans l'heure à {city}, prends un parapluie si tu sors.",
        "break": "Tu travailles depuis {hours} heures sans pause. Lève-toi deux minutes, "
                 "bois un verre d'eau.",
    },
    "en": {
        "battery": "Your battery is at {percent}%, plug in the charger.",
        "rain": "Rain is likely within the hour in {city}, take an umbrella if you go out.",
        "break": "You have been working for {hours} hours without a break. Stand up for "
                 "two minutes and drink some water.",
    },
}


# --------------------------------------------------------------------------- #
# Capteurs (Windows) : remplacables dans les tests
# --------------------------------------------------------------------------- #
def battery() -> tuple[int, bool] | None:
    """(pourcentage, sur secteur) ou None (PC fixe, hors Windows)."""
    if sys.platform != "win32":
        return None
    import ctypes

    class _Power(ctypes.Structure):
        _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                    ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                    ("BatteryLifeTime", ctypes.c_ulong), ("BatteryFullLifeTime", ctypes.c_ulong)]

    status = _Power()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
        return None
    if status.BatteryFlag & 128 or status.BatteryLifePercent > 100:   # pas de batterie
        return None
    return int(status.BatteryLifePercent), status.ACLineStatus == 1


def idle_seconds() -> float:
    """Temps depuis la derniere action au clavier ou a la souris."""
    if sys.platform != "win32":
        return 0.0
    import ctypes

    class _LastInput(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

    info = _LastInput()
    info.cbSize = ctypes.sizeof(info)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    return max(0.0, (ctypes.windll.kernel32.GetTickCount() - info.dwTime) / 1000.0)


def rain_soon(city: str, timeout: float = 6.0) -> bool:
    """Vrai si la pluie est probable dans l'heure et qu'il ne pleut pas deja."""
    from .tools import _http_get_json

    geo = _http_get_json("https://geocoding-api.open-meteo.com/v1/search",
                         {"name": city, "count": 1, "format": "json"}, timeout)
    places = geo.get("results") or []
    if not places:
        return False
    data = _http_get_json("https://api.open-meteo.com/v1/forecast", {
        "latitude": places[0]["latitude"], "longitude": places[0]["longitude"],
        "current": "precipitation", "hourly": "precipitation_probability",
        "forecast_hours": 2, "timezone": "auto"}, timeout)
    if (data.get("current") or {}).get("precipitation", 0) > 0:
        return False
    chances = (data.get("hourly") or {}).get("precipitation_probability") or []
    return any((value or 0) >= RAIN_PROBABILITY for value in chances[:2])


# --------------------------------------------------------------------------- #
# Veilleur
# --------------------------------------------------------------------------- #
class Watcher:
    def __init__(self, lang: str, alert, city=None, sensors: dict | None = None):
        """`alert(text, speak)` previent l'utilisateur ; `city()` donne la ville du profil."""
        self.messages = MESSAGES["fr" if lang == "fr" else "en"]
        self.alert = alert
        self.city = city or (lambda: None)
        sensors = sensors or {}
        self.battery = sensors.get("battery", battery)
        self.idle = sensors.get("idle", idle_seconds)
        self.rain = sensors.get("rain", rain_soon)
        self._battery_warned = False
        self._rain_at = -RAIN_EVERY
        self._work_started: float | None = None
        self._stop = threading.Event()

    def check(self, now: float | None = None, clock: _dt.datetime | None = None) -> list[str]:
        """Une verification ; renvoie les alertes emises (pour les tests)."""
        now = time.monotonic() if now is None else now
        clock = clock or _dt.datetime.now()
        speak = not (clock.hour >= QUIET_HOURS[0] or clock.hour < QUIET_HOURS[1])
        sent: list[str] = []

        def send(text: str) -> None:
            sent.append(text)
            try:
                self.alert(text, speak)
            except Exception as exc:
                log(f"[proactif] {exc}")

        power = self._safe(self.battery)
        if power:
            percent, plugged = power
            if plugged or percent > BATTERY_LOW + 5:
                self._battery_warned = False
            elif percent <= BATTERY_LOW and not self._battery_warned:
                self._battery_warned = True
                send(self.messages["battery"].format(percent=percent))

        idle = self._safe(self.idle) or 0.0
        if idle >= BREAK_RESET:
            self._work_started = None
        elif self._work_started is None:
            self._work_started = now - idle
        elif now - self._work_started >= WORK_LIMIT:
            hours = int((now - self._work_started) // 3600)
            self._work_started = now   # prochain rappel dans 2 h
            send(self.messages["break"].format(hours=hours))

        city = self._safe(self.city)
        if city and now - self._rain_at >= RAIN_EVERY and 7 <= clock.hour < 22:
            self._rain_at = now
            if self._safe(lambda: self.rain(city)):
                send(self.messages["rain"].format(city=city))
        return sent

    @staticmethod
    def _safe(fn):
        try:
            return fn()
        except Exception:
            return None

    def start(self) -> None:
        def run() -> None:
            while not self._stop.wait(CHECK_EVERY):
                self.check()

        threading.Thread(target=run, name="jarvis-proactif", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()


__all__ = ["Watcher", "battery", "idle_seconds", "rain_soon", "MESSAGES"]
