"""Tests de la version de presentation : configuration, refus, verification."""

from __future__ import annotations

import datetime as dt
import tempfile
import time
from pathlib import Path

import jarvis
import verifier_mvp as V
from jarvis_core import config as C
from jarvis_core import pilot

ROOT = Path(__file__).resolve().parent.parent
FILE = ROOT / "jarvis.mvp.yaml"


def test_the_demo_configuration_is_valid_and_separate():
    raw = C.load_config_file(FILE)
    clean, warnings = C.normalise(raw)
    assert warnings == []
    assert clean["mvp"] and clean["orb"] and clean["auto_hide"] == 0
    assert not clean["proactive"] and not clean["vision"] and not clean["plugins"]
    assert clean["memory_path"] != ".jarvis_memory.db"
    assert clean["history_path"] != ".jarvis_history.json"
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert clean["memory_path"] in ignored and clean["history_path"] in ignored


def test_the_command_line_reads_the_demo_configuration():
    args = jarvis.parse_args(["--config", str(FILE)])
    assert args.mvp and args.auto_hide == 0 and not args.proactive and not args.vision
    assert not jarvis.parse_args(["--config", str(FILE), "--auto_hide", "30"]).auto_hide == 0


def test_risky_commands_are_refused_only_in_the_demo():
    calls = []

    class Organizer:
        def __getattr__(self, name):
            def record(*_args, **_kwargs):
                calls.append(name)
                return "fait"
            return record

    class WindowsApi:
        def __getattr__(self, name):
            def record(*_args, **_kwargs):
                calls.append(name)
                return []
            return record

    pilot.MVP_MODE = True
    try:
        for text in ("Range mon bureau", "confirme le rangement", "annule le rangement",
                     "ferme cette fenêtre", "ferme Chrome", "réduis tout",
                     "connecte mon téléphone"):
            answer = pilot.answer(text, "fr", windows_api=WindowsApi(), organizer=Organizer())
            assert "désactivée" in answer, text
        assert calls == []
        assert pilot.answer("quelle heure est-il", "fr") is None     # le reste continue
    finally:
        pilot.MVP_MODE = False
    original = pilot.desktop_answer
    pilot.desktop_answer = lambda *_args: "plan du rangement"
    try:
        assert pilot.answer("Range mon bureau", "fr") == "plan du rangement"
    finally:
        pilot.desktop_answer = original


def test_starting_in_demo_mode_turns_the_guards_on():
    from jarvis_core import context

    try:
        jarvis.main(["--config", str(FILE), "--list_voices"])
        assert pilot.MVP_MODE and not context.ENABLED
    finally:
        pilot.MVP_MODE = False
        context.ENABLED = True


def test_remembering_needs_no_model():
    from jarvis_core import extras
    from jarvis_core.memory import MemoryStore

    with tempfile.TemporaryDirectory() as folder:
        memory = MemoryStore(Path(folder) / "m.db")
        now = dt.datetime(2026, 10, 30, 12, 0)
        answer = extras.answer("Souviens-toi que je préfère le thé", "fr", now, memory=memory)
        assert answer == "C'est noté, je retiens : je préfère le thé."
        assert "je préfère le thé" in extras.answer("Que sais-tu de moi ?", "fr", now, memory=memory)
        # Une demande sans « que » reste au modele, comme une question.
        assert extras.answer("Souviens-toi de la dernière fois", "fr", now, memory=memory) is None
        assert extras.answer("Souviens-toi que je préfère le thé", "fr", now) is None
        memory.close()


def test_the_open_application_is_not_a_fact_about_the_user():
    from jarvis_core import context

    assert "ne la retiens pas" in context.context_line("fr", app="WhatsApp")
    context.ENABLED = False
    try:
        assert context.context_line("fr", app="WhatsApp") == ""
    finally:
        context.ENABLED = True


def test_the_report_measures_the_wait_not_the_speech():
    from langchain_core.messages import AIMessage, AIMessageChunk

    from jarvis_core import gui
    from jarvis_core import growth as G
    from jarvis_core.i18n import STRINGS

    class Graph:
        def stream(self, inputs, stream_mode=None):
            yield ("messages", (AIMessageChunk(content="Une réponse."), {"langgraph_node": "model"}))
            yield ("updates", {"model": {"messages": [AIMessage(content="Une réponse.")]}})

    class Args:
        lang, ability, max_words, retries = "fr", "x", 40, 1
        allow_apps = None
        history_path = str(Path(tempfile.mkdtemp()) / "h.json")
        growth = G.Growth()

    class Chain:
        tools, tools_enabled = [], False
        graph = Graph()

        def advance(self):
            return False

    turn = gui._make_turn(Args, STRINGS["fr"], Chain(), None)
    turn("parle-moi de la tour Eiffel", [], on_sentence=lambda _s: time.sleep(0.3),
         on_tool=lambda n: None, on_status=lambda s: None)
    assert Args.growth.turns[-1]["seconds"] < 0.25


def test_the_check_never_accepts_a_placeholder_key():
    assert not V.has_key({})
    assert not V.has_key({"OPENROUTER_API_KEY": "your_openrouter_key_here"})
    assert V.has_key({"GROQ_API_KEY": "gsk_abc"})
    assert V.has_key({"JARVIS_LOCAL_MODEL": "qwen3:4b"})


def test_the_check_tells_blocking_problems_from_warnings():
    with tempfile.TemporaryDirectory() as folder:
        results = V.checks(env={}, root=Path(folder))
    assert any(blocking and not passed and "cle API" in label for blocking, passed, label in results)
    assert any(not blocking and not passed and "voices/vosk" in label for blocking, passed, label in results)


def test_the_check_survives_no_network():
    def refuse(*_args, **_kwargs):
        raise OSError("hors ligne")

    assert V.has_network(connect=refuse) is False
