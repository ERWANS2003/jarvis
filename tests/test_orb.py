"""Tests de l'orbe flottante (Horizon 6).

Le dessin et la position sont testes sans affichage. Les tests qui ont besoin
d'une vraie fenetre sortent silencieusement si l'affichage est indisponible,
comme ceux de `test_gui_window.py`.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from jarvis_core import orb as O
from jarvis_core.i18n import STRINGS
from jarvis_core.web import JarvisWeb


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
        self.cancelled = 0

    def begin(self) -> None:
        pass

    def say(self, text: str) -> None:
        pass

    def cancel(self) -> None:
        self.cancelled += 1

    def close(self) -> None:
        pass


def _app(listener=None):
    return JarvisWeb(_Args(), STRINGS["fr"], listener, _Speech(), _Chain(), [],
                     greet=False)


def _orb(app):
    if O.tk is None:
        return None, None
    try:
        root = O.tk.Tk()
    except Exception:
        return None, None
    root.withdraw()
    return root, O.Orb(root, app, STRINGS["fr"])


def test_mix_interpolates_colors():
    assert O._mix("#000000", "#ffffff", 0) == "#000000"
    assert O._mix("#000000", "#ffffff", 1) == "#ffffff"
    assert O._mix("#000000", "#ffffff", 0.5) == "#808080"


def test_sphere_rings_shrink_and_follow_the_state_palette():
    rings = O.sphere_rings("listening", 40, 56, 56)
    assert len(rings) == O.RINGS
    widths = [x2 - x1 for x1, _y1, x2, _y2, _c in rings]
    assert widths == sorted(widths, reverse=True)
    assert rings[0][4] == O.PALETTE["listening"][0]   # bord sombre
    assert rings[-1][4] == O.PALETTE["listening"][2]  # reflet clair
    # Un etat inconnu retombe sur la palette « pret ».
    assert O.sphere_rings("???", 40, 56, 56)[0][4] == O.PALETTE["ready"][0]


def test_position_is_saved_and_reloaded():
    original = O.POSITION_FILE
    with tempfile.TemporaryDirectory() as tmp:
        O.POSITION_FILE = Path(tmp) / "orb.json"
        try:
            assert O.load_position() is None
            O.save_position(120, 340)
            assert O.load_position() == (120, 340)
            O.POSITION_FILE.write_text("pas du json", encoding="utf-8")
            assert O.load_position() is None
        finally:
            O.POSITION_FILE = original


def test_orb_strings_exist_in_both_languages():
    for lang in ("en", "fr"):
        for key in ("orb_speak", "orb_type", "orb_stop", "orb_mute", "orb_quit",
                    "orb_listening", "orb_hint"):
            assert STRINGS[lang][key]


def test_orb_follows_session_events():
    app = _app()
    root, orb = _orb(app)
    if orb is None:
        return
    try:
        orb.handle({"type": "state", "state": "thinking"})
        assert orb.state == "thinking"
        orb.handle({"type": "user", "text": "quelle heure est-il"})
        orb.handle({"type": "reply", "text": "Il est midi."})
        orb.handle({"type": "reply", "text": "Bonne journee."})
        assert orb._bubble_text.cget("text") == "Il est midi. Bonne journee."
        orb.handle({"type": "finished"})
        assert orb.state == "ready"
        orb.draw()  # le dessin ne doit pas lever d'erreur
        orb.handle({"type": "closed"})
        assert orb.closing
    finally:
        try:
            root.destroy()
        except Exception:
            pass


def test_click_stops_voice_while_busy_and_opens_prompt_without_mic():
    app = _app(listener=None)
    root, orb = _orb(app)
    if orb is None:
        return
    try:
        orb.state = "speaking"
        orb.on_click()
        assert app.speech.cancelled == 1
        orb.state = "ready"
        orb.on_click()          # pas de micro : on propose d'ecrire
        assert orb._prompt is not None
    finally:
        orb.close()


def test_wake_and_hotkey_trigger_listening_or_stop():
    class _Listener:
        def listen(self):
            return (None, None)

    app = _app(listener=_Listener())
    root, orb = _orb(app)
    if orb is None:
        return
    try:
        calls = []
        app.listen = lambda: calls.append("listen") or True
        orb.trigger("wake")
        assert calls == ["listen"]
        orb.state = "speaking"
        orb.trigger("wake")          # pendant une reponse : ignore
        assert calls == ["listen"] and app.speech.cancelled == 0
        orb.trigger("hotkey")        # le raccourci coupe la voix
        assert app.speech.cancelled == 1
        assert orb.is_listening_paused()
    finally:
        orb.close()


def test_double_click_shows_history_without_listening():
    app = _app()
    app.transcript[:] = [{"kind": "user", "text": "quelle heure est-il"},
                         {"kind": "jarvis", "text": "Il est midi."}]
    root, orb = _orb(app)
    if orb is None:
        return
    try:
        clicks = []
        orb.on_click = lambda: clicks.append(1)
        orb._on_release(None)           # 1er clic : en attente
        orb._on_double(None)            # double-clic : annule le clic simple
        orb._on_release(None)
        root.update()
        assert orb._history is not None and clicks == []
        orb.toggle_history()
        assert orb._history is None
    finally:
        orb.close()

