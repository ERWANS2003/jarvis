"""Horizon 3 - fichiers et presse-papiers.

  * « Ouvre mon dernier PDF », « cherche le fichier rapport » : recherche par
    nom dans les dossiers personnels (Bureau, Documents, Telechargements,
    Images, Musique, Videos), y compris quand Windows les a deplaces dans
    OneDrive. Jamais ailleurs : Jarvis n'ouvre pas les fichiers systeme.
  * « Resume ce que j'ai copie », « copie la reponse » : lecture et ecriture
    du presse-papiers (texte).

Ouvrir un fichier = l'ouvrir avec son application habituelle, comme un
double-clic dans l'Explorateur ; rien n'est jamais execute directement (les
programmes et scripts sont refuses).
"""

from __future__ import annotations

import os
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

MAX_DEPTH = 5
MAX_SCANNED = 40_000
SKIP_DIRS = {"node_modules", ".git", ".venv", "venv", "__pycache__", "appdata",
             "$recycle.bin", ".cache", "site-packages"}
# Jamais ouverts par Jarvis : ils lanceraient un programme.
BLOCKED_SUFFIXES = {".exe", ".bat", ".cmd", ".com", ".msi", ".ps1", ".vbs",
                    ".js", ".jse", ".wsf", ".scr", ".lnk", ".reg", ".py",
                    ".pyw", ".hta", ".cpl", ".jar"}
KIND_SUFFIXES = {
    "pdf": {".pdf"},
    "document": {".pdf", ".doc", ".docx", ".odt", ".rtf", ".txt", ".md"},
    "word": {".doc", ".docx", ".odt"},
    "excel": {".xls", ".xlsx", ".ods", ".csv"},
    "presentation": {".ppt", ".pptx", ".odp"},
    "image": {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".heic"},
    "music": {".mp3", ".wav", ".flac", ".m4a", ".ogg"},
    "video": {".mp4", ".mkv", ".avi", ".mov", ".webm"},
    "archive": {".zip", ".rar", ".7z"},
}
# Synonymes (francais et anglais) vers les familles ci-dessus.
KIND_ALIASES = {
    "pdf": "pdf", "document": "document", "documents": "document", "doc": "word",
    "word": "word", "excel": "excel", "tableur": "excel", "tableau": "excel",
    "spreadsheet": "excel", "powerpoint": "presentation", "presentation": "presentation",
    "diaporama": "presentation", "image": "image", "images": "image", "photo": "image",
    "photos": "image", "picture": "image", "musique": "music", "music": "music",
    "chanson": "music", "video": "video", "videos": "video", "film": "video",
    "archive": "archive", "zip": "archive",
}

# Dossiers connus de Windows (suivent une redirection vers OneDrive).
_KNOWN_FOLDERS = {
    "desktop": "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}",
    "documents": "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}",
    "downloads": "{374DE290-123F-4565-9164-39C4925E467B}",
    "pictures": "{33E28130-4E1E-4676-835A-98395C3BC3BB}",
    "music": "{4BD8D571-6D19-48D3-BE97-422220080E43}",
    "videos": "{18989B1D-99B5-455B-841C-AB7C74E4DDFC}",
}


def _known_folder(guid: str) -> Path | None:
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        import uuid

        class GUID(ctypes.Structure):
            _fields_ = [("data", ctypes.c_ubyte * 16)]

        folder_id = GUID()
        folder_id.data[:] = uuid.UUID(guid).bytes_le
        path_ptr = ctypes.c_wchar_p()
        result = ctypes.windll.shell32.SHGetKnownFolderPath(
            ctypes.byref(folder_id), 0, None, ctypes.byref(path_ptr))
        if result != 0:
            return None
        path = Path(path_ptr.value)
        ctypes.windll.ole32.CoTaskMemFree(path_ptr)
        return path
    except Exception:
        return None


def user_folders() -> list[Path]:
    """Dossiers personnels ou chercher, sans doublon, ceux qui existent."""
    home = Path.home()
    candidates = [_known_folder(guid) for guid in _KNOWN_FOLDERS.values()]
    candidates += [home / name for name in ("Desktop", "Documents", "Downloads",
                                            "Pictures", "Music", "Videos")]
    candidates += [home / "OneDrive" / name for name in ("Bureau", "Desktop",
                                                         "Documents", "Images")]
    seen, folders = set(), []
    for folder in candidates:
        if folder is None:
            continue
        try:
            resolved = folder.resolve()
        except OSError:
            continue
        key = str(resolved).lower()
        if key not in seen and resolved.is_dir():
            seen.add(key)
            folders.append(resolved)
    return folders


def fold(text: str) -> str:
    """Minuscules sans accents, pour comparer des noms de fichiers."""
    text = unicodedata.normalize("NFKD", text or "").lower()
    return "".join(c for c in text if not unicodedata.combining(c))


def kind_suffixes(kind: str | None) -> set[str] | None:
    if not kind:
        return None
    family = KIND_ALIASES.get(fold(kind).strip())
    if family:
        return KIND_SUFFIXES[family]
    suffix = fold(kind).strip().lstrip(".")
    return {"." + suffix} if suffix.isalnum() else None


@dataclass
class FoundFile:
    path: Path
    modified: float

    def label(self) -> str:
        import datetime as _dt

        when = _dt.datetime.fromtimestamp(self.modified).strftime("%d/%m/%Y %H:%M")
        return f"{self.path.name} ({self.path.parent.name}, {when})"


def _walk(folders, max_depth=MAX_DEPTH, max_scanned=MAX_SCANNED):
    scanned = 0
    for root in folders:
        stack = [(Path(root), 0)]
        while stack:
            folder, depth = stack.pop()
            try:
                entries = list(os.scandir(folder))
            except OSError:
                continue
            for entry in entries:
                scanned += 1
                if scanned > max_scanned:
                    return
                name = entry.name
                if name.startswith(".") or name.startswith("~$"):
                    continue
                try:
                    if entry.is_dir(follow_symlinks=False):
                        if depth < max_depth and fold(name) not in SKIP_DIRS:
                            stack.append((Path(entry.path), depth + 1))
                    elif entry.is_file(follow_symlinks=False):
                        yield Path(entry.path), entry.stat().st_mtime
                except OSError:
                    continue


def find_files(query: str = "", kind: str | None = None, limit: int = 5,
               folders=None) -> list[FoundFile]:
    """Fichiers dont le nom contient tous les mots de `query`, plus recents d'abord."""
    words = [w for w in fold(query).replace("_", " ").replace("-", " ").split() if w]
    suffixes = kind_suffixes(kind)
    found: list[FoundFile] = []
    for path, modified in _walk(folders if folders is not None else user_folders()):
        if suffixes is not None and path.suffix.lower() not in suffixes:
            continue
        name = fold(path.name).replace("_", " ").replace("-", " ")
        if all(word in name for word in words):
            found.append(FoundFile(path, modified))
    found.sort(key=lambda item: item.modified, reverse=True)
    return found[:max(1, limit)]


def is_allowed(path: Path, folders=None) -> bool:
    """Vrai pour un fichier existant, inoffensif, dans un dossier personnel."""
    try:
        path = Path(path).resolve()
    except OSError:
        return False
    if not path.is_file() or path.suffix.lower() in BLOCKED_SUFFIXES:
        return False
    roots = folders if folders is not None else user_folders()
    return any(path.is_relative_to(Path(root).resolve()) for root in roots)


def open_file(path: Path, folders=None, opener=None) -> bool:
    """Ouvre le fichier avec son application habituelle (si autorise)."""
    if not is_allowed(path, folders):
        return False
    try:
        (opener or os.startfile)(str(Path(path).resolve()))  # type: ignore[attr-defined]
    except Exception:
        return False
    return True


# --------------------------------------------------------------------------- #
# Presse-papiers (texte, Windows)
# --------------------------------------------------------------------------- #
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002


def _clipboard_api():
    import ctypes
    from ctypes import wintypes

    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    user32.GetClipboardData.restype = wintypes.HANDLE
    user32.SetClipboardData.argtypes = (wintypes.UINT, wintypes.HANDLE)
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalLock.argtypes = (wintypes.HGLOBAL,)
    kernel32.GlobalUnlock.argtypes = (wintypes.HGLOBAL,)
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalAlloc.argtypes = (wintypes.UINT, ctypes.c_size_t)
    return ctypes, user32, kernel32


def read_clipboard() -> str | None:
    """Texte du presse-papiers, ``""`` s'il n'y en a pas, None hors Windows."""
    if sys.platform != "win32":
        return None
    ctypes, user32, kernel32 = _clipboard_api()
    if not user32.OpenClipboard(None):
        return None
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return ""
        pointer = kernel32.GlobalLock(handle)
        try:
            return ctypes.wstring_at(pointer) if pointer else ""
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def write_clipboard(text: str) -> bool:
    if sys.platform != "win32":
        return False
    ctypes, user32, kernel32 = _clipboard_api()
    data = (text or "").encode("utf-16-le") + b"\x00\x00"
    handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
    if not handle:
        return False
    pointer = kernel32.GlobalLock(handle)
    ctypes.memmove(pointer, data, len(data))
    kernel32.GlobalUnlock(handle)
    if not user32.OpenClipboard(None):
        return False
    try:
        user32.EmptyClipboard()
        return bool(user32.SetClipboardData(CF_UNICODETEXT, handle))
    finally:
        user32.CloseClipboard()


__all__ = ["user_folders", "find_files", "open_file", "is_allowed", "kind_suffixes",
           "read_clipboard", "write_clipboard", "FoundFile", "BLOCKED_SUFFIXES"]
