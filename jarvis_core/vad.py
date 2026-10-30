"""Horizon 5 - voix temps reel : detection d'activite vocale (VAD).

Le mode historique (`recognizer.listen`) attend une pause fixe avant de rendre
la main : l'assistant semble lent et coupe parfois la parole. Ici on lit le
micro frame par frame et on decide nous-memes du debut et de la fin de la prise
de parole, ce qui donne :

  * un endpointing naturel (on s'arrete apres un vrai silence, pas un delai fixe) ;
  * une latence plus faible ;
  * une interruption instantanee (le meme detecteur sert au barge-in).

Aucune dependance obligatoire : le detecteur d'energie suffit. Si `webrtcvad`
est installe, il est utilise en complement pour filtrer le bruit.
"""

from __future__ import annotations

import collections
import statistics
from dataclasses import dataclass

from .text import rms

DEFAULT_SAMPLE_RATE = 16000
BYTES_PER_SAMPLE = 2  # int16 mono


@dataclass
class VADConfig:
    sample_rate: int = DEFAULT_SAMPLE_RATE
    frame_ms: int = 30
    silence_ms: int = 700        # silence requis pour clore la parole
    min_speech_ms: int = 250     # en dessous, on considere que c'est du bruit
    max_speech_ms: int = 15000   # securite anti-boucle
    start_timeout_ms: int = 8000  # rien dit -> on rend la main
    pre_roll_ms: int = 300       # on garde l'audio juste avant le declenchement
    energy_margin: float = 1.8   # seuil = bruit de fond * marge
    energy_floor: float = 350.0  # seuil minimal absolu

    @property
    def frame_frames(self) -> int:
        return max(1, int(self.sample_rate * self.frame_ms / 1000))

    @property
    def frame_bytes(self) -> int:
        return self.frame_frames * BYTES_PER_SAMPLE


class EnergyVAD:
    """Detecteur simple : energie RMS du frame comparee a un seuil adaptatif."""

    def __init__(self, config: VADConfig | None = None):
        self.config = config or VADConfig()
        self.noise_floor = 0.0
        self._recent: collections.deque[float] = collections.deque(maxlen=100)   # ~3 s

    def threshold(self) -> float:
        cfg = self.config
        return max(self.noise_floor * cfg.energy_margin, cfg.energy_floor)

    def calibrate(self, frames: list[bytes]) -> float:
        values = [rms(frame) for frame in frames if frame]
        self.noise_floor = statistics.median(values) if values else 0.0
        return self.noise_floor

    def adapt(self, frame: bytes) -> None:
        """Entre deux phrases : suit le bruit ambiant (telle allumee, ventilateur...).
        Une voix proche du micro reste au-dessus du seuil, pas celle de la telle."""
        self._recent.append(rms(frame))
        if len(self._recent) >= 10:
            self.noise_floor = statistics.median(self._recent)

    def is_speech(self, frame: bytes) -> bool:
        return rms(frame) >= self.threshold()


class WebRTCVAD:
    """Enveloppe optionnelle autour de `webrtcvad` (si installe)."""

    def __init__(self, sample_rate: int = DEFAULT_SAMPLE_RATE, aggressiveness: int = 2):
        import webrtcvad  # noqa: WPS433 (import volontairement tardif)

        self._vad = webrtcvad.Vad(aggressiveness)
        self.sample_rate = sample_rate

    @staticmethod
    def available() -> bool:
        try:
            import webrtcvad  # noqa: F401,WPS433
        except Exception:
            return False
        return True

    def is_speech(self, frame: bytes) -> bool:
        try:
            return bool(self._vad.is_speech(frame, self.sample_rate))
        except Exception:
            return False


def make_vad(config: VADConfig | None = None):
    """Retourne un detecteur (WebRTC si dispo, sinon energie)."""
    config = config or VADConfig()
    if WebRTCVAD.available():
        return WebRTCVAD(config.sample_rate)
    return EnergyVAD(config)


@dataclass
class Recording:
    pcm: bytes
    speech_ms: int
    total_ms: int

    def __bool__(self) -> bool:
        return bool(self.pcm)


class VADRecorder:
    """Enregistre une prise de parole en s'appuyant sur un stream PyAudio/SR.

    `stream` doit exposer ``read(n_frames) -> bytes`` (c'est le cas de
    ``speech_recognition.Microphone().stream``). `stream_frames` lit de quoi
    remplir un frame VAD.
    """

    def __init__(self, stream, config: VADConfig | None = None,
                 detector=None, frames_reader=None):
        self.config = config or VADConfig()
        self.stream = stream
        self.detector = detector or make_vad(self.config)
        self._frames_reader = frames_reader or self._read_from_stream

    # -- lecture des frames ------------------------------------------------- #
    def _read_from_stream(self, n_frames: int) -> bytes:
        return self.stream.read(n_frames)

    def read_frame(self) -> bytes:
        return self._frames_reader(self.config.frame_frames)

    # -- calibration ------------------------------------------------------- #
    def calibrate(self, frames: int = 12) -> float:
        samples = []
        for _ in range(max(1, frames)):
            try:
                samples.append(self.read_frame())
            except Exception:
                break
        if isinstance(self.detector, EnergyVAD):
            return self.detector.calibrate(samples)
        if hasattr(self.detector, "calibrate"):
            return self.detector.calibrate(samples)
        return 0.0

    # -- enregistrement ---------------------------------------------------- #
    def record(self) -> Recording | None:
        cfg = self.config
        pre_roll: collections.deque[bytes] = collections.deque(
            maxlen=max(1, cfg.pre_roll_ms // max(1, cfg.frame_ms))
        )
        spoken = bytearray()
        in_speech = False
        speech_ms = 0
        silence_ms = 0
        total_ms = 0

        while total_ms < cfg.max_speech_ms:
            try:
                frame = self.read_frame()
            except Exception:
                break
            if not frame:
                break
            total_ms += cfg.frame_ms
            voiced = bool(self.detector.is_speech(frame))

            if not in_speech:
                if voiced:
                    in_speech = True
                    speech_ms = cfg.frame_ms
                    silence_ms = 0
                    spoken.extend(b"".join(pre_roll))
                    spoken.extend(frame)
                else:
                    pre_roll.append(frame)
                    adapt = getattr(self.detector, "adapt", None)
                    if adapt is not None:
                        adapt(frame)
                    if total_ms >= cfg.start_timeout_ms:
                        return None
                continue

            spoken.extend(frame)
            if voiced:
                speech_ms += cfg.frame_ms
                silence_ms = 0
            else:
                silence_ms += cfg.frame_ms
                if silence_ms >= cfg.silence_ms and speech_ms >= cfg.min_speech_ms:
                    break
                if total_ms >= cfg.max_speech_ms:
                    break

        if not spoken or speech_ms < cfg.min_speech_ms:
            return None
        return Recording(pcm=bytes(spoken), speech_ms=speech_ms, total_ms=total_ms)


def pcm_to_audio_data(pcm: bytes, sample_rate: int = DEFAULT_SAMPLE_RATE):
    """Convertit du PCM 16 bits mono en `speech_recognition.AudioData`."""
    import speech_recognition as sr

    return sr.AudioData(pcm, sample_rate, BYTES_PER_SAMPLE)


def trim_silence(pcm: bytes, sample_rate: int = DEFAULT_SAMPLE_RATE,
                 frame_ms: int = 30, threshold: float = 350.0) -> bytes:
    """Retire les frames silencieux en tete et en queue (testable hors micro)."""
    step = max(1, int(sample_rate * frame_ms / 1000)) * BYTES_PER_SAMPLE
    frames = [pcm[i:i + step] for i in range(0, len(pcm), step)]
    first = 0
    last = len(frames)
    while first < last and rms(frames[first]) < threshold:
        first += 1
    while last > first and rms(frames[last - 1]) < threshold:
        last -= 1
    return b"".join(frames[first:last])


__all__ = [
    "DEFAULT_SAMPLE_RATE",
    "VADConfig",
    "EnergyVAD",
    "WebRTCVAD",
    "make_vad",
    "Recording",
    "VADRecorder",
    "pcm_to_audio_data",
    "trim_silence",
]
