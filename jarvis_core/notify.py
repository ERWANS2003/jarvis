"""Notifications Windows : rappels, minuteurs et alertes s'affichent aussi a l'ecran.

Utile quand le son est coupe ou qu'on n'etait pas devant le PC. Deux voies,
sans dependance nouvelle :

  * l'icone de Jarvis pres de l'horloge (`pystray`), quand l'orbe tourne ;
  * sinon une notification Windows native, via PowerShell (WinRT).

Le titre et le texte passent par des variables d'environnement, jamais dans
la ligne de commande : aucun risque d'injection.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading

from .text import log

APP_ID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"
_TOAST = (
    "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications,"
    " ContentType = WindowsRuntime] > $null;"
    "$t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
    "[Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
    "$x = $t.GetElementsByTagName('text');"
    "$x.Item(0).AppendChild($t.CreateTextNode($env:JARVIS_TITLE)) > $null;"
    "$x.Item(1).AppendChild($t.CreateTextNode($env:JARVIS_TEXT)) > $null;"
    "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("
    "$env:JARVIS_APP).Show([Windows.UI.Notifications.ToastNotification]::new($t))"
)

_backend = None
enabled = True


def set_backend(backend) -> None:
    """`backend(title, message)` : par exemple l'icone de la zone de notification."""
    global _backend
    _backend = backend


def _toast(title: str, message: str) -> None:
    env = {**os.environ, "JARVIS_TITLE": title, "JARVIS_TEXT": message, "JARVIS_APP": APP_ID}
    try:
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _TOAST],
                       env=env, capture_output=True, timeout=15,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception as exc:
        log(f"[notification] {exc}")


def notify(title: str, message: str) -> bool:
    """Affiche une notification (sans bloquer). False si impossible."""
    message = " ".join((message or "").split())[:250]
    if not enabled or not message:
        return False
    if _backend is not None:
        try:
            _backend(title, message)
            return True
        except Exception as exc:
            log(f"[notification] icone : {exc}")
    if sys.platform != "win32":
        return False
    threading.Thread(target=_toast, args=(title, message), name="jarvis-toast",
                     daemon=True).start()
    return True


__all__ = ["notify", "set_backend"]
