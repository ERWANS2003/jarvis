"""Dix commandes instantanees de plus, sans le modele (< 1 s, la plupart hors ligne).

  * **calcul** : « combien font 18 500 fois 3,5 », « 15 % de 240 », « racine de 144 » ;
  * **unites** : « 5 miles en kilometres », « 30 degres Fahrenheit en Celsius » ;
  * **devises** : « 50 dollars en euros » (cours du jour, open.er-api.com, sans cle,
    dirham et franc CFA compris) ;
  * **listes** : « ajoute du lait et des oeufs a ma liste de courses », « lis ma
    liste de courses », « retire le lait », « vide ma liste de taches » ;
  * **dates** : « dans combien de jours est Noel », « quel jour tombe le 14 juillet
    2027 », « quel jour serons-nous dans 3 semaines », « quelle semaine sommes-nous » ;
  * **hasard** : de, pile ou face, nombre entre deux bornes, « choisis entre pizza et sushi » ;
  * **soleil** : « a quelle heure se couche le soleil (a Lyon) » (Open-Meteo) ;
  * **batterie** : niveau, charge, autonomie (Windows, sans paquet en plus) ;
  * **« que sais-tu de moi ? »** : ce que la memoire a retenu, dit en clair ;
  * **pomodoro** : 25 min de concentration puis 5 min de pause, annonces par la voix.

Tout est reconnu sur une version sans accents de la phrase, mais les mots
repris dans la reponse (articles d'une liste, choix) gardent leurs accents.
"""

from __future__ import annotations

import datetime as _dt
import json
import random
import re
import threading
import time
import unicodedata
from pathlib import Path

from .briefing import DAYS, MONTHS, say_time

# --------------------------------------------------------------------------- #
# Texte : version sans accents alignee caractere par caractere sur l'original
# --------------------------------------------------------------------------- #
_POLITE = re.compile(
    r"^(?:jarvis|hey jarvis|ok jarvis|dis jarvis)?[ ,]*"
    r"(?:s'il te plait |s'il vous plait |please |est-ce que tu peux |peux-tu |tu peux |"
    r"pourrais-tu |can you |could you )*")


def _plain_char(char: str) -> str:
    base = "".join(c for c in unicodedata.normalize("NFKD", char) if not unicodedata.combining(c))
    return base[:1] or char


def aligned(text: str) -> tuple[str, str]:
    """(sans accents, original) en minuscules, de meme longueur, sans politesse."""
    orig = " ".join((text or "").replace("’", "'").lower().split())
    plain = "".join(_plain_char(c) for c in orig)
    start = _POLITE.match(plain).end()
    end = len(plain)
    while start < end and plain[start] in " ,.!?;:":
        start += 1
    while end > start and plain[end - 1] in " ,.!?;:":
        end -= 1
    return plain[start:end], orig[start:end]


_NUMBER_WORDS = {
    "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6, "sept": 7,
    "huit": 8, "neuf": 9, "dix": 10, "onze": 11, "douze": 12, "quinze": 15, "vingt": 20,
    "trente": 30, "cent": 100, "mille": 1000, "a": 1, "an": 1, "one": 1, "two": 2,
    "three": 3, "four": 4, "five": 5, "ten": 10, "twelve": 12, "twenty": 20,
    "hundred": 100,
}
_NUM = r"(-?\d+(?:[.,]\d+)?|" + "|".join(sorted(_NUMBER_WORDS, key=len, reverse=True)) + ")"


def _number(raw: str) -> float | None:
    raw = (raw or "").strip()
    if raw in _NUMBER_WORDS:
        return float(_NUMBER_WORDS[raw])
    try:
        return float(raw.replace(",", "."))
    except ValueError:
        return None


def say_number(value: float, lang: str, decimals: int | None = None) -> str:
    """12.0 -> « 12 », 8.04672 -> « 8,05 » (virgule en francais)."""
    if decimals is None:
        decimals = 2 if abs(value) >= 1 else 4
    value = round(float(value), decimals)
    if value.is_integer():
        text = str(int(value))
    else:
        text = f"{value:.{decimals}f}".rstrip("0").rstrip(".")
    return text.replace(".", ",") if lang == "fr" else text


def _join(items: list[str], lang: str) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + (" et " if lang == "fr" else " and ") + items[-1]


# --------------------------------------------------------------------------- #
# 1. Calcul
# --------------------------------------------------------------------------- #
CALC = re.compile(r"^(?:combien (?:font|fait|ca fait)|ca fait combien|calcule(?:-moi)?|"
                  r"what(?: is|'s)|how much is|calculate)\s+(.+)$")
_CALC_STEPS = (
    (r"(?<=\d) (?=\d{3}\b)", ""),                                    # 18 500 -> 18500
    (r"(?<=\d),(?=\d)", "."),                                        # 3,5 -> 3.5
    (r"(\d+(?:\.\d+)?)\s*(?:%|pour ?cent|percent)\s*(?:de |d'|of )\s*(\d+(?:\.\d+)?)",
     r"(\1/100*\2)"),
    (r"\b(?:la )?racine(?: carree)? de (\d+(?:\.\d+)?)|\bsquare root of (\d+(?:\.\d+)?)",
     lambda m: f"({m.group(1) or m.group(2)}**0.5)"),
    (r"\bmultiplie(?:e)? par\b|\bfois\b|\btimes\b|\bmultiplied by\b|(?<=\d)\s*x\s*(?=\d)", "*"),
    (r"\bdivise(?:e)? par\b|\bdivided by\b|\bsur\b", "/"),
    (r"\bplus\b", "+"), (r"\bmoins\b|\bminus\b", "-"),
    (r"\bau carre\b|\bsquared\b", "**2"), (r"\bau cube\b|\bcubed\b", "**3"),
    (r"\b(?:puissance|exposant|to the power of)\b", "**"),
)


def calculate(plain: str, lang: str) -> str | None:
    match = CALC.match(plain)
    if not match:
        return None
    expression = match.group(1)
    for pattern, repl in _CALC_STEPS:
        expression = re.sub(pattern, repl, expression)
    expression = " ".join(expression.split())
    if not re.fullmatch(r"[\d\s.+\-*/()]+", expression) or \
            not re.search(r"\d\s*(?:\*\*|[+\-*/])\s*[\d(]|\*\*", expression):
        return None
    from .tools import safe_eval

    try:
        value = safe_eval(expression)
    except ZeroDivisionError:
        return "On ne peut pas diviser par zéro." if lang == "fr" else "You cannot divide by zero."
    except Exception:
        return None
    if isinstance(value, complex):
        return None
    spoken = say_number(value, lang, 4 if abs(value) < 1 else 2) if isinstance(value, float) \
        else str(value)
    return f"Ça fait {spoken}." if lang == "fr" else f"That's {spoken}."


# --------------------------------------------------------------------------- #
# 2. Unites   cle -> (categorie, facteur vers l'unite de base, noms fr, noms en)
# --------------------------------------------------------------------------- #
UNITS = {
    "mm": ("len", 0.001, ("millimètre", "millimètres"), ("millimetre", "millimetres")),
    "cm": ("len", 0.01, ("centimètre", "centimètres"), ("centimetre", "centimetres")),
    "m": ("len", 1.0, ("mètre", "mètres"), ("metre", "metres")),
    "km": ("len", 1000.0, ("kilomètre", "kilomètres"), ("kilometre", "kilometres")),
    "in": ("len", 0.0254, ("pouce", "pouces"), ("inch", "inches")),
    "ft": ("len", 0.3048, ("pied", "pieds"), ("foot", "feet")),
    "yd": ("len", 0.9144, ("yard", "yards"), ("yard", "yards")),
    "mi": ("len", 1609.344, ("mile", "miles"), ("mile", "miles")),
    "nmi": ("len", 1852.0, ("mille marin", "milles marins"), ("nautical mile", "nautical miles")),
    "mg": ("mass", 1e-6, ("milligramme", "milligrammes"), ("milligram", "milligrams")),
    "g": ("mass", 0.001, ("gramme", "grammes"), ("gram", "grams")),
    "kg": ("mass", 1.0, ("kilo", "kilos"), ("kilogram", "kilograms")),
    "t": ("mass", 1000.0, ("tonne", "tonnes"), ("tonne", "tonnes")),
    "lb": ("mass", 0.45359237, ("livre", "livres"), ("pound", "pounds")),
    "oz": ("mass", 0.028349523125, ("once", "onces"), ("ounce", "ounces")),
    "ml": ("vol", 0.001, ("millilitre", "millilitres"), ("millilitre", "millilitres")),
    "cl": ("vol", 0.01, ("centilitre", "centilitres"), ("centilitre", "centilitres")),
    "l": ("vol", 1.0, ("litre", "litres"), ("litre", "litres")),
    "gal": ("vol", 3.785411784, ("gallon", "gallons"), ("gallon", "gallons")),
    "kmh": ("speed", 1 / 3.6, ("kilomètre heure", "kilomètres heure"),
            ("kilometre per hour", "kilometres per hour")),
    "ms": ("speed", 1.0, ("mètre par seconde", "mètres par seconde"),
           ("metre per second", "metres per second")),
    "mph": ("speed", 0.44704, ("mile par heure", "miles par heure"),
            ("mile per hour", "miles per hour")),
    "kn": ("speed", 1852 / 3600, ("nœud", "nœuds"), ("knot", "knots")),
    "c": ("temp", 0, ("degré Celsius", "degrés Celsius"), ("degree Celsius", "degrees Celsius")),
    "f": ("temp", 0, ("degré Fahrenheit", "degrés Fahrenheit"),
          ("degree Fahrenheit", "degrees Fahrenheit")),
    "k": ("temp", 0, ("kelvin", "kelvins"), ("kelvin", "kelvins")),
    "o": ("data", 1.0, ("octet", "octets"), ("byte", "bytes")),
    "ko": ("data", 1e3, ("kilooctet", "kilooctets"), ("kilobyte", "kilobytes")),
    "mo": ("data", 1e6, ("mégaoctet", "mégaoctets"), ("megabyte", "megabytes")),
    "go": ("data", 1e9, ("gigaoctet", "gigaoctets"), ("gigabyte", "gigabytes")),
    "to": ("data", 1e12, ("téraoctet", "téraoctets"), ("terabyte", "terabytes")),
    "s": ("time", 1.0, ("seconde", "secondes"), ("second", "seconds")),
    "min": ("time", 60.0, ("minute", "minutes"), ("minute", "minutes")),
    "h": ("time", 3600.0, ("heure", "heures"), ("hour", "hours")),
    "d": ("time", 86400.0, ("jour", "jours"), ("day", "days")),
    "wk": ("time", 604800.0, ("semaine", "semaines"), ("week", "weeks")),
    "yr": ("time", 31557600.0, ("an", "ans"), ("year", "years")),
}
_UNIT_ALIASES = {
    "mm": "mm", "cm": "cm", "m": "m", "km": "km", "meter": "m", "meters": "m",
    "kilometer": "km", "kilometers": "km", "pouce": "in", "inch": "in", "inches": "in",
    "pied": "ft", "pieds": "ft", "foot": "ft", "feet": "ft", "mille nautique": "nmi",
    "milles nautiques": "nmi", "mg": "mg", "g": "g", "gr": "g", "kg": "kg", "kilogramme": "kg",
    "kilogrammes": "kg", "gram": "g", "grams": "g", "tonne": "t", "tonnes": "t", "lb": "lb",
    "lbs": "lb", "livre": "lb", "livres": "lb", "oz": "oz", "ml": "ml", "cl": "cl", "l": "l",
    "liter": "l", "liters": "l", "gallon": "gal", "gallons": "gal", "km/h": "kmh", "kmh": "kmh",
    "kilometres-heure": "kmh", "kilometres par heure": "kmh", "kilometres a l'heure": "kmh",
    "km par heure": "kmh", "m/s": "ms", "mph": "mph", "miles a l'heure": "mph",
    "noeud": "kn", "noeuds": "kn", "knot": "kn", "knots": "kn", "celsius": "c", "c": "c",
    "fahrenheit": "f", "f": "f", "kelvin": "k", "kelvins": "k", "octet": "o", "octets": "o",
    "byte": "o", "bytes": "o", "ko": "ko", "kb": "ko", "mo": "mo", "mb": "mo", "go": "go",
    "gb": "go", "tb": "to", "sec": "s", "secondes": "s", "seconde": "s", "minutes": "min",
    "minute": "min", "min": "min", "heure": "h", "heures": "h", "hour": "h", "hours": "h",
    "jour": "d", "jours": "d", "day": "d", "days": "d", "semaine": "wk", "semaines": "wk",
    "week": "wk", "weeks": "wk", "an": "yr", "ans": "yr", "annee": "yr", "annees": "yr",
    "year": "yr", "years": "yr",
}
for _key, (_cat, _f, _fr, _en) in UNITS.items():
    for _name in (*_fr, *_en):
        _UNIT_ALIASES.setdefault("".join(_plain_char(c) for c in _name.lower()), _key)


def unit_key(phrase: str) -> str | None:
    phrase = re.sub(r"^(?:de |d'|des |en |in |to )", "", " ".join(phrase.split()))
    phrase = re.sub(r"^(?:degres?|degrees?) ", "", phrase)
    return _UNIT_ALIASES.get(phrase) or _UNIT_ALIASES.get(phrase.rstrip("s"))


def _to_base(value: float, key: str) -> float:
    if key == "c":
        return value
    if key == "f":
        return (value - 32) * 5 / 9
    if key == "k":
        return value - 273.15
    return value * UNITS[key][1]


def _from_base(value: float, key: str) -> float:
    if key == "c":
        return value
    if key == "f":
        return value * 9 / 5 + 32
    if key == "k":
        return value + 273.15
    return value / UNITS[key][1]


def unit_name(key: str, value: float, lang: str) -> str:
    names = UNITS[key][2 if lang == "fr" else 3]
    plural = abs(value) >= 2 if lang == "fr" else abs(value) != 1
    return names[1] if plural else names[0]


# --------------------------------------------------------------------------- #
# 3. Devises
# --------------------------------------------------------------------------- #
CURRENCIES = {   # code -> (fr singulier, fr pluriel, en singulier, en pluriel)
    "EUR": ("euro", "euros", "euro", "euros"),
    "USD": ("dollar", "dollars", "dollar", "dollars"),
    "CAD": ("dollar canadien", "dollars canadiens", "Canadian dollar", "Canadian dollars"),
    "GBP": ("livre sterling", "livres sterling", "pound sterling", "pounds sterling"),
    "CHF": ("franc suisse", "francs suisses", "Swiss franc", "Swiss francs"),
    "JPY": ("yen", "yens", "yen", "yen"),
    "CNY": ("yuan", "yuans", "yuan", "yuan"),
    "MAD": ("dirham", "dirhams", "dirham", "dirhams"),
    "XOF": ("franc CFA", "francs CFA", "CFA franc", "CFA francs"),
    "TND": ("dinar tunisien", "dinars tunisiens", "Tunisian dinar", "Tunisian dinars"),
    "DZD": ("dinar algérien", "dinars algériens", "Algerian dinar", "Algerian dinars"),
    "INR": ("roupie", "roupies", "rupee", "rupees"),
    "AED": ("dirham émirati", "dirhams émiratis", "UAE dirham", "UAE dirhams"),
    "TRY": ("livre turque", "livres turques", "Turkish lira", "Turkish lira"),
    "RUB": ("rouble", "roubles", "rouble", "roubles"),
    "BRL": ("réal", "reais", "real", "reais"),
    "MXN": ("peso mexicain", "pesos mexicains", "Mexican peso", "Mexican pesos"),
    "KRW": ("won", "wons", "won", "won"),
    "AUD": ("dollar australien", "dollars australiens", "Australian dollar", "Australian dollars"),
    "SEK": ("couronne suédoise", "couronnes suédoises", "Swedish krona", "Swedish kronor"),
}
_CURRENCY_ALIASES = {
    "eur": "EUR", "usd": "USD", "dollar us": "USD", "dollars us": "USD",
    "dollar americain": "USD", "dollars americains": "USD", "us dollar": "USD",
    "us dollars": "USD", "cad": "CAD", "gbp": "GBP", "livre anglaise": "GBP",
    "livres anglaises": "GBP", "pound": "GBP", "pounds": "GBP", "chf": "CHF",
    "jpy": "JPY", "yen japonais": "JPY", "cny": "CNY", "renminbi": "CNY", "mad": "MAD",
    "dirham marocain": "MAD", "dirhams marocains": "MAD", "xof": "XOF", "fcfa": "XOF",
    "franc cfa": "XOF", "francs cfa": "XOF", "tnd": "TND", "dzd": "DZD", "inr": "INR",
    "aed": "AED", "try": "TRY", "lire turque": "TRY", "rub": "RUB", "brl": "BRL",
    "real": "BRL", "mxn": "MXN", "krw": "KRW", "aud": "AUD", "sek": "SEK",
}
for _code, _names in CURRENCIES.items():
    for _name in _names:
        _CURRENCY_ALIASES.setdefault("".join(_plain_char(c) for c in _name.lower()), _code)


def currency_code(phrase: str) -> str | None:
    phrase = re.sub(r"^(?:de |d'|des |en |in |to )", "", " ".join(phrase.split()))
    return _CURRENCY_ALIASES.get(phrase)


_RATES: dict[str, tuple[float, dict]] = {}
RATES_TTL = 3600.0


def fetch_rate(base: str, target: str, timeout: float = 4.0) -> float:
    """Cours du jour (open.er-api.com, sans cle), garde une heure en cache."""
    cached = _RATES.get(base)
    if cached is None or time.monotonic() - cached[0] > RATES_TTL:
        from .tools import _http_get_json

        data = _http_get_json(f"https://open.er-api.com/v6/latest/{base}", {}, timeout)
        if data.get("result") != "success":
            raise RuntimeError("cours indisponible")
        cached = (time.monotonic(), data["rates"])
        _RATES[base] = cached
    return float(cached[1][target])


CONVERT = re.compile(r"^(?:(?:convertis(?:-moi)?|convertir|convert|combien (?:font|fait|valent|vaut)|"
                     r"ca fait combien(?: de)?|how much is|how many is)\s+)?" + _NUM +
                     r" ([a-z/' -]{1,30}?) (?:en|in|to|into) ([a-z/' -]{1,30})$")
CONVERT_HOW_MANY = re.compile(r"^(?:combien (?:de |d')|how many )([a-z/' -]{1,30}?) "
                              r"(?:y a-t-il dans|dans|font|fait|in|are in|are there in) "
                              + _NUM + r" ([a-z/' -]{1,30})$")


def convert(plain: str, lang: str, rate_fn=None) -> str | None:
    match = CONVERT.match(plain)
    if match:
        raw, source, target = match.groups()
    else:
        match = CONVERT_HOW_MANY.match(plain)
        if not match:
            return None
        target, raw, source = match.groups()
    value = _number(raw)
    if value is None:
        return None
    fr = lang == "fr"
    cur_from, cur_to = currency_code(source), currency_code(target)
    if cur_from and not cur_to and unit_key(target) == "lb":
        cur_to = "GBP"
    if cur_to and not cur_from and unit_key(source) == "lb":
        cur_from = "GBP"
    if cur_from and cur_to:
        try:
            rate = (rate_fn or fetch_rate)(cur_from, cur_to)
        except Exception:
            return None                 # reseau coupe : le modele prendra le relais
        result = value * rate
        names_from, names_to = CURRENCIES[cur_from], CURRENCIES[cur_to]
        idx = 0 if fr else 2
        name_from = names_from[idx + (1 if (abs(value) >= 2 if fr else value != 1) else 0)]
        name_to = names_to[idx + (1 if (abs(result) >= 2 if fr else result != 1) else 0)]
        a, b = say_number(value, lang), say_number(result, lang, 2)
        return (f"{a} {name_from} valent environ {b} {name_to}, au cours du jour." if fr
                else f"{a} {name_from} is about {b} {name_to} at today's rate.")
    key_from, key_to = unit_key(source), unit_key(target)
    if not key_from or not key_to or UNITS[key_from][0] != UNITS[key_to][0]:
        return None
    result = _from_base(_to_base(value, key_from), key_to)
    a, b = say_number(value, lang), say_number(result, lang)
    verb = "font" if fr else ("are" if value != 1 else "is")
    return f"{a} {unit_name(key_from, value, lang)} {verb} {b} {unit_name(key_to, result, lang)}."


# --------------------------------------------------------------------------- #
# 4. Listes (courses, taches...) conservees dans un petit fichier JSON
# --------------------------------------------------------------------------- #
class ListStore:
    """Listes nommees persistantes, sures entre fils."""

    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else None
        self._lock = threading.Lock()
        self._lists: dict[str, list[str]] = {}
        if self.path is not None and self.path.is_file():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self._lists = {str(k): [str(i) for i in v] for k, v in data.items()
                               if isinstance(v, list)}
            except Exception:
                self._lists = {}

    def _save(self) -> None:
        if self.path is None:
            return
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._lists, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    @staticmethod
    def _same(a: str, b: str) -> bool:
        """« oeufs » == « œufs » == « Œufs » (la dictee hesite entre les deux)."""
        def key(text):
            return aligned(text)[0].replace("œ", "oe").replace("æ", "ae")
        return key(a) == key(b)

    def items(self, name: str) -> list[str]:
        with self._lock:
            return list(self._lists.get(name, []))

    def names(self) -> list[str]:
        with self._lock:
            return [name for name, items in self._lists.items() if items]

    def add(self, name: str, items: list[str]) -> list[str]:
        with self._lock:
            current = self._lists.setdefault(name, [])
            added = [item for item in items if not any(self._same(item, old) for old in current)]
            current.extend(added)
            self._save()
        return added

    def remove(self, name: str, items: list[str]) -> list[str]:
        with self._lock:
            current = self._lists.get(name, [])
            removed = [old for old in current if any(self._same(item, old) for item in items)]
            self._lists[name] = [old for old in current if old not in removed]
            self._save()
        return removed

    def clear(self, name: str) -> int:
        with self._lock:
            count = len(self._lists.get(name, []))
            self._lists[name] = []
            self._save()
        return count


_LIST_REF = (r"(?:ma|la|mes|notre|my|the|our) (?:liste(?: (?:de |des |d'|du |pour (?:les |la )?)?"
             r"(?P<name>[a-z' -]{2,30}?))?|(?P<ename>[a-z' -]{2,30}?) list)")
LIST_ADD = re.compile(r"^(?:ajoute|rajoute|mets|met|inscris|note|add|put)(?:-moi| moi)? "
                      r"(?P<items>.+?) (?:a|sur|dans|to|on) " + _LIST_REF + "$")
LIST_REMOVE = re.compile(r"^(?:retire|enleve|supprime|efface|barre|raye|remove|delete|cross off)"
                         r"(?:-moi| moi)? (?P<items>.+?) (?:de|du|des|from|off) " + _LIST_REF + "$")
LIST_CLEAR = re.compile(r"^(?:vide|efface|supprime|clear|empty)(?: toute| entierement)? " + _LIST_REF + "$")
LIST_READ = re.compile(r"^(?:(?:qu'est-ce qu'il y a|qu'y a-t-il|quoi|il y a quoi|qu'est-ce que j'ai) "
                       r"(?:sur|dans) |(?:lis|lit|relis|donne|dis|montre|rappelle)(?:-moi| moi)? |"
                       r"(?:c'est quoi|quelle est|qu'est-ce que c'est) |what's on |what is on |"
                       r"read(?: me)? )?" + _LIST_REF + "$")
_DETERMINER = re.compile(r"^(?:du |de la |de l'|des |le |la |les |l'|un |une |d'|aussi |"
                         r"some |the |a |an )+")
_KNOWN_LISTS = {
    "courses": ("courses", "course", "achats", "shopping", "epicerie", "commissions",
                "grocery", "groceries"),
    "tâches": ("taches", "tache", "choses a faire", "trucs a faire", "to do", "todo", "to-do",
               "a faire", "tasks", "task"),
}
_LIST_TITLES = {"courses": ("liste de courses", "shopping list"),
                "tâches": ("liste de tâches", "to-do list")}


def _list_name(match, orig: str, store: ListStore) -> tuple[str, str]:
    """(cle, titre) de la liste visee : « courses », « tâches » ou un nom libre."""
    group = "name" if match.group("name") else "ename" if match.group("ename") else None
    if group is None:                       # « ma liste » : la seule qui existe, sinon courses
        names = store.names()
        key = names[0] if len(names) == 1 else "courses"
    else:
        plain = match.group(group).strip()
        key = next((k for k, words in _KNOWN_LISTS.items() if plain in words),
                   orig[match.start(group):match.end(group)].strip())
    titles = _LIST_TITLES.get(key)
    return key, titles if titles else (f"liste de {key}", f"{key} list")


def _list_items(span: str) -> list[str]:
    items = []
    for part in re.split(r",\s*|\s+et\s+|\s+and\s+|\s+puis\s+", span):
        part = _DETERMINER.sub("", part.strip(" .")).strip()
        if part and part not in items:
            items.append(part)
    return items[:12]


def lists_answer(plain: str, orig: str, lang: str, store: ListStore) -> str | None:
    fr = lang == "fr"
    if "list" not in plain:
        return None
    for kind, pattern in (("clear", LIST_CLEAR), ("add", LIST_ADD), ("remove", LIST_REMOVE),
                          ("read", LIST_READ)):
        match = pattern.match(plain)
        if match:
            break
    else:
        return None
    key, titles = _list_name(match, orig, store)
    title = titles[0] if fr else titles[1]
    if kind == "clear":
        store.clear(key)
        return f"Votre {title} est vidée." if fr else f"Your {title} is now empty."
    if kind == "read":
        items = store.items(key)
        if not items:
            return f"Votre {title} est vide." if fr else f"Your {title} is empty."
        shown = items[:12]
        more = len(items) - len(shown)
        tail = (f", et {more} autres" if fr else f", and {more} more") if more else ""
        return (f"Sur votre {title} : {_join(shown, lang)}{tail}." if fr
                else f"On your {title}: {_join(shown, lang)}{tail}.")
    items = _list_items(orig[match.start("items"):match.end("items")])
    if not items:
        return None
    if kind == "add":
        added = store.add(key, items)
        if not added:
            return (f"{_join(items, lang).capitalize()}, c'est déjà sur votre {title}." if fr
                    else f"{_join(items, lang).capitalize()} is already on your {title}.")
        return (f"C'est noté : {_join(added, lang)} sur votre {title}." if fr
                else f"Noted: {_join(added, lang)} on your {title}.")
    removed = store.remove(key, items)
    if not removed:
        return (f"Je ne trouve pas « {_join(items, lang)} » sur votre {title}." if fr
                else f"I can't find '{_join(items, lang)}' on your {title}.")
    return (f"J'ai retiré {_join(removed, lang)} de votre {title}." if fr
            else f"Removed {_join(removed, lang)} from your {title}.")


# --------------------------------------------------------------------------- #
# 5. Dates
# --------------------------------------------------------------------------- #
_MONTHS_PLAIN = {name: i + 1 for lang in ("fr", "en")
                 for i, name in enumerate("".join(_plain_char(c) for c in m.lower())
                                          for m in MONTHS[lang])}
_MONTH_RE = "|".join(sorted(_MONTHS_PLAIN, key=len, reverse=True))
_DAY_MONTH = re.compile(r"^(?:le |the )?(1er|premier|\d{1,2})(?:st|nd|rd|th)? (" + _MONTH_RE +
                        r")(?: (\d{4}))?$|^(" + _MONTH_RE + r") (\d{1,2})(?:st|nd|rd|th)?(?:,? (\d{4}))?$")
HOLIDAYS = {   # mots -> (mois, jour, nom fr, nom en)
    "noel": (12, 25, "Noël", "Christmas"), "christmas": (12, 25, "Noël", "Christmas"),
    "nouvel an": (1, 1, "le Nouvel An", "New Year's Day"),
    "jour de l'an": (1, 1, "le jour de l'An", "New Year's Day"),
    "new year": (1, 1, "le Nouvel An", "New Year's Day"),
    "new year's day": (1, 1, "le Nouvel An", "New Year's Day"),
    "saint-sylvestre": (12, 31, "la Saint-Sylvestre", "New Year's Eve"),
    "new year's eve": (12, 31, "la Saint-Sylvestre", "New Year's Eve"),
    "halloween": (10, 31, "Halloween", "Halloween"),
    "saint-valentin": (2, 14, "la Saint-Valentin", "Valentine's Day"),
    "saint valentin": (2, 14, "la Saint-Valentin", "Valentine's Day"),
    "valentine's day": (2, 14, "la Saint-Valentin", "Valentine's Day"),
    "fete nationale": (7, 14, "la fête nationale", "Bastille Day"),
    "toussaint": (11, 1, "la Toussaint", "All Saints' Day"),
    "armistice": (11, 11, "l'Armistice", "Armistice Day"),
    "fete du travail": (5, 1, "la fête du Travail", "Labour Day"),
    "fete de la musique": (6, 21, "la fête de la Musique", "Music Day"),
}


def target_date(phrase: str, today: _dt.date, lang: str) -> tuple[_dt.date, str] | None:
    """« noel », « le 14 juillet 2027 », « demain » -> (date, nom a dire)."""
    phrase = re.sub(r"^(?:la |le |l'|the )(?=[a-z])", "", phrase.strip(" ?"))
    fr = lang == "fr"
    relative = {"aujourd'hui": 0, "today": 0, "demain": 1, "tomorrow": 1,
                "apres-demain": 2, "apres demain": 2, "hier": -1, "yesterday": -1}
    if phrase in relative:
        day = today + _dt.timedelta(days=relative[phrase])
        return day, _say_date(day, lang, with_year=False)
    if phrase in HOLIDAYS:
        month, dom, name_fr, name_en = HOLIDAYS[phrase]
        day = _dt.date(today.year, month, dom)
        if day < today:
            day = day.replace(year=today.year + 1)
        return day, name_fr if fr else name_en
    match = _DAY_MONTH.match(phrase) or _DAY_MONTH.match("le " + phrase)
    if not match:
        return None
    if match.group(1):
        raw_day, month_name, year = match.group(1), match.group(2), match.group(3)
    else:
        month_name, raw_day, year = match.group(4), match.group(5), match.group(6)
    dom = 1 if raw_day in ("1er", "premier") else int(raw_day)
    try:
        day = _dt.date(int(year) if year else today.year, _MONTHS_PLAIN[month_name], dom)
    except ValueError:
        return None
    if not year and day < today:
        day = day.replace(year=today.year + 1)
    return day, _say_date(day, lang, with_year=bool(year) or day.year != today.year,
                          weekday=False)


def _say_date(day: _dt.date, lang: str, with_year: bool = True, weekday: bool = True) -> str:
    name, month = DAYS[lang][day.weekday()], MONTHS[lang][day.month - 1]
    if lang == "fr":
        text = f"le {name + ' ' if weekday else ''}{'1er' if day.day == 1 else day.day} {month}"
        return text + (f" {day.year}" if with_year else "")
    text = f"{name + ', ' if weekday else ''}{month} {day.day}"
    return text + (f", {day.year}" if with_year else "")


_RELATIVE_NAMES = {"demain": ("Demain", "Tomorrow"), "tomorrow": ("Demain", "Tomorrow"),
                   "apres-demain": ("Après-demain", "The day after tomorrow"),
                   "apres demain": ("Après-demain", "The day after tomorrow"),
                   "hier": ("Hier", "Yesterday"), "yesterday": ("Hier", "Yesterday")}
COUNTDOWN = re.compile(r"^(?:(?:c'est |il reste )?dans combien de jours|combien de jours "
                       r"(?:avant|jusqu'a|jusqu'au|reste-t-il avant|il reste avant|me separent de|"
                       r"nous separent de)|il reste combien de jours (?:avant|jusqu'a)|"
                       r"how many days (?:until|till|before|to)|how long until)"
                       r"(?: (?:est|c'est|sera|tombe|arrive|is))? (.+?)(?: (?:est|c'est|sera|arrive))?$")
COUNTDOWN_AFTER = re.compile(r"^(.+?) (?:c'est|est|sera|arrive) dans combien de jours$")
WEEKDAY = re.compile(r"^quel jour (?:de la semaine )?(?:sera|est|tombe|tombera|etait|c'est|ce sera|"
                     r"c'etait|tombe-t-il|tombait) (.+)$|^what day (?:of the week )?"
                     r"(?:is|was|will be|falls on|does) (.+?)(?: fall on)?$")
WEEKDAY_AFTER = re.compile(r"^(.+?) (?:tombe|sera|est|etait|c'est|ce sera|tombera|c'etait)(?: un)? "
                           r"quel jour(?: de la semaine)?$")
DATE_IN = re.compile(r"^(?:(?:quel jour|quelle date|on sera quel jour|on sera le combien)"
                     r"(?: serons-nous| on sera| sera-t-on| sera-t-il| ce sera| sera| nous serons)?|"
                     r"what (?:day|date) (?:will it be|is it)) (?:dans|in) " + _NUM +
                     r" (jours?|semaines?|mois|ans|annees?|days?|weeks?|months?|years?)$|"
                     r"^(?:dans|in) " + _NUM + r" (jours?|semaines?|mois|ans|annees?|days?|weeks?|"
                     r"months?|years?),? (?:on sera|nous serons|ce sera|it will be) "
                     r"(?:quel jour|le combien|what day|what date)$")
WEEK = re.compile(r"^(?:quelle semaine (?:sommes-nous|on est|est-on|est-ce)|on est (?:en|dans) "
                  r"quelle semaine|(?:quel est le |c'est quoi le )?numero de (?:la )?semaine|"
                  r"what week (?:is it|number is it)|which week is it)$")


def _add_months(day: _dt.date, months: int) -> _dt.date:
    month = day.month - 1 + months
    year, month = day.year + month // 12, month % 12 + 1
    for dom in range(day.day, 27, -1):
        try:
            return day.replace(year=year, month=month, day=dom)
        except ValueError:
            continue
    return day.replace(year=year, month=month, day=28)


def dates_answer(plain: str, lang: str, now: _dt.datetime) -> str | None:
    fr, today = lang == "fr", now.date()
    if WEEK.match(plain):
        week = today.isocalendar()[1]
        return f"Nous sommes en semaine {week}." if fr else f"It is week {week}."
    match = DATE_IN.match(plain)
    if match:
        raw = match.group(1) or match.group(3)
        unit = match.group(2) or match.group(4)
        count = _number(raw)
        if count is None or count != int(count) or not 0 < count <= 36500:
            return None
        count = int(count)
        if unit.startswith(("jour", "day")):
            day = today + _dt.timedelta(days=count)
        elif unit.startswith(("semaine", "week")):
            day = today + _dt.timedelta(weeks=count)
        elif unit.startswith(("mois", "month")):
            day = _add_months(today, count)
        else:
            day = _add_months(today, 12 * count)
        spoken = _say_date(day, lang, with_year=day.year != today.year)
        return (f"Dans {count} {unit}, nous serons {spoken}." if fr
                else f"In {count} {unit}, it will be {spoken}.")
    match = WEEKDAY.match(plain) or WEEKDAY_AFTER.match(plain)
    if match:
        phrase = (match.group(1) or match.group(match.lastindex)).strip()
        found = target_date(phrase, today, lang)
        if found is None:
            return None
        day, name = found
        weekday = DAYS[lang][day.weekday()]
        if phrase in _RELATIVE_NAMES and day != today:      # « quel jour c'est demain ? »
            label = _RELATIVE_NAMES[phrase][0 if fr else 1]
            spoken = _say_date(day, lang, with_year=day.year != today.year)
            if fr:
                return f"{label}, {'nous serons' if day > today else 'nous étions'} {spoken}."
            return f"{label} {'will be' if day > today else 'was'} {spoken}."
        if day == today:
            return f"Aujourd'hui, c'est {weekday}." if fr else f"Today is {weekday}."
        if fr:
            verb = "sera" if day > today else "était"
            return f"{name[0].upper() + name[1:]} {verb} un {weekday}."
        return f"{name} {'will be' if day > today else 'was'} a {weekday}."
    match = COUNTDOWN.match(plain) or COUNTDOWN_AFTER.match(plain)
    if match:
        found = target_date(match.group(1), today, lang)
        if found is None:
            return None
        day, name = found
        days = (day - today).days
        spoken = _say_date(day, lang, with_year=day.year != today.year)
        if days == 0:
            return "C'est aujourd'hui !" if fr else "It's today!"
        if days == 1:
            return f"C'est demain, {spoken}." if fr else f"It's tomorrow, {spoken}."
        if days < 0:
            return (f"C'était il y a {-days} jours." if fr else f"That was {-days} days ago.")
        if name.startswith("le ") and fr:
            return f"Il reste {days} jours avant {name}, un {DAYS[lang][day.weekday()]}."
        return (f"Il reste {days} jours avant {name}, {spoken}." if fr
                else f"{days} days until {name}, {spoken}.")
    return None


# --------------------------------------------------------------------------- #
# 6. Hasard
# --------------------------------------------------------------------------- #
DICE = re.compile(r"^(?:lance|jette|roule|tire|roll|throw)(?:-moi| moi)? (un|une|deux|trois|quatre|"
                  r"cinq|\d|a|two|three|four|five) (?:de|des|dice|die)(?: a (\d{1,3}) faces|"
                  r" with (\d{1,3}) sides)?$")
COIN = re.compile(r"^(?:(?:fais|tire|lance|joue|on fait|on joue)(?:-moi| moi)? (?:a )?)?pile ou face$|"
                  r"^(?:flip|toss) a coin$|^heads or tails$")
RANDOM_NUMBER = re.compile(r"^(?:choisis|choisi|donne(?:-moi)?|tire|pick|give me|dis(?:-moi)?)(?: moi)? "
                           r"(?:un nombre|un chiffre|a number|a random number)(?: au hasard| aleatoire)? "
                           r"(?:entre|between) (-?\d+) (?:et|and) (-?\d+)$")
CHOOSE = re.compile(r"^(?:choisis|choisi|tranche|decide|pick|choose)(?: pour moi)?"
                    r"(?: entre| between|\s*:)? (?P<options>.+ (?:ou|et|or|and) .+)$")


def chance_answer(plain: str, orig: str, lang: str, rng=None) -> str | None:
    rng = rng or random
    fr = lang == "fr"
    if COIN.match(plain):
        side = rng.choice((("Pile !", "Heads!"), ("Face !", "Tails!")))
        return side[0] if fr else side[1]
    match = DICE.match(plain)
    if match:
        count = int(_number(match.group(1)) or 1)
        faces = int(match.group(2) or match.group(3) or 6)
        if not (1 <= count <= 5 and 2 <= faces <= 100):
            return None
        rolls = [rng.randint(1, faces) for _ in range(count)]
        if count == 1:
            return f"Le dé tombe sur {rolls[0]}." if fr else f"The die shows {rolls[0]}."
        shown = _join([str(r) for r in rolls], lang)
        return (f"Les dés donnent {shown} : total {sum(rolls)}." if fr
                else f"The dice show {shown}: total {sum(rolls)}.")
    match = RANDOM_NUMBER.match(plain)
    if match:
        low, high = sorted((int(match.group(1)), int(match.group(2))))
        return f"Je dis {rng.randint(low, high)}." if fr else f"I say {rng.randint(low, high)}."
    match = CHOOSE.match(plain)
    if match:
        span = orig[match.start("options"):match.end("options")]
        options = [o.strip(" .") for o in re.split(r",\s*|\s+(?:ou|et|or|and)\s+", span) if o.strip(" .")]
        if not 2 <= len(options) <= 8 or any(len(o.split()) > 6 for o in options):
            return None
        pick = rng.choice(options)
        return f"Je choisis : {pick}." if fr else f"I pick: {pick}."
    return None


# --------------------------------------------------------------------------- #
# 7. Lever et coucher du soleil
# --------------------------------------------------------------------------- #
SUN = re.compile(r"^(?:a quelle heure|quand|what time|when)(?: est-ce que)? (?:se (?P<v1>leve|couche) "
                 r"le soleil|le soleil se (?P<v2>leve|couche)|(?:est|a lieu|sera) le (?P<v3>lever|coucher) "
                 r"du soleil|does the sun (?P<v4>rise|set)|is (?P<v5>sunrise|sunset))"
                 r"(?: (?:a|au|en|in|at) (?P<city>[a-z' -]{2,30}?))?(?: (?P<when>aujourd'hui|demain|"
                 r"ce soir|ce matin|today|tomorrow|tonight))?$|"
                 r"^(?:l'heure du |heure du )?(?P<v6>lever|coucher) du soleil(?: (?:a|au|en) "
                 r"(?P<city2>[a-z' -]{2,30}?))?(?: (?P<when2>aujourd'hui|demain))?$")


def fetch_sun(city: str, lang: str, day_offset: int = 0, timeout: float = 5.0) -> dict | None:
    """{'city', 'sunrise', 'sunset'} (heures locales de la ville) via Open-Meteo."""
    from .tools import _http_get_json

    geo = _http_get_json("https://geocoding-api.open-meteo.com/v1/search",
                         {"name": city, "count": 1, "language": lang, "format": "json"}, timeout)
    places = geo.get("results") or []
    if not places:
        return None
    place = places[0]
    data = _http_get_json("https://api.open-meteo.com/v1/forecast",
                          {"latitude": place["latitude"], "longitude": place["longitude"],
                           "daily": "sunrise,sunset", "timezone": "auto", "forecast_days": 2},
                          timeout)
    daily = data.get("daily") or {}
    return {"city": place.get("name", city),
            "sunrise": _dt.datetime.fromisoformat(daily["sunrise"][day_offset]),
            "sunset": _dt.datetime.fromisoformat(daily["sunset"][day_offset])}


def sun_answer(plain: str, orig: str, lang: str, home_city: str | None, sun_fn=None) -> str | None:
    match = SUN.match(plain)
    if not match:
        return None
    verb = next(match.group(g) for g in ("v1", "v2", "v3", "v4", "v5", "v6") if match.group(g))
    rising = verb in ("leve", "lever", "rise", "sunrise")
    group = "city" if match.group("city") else "city2" if match.group("city2") else None
    city = orig[match.start(group):match.end(group)].strip() if group else home_city
    if not city:
        return None
    tomorrow = (match.group("when") or match.group("when2") or "") in ("demain", "tomorrow")
    try:
        info = (sun_fn or fetch_sun)(city, lang, 1 if tomorrow else 0)
    except Exception:
        return None
    if not info:
        return None
    moment = info["sunrise" if rising else "sunset"]
    fr = lang == "fr"
    if fr:
        action = ("se lèvera" if rising else "se couchera") if tomorrow else \
            ("se lève" if rising else "se couche")
        return (f"À {info['city']}, le soleil {action} à {say_time(moment, lang)}"
                f"{' demain' if tomorrow else ''}.")
    action = "rises" if rising else "sets"
    return (f"In {info['city']}, the sun {action} at {say_time(moment, lang)}"
            f"{' tomorrow' if tomorrow else ''}.")


# --------------------------------------------------------------------------- #
# 8. Batterie
# --------------------------------------------------------------------------- #
BATTERY = re.compile(r"^(?:(?:quel est |c'est quoi |donne-moi )?(?:le |mon )?niveau (?:de |d')?(?:la )?batterie|"
                     r"(?:combien|il me reste combien|combien il me reste|combien reste-t-il|"
                     r"il reste combien) (?:de |d')?(?:batterie|autonomie)(?: il me reste| reste-t-il| il reste)?|"
                     r"(?:ma|la) batterie|etat de (?:la |ma )?batterie|(?:est-ce que )?(?:je suis|le pc est|"
                     r"l'ordinateur est|on est) en charge|battery(?: level| status)?|how much battery"
                     r"(?: do i have| is left)?|what's my battery(?: level)?|am i charging)$")


def read_battery() -> tuple[int, bool, int | None] | None:
    """(pourcentage, sur secteur, secondes restantes) ; None sans batterie."""
    import ctypes

    class _Status(ctypes.Structure):
        _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                    ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                    ("BatteryLifeTime", ctypes.c_ulong), ("BatteryFullLifeTime", ctypes.c_ulong)]

    status = _Status()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
        return None
    if status.BatteryFlag & 128 or status.BatteryLifePercent == 255:
        return None
    seconds = status.BatteryLifeTime
    return (int(status.BatteryLifePercent), status.ACLineStatus == 1,
            None if seconds in (0xFFFFFFFF, -1) else int(seconds))


def battery_answer(plain: str, lang: str, battery_fn=None) -> str | None:
    if not BATTERY.match(plain):
        return None
    fr = lang == "fr"
    try:
        info = (battery_fn or read_battery)()
    except Exception:
        return None
    if info is None:
        return ("Cet ordinateur n'a pas de batterie : il est sur secteur." if fr
                else "This computer has no battery: it runs on mains power.")
    percent, plugged, seconds = info
    if plugged:
        return (f"Batterie à {percent} %, en charge." if fr
                else f"Battery at {percent} percent, charging.")
    text = f"Batterie à {percent} %" if fr else f"Battery at {percent} percent"
    if seconds:
        from .intents import say_duration

        left = say_duration(max(60, round(seconds / 60) * 60), lang)
        text += f", environ {left} d'autonomie" if fr else f", about {left} left"
    if percent <= 20:
        text += ". Pensez à brancher le chargeur" if fr else ". Plug in the charger soon"
    return text + "."


# --------------------------------------------------------------------------- #
# 9. Que sais-tu de moi ?
# --------------------------------------------------------------------------- #
ABOUT_ME = re.compile(r"^(?:qu'est-ce que tu sais (?:sur|de) moi|que sais-tu (?:sur|de) moi|"
                      r"tu sais quoi (?:sur|de) moi|qu'est-ce que tu connais de moi|"
                      r"tu te souviens de quoi(?: sur moi| me concernant)?|qu'as-tu retenu(?: sur moi| de moi)?|"
                      r"qu'est-ce que tu as retenu(?: sur moi| de moi)?|tu me connais|"
                      r"what do you (?:know|remember) about me)$")
ABOUT_ME_SHOWN = 5


def about_me_answer(plain: str, lang: str, memory) -> str | None:
    if memory is None or not ABOUT_ME.match(plain):
        return None
    fr = lang == "fr"
    from .briefing import profile_facts

    profile = profile_facts(memory)
    try:
        facts = [m.text.strip().rstrip(".") for m in memory.all(kind="fact", limit=200)]
    except Exception:
        facts = []
    parts = []
    if profile.get("name"):
        parts.append(f"vous vous appelez {profile['name']}" if fr else f"your name is {profile['name']}")
    if profile.get("location"):
        parts.append(f"vous habitez à {profile['location']}" if fr else f"you live in {profile['location']}")
    if not parts and not facts:
        return ("Je ne sais encore rien de vous. Dites par exemple : « retiens que j'aime le jazz »."
                if fr else "I don't know anything about you yet. Say for example: "
                "'remember that I like jazz'.")
    sentences = []
    if parts:
        sentences.append(("Je sais que " + " et que ".join(parts) + ".") if fr
                         else ("I know that " + " and ".join(parts) + "."))
    if facts:
        shown = " ; ".join(facts[:ABOUT_ME_SHOWN])
        count = len(facts)
        if fr:
            head = "J'ai aussi retenu" if parts else "J'ai retenu"
            sentences.append(f"{head} {count} chose{'s' if count > 1 else ''}"
                             f"{', par exemple' if count > ABOUT_ME_SHOWN else ''} : {shown}.")
        else:
            sentences.append(f"I remember {count} thing{'s' if count > 1 else ''}"
                             f"{', for example' if count > ABOUT_ME_SHOWN else ''}: {shown}.")
    sentences.append("Demandez-moi d'oublier ce que vous voulez." if fr
                     else "Ask me to forget anything you like.")
    return " ".join(sentences)


# --------------------------------------------------------------------------- #
# 10. Pomodoro
# --------------------------------------------------------------------------- #
POMODORO = re.compile(r"^(?:(?:lance|demarre|commence|mets|met|start|begin|on fait)(?:-moi| moi)? )?"
                      r"(?:un |une |a )?(?:session (?:de )?)?(?:pomodoro|concentration|focus)"
                      r"(?: session)?(?: de (\d{1,3}) minutes| of (\d{1,3}) minutes)?$|"
                      r"^mode (?:pomodoro|concentration)$|^focus mode$")
POMODORO_STOP = re.compile(r"^(?:arrete|stoppe|annule|termine|stop|cancel|end)(?: le| la| mon| ma| the| my)? "
                           r"(?:pomodoro|session(?: de concentration)?|concentration|focus(?: session)?)$")
POMODORO_WORK = 25


def pomodoro_answer(plain: str, lang: str, timers) -> str | None:
    if timers is None:
        return None
    fr = lang == "fr"
    if POMODORO_STOP.match(plain):
        timers.cancel(None)
        return "Pomodoro arrêté." if fr else "Pomodoro stopped."
    match = POMODORO.match(plain)
    if not match:
        return None
    work = int(match.group(1) or match.group(2) or POMODORO_WORK)
    if not 5 <= work <= 180:
        return None
    pause = max(5, round(work / 5))
    timers.set_timer(work * 60, f"Pomodoro terminé : place à {pause} minutes de pause." if fr
                     else f"Pomodoro done: take a {pause} minute break.")
    timers.set_timer((work + pause) * 60, "Fin de la pause, on s'y remet ?" if fr
                     else "Break is over, back to work?")
    return (f"Pomodoro lancé : {work} minutes de concentration, puis {pause} minutes de pause. "
            f"Je vous préviens." if fr else
            f"Pomodoro started: {work} minutes of focus, then a {pause} minute break. I'll tell you.")


# --------------------------------------------------------------------------- #
# Point d'entree
# --------------------------------------------------------------------------- #
MAX_WORDS = 30


def answer(text: str, lang: str, now: _dt.datetime, *, memory=None, timers=None, lists=None,
           home_city: str | None = None, rate_fn=None, sun_fn=None, battery_fn=None,
           rng=None) -> str | None:
    """Reponse instantanee pour l'une des dix commandes, sinon None."""
    plain, orig = aligned(text)
    if not plain or len(plain.split()) > MAX_WORDS:
        return None
    if lists is not None:
        found = lists_answer(plain, orig, lang, lists)
        if found:
            return found
    if len(plain.split()) > 14:
        return None
    for attempt in (lambda: convert(plain, lang, rate_fn),
                    lambda: calculate(plain, lang),
                    lambda: dates_answer(plain, lang, now),
                    lambda: chance_answer(plain, orig, lang, rng),
                    lambda: sun_answer(plain, orig, lang, home_city, sun_fn),
                    lambda: battery_answer(plain, lang, battery_fn),
                    lambda: about_me_answer(plain, lang, memory),
                    lambda: pomodoro_answer(plain, lang, timers)):
        found = attempt()
        if found:
            return found
    return None


__all__ = ["answer", "ListStore", "aligned", "say_number", "fetch_rate", "fetch_sun",
           "read_battery"]
