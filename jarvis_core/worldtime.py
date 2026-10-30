"""L'heure dans le monde : « quelle heure est-il à Tokyo ? », exact et instantane.

Un modele de langage se trompe facilement avec les fuseaux et l'heure d'ete ;
ici on calcule avec la base officielle des fuseaux (`zoneinfo` + `tzdata`).
"""

from __future__ import annotations

import datetime as _dt
import unicodedata

# ville ou pays (sans accents, minuscules) -> fuseau IANA
ZONES = {
    "tokyo": "Asia/Tokyo", "japon": "Asia/Tokyo", "japan": "Asia/Tokyo",
    "pekin": "Asia/Shanghai", "beijing": "Asia/Shanghai", "shanghai": "Asia/Shanghai",
    "chine": "Asia/Shanghai", "china": "Asia/Shanghai", "hong kong": "Asia/Hong_Kong",
    "seoul": "Asia/Seoul", "coree": "Asia/Seoul", "singapour": "Asia/Singapore",
    "singapore": "Asia/Singapore", "bangkok": "Asia/Bangkok", "dubai": "Asia/Dubai",
    "dubaï": "Asia/Dubai", "emirats": "Asia/Dubai", "inde": "Asia/Kolkata", "india": "Asia/Kolkata",
    "new delhi": "Asia/Kolkata", "delhi": "Asia/Kolkata", "mumbai": "Asia/Kolkata",
    "riyad": "Asia/Riyadh", "arabie saoudite": "Asia/Riyadh", "la mecque": "Asia/Riyadh",
    "moscou": "Europe/Moscow", "moscow": "Europe/Moscow", "russie": "Europe/Moscow",
    "istanbul": "Europe/Istanbul", "turquie": "Europe/Istanbul",
    "paris": "Europe/Paris", "france": "Europe/Paris", "lyon": "Europe/Paris",
    "marseille": "Europe/Paris", "bruxelles": "Europe/Brussels", "belgique": "Europe/Brussels",
    "geneve": "Europe/Zurich", "suisse": "Europe/Zurich", "berlin": "Europe/Berlin",
    "allemagne": "Europe/Berlin", "madrid": "Europe/Madrid", "espagne": "Europe/Madrid",
    "rome": "Europe/Rome", "italie": "Europe/Rome", "londres": "Europe/London",
    "london": "Europe/London", "angleterre": "Europe/London", "royaume-uni": "Europe/London",
    "lisbonne": "Europe/Lisbon", "portugal": "Europe/Lisbon",
    "ouagadougou": "Africa/Ouagadougou", "burkina": "Africa/Ouagadougou",
    "burkina faso": "Africa/Ouagadougou", "bobo-dioulasso": "Africa/Ouagadougou",
    "abidjan": "Africa/Abidjan", "cote d'ivoire": "Africa/Abidjan", "dakar": "Africa/Dakar",
    "senegal": "Africa/Dakar", "bamako": "Africa/Bamako", "mali": "Africa/Bamako",
    "niamey": "Africa/Niamey", "niger": "Africa/Niamey", "lome": "Africa/Lome",
    "togo": "Africa/Lome", "cotonou": "Africa/Porto-Novo", "benin": "Africa/Porto-Novo",
    "accra": "Africa/Accra", "ghana": "Africa/Accra", "lagos": "Africa/Lagos",
    "nigeria": "Africa/Lagos", "douala": "Africa/Douala", "yaounde": "Africa/Douala",
    "cameroun": "Africa/Douala", "kinshasa": "Africa/Kinshasa", "rdc": "Africa/Kinshasa",
    "casablanca": "Africa/Casablanca", "rabat": "Africa/Casablanca", "maroc": "Africa/Casablanca",
    "alger": "Africa/Algiers", "algerie": "Africa/Algiers", "tunis": "Africa/Tunis",
    "tunisie": "Africa/Tunis", "le caire": "Africa/Cairo", "egypte": "Africa/Cairo",
    "nairobi": "Africa/Nairobi", "kenya": "Africa/Nairobi", "johannesburg": "Africa/Johannesburg",
    "afrique du sud": "Africa/Johannesburg",
    "new york": "America/New_York", "washington": "America/New_York",
    "montreal": "America/Toronto", "quebec": "America/Toronto", "toronto": "America/Toronto",
    "chicago": "America/Chicago", "los angeles": "America/Los_Angeles",
    "san francisco": "America/Los_Angeles", "californie": "America/Los_Angeles",
    "mexico": "America/Mexico_City", "sao paulo": "America/Sao_Paulo", "bresil": "America/Sao_Paulo",
    "rio": "America/Sao_Paulo", "buenos aires": "America/Argentina/Buenos_Aires",
    "argentine": "America/Argentina/Buenos_Aires", "sydney": "Australia/Sydney",
    "australie": "Australia/Sydney", "melbourne": "Australia/Melbourne",
    "auckland": "Pacific/Auckland", "nouvelle-zelande": "Pacific/Auckland",
    "martinique": "America/Martinique", "guadeloupe": "America/Guadeloupe",
    "la reunion": "Indian/Reunion", "reunion": "Indian/Reunion",
}


def _key(place: str) -> str:
    text = unicodedata.normalize("NFKD", place or "").lower()
    text = "".join(c for c in text if not unicodedata.combining(c))
    for prefix in ("la ", "le ", "les ", "l'", "au ", "aux ", "en "):
        if text.startswith(prefix) and text not in ZONES:
            text = text[len(prefix):]
    return text.strip(" ?.!")


def time_in(place: str, now: _dt.datetime | None = None) -> _dt.datetime | None:
    """Heure locale de `place`, ou None si le lieu est inconnu."""
    zone = ZONES.get(_key(place))
    if zone is None:
        return None
    try:
        from zoneinfo import ZoneInfo

        moment = now.astimezone(ZoneInfo(zone)) if now else _dt.datetime.now(ZoneInfo(zone))
    except Exception:
        return None
    return moment


__all__ = ["time_in", "ZONES"]
