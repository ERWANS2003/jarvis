"""Horizon 2 - memoire longue duree.

Trois types de souvenirs :
  * ``profile`` : faits durables sur l'utilisateur (nom, ville, preferences).
  * ``fact``    : element ponctuel que l'utilisateur a demande de retenir.
  * ``episode`` : resume automatique d'une conversation passee.

Le stockage est un simple fichier SQLite (stdlib) : pas de dependance, et le
fichier reste inspectable/editable a la main. La recherche est une similitude
par recouvrement de tokens (aucun modele d'embedding requis, donc hors-ligne).
"""

from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

from .text import jaccard, normalize, similar, tokenize

PROFILE = "profile"
FACT = "fact"
EPISODE = "episode"
KINDS = (PROFILE, FACT, EPISODE)

# --------------------------------------------------------------------------- #
# Detection des commandes explicites de memoire
# --------------------------------------------------------------------------- #
_REMEMBER_EN = re.compile(
    r"^\s*(?:please\s+)?(?:remember|note|keep in mind|don't forget|do not forget)"
    r"\s*(?:that|:)?\s*(.+)$",
    re.IGNORECASE,
)
_REMEMBER_FR = re.compile(
    r"^\s*(?:s'il te pla[iî]t\s+)?(?:souviens[- ]toi|retiens|rappelle[- ]toi|note|"
    r"n'oublie pas|ne pas oublier)\s*(?:que|:)?\s*(.+)$",
    re.IGNORECASE,
)
_FORGET_EN = re.compile(
    r"^\s*(?:please\s+)?(?:forget|erase|delete)(?:\s+about)?\s*(?::)?\s*(.+)$",
    re.IGNORECASE,
)
_FORGET_FR = re.compile(
    r"^\s*(?:s'il te pla[iî]t\s+)?(?:oublie|efface|supprime)(?:\s+(?:que|le|la|les))?"
    r"\s*(?::)?\s*(.+)$",
    re.IGNORECASE,
)

# Faits de profil : motifs volontairement etroits pour eviter les faux positifs.
_PROFILE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("name", re.compile(r"\b(?:my name is|i am called|call me)\s+([\w'’-]+)", re.I)),
    ("name", re.compile(r"\b(?:je m'appelle|mon nom est|appelle[- ]moi)\s+([\w'’-]+)", re.I)),
    ("location", re.compile(r"\b(?:i live in|i'm based in|i am based in)\s+([^.,;!?]+)", re.I)),
    ("location", re.compile(r"\b(?:j'habite [aà]|je vis [aà]|je suis bas[ée] [aà])\s+([^.,;!?]+)", re.I)),
    ("job", re.compile(r"\b(?:i work as|i work at|my job is)\s+([^.,;!?]+)", re.I)),
    ("job", re.compile(r"\b(?:je travaille (?:comme|chez|pour|[aà]))\s*([^.,;!?]+)", re.I)),
    ("preference", re.compile(r"\b(?:i (?:really )?(?:like|love|prefer))\s+([^.,;!?]+)", re.I)),
    ("preference", re.compile(r"\b(?:i (?:hate|dislike|can't stand))\s+([^.,;!?]+)", re.I)),
    ("preference", re.compile(r"\b(?:j'aime|j'adore|je pr[ée]f[èe]re)\s+([^.,;!?]+)", re.I)),
    ("preference", re.compile(r"\b(?:je d[ée]teste|je n'aime pas)\s+([^.,;!?]+)", re.I)),
]


def extract_explicit(text: str) -> tuple[str | None, str]:
    """Retourne ('remember'|'forget'|None, charge utile)."""
    for pattern, action in ((_REMEMBER_FR, "remember"), (_REMEMBER_EN, "remember"),
                            (_FORGET_FR, "forget"), (_FORGET_EN, "forget")):
        match = pattern.match(text or "")
        if match and match.group(1).strip():
            return action, match.group(1).strip(" .!")
    return None, ""


def extract_profile(text: str) -> list[tuple[str, str]]:
    """Extrait des faits de profil (nom, ville, metier, preferences)."""
    out: list[tuple[str, str]] = []
    for label, pattern in _PROFILE_PATTERNS:
        for match in pattern.finditer(text or ""):
            value = match.group(1).strip(" .!,").strip()
            if value and len(value) <= 80:
                out.append((label, value))
    return out


@dataclass
class Memory:
    id: int
    text: str
    kind: str
    source: str
    created_at: float
    updated_at: float
    score: float = field(default=0.0)

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "text": self.text,
            "kind": self.kind,
            "source": self.source,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class MemoryStore:
    """Petit magasin de souvenirs persistant (SQLite)."""

    def __init__(self, path: Path | str | None = None):
        if path is None:
            self.path = ":memory:"
            self._conn = sqlite3.connect(":memory:")
        else:
            self.path = Path(path)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        self._create_schema()

    def _create_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memories (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                text       TEXT NOT NULL,
                kind       TEXT NOT NULL DEFAULT 'fact',
                source     TEXT NOT NULL DEFAULT 'user',
                tokens     TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_memories_kind ON memories(kind)"
        )
        self._conn.commit()

    # -- ecriture ----------------------------------------------------------- #
    def remember(self, text: str, kind: str = FACT, source: str = "user",
                 dedupe: bool = True) -> int:
        text = " ".join((text or "").split()).strip(" .!")
        if not text:
            raise ValueError("memoire vide")
        if kind not in KINDS:
            kind = FACT
        now = time.time()
        if dedupe:
            for existing in self.all(kind=kind, limit=200):
                if similar(existing.text, text) >= 0.9:
                    self._conn.execute(
                        "UPDATE memories SET text=?, tokens=?, updated_at=? WHERE id=?",
                        (text, " ".join(tokenize(text)), now, existing.id),
                    )
                    self._conn.commit()
                    return existing.id
        cursor = self._conn.execute(
            "INSERT INTO memories (text, kind, source, tokens, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (text, kind, source, " ".join(tokenize(text)), now, now),
        )
        self._conn.commit()
        return int(cursor.lastrowid)

    def forget(self, mem_id: int) -> bool:
        cursor = self._conn.execute("DELETE FROM memories WHERE id=?", (int(mem_id),))
        self._conn.commit()
        return cursor.rowcount > 0

    def forget_matching(self, query: str, threshold: float = 0.55) -> int:
        """Supprime les souvenirs proches de la requete. Retourne le nombre.

        Deux criteres : similitude de chaine (>= ``threshold``) ou, pour une
        requete assez longue, contenance de tous ses mots dans le souvenir --
        sinon « oublie le cafe » ne retrouverait pas « likes black coffee »
        alors que la recherche, elle, le trouve.
        """
        query = (query or "").strip()
        if not query:
            return 0
        query_tokens = set(tokenize(query))
        removable = len(query) >= 3
        removed = 0
        for memory in self.all(limit=1000):
            mem_tokens = set(tokenize(memory.text))
            contained = removable and bool(query_tokens) and query_tokens <= mem_tokens
            if contained or similar(memory.text, query) >= threshold:
                removed += self.forget(memory.id)
        return removed

    def clear(self, kind: str | None = None) -> int:
        if kind:
            cursor = self._conn.execute("DELETE FROM memories WHERE kind=?", (kind,))
        else:
            cursor = self._conn.execute("DELETE FROM memories")
        self._conn.commit()
        return cursor.rowcount

    # -- lecture ------------------------------------------------------------ #
    @staticmethod
    def _row(row: sqlite3.Row) -> Memory:
        return Memory(
            id=row["id"], text=row["text"], kind=row["kind"], source=row["source"],
            created_at=row["created_at"], updated_at=row["updated_at"],
        )

    def all(self, kind: str | None = None, limit: int = 200) -> list[Memory]:
        if kind:
            rows = self._conn.execute(
                "SELECT * FROM memories WHERE kind=? ORDER BY updated_at DESC LIMIT ?",
                (kind, int(limit)),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM memories ORDER BY updated_at DESC LIMIT ?", (int(limit),)
            ).fetchall()
        return [self._row(row) for row in rows]

    def count(self, kind: str | None = None) -> int:
        if kind:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM memories WHERE kind=?", (kind,)
            ).fetchone()
        else:
            row = self._conn.execute("SELECT COUNT(*) AS n FROM memories").fetchone()
        return int(row["n"])

    def search(self, query: str, k: int = 5, min_score: float = 0.0) -> list[Memory]:
        """Recherche par recouvrement de tokens + similarite de chaine."""
        query_tokens = tokenize(query)
        if not query_tokens:
            return []
        results: list[Memory] = []
        for memory in self.all(limit=1000):
            mem_tokens = tokenize(memory.text)
            overlap = jaccard(query_tokens, mem_tokens)
            contains = 1.0 if normalize(query) in normalize(memory.text) else 0.0
            score = 0.6 * overlap + 0.4 * contains
            if score > min_score:
                memory.score = score
                results.append(memory)
        results.sort(key=lambda m: (m.score, m.updated_at), reverse=True)
        return results[:k]

    # -- rendu pour le prompt ---------------------------------------------- #
    def profile_block(self, strings: dict) -> str:
        entries = self.all(kind=PROFILE, limit=50)
        if not entries:
            return ""
        lines = [f"- {m.text}" for m in reversed(entries)]
        return strings["profile_header"] + "\n" + "\n".join(lines)

    def episodes_block(self, strings: dict, limit: int = 5) -> str:
        entries = self.all(kind=EPISODE, limit=limit)
        if not entries:
            return ""
        lines = [f"- {m.text}" for m in entries]
        return strings["episodes_header"] + "\n" + "\n".join(lines)

    def recall_block(self, query: str, strings: dict, k: int = 5) -> str:
        hits = [m for m in self.search(query, k=k, min_score=0.08)
                if m.kind != EPISODE]
        if not hits:
            return ""
        lines = [f"- {m.text}" for m in hits]
        return strings["memory_header"] + "\n" + "\n".join(lines)

    # -- resumes automatiques ---------------------------------------------- #
    def summarize(self, ask, transcript: str, strings: dict) -> str:
        """Demande un resume a `ask(prompt)->str` puis le stocke en episode."""
        transcript = (transcript or "").strip()
        if len(transcript) < 40:
            return ""
        prompt = strings["summary_prompt"] + "\n\n" + transcript
        try:
            summary = ask(prompt)
        except Exception:
            return ""
        summary = " ".join((summary or "").split()).strip()
        if not summary:
            return ""
        self.remember(summary, kind=EPISODE, source="auto", dedupe=True)
        return summary

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    def __enter__(self) -> "MemoryStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


__all__ = [
    "Memory",
    "MemoryStore",
    "PROFILE",
    "FACT",
    "EPISODE",
    "KINDS",
    "extract_explicit",
    "extract_profile",
]
