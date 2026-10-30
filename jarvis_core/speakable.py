"""Texte pret a etre dit : ce qu'un humain prononcerait, pas ce qui est ecrit.

Le modele ecrit « 26.7 °C, vent 4.0 km/h », « x = 6 », « M. Dupont », « 16:17 »,
« 30/10/2026 », « 2e », « ~10 % »... Lus tels quels, ces symboles rendent la voix
robotique (« vingt-six point sept », « x egal six » mal coupe, sigles epeles).
Ce module les remplace par la forme parlee, avant la synthese vocale :

  « 26.7 °C, vent 4.0 km/h » -> « 26,7 degrés, vent 4 kilomètres heure »
  « 16:17 »                  -> « 16 h 17 »
  « 30/10/2026 »             -> « 30 octobre 2026 »
  « M. Dupont, 2e étage »    -> « Monsieur Dupont, deuxième étage »

Les nombres eux-memes restent en chiffres : la voix sait les lire.
"""

from __future__ import annotations

import re

MONTHS_FR = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
             "septembre", "octobre", "novembre", "décembre")
MONTHS_EN = ("January", "February", "March", "April", "May", "June", "July", "August",
             "September", "October", "November", "December")
ORDINALS_FR = {"1er": "premier", "1re": "première", "1ère": "première", "2e": "deuxième",
               "3e": "troisième", "4e": "quatrième", "5e": "cinquième", "6e": "sixième",
               "7e": "septième", "8e": "huitième", "9e": "neuvième", "10e": "dixième",
               "2nd": "second", "2nde": "seconde"}

# (motif, remplacement francais, remplacement anglais)
UNITS = (
    (r"°\s?C\b", " degrés", " degrees"),
    (r"°\s?F\b", " degrés Fahrenheit", " degrees Fahrenheit"),
    (r"°", " degrés", " degrees"),
    (r"\bkm/h\b", " kilomètres heure", " kilometres per hour"),
    (r"\bm/s\b", " mètres par seconde", " metres per second"),
    (r"\bkWh\b", " kilowattheures", " kilowatt hours"),
    (r"\bkm²", " kilomètres carrés", " square kilometres"),
    (r"\bm²", " mètres carrés", " square metres"),
    (r"\bkm\b", " kilomètres", " kilometres"),
    (r"\bkg\b", " kilos", " kilos"),
    (r"\bmm\b", " millimètres", " millimetres"),
    (r"\bcm\b", " centimètres", " centimetres"),
    (r"\bml\b", " millilitres", " millilitres"),
    (r"\bmin\b", " minutes", " minutes"),
    (r"\bGo\b", " gigaoctets", " gigabytes"),
    (r"\bMo\b", " mégaoctets", " megabytes"),
    (r"\bGB\b", " gigaoctets", " gigabytes"),
    (r"\bMB\b", " mégaoctets", " megabytes"),
    (r"\s?%", " pour cent", " percent"),
    (r"\s?€", " euros", " euros"),
    (r"\s?\$", " dollars", " dollars"),
    (r"\bFCFA\b|\bXOF\b", " francs CFA", " CFA francs"),
)
ABBREVIATIONS_FR = (
    (r"\bM\.\s", "Monsieur "), (r"\bMme\b\.?", "Madame"), (r"\bMlle\b\.?", "Mademoiselle"),
    (r"\bDr\b\.?", "Docteur"), (r"\bPr\b\.?", "Professeur"), (r"\betc\.", "et cetera"),
    (r"\bp\.\s?ex\.", "par exemple"), (r"\benv\.", "environ"), (r"\bn°\s?", "numéro "),
    (r"\bN°\s?", "numéro "), (r"\bvs\.?\b", "contre"), (r"\bcf\.", "voir"),
    (r"\bi\.e\.", "c'est-à-dire"), (r"\be\.g\.", "par exemple"),
    (r"\bJ\.A\.R\.V\.I\.S\.?", "Jarvis"), (r"\bIA\b", "I A"), (r"\bOK\b", "d'accord"),
)
SYMBOLS = (
    (r"\s?≈\s?", " environ ", " about "),
    (r"(?<=\d)\s?[×x]\s?(?=\d)", " fois ", " times "),
    (r"(?<=\d)\s?÷\s?(?=\d)", " divisé par ", " divided by "),
    (r"(?<=[\w)])\s?=\s?(?=[\w(-])", " égale ", " equals "),
    (r"(?<=\d)\s?\+\s?(?=\d)", " plus ", " plus "),
    (r"(?<=\d)\s?[−–]\s?(?=\d)", " moins ", " minus "),
    (r"\s?→\s?", ", donc ", ", so "),
    (r"\s?&\s?", " et ", " and "),
    (r"~\s?(?=\d)", "environ ", "about "),
    (r"(?<=[\d)])\s?/\s?(?=[\d(])", " divisé par ", " divided by "),
)
_URL = re.compile(r"https?://\S+|www\.\S+")
_DECIMAL = re.compile(r"(?<![\d.])(\d+)\.(\d+)(?![\d.])")
_TRAILING_ZERO = re.compile(r"(?<![\d.,])(\d+)[.,]0(?!\d)")
_TIME = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")
_DATE = re.compile(r"\b([0-3]?\d)/([01]?\d)/((?:19|20)\d\d)\b")
_VERSION_WORDS = re.compile(r"(?:version|v|python|windows|ios|android|java|node|chrome)\s*$",
                            re.I)
_MATH_PARENS = re.compile(r"\(([\d\s.,+\-−×*/^=]+)\)")
_THOUSANDS = re.compile(r"(?<=\d)[  ,](?=\d{3}\b)")


def speakable(text: str, lang: str = "fr") -> str:
    """Forme parlee d'un texte ecrit (voir l'en-tete du module)."""
    fr = lang == "fr"
    if not text:
        return ""
    text = text.replace("‑", "-").replace(" ", " ").replace(" ", " ")
    text = re.sub(r"^#+\s*|^\s*[-*•]\s+", "", text, flags=re.M)          # titres, puces
    text = text.replace("**", "").replace("__", "").replace("`", "")
    text = _URL.sub("le lien affiché" if fr else "the link shown", text)

    def date(match):
        day, month, year = int(match.group(1)), int(match.group(2)), match.group(3)
        if not 1 <= month <= 12 or not 1 <= day <= 31:
            return match.group(0)
        if fr:
            return f"{'1er' if day == 1 else day} {MONTHS_FR[month - 1]} {year}"
        return f"{MONTHS_EN[month - 1]} {day}, {year}"

    text = _DATE.sub(date, text)
    text = _TIME.sub(lambda m: (f"{int(m.group(1))} h {m.group(2)}" if m.group(2) != "00"
                                else f"{int(m.group(1))} h") if fr else m.group(0), text)
    text = _TRAILING_ZERO.sub(r"\1", text)                  # « 4.0 km/h » -> « 4 km/h »
    if fr:
        text = _THOUSANDS.sub("", text)                    # « 12 500 » -> « 12500 »
        text = _DECIMAL.sub(lambda m: m.group(0) if _VERSION_WORDS.search(
            text[:m.start()]) else f"{m.group(1)},{m.group(2)}", text)   # « 26.7 » -> « 26,7 »
        for pattern, replacement in ABBREVIATIONS_FR:
            text = re.sub(pattern, replacement, text)
        for written, spoken in ORDINALS_FR.items():
            text = re.sub(rf"\b{re.escape(written)}\b", spoken, text)
    for pattern, french, english in UNITS:
        unit = pattern[2:] if pattern.startswith(r"\b") else pattern
        unit = unit[3:] if unit.startswith(r"\s?") else unit
        text = re.sub(rf"(?<=\d)\s?{unit}", french if fr else english, text)
    text = _MATH_PARENS.sub(r"\1", text)                   # « (25 − 7)/3 » : calcul
    for pattern, french, english in SYMBOLS:
        text = re.sub(pattern, french if fr else english, text)
    text = re.sub(r"\(([^()]{1,80})\)", r", \1,", text)     # parentheses -> incise
    text = re.sub(r"\s*;\s*", ", ", text)                  # point-virgule -> respiration
    text = re.sub(r"\s+([,.!?])", r"\1", text)
    text = re.sub(r",\s*,", ",", text)
    return re.sub(r"\s+", " ", text).strip(" ,")


__all__ = ["speakable"]
