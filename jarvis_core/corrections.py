"""Corrections retenues : Jarvis n'entend pas deux fois le meme mot de travers.

  « Appelle Wedrogo » -> « non, je voulais dire Ouedraogo »
  -> la demande est rejouee corrigee, et « Wedrogo » deviendra « Ouedraogo ».
  « Quand je dis Polo, je veux dire Paul » -> retenu tel quel.

Un mot n'est retenu d'office que s'il ressemble a l'ancien : « non, je voulais
dire Paris » apres « Lyon » est un changement d'avis, pas une erreur d'ecoute.
La demande est alors rejouee, sans rien retenir.
"""

from __future__ import annotations

import difflib
import json
import re
import threading
from pathlib import Path

from .extras import _plain_char, aligned

DEFAULT_FILE = Path(__file__).resolve().parent.parent / ".jarvis_corrections.json"
MIN_SIMILARITY = 0.55
MAX_WORDS = 4

REQUEST = re.compile(r"^(?:non|non non|mais non|pardon|tu as mal compris|t'as mal compris|"
                     r"ce n'est pas ca|c'est pas ca|no|sorry)?[, ]*"
                     r"(?:je voulais dire|je veux dire|j'ai dit|j'ai voulu dire|je disais|"
                     r"i meant|i mean|i said)\s*:?\s+(?P<new>.+)$")
RULE = re.compile(r"^(?:retiens que |remember that )?(?:quand je dis|si je dis|when i say) "
                  r"(?P<old>.{2,40}?),? (?:je veux dire|je parle de|c'est|ca veut dire|i mean) (?P<new>.{2,40})$")
FORGET = re.compile(r"^(?:oublie|efface|supprime|forget|clear) (?:toutes )?(?:tes|les|your|the) corrections$")


def _key(text: str) -> str:
    return "".join(_plain_char(c) for c in text.lower()).strip(" .,!?;:")


def similar(old: str, new: str) -> bool:
    return difflib.SequenceMatcher(None, _key(old), _key(new)).ratio() >= MIN_SIMILARITY


def _words(text: str) -> list[str]:
    return (text or "").strip(" .!?;,").split()


def apply_fragment(previous: str, fragment: str) -> tuple[str, str | None]:
    """« appelle Wedrogo demain » + « Ouedraogo » -> (phrase corrigee, mot remplace)."""
    words, parts = _words(previous), _words(fragment)
    size = len(parts)
    best, best_score = None, 0.0
    for start in range(0, len(words) - size + 1):
        span = " ".join(words[start:start + size])
        score = difflib.SequenceMatcher(None, _key(span), _key(fragment)).ratio()
        if score > best_score:
            best, best_score = start, score
    if best is None or best_score < MIN_SIMILARITY:
        return fragment, None
    old = " ".join(words[best:best + size])
    return " ".join(words[:best] + parts + words[best + size:]), old


def replaced(previous: str, corrected: str) -> tuple[str, str] | None:
    """Le seul passage qui change entre deux phrases, s'il est unique et court."""
    old, new = _words(previous), _words(corrected)
    blocks = [b for b in difflib.SequenceMatcher(None, [_key(w) for w in old],
                                                 [_key(w) for w in new]).get_opcodes()
              if b[0] != "equal"]
    if len(blocks) != 1 or blocks[0][0] != "replace":
        return None
    _tag, i1, i2, j1, j2 = blocks[0]
    if i2 - i1 > MAX_WORDS or j2 - j1 > MAX_WORDS:
        return None
    return " ".join(old[i1:i2]), " ".join(new[j1:j2])


class Corrections:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else None
        self._lock = threading.Lock()
        self.rules: dict[str, str] = {}
        if self.path is not None and self.path.is_file():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self.rules = {str(k): str(v) for k, v in data.items()}
            except Exception:
                self.rules = {}

    def _save(self) -> None:
        if self.path is not None:
            self.path.write_text(json.dumps(self.rules, ensure_ascii=False, indent=1), encoding="utf-8")

    def learn(self, old: str, new: str) -> None:
        with self._lock:
            self.rules[_key(old)] = new.strip(" .,!?;:")
            self._save()

    def forget_all(self) -> int:
        with self._lock:
            count = len(self.rules)
            self.rules = {}
            self._save()
        return count

    def apply(self, text: str) -> str:
        """Remplace les mots appris (sans tenir compte des accents ni de la casse)."""
        if not self.rules or not text:
            return text
        plain = "".join(_plain_char(c) for c in text.lower())
        spans = []
        for old, new in self.rules.items():
            for match in re.finditer(r"(?<!\w)" + re.escape(old) + r"(?!\w)", plain):
                spans.append((match.start(), match.end(), new))
        for start, end, new in sorted(spans, reverse=True):
            text = text[:start] + new + text[end:]
        return text

    def handle(self, text: str, previous: str | None) -> dict | None:
        """{'answer': texte a dire} ou {'replay': demande corrigee} ; None sinon."""
        plain, orig = aligned(text)
        if FORGET.match(plain):
            count = self.forget_all()
            return {"answer": f"C'est oublié : {count} corrections effacées."}
        match = RULE.match(plain)
        if match:
            old = orig[match.start("old"):match.end("old")]
            new = _original_case(text, orig[match.start("new"):match.end("new")])
            self.learn(old, new)
            return {"answer": f"Compris : quand tu dis {old}, je comprendrai {new}."}
        match = REQUEST.match(plain)
        if not match or not previous:
            return None
        new = _original_case(text, orig[match.start("new"):match.end("new")])
        if len(_words(new)) <= MAX_WORDS:
            corrected, old = apply_fragment(previous, new)
            if old is None:
                return {"replay": new}          # sans rapport avec la phrase : nouvelle demande
            pair = (old, new)
        else:
            corrected, pair = new, replaced(previous, new)
        if pair and similar(*pair):
            self.learn(*pair)
        return {"replay": corrected}


def _original_case(text: str, lowered: str) -> str:
    """Retrouve majuscules et accents d'origine (« ouedraogo » -> « Ouédraogo »)."""
    index = " ".join((text or "").replace("’", "'").lower().split()).find(lowered)
    if index < 0:
        return lowered
    return " ".join((text or "").replace("’", "'").split())[index:index + len(lowered)]


__all__ = ["Corrections", "similar", "apply_fragment", "replaced"]
