"""Mieux entendre : hypotheses multiples, phrases coupees, intention plutot que lettre.

La reconnaissance vocale se trompe (homophones, noms propres, mots avales)
et coupe parfois la phrase quand on hesite. Ce module :

  * garde **toutes les hypotheses** de Google avec leur confiance, pour que le
    modele choisisse la plus logique (« met la musique » / « mets la musique ») ;
  * repere une **phrase inachevee** (« ouvre le fichier de », « rappelle-moi
    de ») et ecoute la suite quelques secondes avant de repondre ;
  * corrige quelques **erreurs frequentes** (« you tube », « jarvisse ») ;
  * prepare la **consigne** donnee au modele : comprendre l'intention, ne pas
    suivre a la lettre une transcription manifestement fausse, completer une
    phrase coupee de la facon la plus logique.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

CONTINUE_WAIT = 2.5      # secondes d'ecoute pour la fin d'une phrase coupee
CONTINUE_MAX = 2         # relances au plus
LOW_CONFIDENCE = 0.7

# Mots apres lesquels une phrase francaise ne s'arrete (presque) jamais.
_DANGLING = {
    "le", "la", "les", "l'", "un", "une", "des", "du", "de", "d'", "au", "aux", "a", "à",
    "en", "dans", "sur", "sous", "pour", "par", "avec", "sans", "chez", "vers", "entre",
    "et", "ou", "mais", "donc", "car", "ni", "que", "qu'", "qui", "dont", "où", "si",
    "mon", "ma", "mes", "ton", "ta", "tes", "son", "sa", "ses", "notre", "votre", "leur",
    "ce", "cet", "cette", "ces", "quel", "quelle", "quels", "quelles", "est-ce",
    "je", "tu", "il", "elle", "on", "nous", "vous", "ils", "elles", "me", "te", "se",
    "comment", "pourquoi", "combien", "quand", "parce", "puis", "ensuite", "aussi",
    "très", "plus", "moins", "trop", "peux-tu", "peux", "peut", "pourrais", "pourrait",
    "veux", "veut", "voudrais", "faut", "dois", "sais", "aimerais",
    "the", "a", "an", "of", "to", "in", "on", "for", "with", "and", "or", "but", "my",
    "your", "is", "are", "what", "how", "why", "when", "because", "please",
}
# Commandes qui demandent un complement (« ouvre », « cherche » seuls).
_BARE_VERBS = {"ouvre", "lance", "cherche", "recherche", "mets", "joue", "rappelle-moi",
               "écris", "ecris", "envoie", "appelle", "traduis", "explique", "open",
               "search", "play", "remind", "write"}

CORRECTIONS = (
    (re.compile(r"\byou ?tube\b", re.I), "YouTube"),
    (re.compile(r"\bspoti ?fy\b|\bspotifaï\b", re.I), "Spotify"),
    (re.compile(r"\bwhat'?s ?app\b", re.I), "WhatsApp"),
    (re.compile(r"\bnet ?flix\b", re.I), "Netflix"),
    (re.compile(r"\bchat ?g ?p ?t\b|\bchat j'ai pété\b", re.I), "ChatGPT"),
    (re.compile(r"^(?:jarvisse|jarvice|jervis|charvis|jarvi|djarvis)\b[ ,]*", re.I), "Jarvis, "),
)


@dataclass
class Heard:
    """Ce qui a ete entendu : texte retenu, autres hypotheses, confiance."""

    text: str
    alternatives: list[str] = field(default_factory=list)
    confidence: float | None = None
    continued: bool = False          # la phrase a ete completee par une seconde ecoute
    language: str | None = None      # langue detectee par Whisper : « fr » ou « en »

    def __str__(self) -> str:
        return self.text


def spoken_language(heard, default: str = "fr") -> str:
    language = getattr(heard, "language", None)
    return language if language in ("fr", "en") else default


def language_line(heard, default: str = "fr") -> str:
    """Consigne pour le modele quand on lui parle dans l'autre langue."""
    language = spoken_language(heard, default)
    if language == default:
        return ""
    return ("The user just spoke English: answer in English." if language == "en"
            else "L'utilisateur vient de parler français : réponds en français.")


def correct(text: str) -> str:
    text = " ".join((text or "").split())
    for pattern, replacement in CORRECTIONS:
        text = pattern.sub(replacement, text)
    return text.strip()


def seems_unfinished(text: str) -> bool:
    """Vrai si la phrase s'arrete visiblement au milieu (« ouvre le fichier de »)."""
    words = re.findall(r"[\w'-]+", (text or "").lower())
    if not words:
        return False
    last = words[-1]
    if last in _DANGLING or last.endswith("'"):
        return True
    return len(words) == 1 and last in _BARE_VERBS


def from_google(result) -> Heard | None:
    """Reponse de Google (`show_all=True` ou texte simple) -> Heard."""
    if isinstance(result, str):
        return Heard(correct(result)) if result.strip() else None
    alternatives = (result or {}).get("alternative") or [] if isinstance(result, dict) else []
    texts, confidence = [], None
    for alternative in alternatives:
        text = correct(alternative.get("transcript", ""))
        if text and text.lower() not in {t.lower() for t in texts}:
            texts.append(text)
        if confidence is None and "confidence" in alternative:
            confidence = float(alternative["confidence"])
    if not texts:
        return None
    return Heard(texts[0], texts[1:5], confidence)


def join(first: Heard, more: Heard | str | None) -> Heard:
    """Recolle la suite d'une phrase coupee."""
    if not more or not str(more).strip():
        return first
    extra = more if isinstance(more, Heard) else Heard(correct(str(more)))
    text = f"{first.text} {extra.text}".strip()
    alternatives = [f"{alt} {extra.text}" for alt in first.alternatives[:3]]
    confidence = min(c for c in (first.confidence, extra.confidence) if c is not None) \
        if first.confidence is not None or extra.confidence is not None else None
    return Heard(text, alternatives, confidence, continued=True)


VOCABULARY = {
    "fr": ("Jarvis, mets, ouvre, lance, joue, cherche, rappelle-moi, minuteur, météo, "
           "YouTube, Spotify, WhatsApp, Netflix, Google, Wikipédia, ChatGPT, Ouagadougou, "
           "Bobo-Dioulasso, Burkina Faso."),
    "en": "Jarvis, play, open, launch, search, remind me, timer, weather, YouTube, Spotify.",
}


def vocabulary(lang: str = "fr", extra: str = "") -> str:
    """Mots attendus, pour orienter Whisper (applications, lieux, noms du profil)."""
    base = VOCABULARY.get(lang, VOCABULARY["en"])
    return f"{base} {extra}".strip()


_PROPER = re.compile(r"(?<![.!?]\s)(?<!^)\b([A-ZÀ-ÖØ-Þ][\wÀ-ÿ'-]{2,})")
_NOT_NAMES = {"Il", "Elle", "Son", "Sa", "Ses", "Le", "La", "Les", "Un", "Une", "Hier",
              "Aujourd'hui", "Demain", "Jarvis", "He", "She", "His", "Her", "The"}


def personal_vocabulary(memory, limit: int = 30) -> str:
    """Noms propres des souvenirs (proches, villes, ecoles...) pour orienter Whisper."""
    if memory is None:
        return ""
    names: list[str] = []
    try:
        texts = [m.text for m in memory.all(limit=200)]
    except Exception:
        return ""
    for text in texts:
        for name in _PROPER.findall(text):
            if name not in _NOT_NAMES and name not in names:
                names.append(name)
    return ", ".join(names[:limit])


GUIDANCE = {
    "fr": ("Ce message vient de la reconnaissance vocale : des mots peuvent être mal "
           "entendus (homophones, noms propres déformés, mots avalés) et la phrase peut "
           "s'arrêter au milieu. Ne le suis pas à la lettre : comprends l'intention la plus "
           "logique dans le contexte de la conversation. Si une phrase est inachevée, "
           "complète-la de la façon la plus probable et réponds ; ne demande une précision "
           "que si deux sens vraiment différents sont possibles, en une courte question. "
           "Ne commente jamais les erreurs de transcription."),
    "en": ("This message comes from speech recognition: words may be misheard (homophones, "
           "distorted names, swallowed words) and the sentence may stop midway. Do not "
           "follow it literally: understand the most logical intent in the conversation's "
           "context. If a sentence is unfinished, complete it in the most likely way and "
           "answer; only ask for clarification if two really different meanings are "
           "possible, in one short question. Never comment on transcription errors."),
}


def guidance(heard: Heard | None, lang: str = "fr") -> str:
    """Consigne pour le modele quand le message a ete dicte."""
    if heard is None:
        return ""
    fr = lang == "fr"
    parts = [GUIDANCE["fr" if fr else "en"]]
    if heard.alternatives:
        quoted = ", ".join(f"« {alt} »" if fr else f'"{alt}"' for alt in heard.alternatives[:4])
        parts.append(("Autres transcriptions possibles : " if fr
                      else "Other possible transcriptions: ") + quoted + ".")
    if heard.confidence is not None and heard.confidence < LOW_CONFIDENCE:
        parts.append("La reconnaissance était peu sûre." if fr
                     else "Recognition confidence was low.")
    if seems_unfinished(heard.text):
        parts.append("La phrase semble coupée avant la fin." if fr
                     else "The sentence seems cut before the end.")
    return " ".join(parts)


__all__ = ["Heard", "correct", "seems_unfinished", "from_google", "join", "guidance",
           "CONTINUE_WAIT", "CONTINUE_MAX"]
