"""Horizon 3 - rappels a date fixe, conserves d'un lancement a l'autre.

« Rappelle-moi demain a 9 h d'appeler Paul » : le modele convertit la date
en ``AAAA-MM-JJ HH:MM`` (il connait l'heure grace a `get_current_datetime`),
le rappel est ecrit dans un petit fichier JSON, et un fil le surveille.

Si Jarvis etait ferme a l'heure dite, le rappel est annonce au lancement
suivant (« en retard ») plutot que perdu.
"""

from __future__ import annotations

import datetime as _dt
import json
import threading
from pathlib import Path

from .text import log

CHECK_EVERY = 15.0  # secondes
FORMATS = ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S",
           "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y %H:%M", "%Y-%m-%d")


def parse_when(text: str) -> _dt.datetime:
    """Lit une date du type ``2026-10-29 09:00``. Leve ValueError sinon."""
    text = " ".join((text or "").replace("h", ":").split()).strip()
    if text.endswith(":"):
        text += "00"
    for fmt in FORMATS:
        try:
            when = _dt.datetime.strptime(text, fmt)
        except ValueError:
            continue
        if fmt == "%Y-%m-%d":
            when = when.replace(hour=9)  # date seule : 9 h du matin
        return when
    raise ValueError(f"date illisible : {text}")


class ReminderStore:
    """Rappels persistants (JSON), surs entre fils."""

    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else None
        self._lock = threading.Lock()
        self._items: list[dict] = []
        self._next_id = 1
        self._load()

    def _load(self) -> None:
        if self.path is None or not self.path.is_file():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._items = [item for item in data if isinstance(item, dict)
                           and item.get("when") and item.get("text")]
            self._next_id = max((int(i.get("id", 0)) for i in self._items),
                                default=0) + 1
        except Exception as exc:
            log(f"[rappels] fichier illisible ({exc}) : on repart de zero")
            self._items = []

    def _save(self) -> None:
        if self.path is None:
            return
        try:
            self.path.write_text(json.dumps(self._items, ensure_ascii=False,
                                            indent=2), encoding="utf-8")
        except Exception as exc:
            log(f"[rappels] sauvegarde impossible : {exc}")

    def add(self, when: _dt.datetime, text: str) -> int:
        text = " ".join((text or "").split())
        if not text:
            raise ValueError("rappel vide")
        with self._lock:
            reminder_id = self._next_id
            self._next_id += 1
            self._items.append({"id": reminder_id, "when": when.isoformat(timespec="minutes"),
                                "text": text})
            self._items.sort(key=lambda item: item["when"])
            self._save()
        return reminder_id

    def list(self) -> list[dict]:
        with self._lock:
            return [dict(item) for item in self._items]

    def cancel(self, reminder_id: int | None = None) -> int:
        """Retire un rappel (ou tous si `reminder_id` vaut None)."""
        with self._lock:
            before = len(self._items)
            if reminder_id is None:
                self._items = []
            else:
                self._items = [i for i in self._items if int(i["id"]) != int(reminder_id)]
            removed = before - len(self._items)
            if removed:
                self._save()
        return removed

    def pop_due(self, now: _dt.datetime | None = None) -> list[dict]:
        """Retire et renvoie les rappels arrives a echeance."""
        now = now or _dt.datetime.now()
        with self._lock:
            due = [i for i in self._items
                   if _dt.datetime.fromisoformat(i["when"]) <= now]
            if due:
                self._items = [i for i in self._items if i not in due]
                self._save()
        return due


class ReminderScheduler:
    """Fil qui annonce les rappels a l'heure dite via `announce(item, late)`."""

    def __init__(self, store: ReminderStore, announce, interval: float = CHECK_EVERY):
        self.store = store
        self.announce = announce
        self.interval = interval
        self._stop = threading.Event()
        self._started_at = _dt.datetime.now()

    def check(self, now: _dt.datetime | None = None) -> int:
        now = now or _dt.datetime.now()
        due = self.store.pop_due(now)
        for item in due:
            # Les heures sont enregistrees a la minute pres : marge de 2 min.
            late = _dt.datetime.fromisoformat(item["when"]) < \
                self._started_at - _dt.timedelta(minutes=2)
            try:
                self.announce(item, late)
            except Exception as exc:
                log(f"[rappels] {exc}")
        return len(due)

    def start(self) -> None:
        threading.Thread(target=self._run, name="jarvis-reminders",
                         daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            self.check()
            self._stop.wait(self.interval)


__all__ = ["ReminderStore", "ReminderScheduler", "parse_when"]
