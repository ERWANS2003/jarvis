"""Humeurs de l'orbe : une teinte discrete selon l'heure et le temps qu'il fait.

Le theme choisi reste reconnaissable : l'humeur ne le colore qu'a ~12 %. Aube
rosee, journee neutre, couchant dore, nuit bleutee ; la pluie refroidit la
teinte, le grand soleil la rechauffe, l'orage l'assombrit.
"""

from __future__ import annotations

import datetime as _dt
import threading
import time

from .text import log

WEATHER_EVERY = 1800.0
HOUR_TINTS = (   # (de, a, couleur, force)
    (5, 8, (255, 170, 150), 0.12),      # aube
    (8, 17, (255, 255, 255), 0.0),      # journee : le theme pur
    (17, 21, (255, 165, 80), 0.13),     # couchant
    (21, 24, (90, 110, 220), 0.14),     # soir
    (0, 5, (70, 80, 190), 0.16),        # nuit
)


def weather_kind(code: int | None) -> str | None:
    """Code meteo Open-Meteo -> soleil, pluie, neige, orage, ou None."""
    if code is None:
        return None
    if code >= 95:
        return "storm"
    if code in (71, 73, 75, 77, 85, 86):
        return "snow"
    if 51 <= code <= 82:
        return "rain"
    if code <= 1:
        return "sun"
    return None


_WEATHER_TINTS = {"rain": ((90, 140, 220), 0.10), "storm": ((70, 70, 130), 0.16),
                  "snow": ((210, 230, 255), 0.12), "sun": ((255, 215, 120), 0.07)}


def tint_for(hour: int, kind: str | None = None) -> tuple[tuple[int, int, int], float]:
    """(couleur, force) de l'humeur : l'heure, puis le temps par-dessus."""
    color, strength = (255, 255, 255), 0.0
    for start, end, tint, force in HOUR_TINTS:
        if start <= hour < end:
            color, strength = tint, force
    extra = _WEATHER_TINTS.get(kind)
    if extra is None:
        return color, strength
    if strength == 0.0:
        return extra
    mixed = tuple(round((a + b) / 2) for a, b in zip(color, extra[0]))
    return mixed, min(0.2, max(strength, extra[1]))


def apply_tint(image, color: tuple[int, int, int], strength: float):
    """Melange les pixels vers `color` sans toucher a la transparence."""
    if strength <= 0.0:
        return image
    from PIL import Image

    image = image.convert("RGBA")
    alpha = image.getchannel("A")
    tinted = Image.blend(image.convert("RGB"), Image.new("RGB", image.size, color), strength)
    tinted.putalpha(alpha)
    return tinted


class Mood:
    """Humeur courante ; la meteo est lue en fond, au plus toutes les 30 minutes."""

    def __init__(self, city=None, fetch=None):
        self.city = city or (lambda: None)
        self.fetch = fetch or fetch_code
        self.kind: str | None = None
        self._read_at = -WEATHER_EVERY
        self._busy = False

    def _refresh(self, now: float) -> None:
        if self._busy or now - self._read_at < WEATHER_EVERY:
            return
        self._read_at = now
        self._busy = True

        def run() -> None:
            try:
                city = self.city()
                if city:
                    self.kind = weather_kind(self.fetch(city))
            except Exception as exc:
                log(f"[humeur] {exc}")
            finally:
                self._busy = False

        threading.Thread(target=run, name="jarvis-humeur", daemon=True).start()

    def current(self, clock: _dt.datetime | None = None) -> tuple[tuple[int, int, int], float]:
        self._refresh(time.monotonic())
        return tint_for((clock or _dt.datetime.now()).hour, self.kind)


def fetch_code(city: str, timeout: float = 6.0) -> int | None:
    from .tools import _http_get_json

    geo = _http_get_json("https://geocoding-api.open-meteo.com/v1/search",
                         {"name": city, "count": 1, "format": "json"}, timeout)
    places = geo.get("results") or []
    if not places:
        return None
    data = _http_get_json("https://api.open-meteo.com/v1/forecast",
                          {"latitude": places[0]["latitude"], "longitude": places[0]["longitude"],
                           "current": "weather_code", "timezone": "auto"}, timeout)
    return (data.get("current") or {}).get("weather_code")


__all__ = ["Mood", "tint_for", "apply_tint", "weather_kind"]
