"""Texte de la fenetre active : lire la selection, ecrire a la place de l'utilisateur.

  * « Jarvis, lis ça » : le texte selectionne est copie (Ctrl+C) puis lu ;
  * « Jarvis, écris : je serai en retard » / « rédige un mail... et colle-le » :
    le texte est colle (Ctrl+V) dans la fenetre ou l'utilisateur travaillait.

Quand on clique sur l'orbe, c'est elle qui devient la fenetre active : on
retrouve donc la derniere fenetre de l'utilisateur dans l'ordre d'empilement
(la premiere fenetre visible, titree, qui n'est pas a Jarvis) et on lui rend
la main avant d'envoyer les touches.
"""

from __future__ import annotations

import os
import sys
import time

from . import files

VK_CONTROL = 0x11
VK_C = 0x43
VK_V = 0x56
KEYEVENTF_KEYUP = 0x0002
GW_HWNDNEXT = 2
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
MAX_READ = 4000            # caracteres lus a voix haute au maximum


def supported() -> bool:
    return sys.platform == "win32"


def _user32():
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetTopWindow.restype = wintypes.HWND
    user32.GetTopWindow.argtypes = (wintypes.HWND,)
    user32.GetWindow.restype = wintypes.HWND
    user32.GetWindow.argtypes = (wintypes.HWND, wintypes.UINT)
    user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    user32.IsWindowVisible.argtypes = (wintypes.HWND,)
    user32.GetWindowTextLengthW.argtypes = (wintypes.HWND,)
    user32.GetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int)
    user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
    return ctypes, wintypes, user32


def user_window():
    """Derniere fenetre de l'utilisateur (hors Jarvis), ou None."""
    if not supported():
        return None
    ctypes, wintypes, user32 = _user32()
    mine = os.getpid()
    hwnd = user32.GetTopWindow(None)
    while hwnd:
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if (pid.value != mine and user32.IsWindowVisible(hwnd)
                and user32.GetWindowTextLengthW(hwnd) > 0
                and not user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOOLWINDOW):
            return hwnd
        hwnd = user32.GetWindow(hwnd, GW_HWNDNEXT)
    return None


def _focus_user_window() -> bool:
    _ctypes, _wintypes, user32 = _user32()
    target = user_window()
    if not target:
        return False
    if user32.GetForegroundWindow() != target:
        user32.SetForegroundWindow(target)
        time.sleep(0.15)
    return True


def _chord(vk: int) -> None:
    _ctypes, _wintypes, user32 = _user32()
    user32.keybd_event(VK_CONTROL, 0, 0, 0)
    user32.keybd_event(vk, 0, 0, 0)
    user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)


def copy_selection(wait: float = 0.35) -> str:
    """Texte selectionne dans la fenetre de l'utilisateur ("" si rien).

    Le presse-papiers d'origine est restaure quand la copie n'a rien donne.
    """
    if not supported() or not _focus_user_window():
        return ""
    before = files.read_clipboard() or ""
    marker = f"⁣jarvis-{time.monotonic()}"
    files.write_clipboard(marker)
    _chord(VK_C)
    deadline = time.monotonic() + wait
    text = marker
    while time.monotonic() < deadline:
        time.sleep(0.05)
        text = files.read_clipboard() or ""
        if text != marker:
            break
    if text == marker or not text.strip():
        files.write_clipboard(before)
        return ""
    return text


def selection_or_clipboard() -> tuple[str, str]:
    """(texte, origine) : la selection, sinon le presse-papiers ("selection"/"clipboard")."""
    text = copy_selection()
    if text.strip():
        return text, "selection"
    return (files.read_clipboard() or ""), "clipboard"


def paste_text(text: str) -> bool:
    """Colle `text` dans la fenetre de l'utilisateur (le texte reste copie)."""
    text = (text or "").strip()
    if not text or not supported() or not files.write_clipboard(text):
        return False
    if not _focus_user_window():
        return False
    _chord(VK_V)
    return True


def for_speech(text: str, lang: str = "fr") -> str:
    """Texte a lire : espaces normalises, coupe proprement apres MAX_READ caracteres."""
    text = " ".join((text or "").split())
    if len(text) <= MAX_READ:
        return text
    cut = text[:MAX_READ].rsplit(" ", 1)[0]
    return cut + (" ... Le texte est trop long, je m'arrête là." if lang == "fr"
                  else " ... The text is too long, I will stop here.")


__all__ = ["copy_selection", "selection_or_clipboard", "paste_text", "user_window",
           "for_speech", "supported"]
