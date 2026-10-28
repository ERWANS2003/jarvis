"""Horizon 5 - mot d'activation local (« Jarvis »), sans Internet.

Contrairement au mot d'activation de la console (qui transcrit chaque phrase
en ligne puis cherche « jarvis » dans le texte), ces detecteurs tournent
entierement sur la machine. Rien n'est envoye tant que le mot n'a pas ete
prononce.

  * `SpokenWakeDetector` (recommande) : **« Jarvis » tout court**, dans
    n'importe quelle phrase. Un petit modele Vosk (~40 Mo, `voices/vosk/`)
    transcrit le micro en local ; des qu'un enonce contient « jarvis », la
    suite de la phrase est renvoyee telle quelle : « Jarvis, quelle heure
    est-il ? » est donc traite d'une traite, sans redemander la question.
  * `WakeWordDetector` (repli) : modele openWakeWord « Hey Jarvis ».

Le detecteur se met en pause tout seul pendant que Jarvis ecoute, reflechit
ou parle (`is_paused`), pour ne pas se declencher sur sa propre voix.
"""

from __future__ import annotations

import json
import threading
import time
import unicodedata
from pathlib import Path

from .text import log

SAMPLE_RATE = 16000
CHUNK = 1280                 # 80 ms a 16 kHz, la taille attendue par le modele
DEFAULT_MODEL = "hey_jarvis"
DEFAULT_THRESHOLD = 0.5
COOLDOWN = 2.0               # secondes sans nouveau declenchement


def mic_level(frames: bytes) -> float:
    """Volume (0..1) d'une tranche du micro, un peu amplifie (voix lointaine)."""
    from .tts import audio_level

    return min(1.0, audio_level(frames) * 2.5)


def available() -> bool:
    """Vrai si openWakeWord, onnxruntime et PyAudio sont installes."""
    try:
        import openwakeword  # noqa: F401
        import onnxruntime  # noqa: F401
        import pyaudio  # noqa: F401
    except Exception:
        return False
    return True


def ensure_model(name: str = DEFAULT_MODEL) -> None:
    """Telecharge le modele (et ses briques communes) s'il manque encore."""
    from openwakeword import utils

    utils.download_models(model_names=[f"{name}_v0.1"])


class WakeWordDetector:
    """Ecoute le micro dans un fil et appelle `on_wake()` au mot d'activation."""

    def __init__(self, on_wake, is_paused=None, model: str = DEFAULT_MODEL,
                 threshold: float = DEFAULT_THRESHOLD, scorer=None, stream=None):
        self.on_wake = on_wake
        self.is_paused = is_paused or (lambda: False)
        self.model_name = model
        self.threshold = threshold
        self.enabled = True
        self.level = 0.0  # volume du micro (0..1) : l'orbe reagit a ta voix
        self._scorer = scorer        # doublure possible pour les tests
        self._stream = stream
        self._audio = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last = 0.0

    # -- modele ------------------------------------------------------------- #
    def _load(self):
        from openwakeword.model import Model

        try:
            return Model(wakeword_models=[self.model_name],
                         inference_framework="onnx")
        except Exception:
            ensure_model(self.model_name)
            return Model(wakeword_models=[self.model_name],
                         inference_framework="onnx")

    def _open_stream(self):
        import pyaudio

        self._audio = pyaudio.PyAudio()
        return self._audio.open(format=pyaudio.paInt16, channels=1,
                                rate=SAMPLE_RATE, input=True,
                                frames_per_buffer=CHUNK)

    # -- cycle de vie ------------------------------------------------------- #
    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="jarvis-wake",
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def feed(self, frames: bytes) -> bool:
        """Analyse une tranche audio ; vrai si le mot vient d'etre detecte."""
        import numpy as np

        if self.is_paused() or not self.enabled:
            self._reset()
            return False
        scores = self._scorer.predict(np.frombuffer(frames, dtype=np.int16))
        score = max(scores.values()) if scores else 0.0
        now = time.monotonic()
        if score >= self.threshold and now - self._last >= COOLDOWN:
            self._last = now
            self._reset()
            return True
        return False

    def _reset(self) -> None:
        reset = getattr(self._scorer, "reset", None)
        if callable(reset):
            reset()

    def _run(self) -> None:
        try:
            if self._scorer is None:
                self._scorer = self._load()
            if self._stream is None:
                self._stream = self._open_stream()
            log(f"[reveil] a l'ecoute de « {self.model_name.replace('_', ' ')} »")
            while not self._stop.is_set():
                frames = self._stream.read(CHUNK, exception_on_overflow=False)
                self.level = mic_level(frames)
                if self.feed(frames):
                    log("[reveil] mot d'activation detecte")
                    try:
                        self.on_wake()
                    except Exception as exc:
                        log(f"[reveil] {exc}")
        except Exception as exc:
            log(f"[reveil] desactive : {exc}")
        finally:
            for closer in (lambda: self._stream.stop_stream(),
                           lambda: self._stream.close(),
                           lambda: self._audio.terminate()):
                try:
                    closer()
                except Exception:
                    pass


# --------------------------------------------------------------------------- #
# « Jarvis » tout court : reconnaissance locale Vosk
# --------------------------------------------------------------------------- #
VOSK_DIR = Path(__file__).resolve().parent.parent / "voices" / "vosk"
VOSK_MODELS = {"fr": "vosk-model-small-fr-0.22", "en": "vosk-model-small-en-us-0.15"}
BYTES_PER_SECOND = SAMPLE_RATE * 2   # 16 bits mono
MIN_QUESTION_SECONDS = 0.4           # en dessous : « Jarvis » seul
MAX_UTTERANCE_SECONDS = 20


def vosk_available() -> bool:
    try:
        import pyaudio  # noqa: F401
        import vosk  # noqa: F401
    except Exception:
        return False
    return True


def find_vosk_model(lang: str, directory: Path | None = None) -> Path | None:
    directory = Path(directory or VOSK_DIR)
    preferred = directory / VOSK_MODELS.get(lang, "")
    if VOSK_MODELS.get(lang) and preferred.is_dir():
        return preferred
    prefix = "vosk-model-small-fr" if lang == "fr" else "vosk-model-small-en"
    matches = sorted(p for p in directory.glob(prefix + "*") if p.is_dir()) \
        if directory.is_dir() else []
    return matches[0] if matches else None


def _fold(word: str) -> str:
    """Minuscules sans accents : « Jarvís » == « jarvis »."""
    text = unicodedata.normalize("NFKD", word or "").lower()
    return "".join(c for c in text if not unicodedata.combining(c)).strip(" .,!?;:'\"")


class SpokenWakeDetector:
    """Detecte « Jarvis » dans la parole et renvoie la suite de la phrase.

    `on_wake(question)` recoit l'audio (PCM 16 kHz, 16 bits) prononce apres
    le mot, ou ``b""`` si l'utilisateur n'a dit que « Jarvis ».
    """

    def __init__(self, on_wake, words=("jarvis",), model_path=None,
                 is_paused=None, recognizer_factory=None, stream=None):
        self.on_wake = on_wake
        self.words = {_fold(w) for w in words if _fold(w)} or {"jarvis"}
        self.model_path = model_path
        self.is_paused = is_paused or (lambda: False)
        self.enabled = True
        self.level = 0.0  # volume du micro (0..1) : l'orbe reagit a ta voix
        self._factory = recognizer_factory
        self._recognizer = None
        self._stream = stream
        self._audio = None
        self._stop = threading.Event()
        self._fed = 0                # octets donnes au recogniseur
        self._utterance = bytearray()
        self._utterance_start = 0    # position (octets) du debut de l'enonce
        self._dirty = False

    # -- modele ------------------------------------------------------------- #
    def _make_factory(self):
        import vosk

        vosk.SetLogLevel(-1)
        model = vosk.Model(str(self.model_path))

        def factory():
            recognizer = vosk.KaldiRecognizer(model, SAMPLE_RATE)
            recognizer.SetWords(True)
            return recognizer

        return factory

    def _restart(self) -> None:
        self._recognizer = self._factory()
        self._fed = 0
        self._utterance = bytearray()
        self._utterance_start = 0
        self._dirty = False

    # -- analyse ------------------------------------------------------------ #
    def feed(self, frames: bytes):
        """Analyse une tranche. Renvoie ``None``, ou l'audio de la question
        (``b""`` si « Jarvis » etait seul) quand le mot a ete entendu."""
        if self.is_paused() or not self.enabled:
            if self._dirty:
                self._restart()  # oublie ce qui a ete entendu pendant la pause
            return None
        if self._recognizer is None:
            self._restart()
        self._dirty = True
        self._utterance.extend(frames)
        self._fed += len(frames)
        if not self._recognizer.AcceptWaveform(frames):
            if len(self._utterance) > MAX_UTTERANCE_SECONDS * BYTES_PER_SECOND:
                self._next_utterance()
            return None
        result = json.loads(self._recognizer.Result() or "{}")
        question = self._find_wake(result.get("result") or [])
        self._next_utterance()
        return question

    def _find_wake(self, words: list):
        for index, item in enumerate(words):
            if _fold(item.get("word", "")) in self.words:
                after = words[index + 1:]
                if not after:
                    return b""
                cut = int(float(item.get("end", 0)) * BYTES_PER_SECOND) - self._utterance_start
                cut = max(0, min(len(self._utterance), cut - cut % 2))
                tail = bytes(self._utterance[cut:])
                if len(tail) < MIN_QUESTION_SECONDS * BYTES_PER_SECOND:
                    return b""
                return tail
        return None

    def _next_utterance(self) -> None:
        self._utterance = bytearray()
        self._utterance_start = self._fed

    # -- cycle de vie ------------------------------------------------------- #
    def start(self) -> None:
        self._stop.clear()
        threading.Thread(target=self._run, name="jarvis-wake", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        try:
            if self._factory is None:
                self._factory = self._make_factory()
            if self._stream is None:
                import pyaudio

                self._audio = pyaudio.PyAudio()
                self._stream = self._audio.open(format=pyaudio.paInt16, channels=1,
                                                rate=SAMPLE_RATE, input=True,
                                                frames_per_buffer=CHUNK * 2)
            words = ", ".join(sorted(self.words))
            log(f"[reveil] a l'ecoute de « {words} » (reconnaissance locale)")
            while not self._stop.is_set():
                frames = self._stream.read(CHUNK * 2, exception_on_overflow=False)
                self.level = mic_level(frames)
                question = self.feed(frames)
                if question is not None:
                    log("[reveil] mot d'activation detecte"
                        + (" avec une question" if question else ""))
                    try:
                        self.on_wake(question)
                    except Exception as exc:
                        log(f"[reveil] {exc}")
        except Exception as exc:
            log(f"[reveil] desactive : {exc}")
        finally:
            for closer in (lambda: self._stream.stop_stream(),
                           lambda: self._stream.close(),
                           lambda: self._audio.terminate()):
                try:
                    closer()
                except Exception:
                    pass


__all__ = ["WakeWordDetector", "SpokenWakeDetector", "available", "vosk_available",
           "find_vosk_model", "ensure_model", "DEFAULT_MODEL", "DEFAULT_THRESHOLD"]
