"""Reconnaissance vocale (STT).

Deux moteurs, combinables :

  * **Google** (gratuit, sans cle) : tres bon en ligne, inutilisable hors-ligne ;
  * **Whisper local** (`faster-whisper`, optionnel) : fonctionne sans reseau et
    sans quota. Il est installe a la demande ::

       .\\.venv\\Scripts\\pip install faster-whisper

Jarvis tente les moteurs dans l'ordre demande (`--stt google|whisper|auto`)
et bascule sur le suivant quand l'un echoue (reseau coupe, quota, silence).

Le mode VAD (Horizon 5) remplace `recognizer.listen` par un enregistrement
pilote par la detection de voix : l'assistant repond des la fin de la phrase.
"""

from __future__ import annotations

import contextlib

from .i18n import STRINGS
from .text import log
from .vad import VADConfig, VADRecorder, pcm_to_audio_data

try:
    import speech_recognition as sr
except ImportError:  # pragma: no cover - speech_recognition non disponible
    sr = None  # type: ignore

ORDER_CLOUD_FIRST = ("google", "whisper")
ORDER_LOCAL_FIRST = ("whisper", "google")


# --------------------------------------------------------------------------- #
# Whisper local (optionnel)
# --------------------------------------------------------------------------- #
class WhisperBackend:
    """Enveloppe `faster-whisper`. Ne levate qu'a l'usage, pas a l'import."""

    def __init__(self, model_size: str = "base", language: str = "en",
                 compute_type: str = "int8"):
        self.model_size = model_size
        self.language = language
        self.compute_type = compute_type
        self._model = None
        self._error: str | None = None

    @staticmethod
    def available() -> bool:
        try:
            import faster_whisper  # noqa: F401
        except Exception:
            return False
        return True

    def ensure_loaded(self) -> bool:
        if self._model is not None:
            return True
        if self._error:
            return False
        try:
            from faster_whisper import WhisperModel

            log(f"[stt] {STRINGS['en']['whisper_loading']} ({self.model_size})")
            self._model = WhisperModel(self.model_size, device="cpu",
                                       compute_type=self.compute_type)
            return True
        except Exception as exc:
            self._error = f"{type(exc).__name__}: {exc}"
            log(f"[stt] Whisper indisponible: {self._error}")
            return False

    def transcribe(self, audio) -> str:
        if not self.ensure_loaded():
            raise RuntimeError(self._error or "Whisper indisponible")
        import numpy as np

        raw = audio.get_raw_data(convert_rate=16000, convert_width=2)
        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _info = self._model.transcribe(
            samples, language=self.language, beam_size=1, vad_filter=True,
        )
        return " ".join(segment.text.strip() for segment in segments).strip()


# --------------------------------------------------------------------------- #
# Transcription avec chaine de repli
# --------------------------------------------------------------------------- #
class Transcriber:
    """Essaie chaque moteur dans l'ordre jusqu'a une transcription exploitable."""

    def __init__(self, recognizer, strings: dict, order=ORDER_CLOUD_FIRST,
                 whisper: WhisperBackend | None = None):
        self.recognizer = recognizer
        self.strings = strings
        self.order = tuple(order)
        self.whisper = whisper
        self.last_backend: str | None = None

    def backends(self) -> list[str]:
        usable = []
        for name in self.order:
            if name == "google":
                usable.append(name)
            elif name == "whisper" and (self.whisper or WhisperBackend.available()):
                usable.append(name)
        return usable or ["google"]

    def transcribe(self, audio) -> tuple[str | None, str | None]:
        """Retourne (texte, erreur). L'erreur est None si un moteur a repondu."""
        errors: list[str] = []
        for name in self.backends():
            try:
                if name == "google":
                    text = self.recognizer.recognize_google(
                        audio, language=self.strings["google_lang"]
                    )
                else:
                    backend = self.whisper or WhisperBackend(
                        language=self.strings.get("whisper_lang", "en")
                    )
                    self.whisper = backend
                    text = backend.transcribe(audio)
                text = (text or "").strip()
                if text:
                    self.last_backend = name
                    return text, None
                errors.append(f"{name}:silence")
            except Exception as exc:
                errors.append(_classify(name, exc))
                if name == "google" and isinstance(exc, _unknown_value()):
                    # le son n'etait pas de la parole : inutile d'essayer Whisper
                    return None, "unintelligible"
                log(f"[stt] {name} a echoue: {exc}")

        for error in errors:
            if error.startswith("network:") or error.startswith("mic:"):
                return None, error
        return None, errors[-1] if errors else None


def _unknown_value():
    return (sr.UnknownValueError, sr.WaitTimeoutError) if sr else (Exception,)


def _classify(backend: str, exc: Exception) -> str:
    if sr is not None:
        if isinstance(exc, sr.UnknownValueError):
            return "unintelligible"
        if isinstance(exc, sr.RequestError):
            return f"network:{exc}"
    if isinstance(exc, (OSError, IOError)):
        return f"mic:{exc}"
    return f"{backend}:{type(exc).__name__}"


# --------------------------------------------------------------------------- #
# Ecoute au micro
# --------------------------------------------------------------------------- #
class SpeechToText:
    def __init__(self, recognizer, source, google_lang, phrase_limit: float = 6.0,
                 transcriber: Transcriber | None = None, strings: dict | None = None):
        self.recognizer = recognizer
        self.source = source
        self.google_lang = google_lang
        self.phrase_limit = phrase_limit
        self.strings = strings or {"google_lang": google_lang}
        self.transcriber = transcriber or Transcriber(recognizer, self.strings)

    def listen(self) -> tuple[str | None, str | None]:
        """Retourne (texte, erreur) ; (None, None) si l'on n'a rien saisi."""
        audio = None
        for attempt in (0, 1):
            try:
                audio = self.recognizer.listen(
                    self.source, phrase_time_limit=self.phrase_limit
                )
                break
            except sr.WaitTimeoutError:
                return None, None
            except (OSError, IOError) as exc:
                if attempt:  # deuxieme echec : micro perdu
                    return None, f"mic:{exc}"
                log(f"[stt] micro: {exc} - tentative de reouverture")
                self._reopen()
        if audio is None:
            return None, "mic:flux ferme"

        print("Processing...", flush=True)
        return self.transcriber.transcribe(audio)

    def _reopen(self) -> None:
        with contextlib.suppress(Exception):
            self.source.__exit__(None, None, None)
        self.source.__enter__()

    def calibrate(self, duration: float = 0.5) -> None:
        log(f"[stt] calibration du bruit ambiant ({duration}s)...")
        with contextlib.suppress(Exception):
            self.recognizer.adjust_for_ambient_noise(self.source, duration=duration)
        # on garde l'adaptation dynamique du seuil pendant l'ecoute
        self.recognizer.dynamic_energy_threshold = True
        log(f"[stt] seuil d'energie: {self.recognizer.energy_threshold:.0f}")


class VADSpeechToText(SpeechToText):
    """End-pointing par detection de voix (Horizon 5).

    Au lieu d'attendre une pause de duree fixe, on arrete l'enregistrement
    des que l'utilisateur se tait vraiment : reponse plus rapide et moins de
    phrases coupees.
    """

    def __init__(self, recognizer, source, google_lang, config: VADConfig | None = None,
                 phrase_limit: float = 6.0, transcriber: Transcriber | None = None,
                 strings: dict | None = None):
        super().__init__(recognizer, source, google_lang, phrase_limit,
                         transcriber, strings)
        self.config = config or VADConfig()
        self.recorder = None  # construit paresseusement (le flux doit etre ouvert)

    def _recorder(self) -> VADRecorder:
        if self.recorder is None:
            self.recorder = VADRecorder(self.source.stream, self.config)
            noise = self.recorder.calibrate()
            log(f"[vad] bruit de fond={noise:.0f} seuil={getattr(self.recorder.detector, 'threshold', lambda: 0)():.0f}")
        return self.recorder

    def listen(self) -> tuple[str | None, str | None]:
        try:
            recording = self._recorder().record()
        except Exception as exc:
            log(f"[stt] VAD: {exc} - retour au mode classique")
            self.recorder = None
            return super().listen()
        if recording is None:
            return None, None
        audio = pcm_to_audio_data(recording.pcm, self.config.sample_rate)
        print("Processing...", flush=True)
        return self.transcriber.transcribe(audio)


# --------------------------------------------------------------------------- #
# Fabrique
# --------------------------------------------------------------------------- #
def build_transcriber(recognizer, strings: dict, mode: str = "auto",
                      whisper_model: str = "base"):
    """`mode` : auto | google | whisper (voir `--stt`)."""
    if mode == "google":
        order = ("google",)
    elif mode == "whisper":
        order = ("whisper",)
    elif mode == "local":
        order = ORDER_LOCAL_FIRST
    else:
        order = ORDER_CLOUD_FIRST
    whisper = WhisperBackend(whisper_model, strings.get("whisper_lang", "en")) \
        if mode in ("whisper", "local") or WhisperBackend.available() else None
    return Transcriber(recognizer, strings, order=order, whisper=whisper)


__all__ = [
    "SpeechToText",
    "VADSpeechToText",
    "Transcriber",
    "WhisperBackend",
    "build_transcriber",
    "ORDER_CLOUD_FIRST",
    "ORDER_LOCAL_FIRST",
]
