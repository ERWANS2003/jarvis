"""Horizon 3 - controle du PC (Windows) : volume, musique, ecran.

Aucune dependance : Jarvis simule les touches multimedia du clavier
(`keybd_event`), exactement comme les boutons volume / lecture d'un clavier
ou d'un casque. Elles agissent donc sur l'application qui joue du son
(Spotify, YouTube dans le navigateur, VLC...).

Chaque fonction renvoie ``True`` si l'action a ete envoyee ; hors Windows,
``False`` (l'outil l'annonce au lieu d'echouer).
"""

from __future__ import annotations

import datetime as _dt
import subprocess
import sys
import time
from pathlib import Path

VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF
VK_MEDIA_NEXT = 0xB0
VK_MEDIA_PREV = 0xB1
VK_MEDIA_STOP = 0xB2
VK_MEDIA_PLAY_PAUSE = 0xB3
KEYEVENTF_KEYUP = 0x0002
VOLUME_STEP = 2            # chaque appui sur « volume + » ajoute 2 %

MEDIA_KEYS = {
    "play_pause": VK_MEDIA_PLAY_PAUSE,
    "play": VK_MEDIA_PLAY_PAUSE,
    "pause": VK_MEDIA_PLAY_PAUSE,
    "next": VK_MEDIA_NEXT,
    "previous": VK_MEDIA_PREV,
    "stop": VK_MEDIA_STOP,
}


def supported() -> bool:
    return sys.platform == "win32"


def _default_press(vk: int) -> None:
    import ctypes

    user32 = ctypes.windll.user32
    user32.keybd_event(vk, 0, 0, 0)
    user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)


# Remplacable dans les tests (aucune touche n'est alors envoyee).
press = _default_press


def tap(vk: int, times: int = 1, pause: float = 0.01) -> bool:
    if not supported() and press is _default_press:
        return False
    for _ in range(max(0, int(times))):
        press(vk)
        if pause:
            time.sleep(pause)
    return True


def volume(action: str, percent: int | None = None, step: int = 10) -> bool:
    """`up` / `down` (de `step` %), `mute` (bascule) ou `set` (a `percent` %)."""
    action = (action or "").strip().lower()
    if action == "mute":
        return tap(VK_VOLUME_MUTE)
    if action == "up":
        return tap(VK_VOLUME_UP, max(1, round(step / VOLUME_STEP)))
    if action == "down":
        return tap(VK_VOLUME_DOWN, max(1, round(step / VOLUME_STEP)))
    if action == "set":
        target = min(max(int(percent if percent is not None else 50), 0), 100)
        # Sans API audio : on descend a 0, puis on remonte au niveau voulu.
        if not tap(VK_VOLUME_DOWN, 100 // VOLUME_STEP, pause=0):
            return False
        return tap(VK_VOLUME_UP, round(target / VOLUME_STEP), pause=0)
    raise ValueError(f"action de volume inconnue : {action}")


def media(action: str) -> bool:
    key = MEDIA_KEYS.get((action or "").strip().lower().replace(" ", "_"))
    if key is None:
        raise ValueError(f"action multimedia inconnue : {action}")
    return tap(key)


def lock_screen() -> bool:
    if not supported():
        return False
    import ctypes

    return bool(ctypes.windll.user32.LockWorkStation())


def screenshot_folder() -> Path:
    return Path.home() / "Pictures" / "Jarvis"


def screenshot(folder: Path | None = None) -> Path | None:
    """Capture tout l'ecran principal en PNG ; renvoie le chemin ou None."""
    if not supported():
        return None
    folder = Path(folder or screenshot_folder())
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"capture-{_dt.datetime.now():%Y-%m-%d_%H-%M-%S}.png"
    # .NET via PowerShell : pas besoin de Pillow.
    script = (
        "Add-Type -AssemblyName System.Windows.Forms,System.Drawing;"
        "$b=[System.Windows.Forms.SystemInformation]::VirtualScreen;"
        "$i=New-Object System.Drawing.Bitmap $b.Width,$b.Height;"
        "$g=[System.Drawing.Graphics]::FromImage($i);"
        "$g.CopyFromScreen($b.Left,$b.Top,0,0,$i.Size);"
        f"$i.Save('{target}');"
    )
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", script],
                       check=True, capture_output=True, timeout=15,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:
        return None
    return target if target.is_file() else None


__all__ = ["supported", "volume", "media", "lock_screen", "screenshot",
           "screenshot_folder", "MEDIA_KEYS"]
