"""Tests du mot d'activation local, du raccourci global et de la voix Piper.

Ni micro, ni modele, ni carte son : tout passe par des doublures.
"""

from __future__ import annotations

import json
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


# --------------------------------------------------------------------------- #
# « Jarvis » tout court (Vosk) -- recogniseur factice
# --------------------------------------------------------------------------- #
class _FakeRecognizer:
    """Chaque tranche annoncee comme fin d'enonce renvoie le resultat suivant."""

    def __init__(self, results):
        self.results = list(results)

    def AcceptWaveform(self, frames):
        return bool(frames) and frames[0] == 1   # octet marqueur = fin d'enonce

    def Result(self):
        return json.dumps({"result": self.results.pop(0)})


def _spoken(results, paused=None):
    holder = {}

    def factory():
        holder["rec"] = _FakeRecognizer(results)
        return holder["rec"]

    return W.SpokenWakeDetector(on_wake=None, recognizer_factory=factory,
                                is_paused=paused), holder


SECOND = b"\x00" * W.BYTES_PER_SECOND
END = b"\x01\x00"


def test_spoken_wake_alone_and_with_question():
    detector, _ = _spoken([
        [{"word": "jarvis", "start": 0.5, "end": 1.0}],
        # Vosk compte le temps depuis le debut du flux : l'enonce commence a 1 s.
        [{"word": "jarvis", "start": 1.2, "end": 1.6},
         {"word": "quelle", "start": 1.8, "end": 2.1},
         {"word": "heure", "start": 2.1, "end": 2.5}],
    ])
    assert detector.feed(SECOND) is None
    assert detector.feed(END) == b""              # « Jarvis » seul
    assert detector.feed(SECOND) is None
    assert detector.feed(SECOND) is None
    question = detector.feed(END)
    # la question commence juste apres le mot (a 1.6 s dans le flux)
    utterance_start = len(SECOND) + len(END)
    utterance = 2 * len(SECOND) + len(END)
    cut = int(1.6 * W.BYTES_PER_SECOND) - utterance_start
    assert len(question) == utterance - (cut - cut % 2)


def test_spoken_wake_ignores_other_words_and_accents():
    detector, _ = _spoken([
        [{"word": "jardin", "start": 0.0, "end": 0.5}],
        [{"word": "Jarvís", "start": 0.0, "end": 0.5}],
    ])
    assert detector.feed(END) is None
    assert detector.feed(END) == b""


def test_spoken_wake_forgets_what_was_heard_while_paused():
    paused = {"value": False}
    detector, holder = _spoken([[{"word": "jarvis", "start": 0, "end": 0.4}]] * 2,
                               paused=lambda: paused["value"])
    detector.feed(SECOND)
    first = holder["rec"]
    paused["value"] = True
    assert detector.feed(END) is None          # Jarvis parle : on n'ecoute pas
    paused["value"] = False
    assert detector.feed(END) == b""
    assert holder["rec"] is not first          # recogniseur remis a zero


def test_find_vosk_model():
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        assert W.find_vosk_model("fr", folder) is None
        (folder / "vosk-model-small-fr-0.22").mkdir()
        assert W.find_vosk_model("fr", folder).name == "vosk-model-small-fr-0.22"
        assert W.find_vosk_model("en", folder) is None


def test_split_voice_and_speaker_lookup():
    assert tts.split_voice("fr_FR-upmc-medium:pierre") == ("fr_FR-upmc-medium", "pierre")
    assert tts.split_voice("fr_FR-siwis-medium") == ("fr_FR-siwis-medium", None)
    assert tts.split_voice("C:\\voix\\fr.onnx") == ("C:\\voix\\fr.onnx", None)
    assert tts.split_voice(None) == (None, None)
    with tempfile.TemporaryDirectory() as tmp:
        model = Path(tmp) / "multi.onnx"
        Path(f"{model}.json").write_text(
            json.dumps({"speaker_id_map": {"jessica": 0, "Pierre": 1}}), encoding="utf-8")
        assert tts.piper_speaker_id(model, "pierre") == 1
        assert tts.piper_speaker_id(model, "3") == 3
        assert tts.piper_speaker_id(model, "inconnu") is None
        assert tts.piper_speaker_id(model, None) is None


def test_mic_level_is_amplified_and_bounded():
    import struct

    assert W.mic_level(b"\x00\x00" * 64) == 0.0
    quiet = W.mic_level(struct.pack("<4h", 1500, -1500, 1500, -1500))
    assert 0.4 < quiet < 0.6
    assert W.mic_level(struct.pack("<4h", 20000, -20000, 20000, -20000)) == 1.0

