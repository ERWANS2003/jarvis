"""Tests de la version de presentation : configuration, refus, verification."""

from __future__ import annotations

import tempfile
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
