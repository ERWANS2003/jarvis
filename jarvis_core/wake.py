"""Horizon 5 - mot d'activation local (« Hey Jarvis »), sans Internet.

Contrairement au mot d'activation de la console (qui transcrit chaque phrase
en ligne puis cherche « jarvis » dans le texte), ce detecteur tourne
entierement sur la machine : openWakeWord analyse le micro par tranches de
80 ms avec un petit modele ONNX (~2 ms de calcul par tranche). Rien n'est
envoye tant que le mot n'a pas ete prononce.

Le detecteur se met en pause tout seul pendant que Jarvis ecoute, reflechit
ou parle (`is_paused`), pour ne pas se declencher sur sa propre voix.
"""

from __future__ import annotations

import threading
import time

from .text import log

SAMPLE_RATE = 16000
CHUNK = 1280                 # 80 ms a 16 kHz, la taille attendue par le modele
DEFAULT_MODEL = "hey_jarvis"
DEFAULT_THRESHOLD = 0.5
COOLDOWN = 2.0               # secondes sans nouveau declenchement


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


__all__ = ["WakeWordDetector", "available", "ensure_model", "DEFAULT_MODEL",
           "DEFAULT_THRESHOLD"]
