"""Plugin d'exemple : informations systeme.

Copiez ce fichier comme modele pour ecrire vos propres plugins. Il suffit
d'exposer ``build_tools(ctx)`` ; Jarvis decouvre le fichier automatiquement.

Les notions utiles :
  * ``ctx.lang``    : langue courante ('en' ou 'fr')
  * ``ctx.strings`` : textes traduits (voir jarvis_core/i18n.py)
  * ``ctx.memory``  : magasin de memoire longue duree (ou None)
  * ``ctx.speak``   : fonction pour parler spontanement (minuteurs...)
"""

from __future__ import annotations

import os
import platform
import shutil

from langchain_core.tools import tool


def build_tools(ctx):
    fr = getattr(ctx, "lang", "en") == "fr"

    @tool
    def get_system_info() -> str:
        """Report basic information about the computer Jarvis runs on."""
        try:
            bits = platform.machine()
            cpu = platform.processor() or "CPU"
            count = os.cpu_count() or 0
            system = f"{platform.system()} {platform.release()} ({bits})"
        except Exception:
            return "Information indisponible." if fr else "Information unavailable."
        if fr:
            return f"{system}, {count} coeurs, {cpu}."
        return f"{system}, {count} cores, {cpu}."

    @tool
    def get_disk_usage(path: str = ".") -> str:
        """Report free and total disk space for a path."""
        try:
            usage = shutil.disk_usage(path or ".")
        except Exception:
            return "Chemin introuvable." if fr else "Path not found."
        free = usage.free / (1024 ** 3)
        total = usage.total / (1024 ** 3)
        if fr:
            return f"{free:.1f} Go libres sur {total:.1f} Go."
        return f"{free:.1f} GB free out of {total:.1f} GB."

    return [get_system_info, get_disk_usage]
