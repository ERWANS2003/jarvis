"""Ce que l'utilisateur a devant lui : l'application au premier plan.

« Traduis ça », « c'est quoi cette erreur ? », « résume cette page » : sans
savoir dans quelle application il travaille, Jarvis devine mal. On lui donne
donc le **nom de l'application** (« Visual Studio Code », « Google Chrome »),
jamais le titre de la fenetre, qui peut contenir des informations privees
(objet d'un e-mail, nom d'un document).

Quand on clique sur l'orbe, c'est elle qui passe au premier plan : on prend
alors la derniere fenetre de l'utilisateur (voir `selection.user_window`).
"""

from __future__ import annotations

import sys
from pathlib import Path

# Executable -> nom parle (les autres : nom du fichier, joliment ecrit).
FRIENDLY = {
    "chrome": "Google Chrome", "msedge": "Microsoft Edge", "firefox": "Firefox",
    "brave": "Brave", "opera": "Opera", "code": "Visual Studio Code", "cursor": "Cursor",
    "devenv": "Visual Studio", "pycharm64": "PyCharm", "idea64": "IntelliJ IDEA",
    "winword": "Word", "excel": "Excel", "powerpnt": "PowerPoint", "outlook": "Outlook",
    "onenote": "OneNote", "notepad": "le Bloc-notes", "notepad++": "Notepad++",
    "explorer": "l'Explorateur de fichiers", "windowsterminal": "le Terminal Windows",
    "cmd": "l'Invite de commandes", "powershell": "PowerShell", "pwsh": "PowerShell",
    "whatsapp": "WhatsApp", "telegram": "Telegram", "discord": "Discord", "slack": "Slack",
    "teams": "Microsoft Teams", "ms-teams": "Microsoft Teams", "zoom": "Zoom",
    "spotify": "Spotify", "vlc": "VLC", "acrord32": "Adobe Acrobat", "acrobat": "Adobe Acrobat",
    "sumatrapdf": "SumatraPDF", "photoshop": "Photoshop", "figma": "Figma",
    "obsidian": "Obsidian", "notion": "Notion", "claude": "Claude",
}
_SKIP = {"applicationframehost", "shellexperiencehost", "searchhost", "startmenuexperiencehost",
         "textinputhost", "lockapp"}


def friendly_name(executable: str) -> str | None:
    stem = Path(executable or "").stem.lower()
    if not stem or stem in _SKIP:
        return None
    return FRIENDLY.get(stem, stem.replace("_", " ").replace("-", " ").title())


def _process_path(hwnd) -> str | None:
    import ctypes
    from ctypes import wintypes

    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
    handle = kernel32.OpenProcess(0x1000, False, pid.value)   # QUERY_LIMITED_INFORMATION
    if not handle:
        return None
    try:
        buffer = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buffer))
        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return buffer.value
        return None
    finally:
        kernel32.CloseHandle(handle)


def active_app() -> str | None:
    """Nom de l'application de l'utilisateur au premier plan (None si inconnu)."""
    if sys.platform != "win32":
        return None
    try:
        from .selection import user_window

        hwnd = user_window()
        path = _process_path(hwnd) if hwnd else None
        return friendly_name(path) if path else None
    except Exception:
        return None


LINE = {"fr": "Application ouverte devant l'utilisateur : {app}. Quand il dit « ça », "
              "« cette page », « cette erreur », il parle sans doute de ce qu'il y voit.",
        "en": "Application in front of the user: {app}. When they say 'this', 'this page' "
              "or 'this error', they most likely mean what is shown there."}


def context_line(lang: str = "fr", app: str | None = None) -> str:
    app = app if app is not None else active_app()
    if not app:
        return ""
    return LINE["fr" if lang == "fr" else "en"].format(app=app)


__all__ = ["active_app", "friendly_name", "context_line"]
