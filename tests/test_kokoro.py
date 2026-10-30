"""Tests de la voix Kokoro (reseau de neurones local), sans modele ni carte son."""

from __future__ import annotations

import tempfile
from pathlib import Path

from jarvis_core import tts
from jarvis_core import voice_kokoro as K


class _Model:
    def __init__(self):
        self.calls = []

    def create(self, text, voice, speed, lang):
        import numpy as np

        self.calls.append((text, voice, round(speed, 2), lang))
        return np.zeros(4800, dtype=np.float32) + 0.1, 24000


class _Stream:
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


class _Audio:
    def __init__(self, stream):
        self.stream = stream
        self.rates = []

    def open(self, format, channels, rate, output):
        self.rates.append(rate)
        return self.stream


def test_kokoro_speaks_each_sentence_in_french():
    model, stream = _Model(), _Stream()
    audio = _Audio(stream)
    engine = K.KokoroEngine("ff_siwis", lang="fr", rate=220, model=model, audio=audio)
    engine.say("Bonjour.")
    engine.say("Il fait beau.")
    engine.runAndWait()
    assert model.calls == [("Bonjour.", "ff_siwis", 1.1, "fr-fr"),
                           ("Il fait beau.", "ff_siwis", 1.1, "fr-fr")]
    pause = 2 * int(24000 * engine.SENTENCE_PAUSE)
    assert stream.written == 2 * (4800 * 2 + pause) and audio.rates == [24000]


def test_long_sentences_are_spoken_clause_by_clause():
    assert K.clauses("À Bobo-Dioulasso, il fait 26,7 degrés, partiellement nuageux, vent 4.") == \
        ["À Bobo-Dioulasso,", "il fait 26,7 degrés, partiellement nuageux, vent 4."]  # 1er court
    assert K.clauses("Oui, bien sûr.") == ["Oui, bien sûr."]           # trop court : entier
    model, stream = _Model(), _Stream()
    engine = K.KokoroEngine("ff_siwis", model=model, audio=_Audio(stream))
    engine.say("À Bobo-Dioulasso, il fait 26,7 degrés, partiellement nuageux, vent 4.")
    engine.runAndWait()
    assert [call[0] for call in model.calls] == [
        "À Bobo-Dioulasso,", "il fait 26,7 degrés, partiellement nuageux, vent 4."]
    pauses = 2 * (int(24000 * engine.CLAUSE_PAUSE) + int(24000 * engine.SENTENCE_PAUSE))
    assert stream.written == 2 * 4800 * 2 + pauses


def test_kokoro_stops_at_once():
    holder = {}
    stream = _Stream(on_write=lambda: holder["engine"].stop())
    engine = K.KokoroEngine("ff_siwis", model=_Model(), audio=_Audio(stream))
    holder["engine"] = engine
    engine.say("Une longue phrase.")
    engine.runAndWait()
    assert stream.written == engine.BLOCK_FRAMES * 2


def test_model_files_are_found_on_the_chosen_folder():
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        assert K.find_files(folder) is None or K.find_files(folder)[0].parent != folder
        (folder / K.VOICES_FILE).write_bytes(b"v")
        (folder / "kokoro-v1.0.onnx").write_bytes(b"x")       # telechargement incomplet
        assert K.find_files(folder) is None or K.find_files(folder)[0].parent != folder
        with open(folder / "kokoro-v1.0.onnx", "wb") as handle:
            handle.truncate(60_000_000)
        assert K.find_files(folder) == (folder / "kokoro-v1.0.onnx", folder / K.VOICES_FILE)


def test_kokoro_is_offered_first_and_falls_back_to_piper():
    original_available, original_engine = K.available, K.KokoroEngine
    try:
        K.available = lambda: True
        voices = tts.installed_voices("fr")
        assert voices[0] == ("Kokoro · Siwis (naturelle)", "kokoro:ff_siwis")

        def broken(*_a, **_k):
            raise RuntimeError("modele absent")

        K.KokoroEngine = broken
        original_piper = tts.PiperEngine
        tts.PiperEngine = lambda *a, **k: "piper"
        try:
            factory = tts.make_engine_factory(None, piper_model=Path("x.onnx"),
                                              kokoro_voice="ff_siwis", lang="fr")
            assert factory() == "piper"                  # Kokoro absent : Piper prend le relais
        finally:
            tts.PiperEngine = original_piper
    finally:
        K.available, K.KokoroEngine = original_available, original_engine


def test_voice_pace_can_be_changed_by_voice():
    import tempfile

    from jarvis_core import intents

    assert intents.pace_request("Parle plus lentement") < 1
    assert intents.pace_request("Jarvis, parle un peu plus vite") > 1
    assert intents.pace_request("Ralentis") < 1 and intents.pace_request("Bonjour") is None

    kokoro = K.KokoroEngine("ff_siwis", model=_Model(), audio=_Audio(_Stream()))
    tts.apply_pace(kokoro, 0.8)
    assert round(kokoro.speed, 2) == 0.8
    tts.apply_pace(kokoro, 1.2)                      # toujours par rapport a la vitesse d'origine
    assert round(kokoro.speed, 2) == 1.2

    class Piper:
        length_scale = 1.0

    piper = Piper()
    tts.apply_pace(piper, 1.25)
    assert round(piper.length_scale, 2) == 0.8

    original = tts.PACE_FILE
    with tempfile.TemporaryDirectory() as tmp:
        tts.PACE_FILE = Path(tmp) / "voice.json"
        try:
            class Speech:
                pace = 1.0
                change_pace = tts.Speech.change_pace

            speech = Speech()
            assert round(speech.change_pace(1 / 1.15), 2) == 0.87
            assert round(tts.load_pace(), 2) == 0.87          # retenu pour la prochaine fois
            for _ in range(10):
                speech.change_pace(1 / 1.15)
            assert speech.pace == tts.PACE_MIN                 # jamais trop lent
        finally:
            tts.PACE_FILE = original
