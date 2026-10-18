"""Tests de la reconnaissance vocale (Horizons 1, 4 et 5)."""

from __future__ import annotations

import struct

import speech_recognition as sr

from jarvis_core import stt
from jarvis_core.vad import VADConfig

STRINGS = {"google_lang": "fr-FR", "whisper_lang": "fr"}

FRAME_FRAMES = 480          # 30 ms a 16 kHz
BYTES_PER_SAMPLE = 2
SILENT = b"\x00" * (FRAME_FRAMES * BYTES_PER_SAMPLE)
LOUD = struct.pack("<" + "h" * FRAME_FRAMES, *([2000] * FRAME_FRAMES))


class FakeRecognizer:
    def __init__(self, text="bonjour", error=None):
        self.text = text
        self.error = error
        self.languages = []
        self.errors = []          # erreurs a lever, une par appel

    def recognize_google(self, audio, language=None, **kwargs):
        self.languages.append(language)
        if self.errors:
            raise self.errors.pop(0)
        if self.error is not None:
            raise self.error
        return self.text

    def listen(self, source, phrase_time_limit=None):
        if self.errors:
            raise self.errors.pop(0)
        return "AUDIO"


class FakeWhisper:
    def __init__(self, text="transcription locale", error=None):
        self.text = text
        self.error = error
        self.calls = 0

    def transcribe(self, audio):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.text


class FakeStream:
    def __init__(self, frames):
        self.frames = list(frames)

    def read(self, n_frames):
        if not self.frames:
            return b""
        return self.frames.pop(0)


class FakeSource:
    def __init__(self, frames):
        self.stream = FakeStream(frames)
        self.opened = 0

    def __enter__(self):
        self.opened += 1
        return self

    def __exit__(self, *exc):
        return False


# --------------------------------------------------------------------------- #
# Transcriber
# --------------------------------------------------------------------------- #
def test_transcriber_google_success():
    recognizer = FakeRecognizer("bonjour")
    transcriber = stt.Transcriber(recognizer, STRINGS, order=("google",))
    text, error = transcriber.transcribe("AUDIO")
    assert (text, error) == ("bonjour", None)
    assert recognizer.languages == ["fr-FR"]
    assert transcriber.last_backend == "google"


def test_transcriber_unknown_value_is_unintelligible():
    recognizer = FakeRecognizer()
    recognizer.error = sr.UnknownValueError()
    transcriber = stt.Transcriber(recognizer, STRINGS, order=("google",))
    assert transcriber.transcribe("AUDIO") == (None, "unintelligible")


def test_transcriber_request_error_reports_network():
    recognizer = FakeRecognizer()
    recognizer.error = sr.RequestError("DNS down")
    transcriber = stt.Transcriber(recognizer, STRINGS, order=("google",))
    text, error = transcriber.transcribe("AUDIO")
    assert text is None
    assert error.startswith("network:")


def test_transcriber_falls_back_to_whisper():
    recognizer = FakeRecognizer()
    recognizer.error = sr.RequestError("no internet")
    whisper = FakeWhisper("il fait beau")
    transcriber = stt.Transcriber(recognizer, STRINGS,
                                 order=("google", "whisper"), whisper=whisper)
    assert transcriber.backends() == ["google", "whisper"]
    assert transcriber.transcribe("AUDIO") == ("il fait beau", None)
    assert whisper.calls == 1
    assert transcriber.last_backend == "whisper"


def test_transcriber_whisper_only_mode():
    recognizer = FakeRecognizer()
    whisper = FakeWhisper("salut")
    transcriber = stt.Transcriber(recognizer, STRINGS, order=("whisper",),
                                 whisper=whisper)
    assert transcriber.transcribe("AUDIO") == ("salut", None)


def test_transcriber_reports_silence_when_all_backends_empty():
    recognizer = FakeRecognizer("")
    transcriber = stt.Transcriber(recognizer, STRINGS, order=("google",))
    text, error = transcriber.transcribe("AUDIO")
    assert text is None
    assert error == "google:silence"


def test_build_transcriber_modes():
    recognizer = FakeRecognizer()
    google_only = stt.build_transcriber(recognizer, STRINGS, mode="google")
    assert google_only.backends() == ["google"]

    whisper_only = stt.build_transcriber(recognizer, STRINGS, mode="whisper")
    assert whisper_only.backends() == ["whisper"]

    automatic = stt.build_transcriber(recognizer, STRINGS, mode="auto")
    expected = ["google", "whisper"] if stt.WhisperBackend.available() else ["google"]
    assert automatic.backends() == expected


def test_classify_maps_errors():
    assert stt._classify("google", sr.UnknownValueError()) == "unintelligible"
    assert stt._classify("google", sr.RequestError("x")).startswith("network:")
    assert stt._classify("google", OSError("mic")).startswith("mic:")
    assert stt._classify("whisper", ValueError("nope")) == "whisper:ValueError"


# --------------------------------------------------------------------------- #
# SpeechToText
# --------------------------------------------------------------------------- #
def test_speech_to_text_wait_timeout_returns_empty():
    recognizer = FakeRecognizer()
    recognizer.errors = [sr.WaitTimeoutError()]
    source = FakeSource([])
    listener = stt.SpeechToText(recognizer, source, "fr-FR",
                                transcriber=stt.Transcriber(recognizer, STRINGS))
    assert listener.listen() == (None, None)


def test_speech_to_text_reopens_microphone_after_error():
    recognizer = FakeRecognizer("bonjour")
    recognizer.errors = [OSError("flux perdu")]
    source = FakeSource([])
    listener = stt.SpeechToText(recognizer, source, "fr-FR",
                                transcriber=stt.Transcriber(recognizer, STRINGS,
                                                            order=("google",)))
    text, error = listener.listen()
    assert (text, error) == ("bonjour", None)
    assert source.opened == 1  # une reouverture, puis succes


def test_speech_to_text_reports_mic_error_after_two_failures():
    recognizer = FakeRecognizer()
    recognizer.errors = [OSError("flux perdu"), OSError("toujours perdu")]
    source = FakeSource([])
    listener = stt.SpeechToText(recognizer, source, "fr-FR",
                                transcriber=stt.Transcriber(recognizer, STRINGS))
    text, error = listener.listen()
    assert text is None
    assert error.startswith("mic:")


# --------------------------------------------------------------------------- #
# VADSpeechToText (Horizon 5)
# --------------------------------------------------------------------------- #
VAD_SETTINGS = dict(frame_ms=30, silence_ms=90, min_speech_ms=60,
                    start_timeout_ms=1000, max_speech_ms=5000, pre_roll_ms=30)


def test_vad_speech_to_text_endpoints_on_silence():
    # 12 frames sont consommees par la calibration du bruit de fond.
    frames = [SILENT] * 40 + [LOUD] * 6 + [SILENT] * 10
    recognizer = FakeRecognizer("quelle heure est-il")
    source = FakeSource(frames)
    listener = stt.VADSpeechToText(recognizer, source, "fr-FR",
                                   config=VADConfig(**VAD_SETTINGS),
                                   transcriber=stt.Transcriber(
                                       recognizer, STRINGS, order=("google",)))
    text, error = listener.listen()
    assert (text, error) == ("quelle heure est-il", None)


def test_vad_speech_to_text_returns_empty_without_speech():
    frames = [SILENT] * 80
    recognizer = FakeRecognizer("jamais entendu")
    source = FakeSource(frames)
    listener = stt.VADSpeechToText(recognizer, source, "fr-FR",
                                   config=VADConfig(**VAD_SETTINGS),
                                   transcriber=stt.Transcriber(
                                       recognizer, STRINGS, order=("google",)))
    assert listener.listen() == (None, None)


def test_vad_speech_to_text_falls_back_on_recorder_error():
    class BrokenSource:
        @property
        def stream(self):
            raise OSError("pas de flux audio")

    recognizer = FakeRecognizer("repli")
    listener = stt.VADSpeechToText(recognizer, BrokenSource(), "fr-FR",
                                   config=VADConfig(**VAD_SETTINGS),
                                   transcriber=stt.Transcriber(
                                       recognizer, STRINGS, order=("google",)))
    text, error = listener.listen()
    assert (text, error) == ("repli", None)
