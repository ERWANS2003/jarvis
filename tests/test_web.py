"""Tests de l'interface web (Horizon 6).

Un vrai serveur HTTP est lance sur 127.0.0.1, mais sans navigateur, sans micro,
sans moteur vocal ni modele de langage : le tour est remplace par une doublure.
"""

from __future__ import annotations

import json
import queue
import urllib.error
import urllib.request

from jarvis_core import web as W
from jarvis_core.i18n import STRINGS
from jarvis_core.memory import MemoryStore


class _Args:
    ability = "general knowledge"
    max_words = 40
    retries = 1
    history_path = None
    lang = "fr"


class _Chain:
    tools = []
    tools_enabled = False

    def label(self) -> str:
        return "modele-de-test"


class _Speech:
    def __init__(self) -> None:
        self.said: list[str] = []
        self.cancelled = 0

    def begin(self) -> None:
        pass

    def say(self, text: str) -> None:
        self.said.append(text)

    def cancel(self) -> None:
        self.cancelled += 1

    def close(self) -> None:
        pass


def _app(memory=None, greet=False, history_path=None):
    args = _Args()
    args.history_path = history_path
    app = W.JarvisWeb(args, STRINGS["fr"], None, _Speech(), _Chain(), [],
                      memory=memory, greet=greet)

    def fake_turn(text, history, on_sentence, on_tool, on_status):
        on_tool("get_current_datetime")
        on_sentence("Il est midi.")

    app.turn = fake_turn
    return app


def _request(url, path, token=None, body=None, host=None):
    request = urllib.request.Request(url.rstrip("/") + path)
    if token:
        request.add_header("X-Jarvis-Token", token)
    if host:
        request.add_header("Host", host)
    if body is not None:
        request.data = json.dumps(body).encode("utf-8")
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def _events_until(inbox, kind, timeout=5.0):
    seen = []
    while True:
        event = inbox.get(timeout=timeout)
        seen.append(event)
        if event["type"] == kind:
            return seen


def test_page_embeds_token_and_api_requires_it():
    app = _app()
    server, url = W.start_server(app, 18765)
    try:
        status, page = _request(url, "/")
        assert status == 200
        assert app.token in page and "__JARVIS_TOKEN__" not in page

        status, _ = _request(url, "/api/info")
        assert status == 403
        status, _ = _request(url, "/api/info", token="mauvais")
        assert status == 403
        status, body = _request(url, "/api/info", token=app.token)
        assert status == 200
        info = json.loads(body)
        assert info["model"] == "modele-de-test"
        assert info["strings"]["web_new_chat"] == "Nouvelle conversation"
    finally:
        server.shutdown()
        server.server_close()


def test_foreign_host_header_is_rejected():
    # Protection contre le DNS rebinding : seul 127.0.0.1/localhost est servi.
    app = _app()
    server, url = W.start_server(app, 18785)
    try:
        status, _ = _request(url, "/", host="evil.example:80")
        assert status == 403
        status, _ = _request(url, "/api/info", token=app.token,
                             host="evil.example:80")
        assert status == 403
    finally:
        server.shutdown()
        server.server_close()


def test_send_streams_events_and_records_transcript():
    app = _app()
    inbox = app.bus.subscribe()
    assert app.send("quelle heure est-il")
    events = _events_until(inbox, "finished")
    kinds = [event["type"] for event in events]
    assert kinds[0] == "user"
    assert "tool" in kinds and "reply" in kinds
    assert app.speech.said == ["Il est midi."]
    assert app.transcript == [
        {"kind": "user", "text": "quelle heure est-il"},
        {"kind": "jarvis", "text": "Il est midi."},
    ]
    assert app.send("encore")  # le verrou a bien ete relache
    _events_until(inbox, "finished")


def test_send_is_refused_while_a_turn_runs():
    app = _app()
    app._busy.acquire()
    try:
        assert not app.send("bonjour")
    finally:
        app._busy.release()
    assert not app.send("   ")


def test_mute_silences_speech_and_listen_needs_a_microphone():
    app = _app()
    app.set_muted(True)
    assert app.speech.cancelled == 1
    inbox = app.bus.subscribe()
    app.send("bonjour")
    _events_until(inbox, "finished")
    assert app.speech.said == []
    assert app.listen() is False  # aucun micro dans les tests


def test_memory_can_be_listed_and_forgotten():
    store = MemoryStore()
    mem_id = store.remember("je prefere le the vert")
    app = _app(memory=store)
    assert [m["text"] for m in app.memories()] == ["je prefere le the vert"]
    assert app.forget(mem_id)
    assert app.memories() == []


def test_clear_starts_a_new_conversation():
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        app = _app(history_path=str(Path(tmp) / "history.json"))
        inbox = app.bus.subscribe()
        app.send("bonjour")
        _events_until(inbox, "finished")
        assert app.clear()
        assert app.history == [] and app.transcript == []
        assert inbox.get(timeout=2)["type"] == "cleared"


def test_greeting_is_shown_and_spoken():
    app = _app(greet=True)
    assert app.transcript[0]["kind"] == "jarvis"
    assert app.transcript[0]["text"] == STRINGS["fr"]["greeting"]


def test_event_bus_unsubscribe():
    bus = W.EventBus()
    inbox = bus.subscribe()
    bus.unsubscribe(inbox)
    bus.publish("state", state="ready")
    try:
        inbox.get_nowait()
        raise AssertionError("evenement recu apres desabonnement")
    except queue.Empty:
        pass


class _SilentListener:
    def listen(self):
        return (None, None)


def test_listening_without_result_still_answers_out_loud():
    app = W.JarvisWeb(_Args(), STRINGS["fr"], _SilentListener(), _Speech(),
                      _Chain(), [], greet=False)
    inbox = app.bus.subscribe()
    assert app.listen()
    _events_until(inbox, "finished")
    assert app.speech.said == [STRINGS["fr"]["not_heard"]]


def test_status_messages_are_spoken():
    app = _app()

    def failing_turn(text, history, on_sentence, on_tool, on_status):
        on_status(STRINGS["fr"]["llm_error"])

    app.turn = failing_turn
    inbox = app.bus.subscribe()
    app.send("bonjour")
    _events_until(inbox, "finished")
    assert app.speech.said == [STRINGS["fr"]["llm_error"]]


def test_tool_hint_is_shown_but_not_spoken():
    app = _app()

    def turn_with_tool(text, history, on_sentence, on_tool, on_status):
        on_status(STRINGS["fr"]["tool_running"])
        on_sentence("Il est midi.")

    app.turn = turn_with_tool
    inbox = app.bus.subscribe()
    app.send("quelle heure est-il")
    _events_until(inbox, "finished")
    assert app.speech.said == ["Il est midi."]          # « Un instant » non dit
    assert {"kind": "system", "text": STRINGS["fr"]["tool_running"]} in app.transcript

