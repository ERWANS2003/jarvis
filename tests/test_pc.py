"""Tests du controle du PC, des rappels et de la relance sans doublon.

Aucune touche n'est envoyee : `pc.press` est remplace par un enregistreur.
"""

from __future__ import annotations

import datetime as dt
import json
import tempfile
from pathlib import Path

from langchain_core.messages import AIMessageChunk, HumanMessage

from jarvis_core import graph as G
from jarvis_core import pc
from jarvis_core import tools as T
from jarvis_core.i18n import STRINGS
from jarvis_core.reminders import ReminderScheduler, ReminderStore, parse_when


class _Keys:
    """Remplace `pc.press` le temps d'un test."""

    def __enter__(self):
        self.pressed: list[int] = []
        self._original = pc.press
        pc.press = self.pressed.append
        return self

    def __exit__(self, *exc):
        pc.press = self._original


# --------------------------------------------------------------------------- #
# Controle du PC
# --------------------------------------------------------------------------- #
def test_volume_up_down_and_mute():
    with _Keys() as keys:
        assert pc.volume("up", step=10)
        assert keys.pressed == [pc.VK_VOLUME_UP] * 5   # 5 x 2 %
        keys.pressed.clear()
        assert pc.volume("down", step=4)
        assert keys.pressed == [pc.VK_VOLUME_DOWN] * 2
        keys.pressed.clear()
        assert pc.volume("mute")
        assert keys.pressed == [pc.VK_VOLUME_MUTE]


def test_volume_set_goes_to_zero_then_up():
    with _Keys() as keys:
        assert pc.volume("set", 30)
        assert keys.pressed.count(pc.VK_VOLUME_DOWN) == 50
        assert keys.pressed.count(pc.VK_VOLUME_UP) == 15
        assert keys.pressed[-1] == pc.VK_VOLUME_UP


def test_media_keys_and_unknown_actions():
    with _Keys() as keys:
        assert pc.media("next")
        assert pc.media("play pause")
        assert keys.pressed == [pc.VK_MEDIA_NEXT, pc.VK_MEDIA_PLAY_PAUSE]
    for call in (lambda: pc.media("rewind"), lambda: pc.volume("louder")):
        try:
            call()
        except ValueError:
            continue
        raise AssertionError("action inconnue acceptee")


def test_pc_tools_are_exposed_and_answer_in_french():
    ctx = T.ToolContext(lang="fr", strings=STRINGS["fr"])
    tools = {t.name: t for t in T.build_tools(ctx)}
    for name in ("control_volume", "control_media", "lock_screen",
                 "take_screenshot"):
        assert name in tools
    with _Keys():
        answer = tools["control_volume"].invoke({"action": "set", "percent": 40})
        assert answer == "Volume réglé à 40 %."
        assert tools["control_media"].invoke({"action": "next"}) == "C'est fait."
        assert tools["control_media"].invoke({"action": "rewind"}) == "Action inconnue."


# --------------------------------------------------------------------------- #
# Rappels
# --------------------------------------------------------------------------- #
def test_parse_when_accepts_common_formats():
    assert parse_when("2026-10-29 09:30") == dt.datetime(2026, 10, 29, 9, 30)
    assert parse_when("2026-10-29T18:05") == dt.datetime(2026, 10, 29, 18, 5)
    assert parse_when("29/10/2026 14h") == dt.datetime(2026, 10, 29, 14, 0)
    assert parse_when("2026-10-29") == dt.datetime(2026, 10, 29, 9, 0)
    try:
        parse_when("demain")
    except ValueError:
        pass
    else:
        raise AssertionError("date floue acceptee")


def test_reminders_survive_a_restart_and_fire_once():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "reminders.json"
        store = ReminderStore(path)
        soon = dt.datetime(2026, 10, 29, 9, 0)
        store.add(soon, "appeler Paul")
        store.add(soon + dt.timedelta(days=1), "rendre le projet")
        reloaded = ReminderStore(path)
        assert [r["text"] for r in reloaded.list()] == ["appeler Paul", "rendre le projet"]
        due = reloaded.pop_due(soon)
        assert [r["text"] for r in due] == ["appeler Paul"]
        assert reloaded.pop_due(soon) == []
        assert len(json.loads(path.read_text(encoding="utf-8"))) == 1


def test_scheduler_marks_reminders_missed_while_closed_as_late():
    store = ReminderStore()
    now = dt.datetime.now()
    store.add(now - dt.timedelta(hours=2), "en retard")
    store.add(now - dt.timedelta(seconds=1), "a l'heure")
    heard = []
    scheduler = ReminderScheduler(store, lambda item, late: heard.append((item["text"], late)))
    assert scheduler.check(now) == 2
    assert sorted(heard) == [("a l'heure", False), ("en retard", True)]


def test_reminder_tools_roundtrip():
    store = ReminderStore()
    ctx = T.ToolContext(lang="fr", strings=STRINGS["fr"], reminders=store)
    tools = {t.name: t for t in T.build_tools(ctx)}
    answer = tools["set_reminder"].invoke({"when": "2030-01-02 08:15",
                                           "text": "sortir le chien"})
    assert answer == "Rappel 1 enregistré pour le 02/01/2030 08:15."
    assert "sortir le chien" in tools["list_reminders"].invoke({})
    assert tools["set_reminder"].invoke({"when": "bientot", "text": "x"}) == \
        STRINGS["fr"]["reminder_bad_date"]
    assert tools["cancel_reminder"].invoke({"reminder_id": 1}) == "1 rappel(s) annulé(s)."
    assert tools["list_reminders"].invoke({}) == STRINGS["fr"]["no_reminders"]


# --------------------------------------------------------------------------- #
# Relance sans doublon
# --------------------------------------------------------------------------- #
class _GraphFailingAfterTool:
    """Demande un outil, puis la connexion tombe avant la reponse."""

    def __init__(self):
        self.calls = 0

    def stream(self, _inputs, stream_mode=None):
        self.calls += 1
        chunk = AIMessageChunk(content="", tool_call_chunks=[
            {"name": "set_timer", "args": "{}", "id": "c1", "index": 0}])
        yield "messages", (chunk, {"langgraph_node": "model"})
        raise ConnectionError("reseau coupe")


def test_retry_does_not_replay_a_tool():
    graph = _GraphFailingAfterTool()
    result = G.stream_reply(graph, [HumanMessage(content="minuteur 5 min")],
                            on_sentence=lambda _s: None, retries=3)
    assert not result.ok
    assert graph.calls == 1          # pas de second minuteur
    assert result.tools_used == ["set_timer"]
