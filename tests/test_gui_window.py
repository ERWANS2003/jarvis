"""Tests de la fenetre Tkinter elle-meme (Horizon 6).

Contrairement a `test_gui.py` (qui ne verifie que le contrat du module), ces
tests construisent une vraie fenetre -- mais toujours **sans** `mainloop`, et
en la cachant (`withdraw`). Si la machine n'a pas d'affichage, les tests
sortent silencieusement : ils ne doivent jamais faire echouer la suite sur un
serveur ou une session distante.
"""

from __future__ import annotations

import os
import sys
import time

from jarvis_core import gui as G
from jarvis_core.i18n import STRINGS


# --------------------------------------------------------------------------- #
# Doublures : on ne veut ni micro, ni moteur vocal, ni modele de langage.
# --------------------------------------------------------------------------- #
class _Args:
    ability = "general knowledge"
    max_words = 40
    retries = 1
    history_path = None
    model = "modele-de-test"
    lang = "fr"


class _Spec:
    def label(self) -> str:
        return "Modele de test"


class _Chain:
    spec = _Spec()
    tools = []
    tools_enabled = False
    graph = None


class _Speech:
    def __init__(self) -> None:
        self.said: list[str] = []

    def begin(self) -> None:
        pass

    def say(self, text: str) -> None:
        self.said.append(text)

    def cancel(self) -> None:
        pass

    def close(self) -> None:
        pass


class _Listener:
    """Premier appel : une question. Ensuite : silence."""

    def __init__(self) -> None:
        self.calls = 0

    def listen(self):
        self.calls += 1
        if self.calls == 1:
            return ("quelle heure est-il", None)
        return (None, None)


def _open_root():
    """Retourne un `Tk` cache, ou ``None`` si l'affichage est indisponible."""
    if not G.available():
        return None
    import tkinter as tk

    try:
        root = tk.Tk()
    except Exception:
        return None
    root.withdraw()
    return root


def _window(root, listener=None, speech=None, greet=True):
    return G._Window(root, _Args(), STRINGS["fr"], listener,
                     speech or _Speech(), _Chain(), [], None, greet)


def _pump(root, window, seconds=5.0, until=None) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        root.update()
        window._poll()
        if until is not None and until():
            return True
        time.sleep(0.02)
    return False


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #
def test_window_renders_messages_and_resets():
    root = _open_root()
    if root is None:
        return
    try:
        window = _window(root)
        window.start()
        window._add_message("Vous", "bonjour", "user")
        window._set_state("thinking")
        window._set_state("speaking")
        window._append_reply("Bonjour")
        window._append_reply("a vous.")
        window._add_message("", "outil : get_weather", "system")
        window._set_state("ready")
        root.update()

        assert window.state == "ready"
        assert window._stream_text == "Bonjour a vous."
        assert len(window._bubbles) >= 3

        window.on_clear()
        assert window._bubbles == []
        assert window._transcript == []
    finally:
        root.destroy()


def test_voice_turn_runs_to_completion():
    """Le bogue corrige : un tour venu du micro etait avale par le garde-fou."""
    root = _open_root()
    if root is None:
        return
    try:
        speech = _Speech()
        listener = _Listener()
        window = _window(root, listener=listener, speech=speech, greet=False)

        def fake_turn(text, history, on_sentence, on_tool, on_status):
            on_tool("get_current_datetime")
            on_sentence("Il est")
            on_sentence("midi.")

        window.turn = fake_turn
        window.start()

        window.on_listen()
        done = _pump(root, window,
                     until=lambda: not window.busy and window.events.empty())
        assert done, "le tour vocal n'a jamais abouti"
        assert window.state == "ready"
        assert ("user", "quelle heure est-il") in window._transcript
        assert any(kind == "jarvis" and "midi." in text
                   for kind, text in window._transcript)
        assert "Il est" in speech.said
    finally:
        root.destroy()


# --------------------------------------------------------------------------- #
# _make_turn : reponse vide (modeles de raisonnement gratuits)
# --------------------------------------------------------------------------- #
class _TurnChain:
    """Chaine minimaliste pour exercer `_make_turn` sans modele ni reseau."""

    tools = []
    tools_enabled = False

    def __init__(self, graph, next_graph=None):
        self.graph = graph
        self._next = next_graph

    def advance(self) -> bool:
        if self._next is None:
            return False
        self.graph, self._next = self._next, None
        return True


class _ScriptGraph:
    def __init__(self, script):
        self.script = script

    def stream(self, inputs, stream_mode=None):
        for item in self.script:
            yield item


def _empty_script():
    """Un modele de raisonnement : `content` vide, aucun appel d'outil."""
    from langchain_core.messages import AIMessage

    return [("updates", {"model": {"messages": [AIMessage(content="")]}})]


def _spoken_script(text):
    from langchain_core.messages import AIMessageChunk

    return [("messages", (AIMessageChunk(content=text),
                          {"langgraph_node": "model"}))]


def _turn_args(history_path):
    import types

    return types.SimpleNamespace(
        ability="general knowledge", max_words=40, retries=1,
        history_path=history_path, model="modele-de-test", lang="fr",
    )


def test_empty_reply_is_announced_instead_of_silence():
    """Un modele sans `content` ne doit pas rendre Jarvis muet."""
    import tempfile

    fr = STRINGS["fr"]
    with tempfile.TemporaryDirectory() as tmp:
        args = _turn_args(os.path.join(tmp, "history.json"))
        chain = _TurnChain(_ScriptGraph(_empty_script()))
        turn = G._make_turn(args, fr, chain, None)
        spoken, statuses, history = [], [], []
        turn("bonjour", history, on_sentence=spoken.append,
             on_tool=lambda _name: None, on_status=statuses.append)

    assert spoken == [fr["empty_reply"]]
    assert history, "la question doit rester pour le tour suivant"


def test_empty_reply_falls_back_then_answers():
    """Un tour vide declenche le repli, qui lui repond vraiment."""
    import tempfile

    fr = STRINGS["fr"]
    with tempfile.TemporaryDirectory() as tmp:
        args = _turn_args(os.path.join(tmp, "history.json"))
        chain = _TurnChain(_ScriptGraph(_empty_script()),
                           next_graph=_ScriptGraph(_spoken_script("Bonjour.")))
        turn = G._make_turn(args, fr, chain, None)
        spoken, statuses = [], []
        turn("bonjour", [], on_sentence=spoken.append,
             on_tool=lambda _name: None, on_status=statuses.append)

    assert spoken == ["Bonjour."]
    assert fr["empty_reply"] not in spoken
    assert statuses == [fr.get("fallback_used", "")]


def test_mute_suppresses_speech():
    root = _open_root()
    if root is None:
        return
    try:
        speech = _Speech()
        window = _window(root, listener=_Listener(), speech=speech,
                         greet=False)
        window.turn = lambda text, history, on_sentence, on_tool, on_status: (
            on_sentence("bonjour"))
        window.start()

        window.mute_var.set(True)
        window.on_mute()
        assert window.muted is True

        window.on_listen()
        _pump(root, window,
              until=lambda: not window.busy and window.events.empty())
        assert speech.said == [], "muet n'a pas empeche la synthese"
    finally:
        root.destroy()


def test_about_and_export_speak_the_interface_language():
    """A propos et export doivent utiliser les chaines traduites."""
    root = _open_root()
    if root is None:
        return
    import tempfile
    import types

    saved_box, saved_dialog = G.messagebox, G.filedialog
    seen: list[tuple[str, str]] = []
    with tempfile.TemporaryDirectory() as tmp:
        target = os.path.join(tmp, "conversation.txt")
        G.messagebox = types.SimpleNamespace(
            showinfo=lambda title, body: seen.append((title, body)))
        G.filedialog = types.SimpleNamespace(
            asksaveasfilename=lambda **kwargs: target)
        try:
            window = _window(root, greet=False)
            window.start()
            window._add_message("Vous", "bonjour", "user")
            window._transcript.append(("user", "bonjour"))
            window._add_message("Jarvis", "salut", "jarvis")
            window._transcript.append(("jarvis", "salut"))

            window.on_about()
            assert seen, "la fenetre A propos n'a rien affiche"
            assert "modele-de-test" in seen[-1][1]
            assert "aucun" in seen[-1][1]  # aucun outil dans la doublure

            window.on_export()
            with open(target, encoding="utf-8") as handle:
                exported = handle.read()
            assert "bonjour" in exported and "salut" in exported
        finally:
            G.messagebox, G.filedialog = saved_box, saved_dialog
            root.destroy()


def test_export_without_content_warns_instead_of_writing():
    root = _open_root()
    if root is None:
        return
    import types

    saved_box, saved_dialog = G.messagebox, G.filedialog
    seen: list[tuple[str, str]] = []
    opened: list[int] = []
    G.messagebox = types.SimpleNamespace(
        showinfo=lambda title, body: seen.append((title, body)))
    G.filedialog = types.SimpleNamespace(
        asksaveasfilename=lambda **kwargs: opened.append(1) or "")
    try:
        window = _window(root, greet=False)
        window.start()
        window.on_export()
        assert seen, "aucun avertissement pour une conversation vide"
        assert not opened, "le selecteur de fichier ne devait pas s'ouvrir"
    finally:
        G.messagebox, G.filedialog = saved_box, saved_dialog
        root.destroy()


def test_ensure_tcl_points_at_bundled_libraries():
    """Sur une distribution ou Tcl est mal place, on doit le retrouver."""
    base = getattr(sys, "base_prefix", "")
    tcl = os.path.join(base, "tcl", "tcl8.6")
    if not os.path.isfile(os.path.join(tcl, "init.tcl")):
        return  # rien a verifier sur cette machine

    saved = {key: os.environ.pop(key, None)
             for key in ("TCL_LIBRARY", "TK_LIBRARY")}
    try:
        G._ensure_tcl()
        assert os.environ.get("TCL_LIBRARY", "").endswith("tcl8.6")
        assert os.path.isfile(os.path.join(os.environ["TCL_LIBRARY"],
                                           "init.tcl"))
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
