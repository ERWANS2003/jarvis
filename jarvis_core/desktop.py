"""Ranger le bureau d'apres le nom des fichiers, sans jamais rien perdre.

  1. « range mon bureau » : Jarvis calcule un plan et le dit, **sans rien deplacer** ;
  2. « confirme le rangement » : les fichiers partent dans ``Rangé/<categorie>`` ;
  3. « annule le rangement » : chaque fichier revient a sa place (journal JSON).

Le classement lit le nom : un mot-cle connu (« facture_edf.pdf » -> Factures),
sinon un debut de nom commun a au moins deux fichiers (« vacances_01.jpg »,
« vacances_02.jpg » -> Vacances). Un fichier sans groupe reste ou il est.

Seuls les fichiers bouges sont ceux du premier niveau : les dossiers, les
raccourcis et les fichiers caches ne sont jamais touches, rien n'est ecrase
ni supprime.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
import unicodedata
from pathlib import Path

ROOT_NAME = "Rangé"
PLAN_TTL = 600.0                # un plan vieux de 10 min doit etre recalcule
MIN_GROUP = 2
UNDO_FILE = Path(__file__).resolve().parent.parent / ".jarvis_desktop_undo.json"
SKIPPED_SUFFIXES = {".lnk", ".url", ".ini", ".tmp", ".crdownload", ".part"}

CATEGORIES = (   # (dossier, mots du nom de fichier) ; le premier qui correspond gagne
    ("Factures", ("facture", "factures", "invoice", "devis", "quittance", "recu")),
    ("Banque et impôts", ("banque", "releve", "rib", "impot", "impots", "bank", "tax")),
    ("Papiers", ("contrat", "attestation", "certificat", "passeport", "identite", "carte",
                 "permis", "assurance", "justificatif", "administratif")),
    ("CV et emploi", ("cv", "resume", "lettre", "motivation", "candidature", "stage",
                      "emploi", "entretien", "bulletin", "paie")),
    ("Cours", ("cours", "td", "tp", "examen", "exam", "partiel", "memoire", "these",
               "lecon", "chapitre", "revision", "devoir", "exercice", "exercices")),
    ("Travail", ("rapport", "reunion", "projet", "presentation", "budget", "planning",
                 "report", "meeting", "project")),
    ("Captures d'écran", ("capture", "screenshot", "screen")),
    ("Photos", ("photo", "photos", "img", "image", "dsc", "pxl", "wallpaper", "fond")),
    ("Vidéos", ("video", "videos", "vid", "film", "clip")),
    ("Musique", ("musique", "music", "audio", "song", "chanson")),
    ("Installateurs", ("setup", "install", "installer", "installeur", "update")),
)
_STOP_WORDS = {"le", "la", "les", "de", "du", "des", "un", "une", "et", "the", "of", "new",
               "nouveau", "copie", "copy", "final", "v1", "v2", "v3", "doc", "document",
               "fichier", "file", "sans", "titre", "untitled"}


def desktop_path() -> Path:
    """Le vrai dossier Bureau, y compris redirige vers OneDrive."""
    try:
        import ctypes
        from ctypes import wintypes

        buffer = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0x0000, None, 0, buffer) == 0 and buffer.value:
            return Path(buffer.value)
    except Exception:
        pass
    return Path.home() / "Desktop"


def _plain(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).lower()
    return "".join(c for c in text if not unicodedata.combining(c))


def name_words(filename: str) -> list[str]:
    """« Facture_EDF-2026 (2).pdf » -> ['facture', 'edf', '2026', '2']."""
    stem = Path(filename).stem
    stem = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", stem)       # rapportAnnuel -> rapport Annuel
    return re.findall(r"[a-z0-9]+", _plain(stem))


def category_of(filename: str) -> str | None:
    words = set(name_words(filename))
    for folder, keywords in CATEGORIES:
        if words & set(keywords):
            return folder
    return None


def _group_key(filename: str) -> str | None:
    """Premier mot parlant du nom (ni nombre, ni mot vide, 3 lettres au moins)."""
    for word in name_words(filename):
        if word not in _STOP_WORDS and not word.isdigit() and len(word) >= 3:
            return word
    return None


def _movable(path: Path) -> bool:
    if not path.is_file() or path.name.startswith((".", "~$")):
        return False
    if path.suffix.lower() in SKIPPED_SUFFIXES:
        return False
    try:
        if os.stat(path).st_file_attributes & 2:          # attribut « cache »
            return False
    except (OSError, AttributeError):
        pass
    return True


def make_plan(folder: Path | None = None) -> dict[str, list[str]]:
    """{dossier: [fichiers]} d'apres les noms. Ne touche a rien."""
    folder = Path(folder) if folder else desktop_path()
    files = sorted(p.name for p in folder.iterdir() if _movable(p))
    plan: dict[str, list[str]] = {}
    groups: dict[str, list[str]] = {}
    for name in files:
        category = category_of(name)
        if category:
            plan.setdefault(category, []).append(name)
            continue
        key = _group_key(name)
        if key:
            groups.setdefault(key, []).append(name)
    for key, names in groups.items():
        if len(names) >= MIN_GROUP:
            plan.setdefault(key.capitalize(), []).extend(names)
    return dict(sorted(plan.items(), key=lambda item: (-len(item[1]), item[0])))


def _free_target(target: Path) -> Path:
    """« a.pdf » existe deja -> « a (2).pdf » : jamais d'ecrasement."""
    if not target.exists():
        return target
    for index in range(2, 1000):
        other = target.with_name(f"{target.stem} ({index}){target.suffix}")
        if not other.exists():
            return other
    raise OSError(f"trop de doublons pour {target.name}")


class DesktopOrganizer:
    def __init__(self, folder: Path | str | None = None, undo_file: Path | str | None = None):
        self.folder = Path(folder) if folder else desktop_path()
        self.undo_file = Path(undo_file) if undo_file else UNDO_FILE
        self._plan: dict[str, list[str]] | None = None
        self._plan_at = 0.0

    def propose(self) -> dict[str, list[str]]:
        self._plan = make_plan(self.folder)
        self._plan_at = time.monotonic()
        return self._plan

    def pending(self) -> bool:
        return bool(self._plan) and time.monotonic() - self._plan_at <= PLAN_TTL

    def apply(self) -> tuple[int, int]:
        """Execute le plan propose. Renvoie (deplaces, echoues)."""
        if not self.pending():
            return 0, 0
        moved: list[dict] = []
        failed = 0
        root = self.folder / ROOT_NAME
        for folder, names in self._plan.items():
            for name in names:
                source = self.folder / name
                try:
                    (root / folder).mkdir(parents=True, exist_ok=True)
                    target = _free_target(root / folder / name)
                    shutil.move(str(source), str(target))
                    moved.append({"from": str(source), "to": str(target)})
                except OSError:          # fichier ouvert, droits... : il reste ou il est
                    failed += 1
        self._plan = None
        if moved:
            self.undo_file.write_text(json.dumps(moved, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
        return len(moved), failed

    def undo(self) -> int:
        """Remet les fichiers du dernier rangement a leur place. Renvoie le nombre."""
        try:
            moves = json.loads(self.undo_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return 0
        restored, remaining = 0, []
        for move in moves:
            source, target = Path(move["to"]), Path(move["from"])
            try:
                if source.exists():
                    shutil.move(str(source), str(_free_target(target)))
                    restored += 1
                    self._remove_if_empty(source.parent)
            except OSError:
                remaining.append(move)
        if remaining:
            self.undo_file.write_text(json.dumps(remaining, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
        else:
            self.undo_file.unlink(missing_ok=True)
        self._remove_if_empty(self.folder / ROOT_NAME)
        return restored

    @staticmethod
    def _remove_if_empty(folder: Path) -> None:
        try:
            folder.rmdir()            # echoue si le dossier contient encore quelque chose
        except OSError:
            pass


def say_plan(plan: dict[str, list[str]], lang: str = "fr") -> str:
    fr = lang == "fr"
    if not plan:
        return ("Je ne vois rien à classer d'après les noms sur ton bureau." if fr
                else "I see nothing to sort by name on your desktop.")
    total = sum(len(names) for names in plan.values())
    shown = [f"{folder} ({len(names)})" for folder, names in list(plan.items())[:6]]
    more = len(plan) - len(shown)
    tail = (f", et {more} autres dossiers" if fr else f", and {more} more folders") if more else ""
    if fr:
        return (f"Je propose de ranger {total} fichiers dans {len(plan)} dossiers : "
                f"{', '.join(shown)}{tail}. Rien n'a bougé. Dis « confirme le rangement » "
                f"pour le faire.")
    return (f"I suggest sorting {total} files into {len(plan)} folders: {', '.join(shown)}{tail}. "
            f"Nothing has moved. Say 'confirm the tidy up' to do it.")


__all__ = ["DesktopOrganizer", "make_plan", "say_plan", "category_of", "desktop_path", "ROOT_NAME"]
