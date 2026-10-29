"""Petits utilitaires de texte partages (et testables sans dependance lourde)."""

from __future__ import annotations

import array
import contextlib
import difflib
import math
import re
import sys
import unicodedata
import uuid

from langchain_core.messages import HumanMessage, SystemMessage

from .i18n import STRINGS

# Tokens pouvant preceder le wake word ("hey jarvis", "ok jarvis" ...).
WAKE_FILLERS = {"hey", "hi", "ok", "okay", "oi", "eh", "he", "hallo", "salut", "coucou"}
SENTENCE_RE = re.compile(r"(?<=[.!?…])\s+")
WORD_RE = re.compile(r"[\w'’]+", re.UNICODE)

# Caracteres que la synthese vocale ne doit pas prononcer (emoji, fleches...).
EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF"
    "\U00002190-\U000021FF"
    "\U00002300-\U000027BF"
    "\U00002B00-\U00002BFF"
    "\U0000FE0F"
    "\U0000200D"
    "]+"
)


def log(message: str) -> None:
    """print() qui ne fait jamais planter l'assistant (console cp1252)."""
    try:
        print(message, flush=True)
    except Exception:
        with contextlib.suppress(Exception):
            print(message.encode("ascii", "replace").decode("ascii"), flush=True)


def clean_text(text: str) -> str:
    """Retire le markdown de base, les emoji, et normalise les espaces."""
    text = text.replace("**", "").replace("__", "").replace("`", "")
    text = EMOJI_RE.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def take_sentences(buffer: str) -> tuple[list[str], str]:
    """Decoupe le flux en phrases completes, en gardant le reste dans buffer."""
    out: list[str] = []
    start = 0
    for match in SENTENCE_RE.finditer(buffer):
        piece = buffer[start:match.start()].strip()
        if piece:
            out.append(piece)
        start = match.end()
    return out, buffer[start:]


def rms(data: bytes) -> float:
    """Efficace carre du signal 16 bits (pas de module audioop, supprime en 3.13)."""
    try:
        samples = array.array("h", data)
    except (ValueError, TypeError):
        return 0.0
    if sys.byteorder == "big":
        samples.byteswap()
    if not samples:
        return 0.0
    total = 0
    for value in samples:
        total += value * value
    return math.sqrt(total / len(samples))


def strip_wake(text: str, wake_words: list[str]) -> tuple[bool, str]:
    """Cherche le wake word en debut d'execution ("jarvis", "hey jarvis"...).

    Retourne (trouve, commande) ; (False, "") si l'input doit etre ignoree.
    """
    if not wake_words:
        return True, text
    tokens = list(WORD_RE.finditer(text))
    if not tokens:
        return False, ""
    positions = [0]
    if len(tokens) >= 2 and tokens[0].group(0).lower() in WAKE_FILLERS:
        positions.append(1)  # "hey jarvis", "ok jarvis"...

    for index in positions:
        word = tokens[index].group(0).lower()
        if word in wake_words:
            return True, _after_token(text, tokens[index])
        # tolere les fautes de reconnaissance ("jarves", "jervis"...)
        if len(word) >= 4:
            close = difflib.get_close_matches(word, wake_words, n=1, cutoff=0.75)
            if close:
                return True, _after_token(text, tokens[index])
    return False, ""


def _after_token(text: str, token: "re.Match[str]") -> str:
    return text[token.end():].lstrip(" \t,;:.!?—-")


def is_exit_phrase(text: str, phrases: list[str]) -> bool:
    low = text.lower().strip(" .!?")
    if low in phrases:
        return True
    return bool(difflib.get_close_matches(low, phrases, n=1, cutoff=0.7))


def status_code(exc: Exception) -> int | None:
    for attr in ("status_code", "code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    return value if isinstance(value, int) else None


# marqueurs d'erreurs qui ne se resoudront jamais tout seuls : inutile de relancer
_FATAL_MARKERS = (
    "insufficient_quota",
    "credit_balance_exhausted",
    "invalid_api_key",
    "incorrect api key",
    "model_not_found",
    "unsupported_temperature",
    "does not exist",
    "no auth credentials",
)


_QUOTA_RESET = re.compile(r"X-RateLimit-Reset['\"]?\s*:\s*['\"]?(\d{10,13})")


def is_daily_quota(exc) -> bool:
    """Quota gratuit du jour epuise (OpenRouter : 50 requetes/jour sans credits)."""
    text = str(exc or "").lower()
    return "free-models-per-day" in text or ("rate limit" in text and "per day" in text)


def quota_reset(exc) -> float | None:
    """Heure (epoch, secondes) du renouvellement du quota, si l'erreur la donne."""
    match = _QUOTA_RESET.search(str(exc or ""))
    if not match:
        return None
    value = int(match.group(1))
    return value / 1000.0 if value > 10 ** 11 else float(value)


def is_fatal(exc: Exception) -> bool:
    if status_code(exc) in (400, 401, 403, 404, 422):
        return True
    if is_daily_quota(exc):
        return True     # inutile de reessayer avant le renouvellement
    text = str(exc).lower()
    return any(marker in text for marker in _FATAL_MARKERS)


def make_messages(system_prompt: str, first_turn: bool, text: str,
                  refresh_system: bool = False) -> list:
    """Construit les messages du tour, avec des IDs stables pour le retry.

    `refresh_system=True` reinjecte le prompt systeme a chaque tour ; comme il
    garde le meme id, LangGraph le remplace au lieu d'en ajouter un second.
    """
    messages = []
    if first_turn or refresh_system:
        messages.append(SystemMessage(content=system_prompt, id="system-prompt"))
    messages.append(HumanMessage(content=text, id=str(uuid.uuid4())))
    return messages


# --------------------------------------------------------------------------- #
# Normalisation utilisee par la memoire (insensible aux accents et a la casse)
# --------------------------------------------------------------------------- #
def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize(text: str) -> str:
    return strip_accents(text or "").lower()


def tokenize(text: str) -> list[str]:
    """Tokens utiles (sans accents, sans mots vides)."""
    tokens = WORD_RE.findall(normalize(text))
    return [t for t in tokens if len(t) > 2 and t not in _STOPWORDS]


_STOPWORDS = {
    # fr
    "les", "des", "une", "que", "qui", "pour", "avec", "dans", "est", "sont",
    "pas", "sur", "mais", "comme", "tout", "plus", "ses", "son", "leur", "aux",
    "cette", "cest", "fait", "faire", "peux", "peut", "veux", "veut", "the",
    # en
    "the", "and", "for", "you", "your", "that", "this", "with", "have", "has",
    "are", "was", "were", "from", "not", "but", "all", "can", "will", "would",
    "there", "their", "them", "they", "what", "when", "how", "why", "who",
}


def jaccard(a: list[str] | set[str], b: list[str] | set[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def similar(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, normalize(a), normalize(b)).ratio()


def language_strings(lang: str) -> dict:
    return STRINGS.get(lang, STRINGS["en"])


__all__ = [
    "STRINGS",
    "WAKE_FILLERS",
    "SENTENCE_RE",
    "EMOJI_RE",
    "log",
    "clean_text",
    "take_sentences",
    "rms",
    "strip_wake",
    "is_exit_phrase",
    "status_code",
    "is_fatal",
    "make_messages",
    "normalize",
    "strip_accents",
    "tokenize",
    "jaccard",
    "similar",
    "language_strings",
]
