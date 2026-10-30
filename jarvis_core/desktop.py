"""Ranger le bureau d'apres le nom des elements, sans jamais rien perdre.

  1. « range mon bureau » : Jarvis calcule un plan et le dit, **sans rien deplacer** ;
  2. « detaille le rangement », « renomme le dossier Divers en Archives »,
     « laisse le CV sur le bureau » : on retouche le plan a la voix ;
  3. « confirme le rangement » : tout part dans ``Rangé/<categorie>`` ;
  4. « annule le rangement » : le dernier rangement est defait (les precedents
     restent dans le journal, on peut remonter plusieurs fois).

Pour chaque fichier, dans l'ordre : un logiciel reconnaissable a son extension
(un projet Premiere va dans « Montage vidéo »), un mot-cle du nom (« facture_edf »
-> Factures), un debut de nom commun a plusieurs fichiers (« vacances_01 »,
« vacances_02 » -> Vacances), enfin le type de fichier (Documents, Images...).
Dans une categorie, les fichiers d'un meme projet forment un sous-dossier
(« loff.prproj », « loff_1.prin » -> Montage vidéo/Loff).

Par defaut seuls les fichiers bougent. Dossiers et raccourcis ne bougent que sur
demande (« range aussi les dossiers », « range aussi les raccourcis »). Ne bougent
jamais : les fichiers caches ou temporaires, le dossier de Jarvis, les dossiers
geres par Adobe, ceux qui contiennent un environnement Python ; rien n'est ecrase
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
MAX_UNDO = 10
UNDO_FILE = Path(__file__).resolve().parent.parent / ".jarvis_desktop_undo.json"
SHORTCUTS = {".lnk", ".url"}
SKIPPED_SUFFIXES = {".ini", ".tmp", ".crdownload", ".part"}
JARVIS_HOME = Path(__file__).resolve().parent.parent
PROTECTED_PREFIXES = ("adobe ", "premiere ", "motion graphics")

SOFTWARE = (   # (categorie, extensions) : le fichier parle de lui-meme
    ("Montage vidéo", {".prproj", ".prin", ".prfpset", ".prel", ".aep", ".aet", ".mogrt", ".drp",
                       ".veg", ".vdoc", ".~vdoc", ".kdenlive"}),
    ("Musique", {".flp", ".als", ".ptx"}),
    ("Modélisation", {".mdj", ".bpmn", ".drawio", ".vsdx", ".uml"}),
    ("Bases de données", {".sql", ".accdb", ".mdb", ".sqlite", ".db"}),
)
CATEGORIES = (   # (dossier, mots du nom) ; le premier qui correspond gagne
    ("CV et candidatures", ("cv", "lettre", "motivation", "candidature", "entretien", "statement")),
    ("Rapports", ("rapport", "report", "protocole", "memoire", "these", "soutenance", "stage")),
    ("Factures", ("facture", "factures", "invoice", "devis", "quittance", "recu")),
    ("Banque et impôts", ("banque", "releve", "rib", "impot", "impots", "bank", "tax", "bulletin", "paie")),
    ("Papiers", ("contrat", "attestation", "certificat", "passeport", "identite", "permis",
                 "assurance", "justificatif", "administratif")),
    ("Cours", ("cours", "td", "tp", "examen", "exam", "partiel", "lecon", "chapitre", "revision",
               "devoir", "exercice", "exercices", "exo", "reading", "materials")),
    ("Présentations", ("presentation", "expose", "soutenance", "diaporama", "slides")),
    ("Projets", ("projet", "project", "budget", "planning", "reunion", "meeting")),
    ("Captures d'écran", ("capture", "screenshot")),
    ("Photos", ("photo", "photos", "img", "dsc", "pxl", "wallpaper", "whatsapp")),
    ("Vidéos", ("video", "videos", "film", "clip")),
    ("Musique", ("musique", "music", "audio", "song", "chanson")),
    ("Installateurs", ("setup", "install", "installer", "installeur")),
)
BY_TYPE = (   # dernier recours : le type de fichier
    ("Documents", {".pdf", ".doc", ".docx", ".odt", ".rtf", ".txt", ".md", ".xls", ".xlsx", ".csv",
                   ".ods", ".ppt", ".pptx", ".odp"}),
    ("Images", {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".heic", ".ico", ".psd", ".ai"}),
    ("Vidéos", {".mp4", ".mov", ".avi", ".mkv", ".m4v", ".webm", ".wmv"}),
    ("Musique", {".mp3", ".wav", ".aac", ".flac", ".m4a", ".ogg", ".wma"}),
    ("Archives", {".zip", ".rar", ".7z", ".tar", ".gz"}),
    ("Installateurs", {".exe", ".msi", ".apk"}),
    ("Pages web", {".html", ".htm", ".mhtml"}),
    ("Code", {".py", ".js", ".ts", ".java", ".c", ".cpp", ".php", ".json", ".xml", ".css", ".ipynb"}),
)
FOLDER_CATEGORIES = (   # dossiers : uniquement si « range aussi les dossiers »
    ("Montage vidéo", ("montage", "premiere", "storyteller", "histoire", "histoires", "fifa")),
    ("Cours", ("cours", "tp", "td", "exam", "m1", "m2", "licence", "intelligence", "artificielle",
               "machine", "learning", "geomatique", "sig", "xml", "bpmn", "microservices",
               "extraction", "school", "schhol")),
    ("Sites et applications", ("portfolio", "site", "app", "web", "react", "refontesite", "projet",
                               "projets", "proet", "campusflow", "cascadeprojects", "playground",
                               "glpi", "patrimonia")),
    ("Stage et travail", ("stage", "travail", "mining", "nere", "nereinterne", "indaba", "documents")),
    ("Photos et médias", ("photos", "camera", "logo", "image", "images", "powerpoint")),
    ("Musique", ("studio", "music", "musique")),
)
SHORTCUT_FOLDERS = {".url": "Jeux", ".lnk": "Applications"}
_STOP_WORDS = {"le", "la", "les", "de", "du", "des", "un", "une", "et", "the", "of", "new",
               "nouveau", "nouvelle", "copie", "copy", "copier", "final", "doc", "document",
               "fichier", "file", "sans", "titre", "untitled", "avec", "pour", "bon", "mon", "ma"}


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


def _with_bare(words: list[str]) -> set[str]:
    """« tp2 », « expose1 » comptent aussi comme « tp », « expose »."""
    return set(words) | {re.sub(r"\d+$", "", word) for word in words}


def category_of(filename: str) -> str | None:
    """Categorie par logiciel, puis par mot-cle du nom."""
    suffix = Path(filename).suffix.lower()
    for folder, suffixes in SOFTWARE:
        if suffix in suffixes:
            return folder
    words = _with_bare(name_words(filename))
    for folder, keywords in CATEGORIES:
        if words & set(keywords):
            return folder
    return None


def type_of(filename: str) -> str | None:
    suffix = Path(filename).suffix.lower()
    return next((folder for folder, suffixes in BY_TYPE if suffix in suffixes), None)


def folder_category(name: str) -> str | None:
    words = _with_bare(re.findall(r"[a-z0-9]+", _plain(name)))
    for folder, keywords in FOLDER_CATEGORIES:
        if words & set(keywords):
            return folder
    return None


def _group_key(filename: str) -> str | None:
    """Premier mot parlant du nom (ni nombre, ni mot vide, 3 lettres au moins)."""
    for word in name_words(filename):
        if word not in _STOP_WORDS and not word.isdigit() and len(word) >= 3:
            return word
    return None


def _hidden(path: Path) -> bool:
    if path.name.startswith((".", "~$")):
        return True
    try:
        return bool(os.stat(path).st_file_attributes & 2)
    except (OSError, AttributeError):
        return False


def _movable(path: Path) -> bool:
    return path.is_file() and not _hidden(path) and path.suffix.lower() not in SKIPPED_SUFFIXES \
        and path.suffix.lower() not in SHORTCUTS


def folder_protected(path: Path) -> bool:
    """Le dossier de Jarvis, les dossiers geres par Adobe, les environnements Python."""
    low = path.name.lower()
    if path.name == ROOT_NAME or _hidden(path) or low.startswith(PROTECTED_PREFIXES):
        return True
    try:
        if JARVIS_HOME == path.resolve() or path.resolve() in JARVIS_HOME.parents:
            return True
        return (path / ".venv").is_dir() or (path / "venv").is_dir()
    except OSError:
        return True


def _subgroup(names: list[str]) -> dict[str, list[str]]:
    """Dans une categorie : les fichiers d'un meme projet ont leur sous-dossier."""
    groups: dict[str, list[str]] = {}
    for name in names:
        key = _group_key(Path(name).name)
        groups.setdefault(key or "", []).append(name)
    result: dict[str, list[str]] = {}
    for key, members in groups.items():
        target = key.capitalize() if key and len(members) >= MIN_GROUP else ""
        result.setdefault(target, []).extend(members)
    return result


def make_plan(folder: Path | None = None, folders: bool = False, shortcuts: bool = False,
              again: bool = False) -> dict[str, list[str]]:
    """{dossier cible: [elements, chemins relatifs au bureau]}. Ne touche a rien.

    `again` reprend aussi ce qui est deja dans ``Rangé`` pour le reclasser.
    """
    folder = Path(folder) if folder else desktop_path()
    entries = sorted(folder.iterdir(), key=lambda p: p.name.lower())
    files = [p.name for p in entries if _movable(p)]
    root = folder / ROOT_NAME
    if again and root.is_dir():
        files += sorted(str(p.relative_to(folder)) for p in root.rglob("*") if _movable(p))
    by_category: dict[str, list[str]] = {}
    groups: dict[str, list[str]] = {}
    for rel in files:
        name = Path(rel).name
        category = category_of(name)
        if category:
            by_category.setdefault(category, []).append(rel)
            continue
        key = _group_key(name)
        if key:
            groups.setdefault(key, []).append(rel)
        elif type_of(name):
            by_category.setdefault(type_of(name), []).append(rel)
    for key, members in groups.items():
        if len(members) >= MIN_GROUP:
            by_category.setdefault(key.capitalize(), []).extend(members)
        else:
            for rel in members:
                kind = type_of(Path(rel).name)
                if kind:
                    by_category.setdefault(kind, []).append(rel)
    plan: dict[str, list[str]] = {}
    for category, members in by_category.items():
        if category in {f for f, _s in SOFTWARE}:
            for sub, names in _subgroup(members).items():
                plan.setdefault(f"{category}/{sub}" if sub else category, []).extend(names)
        else:
            plan.setdefault(category, []).extend(members)
    if shortcuts:
        for path in entries:
            target = SHORTCUT_FOLDERS.get(path.suffix.lower())
            if target and path.is_file() and not _hidden(path):
                plan.setdefault(target, []).append(path.name)
    if folders:
        for path in entries:
            target = folder_category(path.name) if path.is_dir() else None
            if target and not folder_protected(path):
                plan.setdefault(target, []).append(path.name)
    # Un element deja a sa place ne bouge pas (reclassement).
    for target in list(plan):
        plan[target] = [rel for rel in plan[target]
                        if Path(rel).parent != Path(ROOT_NAME) / target]
        if not plan[target]:
            del plan[target]
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


_BAD_FOLDER_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class DesktopOrganizer:
    def __init__(self, folder: Path | str | None = None, undo_file: Path | str | None = None):
        self.folder = Path(folder) if folder else desktop_path()
        self.undo_file = Path(undo_file) if undo_file else UNDO_FILE
        self._plan: dict[str, list[str]] | None = None
        self._plan_at = 0.0

    def propose(self, folders: bool = False, shortcuts: bool = False,
                again: bool = False) -> dict[str, list[str]]:
        self._plan = make_plan(self.folder, folders=folders, shortcuts=shortcuts, again=again)
        self._plan_at = time.monotonic()
        return self._plan

    def pending(self) -> bool:
        return bool(self._plan) and time.monotonic() - self._plan_at <= PLAN_TTL

    def plan(self) -> dict[str, list[str]]:
        return dict(self._plan or {}) if self.pending() else {}

    def _touch(self) -> None:
        self._plan_at = time.monotonic()

    def rename(self, old: str, new: str) -> bool:
        """Renomme un dossier du plan (sa categorie ou son sous-dossier)."""
        new = _BAD_FOLDER_CHARS.sub("", new).strip(" .")
        wanted = _plain(old).strip()
        if not self.pending() or not new:
            return False
        hits = [key for key in self._plan
                if _plain(key) == wanted or _plain(key.split("/")[-1]) == wanted]
        if not hits:
            return False
        for key in hits:
            parts = key.split("/")
            parts[-1 if _plain(parts[-1]) == wanted else 0] = new
            target = "/".join(parts)
            self._plan.setdefault(target, [])
            self._plan[target].extend(self._plan.pop(key))
        self._touch()
        return True

    def leave(self, what: str) -> int:
        """Retire du plan un dossier ou les elements dont le nom contient `what`."""
        wanted = _plain(what).strip()
        if not self.pending() or len(wanted) < 2:
            return 0
        removed = 0
        for key in list(self._plan):
            if _plain(key) == wanted or _plain(key.split("/")[-1]) == wanted:
                removed += len(self._plan.pop(key))
                continue
            kept = [rel for rel in self._plan[key] if wanted not in _plain(Path(rel).name)]
            removed += len(self._plan[key]) - len(kept)
            if kept:
                self._plan[key] = kept
            else:
                del self._plan[key]
        self._touch()
        return removed

    def apply(self) -> tuple[int, int]:
        """Execute le plan propose. Renvoie (deplaces, echoues)."""
        if not self.pending():
            return 0, 0
        moved: list[dict] = []
        failed = 0
        root = self.folder / ROOT_NAME
        for target_folder, items in self._plan.items():
            for rel in items:
                source = self.folder / rel
                try:
                    (root / target_folder).mkdir(parents=True, exist_ok=True)
                    target = _free_target(root / target_folder / source.name)
                    shutil.move(str(source), str(target))
                    moved.append({"from": str(source), "to": str(target)})
                except OSError:          # fichier ouvert, droits... : il reste ou il est
                    failed += 1
        self._plan = None
        for move in moved:
            self._prune(Path(move["from"]).parent)
        if moved:
            runs = self._runs()
            runs.append(moved)
            self._save_runs(runs[-MAX_UNDO:])
        return len(moved), failed

    def _runs(self) -> list[list[dict]]:
        try:
            data = json.loads(self.undo_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        if isinstance(data, list):                  # ancien format : un seul rangement
            return [data] if data else []
        return data.get("runs", [])

    def _save_runs(self, runs: list[list[dict]]) -> None:
        if runs:
            self.undo_file.write_text(json.dumps({"runs": runs}, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
        else:
            self.undo_file.unlink(missing_ok=True)

    def undo(self) -> int:
        """Defait le dernier rangement. Renvoie le nombre d'elements remis en place."""
        runs = self._runs()
        if not runs:
            return 0
        restored, remaining = 0, []
        for move in reversed(runs.pop()):
            source, target = Path(move["to"]), Path(move["from"])
            try:
                if source.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(source), str(_free_target(target)))
                    restored += 1
                    self._prune(source.parent)
            except OSError:
                remaining.append(move)
        if remaining:
            runs.append(remaining)
        self._save_runs(runs)
        return restored

    def _prune(self, folder: Path) -> None:
        """Retire un dossier de ``Rangé`` vide par un deplacement, puis ses parents vides.
        Ne parcourt jamais l'interieur : un dossier vide de l'utilisateur reste intact."""
        root = self.folder / ROOT_NAME
        while folder == root or root in folder.parents:
            try:
                folder.rmdir()
            except OSError:
                return
            folder = folder.parent


def say_plan(plan: dict[str, list[str]], lang: str = "fr") -> str:
    fr = lang == "fr"
    if not plan:
        return ("Je ne vois rien à classer sur ton bureau." if fr
                else "I see nothing to sort on your desktop.")
    total = sum(len(names) for names in plan.values())
    tops: dict[str, int] = {}
    for key, names in plan.items():
        top = key.split("/")[0]
        tops[top] = tops.get(top, 0) + len(names)
    ordered = sorted(tops.items(), key=lambda item: -item[1])
    shown = [f"{folder} ({count})" for folder, count in ordered[:6]]
    more = len(ordered) - len(shown)
    tail = (f", et {more} autres dossiers" if fr else f", and {more} more folders") if more else ""
    if fr:
        return (f"Je propose de ranger {total} éléments dans {len(ordered)} dossiers : "
                f"{', '.join(shown)}{tail}. Rien n'a bougé. Dis « détaille le rangement » pour "
                f"voir le contenu, ou « confirme le rangement » pour le faire.")
    return (f"I suggest sorting {total} items into {len(ordered)} folders: {', '.join(shown)}{tail}. "
            f"Nothing has moved. Say 'detail the tidy up' to see more, or 'confirm the tidy up' to do it.")


def say_details(plan: dict[str, list[str]], lang: str = "fr", limit: int = 8) -> str:
    fr = lang == "fr"
    if not plan:
        return ("Il n'y a pas de plan en cours : dis « range mon bureau »." if fr
                else "No plan yet: say 'tidy my desktop'.")
    parts = []
    for key, names in list(plan.items())[:limit]:
        sample = ", ".join(Path(rel).stem[:30] for rel in names[:2])
        extra = (f" et {len(names) - 2} autres" if fr else f" and {len(names) - 2} more") if len(names) > 2 else ""
        parts.append(f"{key.replace('/', ', ')} : {sample}{extra}")
    more = len(plan) - len(parts)
    tail = (f" Et {more} autres dossiers." if fr else f" And {more} more folders.") if more else ""
    return ". ".join(parts) + "." + tail


__all__ = ["DesktopOrganizer", "make_plan", "say_plan", "say_details", "category_of", "desktop_path",
           "folder_category", "folder_protected", "ROOT_NAME"]
