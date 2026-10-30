"""Voix Kokoro : un reseau de neurones de synthese vocale, local et gratuit.

Kokoro (82 millions de parametres, licence Apache 2.0) donne une voix bien plus
humaine que Piper, sans Internet. Le modele (~310 Mo) et ses voix (~27 Mo)
vivent hors du projet, par defaut sur le disque D :

    D:\\Jarvis\\kokoro\\kokoro-v1.0.onnx
    D:\\Jarvis\\kokoro\\voices-v1.0.bin

`JARVIS_KOKORO_DIR` permet de les mettre ailleurs ; `voices/kokoro/` dans le
projet est aussi accepte. Voix francaise : « ff_siwis » (feminine).

Meme interface que `tts.PiperEngine` (say / runAndWait / stop / level) : le
reste de Jarvis ne voit pas la difference, et Piper reste le secours.
"""

from __future__ import annotations

import os
import queue
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .text import log

DEFAULT_DIRS = (Path(r"D:\Jarvis\kokoro"),
                Path(__file__).resolve().parent.parent / "voices" / "kokoro")
MODEL_FILES = ("kokoro-v1.0.onnx", "kokoro-v1.0.fp16.onnx", "kokoro-v1.0.int8.onnx")
VOICES_FILE = "voices-v1.0.bin"
LANG_CODES = {"fr": "fr-fr", "en": "en-us"}
VOICES = {   # voix proposees dans le menu, par langue : (code, libelle)
    "fr": (("ff_siwis", "Kokoro · Siwis (naturelle)"),),
    "en": (("af_heart", "Kokoro · Heart (natural)"), ("am_michael", "Kokoro · Michael (natural)")),
}
DEFAULT_VOICE = {"fr": "ff_siwis", "en": "af_heart"}
SAMPLE_RATE = 24000
_models: dict = {}
_lock = threading.Lock()


def find_files(directory: str | os.PathLike | None = None) -> tuple[Path, Path] | None:
    """(modele, voix) si Kokoro est installe, sinon None."""
    candidates = [Path(directory)] if directory else []
    if os.environ.get("JARVIS_KOKORO_DIR"):
        candidates.append(Path(os.environ["JARVIS_KOKORO_DIR"]))
    candidates += list(DEFAULT_DIRS)
    for folder in candidates:
        voices = folder / VOICES_FILE
        if not voices.is_file():
            continue
        for name in MODEL_FILES:
            model = folder / name
            if model.is_file() and model.stat().st_size > 50_000_000:   # pas un .part
                return model, voices
    return None


def available() -> bool:
    try:
        import kokoro_onnx  # noqa: F401
        import pyaudio  # noqa: F401
    except Exception:
        return False
    return find_files() is not None


def voices_for(lang: str) -> list[tuple[str, str]]:
    """[(libelle, spec)] pour le menu, ex. ("Kokoro · Siwis (naturelle)", "kokoro:ff_siwis")."""
    if not available():
        return []
    return [(label, f"kokoro:{code}") for code, label in VOICES.get(lang, ())]


_CLAUSE = re.compile(r"(?<=[,;:])\s+")
CLAUSE_MIN = 28          # un morceau plus court est recolle au suivant (intonation)
FIRST_CLAUSE_MIN = 10    # ... sauf le premier : la voix demarre plus tot (1,7 -> 1,2 s)


def clauses(text: str) -> list[str]:
    """Decoupe une phrase aux virgules en morceaux assez longs pour bien sonner.

    Kokoro calcule a peu pres en temps reel sur un processeur : en jouant un
    morceau pendant que le suivant se calcule, la voix demarre plus tot et ne
    s'arrete plus entre deux morceaux.
    """
    pieces, current = [], ""
    for part in _CLAUSE.split((text or "").strip()):
        current = f"{current} {part}".strip()
        # Le premier morceau peut etre court : c'est lui qui fixe le delai avant
        # le premier son (calcul proportionnel a la longueur).
        if len(current) >= (FIRST_CLAUSE_MIN if not pieces else CLAUSE_MIN):
            pieces.append(current)
            current = ""
    if current:
        if pieces and len(current) < CLAUSE_MIN // 2:
            pieces[-1] = f"{pieces[-1]} {current}"
        else:
            pieces.append(current)
    return pieces


def load(files: tuple[Path, Path]):
    """Charge le modele une seule fois (partage entre les moteurs)."""
    with _lock:
        if files not in _models:
            from kokoro_onnx import Kokoro

            log(f"[tts] chargement de Kokoro ({files[0].name})...")
            model = Kokoro(str(files[0]), str(files[1]))

            def warm() -> None:   # premiere phrase ~7 s a froid : on chauffe en fond
                try:
                    model.create("Bonjour.", voice="ff_siwis", lang="fr-fr")
                except Exception:
                    pass

            threading.Thread(target=warm, name="jarvis-kokoro-chauffe", daemon=True).start()
            _models[files] = model
        return _models[files]


class KokoroEngine:
    """Voix Kokoro jouee par PyAudio, interruptible bloc par bloc."""

    BLOCK_FRAMES = 1024
    SENTENCE_PAUSE = 0.18
    CLAUSE_PAUSE = 0.1       # Kokoro retire le silence de la virgule : on le rend

    def __init__(self, voice: str = "ff_siwis", lang: str = "fr", rate: int = 200,
                 volume: float = 1.0, files=None, model=None, audio=None):
        files = files or find_files()
        if model is None:
            if files is None:
                raise RuntimeError("modele Kokoro introuvable")
            model = load(files)
        if audio is None:
            import pyaudio

            audio = pyaudio.PyAudio()
        self.model = model
        self.audio = audio
        self.voice = voice or DEFAULT_VOICE.get(lang, "ff_siwis")
        self.lang = LANG_CODES.get(lang, "fr-fr")
        self.speed = min(max((rate or 200) / 200.0, 0.6), 1.6)
        self.volume = min(max(volume, 0.0), 1.0)
        self.sample_rate = SAMPLE_RATE
        self.level = 0.0
        self._pending: list[str] = []
        self._stop = threading.Event()
        # Un seul calcul a la fois (le processeur est l'etranglement) ; les
        # morceaux annonces d'avance (`prefetch`) y attendent leur tour.
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="jarvis-kokoro")
        self._futures: dict[str, object] = {}
        self._futures_lock = threading.Lock()

    def say(self, text: str) -> None:
        self._pending.append(text)

    def _future(self, piece: str):
        with self._futures_lock:
            future = self._futures.get(piece)
            if future is None:
                future = self._pool.submit(self.synthesize, piece)
                self._futures[piece] = future
            return future

    def prefetch(self, text: str) -> None:
        """Commence a calculer une phrase qui sera dite juste apres."""
        for piece in clauses(text):
            self._future(piece)

    def synthesize(self, text: str) -> bytes:
        """Phrase -> PCM 16 bits mono."""
        import numpy as np

        samples, rate = self.model.create(text, voice=self.voice, speed=self.speed,
                                          lang=self.lang)
        self.sample_rate = int(rate)
        samples = np.clip(np.asarray(samples, dtype=np.float32) * self.volume, -1.0, 1.0)
        return (samples * 32767).astype(np.int16).tobytes()

    def runAndWait(self) -> None:  # noqa: N802 - interface pyttsx3
        """Joue les phrases en attente ; le morceau suivant se calcule pendant
        que le precedent est joue (aucun blanc entre deux morceaux)."""
        from .tts import audio_level

        self._stop.clear()
        pending, self._pending = self._pending, []
        pieces = [(piece, i == len(parts) - 1)
                  for text in pending for parts in [clauses(text)]
                  for i, piece in enumerate(parts)]
        if not pieces:
            return
        ready: queue.Queue = queue.Queue(maxsize=3)
        done = object()

        def produce() -> None:
            try:
                for piece, last in pieces:
                    if self._stop.is_set():
                        break
                    future = self._future(piece)
                    audio = future.result()
                    with self._futures_lock:
                        if self._futures.get(piece) is future:
                            del self._futures[piece]
                    ready.put((audio, last))
            except Exception as exc:          # renvoye au fil qui joue
                ready.put(exc)
            finally:
                ready.put(done)

        threading.Thread(target=produce, name="jarvis-kokoro", daemon=True).start()
        stream = None
        try:
            block = self.BLOCK_FRAMES * 2
            while True:
                item = ready.get()
                if item is done or self._stop.is_set():
                    return
                if isinstance(item, Exception):
                    raise item
                audio, last = item
                if stream is None:
                    stream = self.audio.open(format=8, channels=1, rate=self.sample_rate,
                                             output=True)   # 8 = paInt16
                for start in range(0, len(audio), block):
                    if self._stop.is_set():
                        return
                    chunk = audio[start:start + block]
                    self.level = audio_level(chunk)
                    stream.write(chunk)
                self.level = 0.0
                pause = self.SENTENCE_PAUSE if last else self.CLAUSE_PAUSE
                stream.write(b"\x00\x00" * int(self.sample_rate * pause))
        finally:
            self.level = 0.0
            if stream is not None:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception:
                    pass

    def stop(self) -> None:
        self._pending = []
        self._stop.set()
        with self._futures_lock:
            for future in self._futures.values():
                future.cancel()
            self._futures.clear()


__all__ = ["KokoroEngine", "available", "find_files", "voices_for", "VOICES", "DEFAULT_VOICE"]
