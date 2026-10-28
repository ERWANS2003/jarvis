"""Horizon 6 - raccourci clavier global (Windows), sans dependance.

`RegisterHotKey` (API Win32, via ctypes) previent Jarvis meme quand une autre
application est au premier plan. Le raccourci est enregistre dans un fil qui
tient sa propre boucle de messages ; `stop()` la termine proprement.
"""

from __future__ import annotations

import sys
import threading

from .text import log

MODIFIERS = {"alt": 0x0001, "ctrl": 0x0002, "control": 0x0002,
             "shift": 0x0004, "win": 0x0008}
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
NAMED_KEYS = {"space": 0x20, "espace": 0x20, "enter": 0x0D, "entree": 0x0D,
              "tab": 0x09, "pause": 0x13, "insert": 0x2D, "home": 0x24,
              "end": 0x23}


def parse_hotkey(text: str) -> tuple[int, int]:
    """« ctrl+space » -> (modificateurs, code de touche). Leve ValueError."""
    parts = [part.strip().lower() for part in (text or "").split("+") if part.strip()]
    if not parts:
        raise ValueError("raccourci vide")
    modifiers = 0
    for part in parts[:-1]:
        if part not in MODIFIERS:
            raise ValueError(f"modificateur inconnu : {part}")
        modifiers |= MODIFIERS[part]
    key = parts[-1]
    if key in NAMED_KEYS:
        code = NAMED_KEYS[key]
    elif len(key) == 1 and key.isalnum():
        code = ord(key.upper())
    elif key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        code = 0x70 + int(key[1:]) - 1
    else:
        raise ValueError(f"touche inconnue : {key}")
    if not modifiers and not key.startswith("f"):
        raise ValueError("ajoute un modificateur (ctrl, alt, shift ou win)")
    return modifiers, code


class GlobalHotkey:
    """Appelle `callback()` (depuis son propre fil) a chaque appui."""

    def __init__(self, combo: str, callback):
        self.combo = combo
        self.callback = callback
        self.modifiers, self.key = parse_hotkey(combo)
        self._thread: threading.Thread | None = None
        self._thread_id = None
        self.registered = threading.Event()
        self.failed = threading.Event()

    def start(self) -> bool:
        """Enregistre le raccourci. Faux s'il est indisponible (deja pris...)."""
        if sys.platform != "win32":
            log("[raccourci] disponible seulement sous Windows")
            return False
        self._thread = threading.Thread(target=self._run, name="jarvis-hotkey",
                                        daemon=True)
        self._thread.start()
        while not (self.registered.is_set() or self.failed.is_set()):
            self.registered.wait(0.05)
        return self.registered.is_set()

    def stop(self) -> None:
        if self._thread_id is not None:
            import ctypes

            ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)

    def _run(self) -> None:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self._thread_id = kernel32.GetCurrentThreadId()
        if not user32.RegisterHotKey(None, 1, self.modifiers | MOD_NOREPEAT,
                                     self.key):
            log(f"[raccourci] « {self.combo} » est deja utilise par une autre "
                "application")
            self.failed.set()
            return
        self.registered.set()
        log(f"[raccourci] {self.combo} : parler a Jarvis")
        message = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                if message.message == WM_HOTKEY:
                    try:
                        self.callback()
                    except Exception as exc:
                        log(f"[raccourci] {exc}")
        finally:
            user32.UnregisterHotKey(None, 1)


__all__ = ["GlobalHotkey", "parse_hotkey"]
