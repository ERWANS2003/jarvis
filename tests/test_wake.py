"""Tests du mot d'activation local, du raccourci global et de la voix Piper.

Ni micro, ni modele, ni carte son : tout passe par des doublures.
"""

from __future__ import annotations

import tempfile
import types
from pathlib import Path

from jarvis_core import hotkey as H
from jarvis_core import tts
from jarvis_core import wake as W


# --------------------------------------------------------------------------- #
# Mot d'activation
# --------------------------------------------------------------------------- #
class _Scorer:
    def __init__(self, scores):
        self.scores = list(scores)
        self.resets = 0

    def predict(self, _frames):
        return {"hey_jarvis": self.scores.pop(0) if self.scores else 0.0}

    def reset(self):
        self.resets += 1


SILENCE = b"\x00\x00" * W.CHUNK


def test_detector_fires_above_threshold_only():
    detector = W.WakeWordDetector(on_wake=None, scorer=_Scorer([0.1, 0.4, 0.9]))
    assert [detector.feed(SILENCE) for _ in range(3)] == [False, False, True]


def test_detector_cooldown_avoids_double_trigger():
    detector = W.WakeWordDetector(on_wake=None, scorer=_Scorer([0.9, 0.9]))
    assert detector.feed(SILENCE) is True
    assert detector.feed(SILENCE) is False  # meme mot, une seule fois


def test_detector_is_deaf_while_paused_or_disabled():
    paused = {"value": True}
    scorer = _Scorer([0.99, 0.99, 0.99])
    detector = W.WakeWordDetector(on_wake=None, scorer=scorer,
                                  is_paused=lambda: paused["value"])
    assert detector.feed(SILENCE) is False
    assert scorer.resets == 1  # l'historique audio est oublie
    paused["value"] = False
    detector.enabled = False
    assert detector.feed(SILENCE) is False
    detector.enabled = True
    assert detector.feed(SILENCE) is True


# --------------------------------------------------------------------------- #
# Raccourci clavier
# --------------------------------------------------------------------------- #
def test_parse_hotkey():
    assert H.parse_hotkey("ctrl+space") == (0x0002, 0x20)
    assert H.parse_hotkey("Ctrl + Alt + J") == (0x0003, ord("J"))
    assert H.parse_hotkey("f9") == (0, 0x78)


def test_parse_hotkey_rejects_bad_input():
    for bad in ("", "space", "ctrl+", "hyper+a", "ctrl+inconnue"):
        try:
            H.parse_hotkey(bad)
        except ValueError:
            continue
        raise AssertionError(f"« {bad} » aurait du etre refuse")


# --------------------------------------------------------------------------- #
# Voix Piper
# --------------------------------------------------------------------------- #
def test_find_piper_voice_prefers_default_then_language():
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        assert tts.find_piper_voice("fr", directory=folder) is None
        (folder / "fr_FR-autre-low.onnx").write_bytes(b"")
        assert tts.find_piper_voice("fr", directory=folder).name == "fr_FR-autre-low.onnx"
        (folder / "fr_FR-siwis-medium.onnx").write_bytes(b"")
        assert tts.find_piper_voice("fr", directory=folder).name == "fr_FR-siwis-medium.onnx"
        assert tts.find_piper_voice("en", directory=folder) is None
        assert tts.find_piper_voice("fr", "fr_FR-autre-low", folder).name == "fr_FR-autre-low.onnx"
        assert tts.find_piper_voice("fr", "absente", folder) is None


class _FakePiperVoice:
    config = types.SimpleNamespace(sample_rate=22050)

    def __init__(self):
        self.texts = []

    def synthesize(self, text, syn_config=None):
        self.texts.append(text)
        yield types.SimpleNamespace(audio_int16_bytes=b"\x01\x00" * 5000)


class _FakeStream:
    def __init__(self, on_write=None):
        self.written = 0
        self.on_write = on_write

    def write(self, data):
        self.written += len(data)
        if self.on_write:
            self.on_write()

    def stop_stream(self):
        pass

    def close(self):
        pass


class _FakeAudio:
    def __init__(self, stream):
        self.stream = stream

    def open(self, **_kwargs):
        return self.stream


def test_piper_engine_plays_every_sentence():
    voice, stream = _FakePiperVoice(), _FakeStream()
    engine = tts.PiperEngine(None, voice=voice, audio=_FakeAudio(stream))
    for text in ("un", "deux"):
        engine.say(text)
        engine.runAndWait()
    assert voice.texts == ["un", "deux"]
    assert stream.written == 2 * 10000


def test_piper_engine_stop_cuts_playback():
    voice = _FakePiperVoice()
    holder = {}
    stream = _FakeStream(on_write=lambda: holder["engine"].stop())
    engine = tts.PiperEngine(None, voice=voice, audio=_FakeAudio(stream))
    holder["engine"] = engine
    engine.say("une longue phrase")
    engine.runAndWait()
    assert stream.written == engine.BLOCK_FRAMES * 2  # un seul bloc joue


def test_engine_factory_prefers_piper_and_falls_back():
    original = tts.PiperEngine
    try:
        tts.PiperEngine = lambda *a, **k: "piper"
        factory = tts.make_engine_factory(None, piper_model=Path("x.onnx"),
                                          backend="auto")
        assert factory() == "piper"

        def broken(*_a, **_k):
            raise RuntimeError("pas de carte son")

        tts.PiperEngine = broken
        original_sapi = tts.SapiEngine
        tts.SapiEngine = lambda **k: "sapi"
        try:
            factory = tts.make_engine_factory(None, piper_model=Path("x.onnx"),
                                              backend="piper")
            if tts.sapi_available():
                assert factory() == "sapi"
        finally:
            tts.SapiEngine = original_sapi
    finally:
        tts.PiperEngine = original
