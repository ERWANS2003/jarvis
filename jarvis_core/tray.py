"""Horizon 6 - icone dans la zone de notification (a cote de l'horloge).

Permet de masquer l'orbe sans quitter Jarvis : le mot d'activation et le
raccourci restent actifs, et l'orbe reapparait des qu'on l'appelle. Un clic
sur l'icone la reaffiche ; son menu propose aussi de quitter.

`pystray` tourne dans son propre fil : les actions sont deposees dans la file
de l'orbe (`actions`), consommee par le fil de Tkinter.
"""

from __future__ import annotations

from .text import log


def available() -> bool:
    try:
        import pystray  # noqa: F401
    except Exception:
        return False
    return True


class Tray:
    def __init__(self, actions, image, labels: dict):
        self.actions = actions
        self.image = image
        self.labels = labels
        self.icon = None

    def start(self) -> bool:
        try:
            import pystray

            menu = pystray.Menu(
                pystray.MenuItem(self.labels["show"], lambda: self.actions.put("show"),
                                 default=True),
                pystray.MenuItem(self.labels["quit"], lambda: self.actions.put("quit")),
            )
            self.icon = pystray.Icon("jarvis", self.image, "Jarvis", menu)
            self.icon.run_detached()
            return True
        except Exception as exc:
            log(f"[icone] indisponible : {exc}")
            self.icon = None
            return False

    def notify(self, title: str, message: str) -> None:
        """Bulle de notification Windows au nom de Jarvis."""
        if self.icon is None:
            raise RuntimeError("icone arretee")
        self.icon.notify(message, title)

    def stop(self) -> None:
        if self.icon is not None:
            try:
                self.icon.stop()
            except Exception:
                pass


__all__ = ["Tray", "available"]
