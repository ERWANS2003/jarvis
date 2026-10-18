"""Tests de la synthese vocale (Horizons 1 et 4)."""

from __future__ import annotations

import types

from jarvis_core import tts


class FakeVoice:
    def __init__(self, voice_id, name, languages=()):
        self.id = voice_id
        self.name = name
        self.languages = list(languages)


class FakeEngine:
    def __init__(self, voices=()):
        self.props = {"voices": list(voices)}
        self.spoken = []
        self.stopped = 0

    def getProperty(self, name):
        return self.props.get(name)

    def setProperty(self, name, value):
        self.props[name] = value

    def say(self, text):
        self.spoken.append(text)

    def runAndWait(self):
        pass

    def stop(self):
        self.stopped += 1


EN_VOICES = [
    FakeVoice("TTS_MS_EN-US_DAVID_11.0", "Microsoft David Desktop - English (United States)"),
    FakeVoice("TTS_MS_FR-FR_HORTENSE_11.0", "Microsoft Hortense Desktop - French (France)"),
]


# --------------------------------------------------------------------------- #
# pick_voice
# --------------------------------------------------------------------------- #
def test_pick_voice_english():
    engine = FakeEngine(EN_VOICES)
    assert tts.pick_voice(engine, "en") == "TTS_MS_EN-US_DAVID_11.0"


def test_pick_voice_french():
    engine = FakeEngine(EN_VOICES)
    assert tts.pick_voice(engine, "fr") == "TTS_MS_FR-FR_HORTENSE_11.0"


def test_pick_voice_no_voices():
    assert tts.pick_voice(FakeEngine([]), "en") is None


def test_pick_voice_custom_hints():
    engine = FakeEngine(EN_VOICES)
    assert tts.pick_voice(engine, "xx", hints=["hortense"]) == \
        "TTS_MS_FR-FR_HORTENSE_11.0"


def test_pick_voice_falls_back_to_first():
    voices = [FakeVoice("voice-a", "Alpha"), FakeVoice("voice-b", "Beta")]
    assert tts.pick_voice(FakeEngine(voices), "de") == "voice-a"


# --------------------------------------------------------------------------- #
# make_engine_factory
# --------------------------------------------------------------------------- #
def test_engine_factory_clamps_settings():
    captured = {}

    class FakePyttsx3:
        @staticmethod
        def init():
            engine = FakeEngine()
            captured["engine"] = engine
            return engine

    import sys

    fake_module = types.ModuleType("pyttsx3")
    fake_module.init = FakePyttsx3.init
    original = sys.modules.get("pyttsx3")
    sys.modules["pyttsx3"] = fake_module
    try:
        factory = tts.make_engine_factory("voice-x", volume=5.0, rate=9999)
        factory()
    finally:
        if original is None:
            sys.modules.pop("pyttsx3", None)
        else:
            sys.modules["pyttsx3"] = original

    engine = captured["engine"]
    assert engine.props["volume"] == 1.0
    assert engine.props["rate"] == 500
    assert engine.props["voice"] == "voice-x"


# --------------------------------------------------------------------------- #
# SilentSpeech
# --------------------------------------------------------------------------- #
def test_silent_speech_says_nothing_after_cancel():
    speech = tts.SilentSpeech()
    speech.begin()
    speech.say("bonjour")
    speech.cancel()
    speech.say("ignored")
    assert speech.interrupted.is_set()


# --------------------------------------------------------------------------- #
# Speech
# --------------------------------------------------------------------------- #
def test_speech_says_cleaned_text():
    engine = FakeEngine()
    speech = tts.Speech(lambda: engine, source=None, bargein=False,
                        watchdog_seconds=0)
    speech.begin()
    speech.say("  **Salut**  ")
    assert engine.spoken == ["Salut"]


def test_speech_skips_empty_text():
    engine = FakeEngine()
    speech = tts.Speech(lambda: engine, source=None, bargein=False,
                        watchdog_seconds=0)
    speech.say("   ")
    assert engine.spoken == []


def test_speech_cancel_stops_and_mutes_following_sentences():
    engine = FakeEngine()
    speech = tts.Speech(lambda: engine, source=None, bargein=False,
                        watchdog_seconds=0)
    speech.begin()
    speech.cancel()
    speech.say("should not be spoken")
    assert engine.stopped == 1
    assert engine.spoken == []


def test_speech_reinitialises_after_cancel():
    engines = []

    def factory():
        engine = FakeEngine()
        engines.append(engine)
        return engine

    speech = tts.Speech(factory, source=None, bargein=False, watchdog_seconds=0)
    speech.begin()
    speech.say("first")
    speech.cancel()
    speech.begin()
    speech.say("second")
    assert len(engines) == 2
    assert engines[0].spoken == ["first"]
    assert engines[1].spoken == ["second"]


# --------------------------------------------------------------------------- #
# build_speech
# --------------------------------------------------------------------------- #
def _args(**overrides):
    base = dict(voice=None, lang="en", volume=1.0, rate=200, bargein=True,
                max_speak=30.0)
    base.update(overrides)
    return types.SimpleNamespace(**base)


def test_build_speech_falls_back_to_silent():
    original = tts.available
    tts.available = lambda: False
    try:
        speech = tts.build_speech(_args(), {"voice_hints": ["en-us"]})
    finally:
        tts.available = original
    assert isinstance(speech, tts.SilentSpeech)


def test_build_speech_returns_speech_when_engine_exists():
    original_available = tts.available
    original_init = tts._init_for_voices
    tts.available = lambda: True
    tts._init_for_voices = lambda: FakeEngine(EN_VOICES)
    try:
        speech = tts.build_speech(_args(), {"voice_hints": ["en-us"]})
    finally:
        tts.available = original_available
        tts._init_for_voices = original_init
    assert isinstance(speech, tts.Speech)
    assert speech.bargein is False  # pas de micro en mode texte
