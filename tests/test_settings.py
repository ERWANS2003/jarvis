"""Tests de la vision, des reglages de l'orbe et du changement de voix.

Aucun ecran n'est capture et aucun modele n'est appele : doublures partout.
"""

from __future__ import annotations

import json
import tempfile
import types
from pathlib import Path

from jarvis_core import orb as O
from jarvis_core import tools as T
from jarvis_core import tts, vision
from jarvis_core.i18n import STRINGS
from jarvis_core.providers import ProviderSpec
from jarvis_core.web import JarvisWeb


# --------------------------------------------------------------------------- #
# Vision
# --------------------------------------------------------------------------- #
class _FakeLLM:
    def __init__(self):
        self.messages = None

    def invoke(self, messages):
        self.messages = messages
        return types.SimpleNamespace(content="Une fenetre d'erreur numpy.")


def _image():
    from PIL import Image

    return Image.new("RGB", (3200, 1800), (200, 30, 30))


def test_vision_sends_a_reduced_jpeg_with_the_question():
    try:
        import PIL  # noqa: F401
    except Exception:
        return
    llm = _FakeLLM()
    seer = vision.Vision(ProviderSpec(name="c", model="m"), "fr", llm=llm, capture=_image)
    assert seer("Que vois-tu ?") == "Une fenetre d'erreur numpy."
    content = llm.messages[0].content
    assert "Que vois-tu ?" in content[0]["text"]
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    from PIL import Image
    import base64
    import io

    data = base64.b64decode(content[1]["image_url"]["url"].split(",", 1)[1])
    assert max(Image.open(io.BytesIO(data)).size) == vision.MAX_SIDE


def test_make_vision_only_where_a_vision_model_is_known():
    openrouter = ProviderSpec(name="c", model="x", base_url="https://openrouter.ai/api/v1",
                              api_key="k")
    other = ProviderSpec(name="c", model="x", base_url="https://exemple.org/v1", api_key="k")
    try:
        import PIL  # noqa: F401
    except Exception:
        return
    assert vision.make_vision(openrouter).spec.model == vision.VISION_MODEL_DEFAULT
    assert vision.make_vision(other) is None
    assert vision.make_vision(other, "mon-modele-vision").spec.model == "mon-modele-vision"


def test_look_at_screen_tool_is_optional_and_reports_errors():
    names = [t.name for t in T.build_tools(T.ToolContext())]
    assert "look_at_screen" not in names

    def broken(_question):
        raise TimeoutError

    ctx = T.ToolContext(lang="fr", strings=STRINGS["fr"], vision=lambda q: f"vu : {q}")
    tool = {t.name: t for t in T.build_tools(ctx)}["look_at_screen"]
    assert tool.invoke({"question": "l'erreur"}) == "vu : l'erreur"
    ctx = T.ToolContext(lang="fr", strings=STRINGS["fr"], vision=broken)
    tool = {t.name: t for t in T.build_tools(ctx)}["look_at_screen"]
    assert tool.invoke({}).startswith(STRINGS["fr"]["vision_error"])


# --------------------------------------------------------------------------- #
# Reglages et voix
# --------------------------------------------------------------------------- #
class _SettingsFile:
    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original = O.POSITION_FILE
        O.POSITION_FILE = Path(self.tmp.name) / "orb.json"
        return O.POSITION_FILE

    def __exit__(self, *exc):
        O.POSITION_FILE = self.original
        self.tmp.cleanup()


def test_settings_merge_and_apply_to_args():
    with _SettingsFile() as path:
        O.save_position(10, 20)
        O.save_settings(voice="fr_FR-upmc-medium:jessica", theme="siri", follow_up=False)
        assert O.load_position() == (10, 20)            # la position est gardee
        args = types.SimpleNamespace(tts="auto", piper_voice=None, orb_theme="jarvis",
                                     follow_up=True)
        O.apply_saved_settings(args)
        assert (args.piper_voice, args.orb_theme, args.follow_up) == \
            ("fr_FR-upmc-medium:jessica", "siri", False)
        O.save_settings(voice="sapi")
        O.apply_saved_settings(args)
        assert args.tts == "sapi"
        assert json.loads(path.read_text(encoding="utf-8"))["x"] == 10


def test_installed_voices_detail_small_multi_speaker_models():
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        for name, speakers in (("fr_FR-upmc-medium", {"jessica": 0, "pierre": 1}),
                               ("fr_FR-tom-medium", {}),
                               ("fr_FR-mls-medium", {str(i): i for i in range(50)}),
                               ("en_US-lessac-medium", {})):
            (folder / f"{name}.onnx").write_bytes(b"")
            (folder / f"{name}.onnx.json").write_text(
                json.dumps({"speaker_id_map": speakers}), encoding="utf-8")
        voices = tts.installed_voices("fr", folder)
        specs = [spec for _label, spec in voices]
        assert specs == ["fr_FR-mls-medium", "fr_FR-tom-medium",
                         "fr_FR-upmc-medium:jessica", "fr_FR-upmc-medium:pierre"]


def test_speech_can_switch_voice_on_the_fly():
    class _Engine:
        def __init__(self, name):
            self.name, self.spoken = name, []

        def say(self, text):
            self.spoken.append(text)

        def runAndWait(self):
            pass

        def stop(self):
            pass

    first, second = _Engine("a"), _Engine("b")
    speech = tts.Speech(lambda: first, source=None, bargein=False, watchdog_seconds=0)
    speech.set_factory(lambda: second)
    speech.begin()
    speech.say("bonjour")
    assert second.spoken == ["bonjour"] and first.spoken == []
    speech.close()


# --------------------------------------------------------------------------- #
# Menu de l'orbe
# --------------------------------------------------------------------------- #
class _Args:
    ability, max_words, retries, history_path, lang = "x", 40, 1, None, "fr"
    volume, rate, voice, tts = 1.0, 200, None, "auto"


class _Chain:
    tools, tools_enabled = [], False

    def label(self):
        return "test"


class _Speech:
    def __init__(self):
        self.factories = []

    def begin(self):
        pass

    def say(self, _text):
        pass

    def cancel(self):
        pass

    def close(self):
        pass

    def set_factory(self, factory):
        self.factories.append(factory)


def test_orb_settings_menu_theme_switch_and_hide():
    if O.tk is None:
        return
    try:
        root = O.tk.Tk()
    except Exception:
        return
    root.withdraw()
    app = JarvisWeb(_Args(), STRINGS["fr"], None, _Speech(), _Chain(), [], greet=False)
    orb = O.Orb(root, app, STRINGS["fr"])
    try:
        with _SettingsFile():
            orb.tray = object()            # icone presente : « Masquer » propose
            orb.build_settings(_Args(), None)
            labels = [orb.settings_menu.entrycget(i, "label")
                      for i in range(orb.settings_menu.index("end") + 1)
                      if orb.settings_menu.type(i) != "separator"]
            assert STRINGS["fr"]["orb_theme"] in labels
            assert STRINGS["fr"]["orb_hide"] in labels
            orb.set_theme("siri")
            assert orb.theme == "siri" and O.load_settings()["theme"] == "siri"
            assert str(orb.menu.cget("bg")) == O.THEME_COLORS["siri"]["bg"]
            orb.hide()
            assert orb.hidden
            orb.trigger("show")
            assert not orb.hidden
    finally:
        orb.close()
