"""Reconnaissance vocale (STT).

Trois moteurs, combinables :

  * **Google** (gratuit, sans cle) : tres bon en ligne, inutilisable hors-ligne ;
    son service gratuit renvoie parfois une reponse vide : on reessaie une fois ;
  * **Whisper local** (`faster-whisper`, optionnel) : fonctionne sans reseau et
    sans quota. Il est installe a la demande ::

       .\\.venv\\Scripts\\pip install faster-whisper

  * **Vosk local** (secours) : le petit modele deja utilise pour « Jarvis »
    transcrit aussi la question quand les autres echouent.

Jarvis tente les moteurs dans l'ordre demande (`--stt google|whisper|auto`)
et bascule sur le suivant quand l'un echoue (reseau coupe, quota, silence).

Le mode VAD (Horizon 5) remplace `recognizer.listen` par un enregistrement
pilote par la detection de voix : l'assistant repond des la fin de la phrase.
"""

from __future__ import annotations

import contextlib
import time

from . import hearing
from .i18n import STRINGS
from .text import log
from .vad import VADConfig, VADRecorder, pcm_to_audio_data

try:
    import speech_recognition as sr
except ImportError:  # pragma: no cover - speech_recognition non disponible
    sr = None  # type: ignore

ORDER_CLOUD_FIRST = ("google", "whisper", "vosk")
GOOGLE_GRACE = 0.6        # Whisper (Groq) a repondu : on attend Google au plus 0,6 s de plus
SHORT_COMMAND_WORDS = 5   # ... seulement pour une commande courte ou une phrase coupee
ORDER_LOCAL_FIRST = ("whisper", "vosk", "google")
GOOGLE_RETRY_DELAY = 0.3  # secondes avant de redemander a Google


class GroqWhisperBackend:
    """Whisper large v3 turbo sur Groq : ~0,6 s par phrase, ponctue, bon sur les noms.

    Mesure du 30/10/2026 : 0,5 a 1 s contre 1,5 a 2,3 s pour Google. Un
    vocabulaire (applications, villes, noms du profil) l'oriente vers les mots
    attendus (« Ouedraogo » au lieu de « WeDroggo »).
    """

    URL = "https://api.groq.com/openai/v1/audio/transcriptions"
    MODEL = "whisper-large-v3-turbo"
    # Phrases que Whisper invente sur du silence ou du bruit (apprises des sous-titres).
    HALLUCINATIONS = ("amara.org", "sous-titres", "sous-titrage", "merci d'avoir regardé",
                      "merci de votre attention", "abonnez-vous", "thanks for watching",
                      "subtitles by")

    def __init__(self, api_key: str, language: str = "fr", vocabulary: str = "",
                 session=None, timeout: float = 4.0):   # Whisper repond en < 1,5 s ; sinon Google
        self.api_key = api_key
        self.language = language
        self.vocabulary = vocabulary
        self.timeout = timeout
        self._session = session

    def _http(self):
        if self._session is None:
            import requests

            self._session = requests.Session()   # connexion gardee ouverte : plus rapide
        return self._session

    def warm(self) -> None:
        """Ouvre la connexion des le lancement (la 1re coute ~0,5 s de plus)."""
        import threading

        def run() -> None:
            try:
                self._http().get("https://api.groq.com/openai/v1/models",
                                 headers={"Authorization": f"Bearer {self.api_key}"}, timeout=8)
            except Exception:
                pass

        threading.Thread(target=run, name="jarvis-groq-chauffe", daemon=True).start()

    def transcribe(self, audio, prompt: str = "") -> str:
        wav = audio.get_wav_data(convert_rate=16000, convert_width=2)
        data = {"model": self.MODEL, "language": self.language, "temperature": "0",
                "response_format": "json"}
        vocabulary = " ".join(part for part in (self.vocabulary, prompt) if part).strip()
        if vocabulary:
            data["prompt"] = vocabulary[-600:]
        response = self._http().post(self.URL, headers={"Authorization": f"Bearer {self.api_key}"},
                                     files={"file": ("voix.wav", wav, "audio/wav")},
                                     data=data, timeout=self.timeout)
        response.raise_for_status()
        text = " ".join((response.json().get("text") or "").split())
        if any(marker in text.lower() for marker in self.HALLUCINATIONS):
            return ""
        return text


class VoskBackend:
    """Transcription locale avec le modele Vosk (secours hors-ligne)."""

    def __init__(self, language: str = "fr", model_path=None):
        self.language = language
        self.model_path = model_path

    @staticmethod
    def available(language: str = "fr") -> bool:
        from . import wake

        return wake.vosk_available() and wake.find_vosk_model(language) is not None

    def transcribe(self, audio) -> str:
        import json

        import vosk

        from . import wake

        path = self.model_path or wake.find_vosk_model(self.language)
        if path is None:
            raise RuntimeError("modele Vosk introuvable")
        recognizer = vosk.KaldiRecognizer(wake.load_vosk_model(path), 16000)
        recognizer.AcceptWaveform(audio.get_raw_data(convert_rate=16000, convert_width=2))
        return json.loads(recognizer.FinalResult() or "{}").get("text", "")


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
                 whisper: WhisperBackend | None = None, vosk: VoskBackend | None = None,
                 groq: GroqWhisperBackend | None = None):
        self.recognizer = recognizer
        self.strings = strings
        self.order = tuple(order)
        self.whisper = whisper
        self.vosk = vosk
        self.groq = groq           # Whisper sur Groq : en duo avec Google, le plus rapide gagne
        self.context = ""          # derniere reponse de Jarvis : oriente Whisper
        self.personal = ""         # noms propres des souvenirs (proches, ville...)
        self.last_backend: str | None = None
        self.last_heard: hearing.Heard | None = None   # hypotheses + confiance du dernier essai

    def backends(self) -> list[str]:
        usable = []
        for name in self.order:
            if name == "google":
                usable.append(name)
            elif name == "whisper" and (self.whisper or WhisperBackend.available()):
                usable.append(name)
            elif name == "vosk" and self.vosk is not None:
                usable.append(name)
        return usable or ["google"]

    def _google(self, audio) -> hearing.Heard:
        """Google, avec un second essai si sa reponse est vide (service gratuit)."""
        language = self.strings["google_lang"]
        try:
            return _google_once(self.recognizer, audio, language)
        except Exception as exc:
            if not _is_empty_reply(exc):
                raise
            log("[stt] reponse vide de Google : nouvel essai")
            time.sleep(GOOGLE_RETRY_DELAY)
            return _google_once(self.recognizer, audio, language)

    def transcribe(self, audio) -> tuple[str | None, str | None]:
        """Retourne (texte, erreur). L'erreur est None si un moteur a repondu."""
        if self.groq is not None and "google" in self.backends():
            duo = self._duo(audio)
            if duo is not None:
                return duo
        return self._in_order(audio)

    def _duo(self, audio):
        """Whisper (Groq) et Google en parallele : Whisper fait foi (2,5 x plus rapide),
        Google s'ajoute aux hypotheses s'il arrive dans la foulee."""
        import threading

        google: dict = {}

        def run_google() -> None:
            try:
                google["heard"] = self._google(audio)
            except Exception as exc:
                google["error"] = exc

        worker = threading.Thread(target=run_google, name="jarvis-google", daemon=True)
        worker.start()
        started = time.monotonic()
        try:
            prompt = " ".join(part for part in (self.personal, self.context) if part)
            text = hearing.correct(self.groq.transcribe(audio, prompt))
        except Exception as exc:
            log(f"[stt] Whisper (Groq) a echoue : {exc}")
            text = ""
        whisper_time = time.monotonic() - started
        if not text:                      # Whisper muet ou en panne : Google seul
            worker.join(10.0)
            return None if "heard" not in google else self._from_google(google["heard"])
        # Google n'est attendu que la ou une 2e hypothese sert vraiment : commande
        # courte (les commandes rapides essaient chaque hypothese) ou phrase coupee.
        # Pour une vraie question, le modele corrige seul : pas d'attente.
        if len(text.split()) <= SHORT_COMMAND_WORDS or hearing.seems_unfinished(text):
            worker.join(GOOGLE_GRACE)
        other = google.get("heard")
        alternatives = []
        if other is not None and other.text:
            alternatives = [alt for alt in [other.text] + list(other.alternatives)
                            if alt.lower().strip(" .!?") != text.lower().strip(" .!?")]
        self.last_backend = "groq"
        self.last_heard = hearing.Heard(text, alternatives[:4],
                                        other.confidence if other is not None else None)
        log(f"[stt] Whisper {whisper_time:.2f} s : « {text} »"
            + (f" | Google : « {alternatives[0]} »" if alternatives else ""))
        return text, None

    def _from_google(self, heard):
        if heard is None or not heard.text:
            return None
        self.last_backend, self.last_heard = "google", heard
        return heard.text, None

    def _in_order(self, audio) -> tuple[str | None, str | None]:
        errors: list[str] = []
        self.last_heard = None
        for name in self.backends():
            try:
                if name == "google":
                    heard = self._google(audio)
                    if heard is not None and heard.text:
                        self.last_backend, self.last_heard = name, heard
                        if heard.alternatives:
                            log(f"[stt] autres hypotheses : {' | '.join(heard.alternatives[:3])}")
                        return heard.text, None
                    text = ""
                elif name == "vosk":
                    text = self.vosk.transcribe(audio)
                else:
                    backend = self.whisper or WhisperBackend(
                        language=self.strings.get("whisper_lang", "en")
                    )
                    self.whisper = backend
                    text = backend.transcribe(audio)
                text = hearing.correct(text or "")
                if text:
                    self.last_backend = name
                    self.last_heard = hearing.Heard(text)
                    return text, None
                errors.append(f"{name}:silence")
            except Exception as exc:
                errors.append(_classify(name, exc))
                if name == "google" and isinstance(exc, _unknown_value()):
                    # le son n'etait pas de la parole : inutile d'essayer Whisper
                    return None, "unintelligible"
                log(f"[stt] {name} a echoue: {exc}")

        if errors:
            log(f"[stt] aucun moteur n'a compris ({', '.join(errors)})")
        for error in errors:
            if error.startswith("network:") or error.startswith("mic:"):
                return None, error
        return None, errors[-1] if errors else None


def _google_once(recognizer, audio, language) -> hearing.Heard:
    """Toutes les hypotheses de Google (show_all), avec leur confiance."""
    try:
        result = recognizer.recognize_google(audio, language=language, show_all=True)
    except TypeError:            # reconnaisseur sans show_all (doublures, anciennes versions)
        result = recognizer.recognize_google(audio, language=language)
    if isinstance(result, str):  # texte simple (vide = silence, comme avant)
        return hearing.Heard(hearing.correct(result))
    heard = hearing.from_google(result)
    if heard is None:
        if sr is not None:
            raise sr.UnknownValueError()
        raise ValueError("rien compris")
    return heard


def _is_empty_reply(exc: Exception) -> bool:
    """Reponse vide ou illisible de Google (« Expecting value... »)."""
    return isinstance(exc, ValueError) and not isinstance(exc, _unknown_value())


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

    def listen(self, timeout: float | None = None) -> tuple[str | None, str | None]:
        """Retourne (texte, erreur) ; (None, None) si l'on n'a rien saisi.

        `timeout` : delai max avant le debut de la parole (None = attendre).
        """
        text, error = self._listen_once(timeout)
        return self._complete(text, error)

    def _listen_once(self, timeout: float | None = None) -> tuple[str | None, str | None]:
        audio = None
        for attempt in (0, 1):
            try:
                extra = {"timeout": timeout} if timeout else {}
                audio = self.recognizer.listen(
                    self.source, phrase_time_limit=self.phrase_limit, **extra
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

    def _complete(self, text, error):
        """Phrase coupee (« ouvre le fichier de ») : on ecoute la suite un instant."""
        heard = getattr(self.transcriber, "last_heard", None) or (
            hearing.Heard(text) if text else None)
        for _ in range(hearing.CONTINUE_MAX):
            if not text or not hearing.seems_unfinished(text):
                break
            log(f"[stt] phrase inachevee « {text} » : j'ecoute la suite")
            try:
                more, _error = self._listen_once(timeout=hearing.CONTINUE_WAIT)
            except Exception:
                break
            if not more:
                break
            more_heard = getattr(self.transcriber, "last_heard", None) or hearing.Heard(more)
            heard = hearing.join(heard, more_heard)
            text = heard.text
            log(f"[stt] phrase complete : « {text} »")
        if heard is not None and hasattr(self.transcriber, "last_heard"):
            self.transcriber.last_heard = heard
        return text, error

    def continue_heard(self, text):
        """Audio deja enregistre (mot d'activation) : ecoute la suite si la phrase est coupee."""
        return self._complete(text, None)[0]

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

    def listen(self, timeout: float | None = None) -> tuple[str | None, str | None]:
        # Le VAD a deja son propre delai de debut de parole.
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
        text, error = self.transcriber.transcribe(audio)
        return self._complete(text, error)


# --------------------------------------------------------------------------- #
# Fabrique
# --------------------------------------------------------------------------- #
def build_transcriber(recognizer, strings: dict, mode: str = "auto",
                      whisper_model: str = "base", groq_key: str = ""):
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
    language = strings.get("whisper_lang", "en")
    vosk = VoskBackend(language) if mode != "google" and VoskBackend.available(language) \
        else None
    if vosk is not None and "vosk" not in order:
        order = tuple(order) + ("vosk",)
    groq = None
    if groq_key and mode in ("auto", "google", "groq"):
        groq = GroqWhisperBackend(groq_key, language, hearing.vocabulary(language))
        groq.warm()
        log("[stt] Whisper sur Groq + Google en parallele")
    return Transcriber(recognizer, strings, order=order, whisper=whisper, vosk=vosk,
                       groq=groq)


__all__ = [
    "SpeechToText",
    "VADSpeechToText",
    "Transcriber",
    "WhisperBackend",
    "VoskBackend",
    "GroqWhisperBackend",
    "build_transcriber",
    "ORDER_CLOUD_FIRST",
    "ORDER_LOCAL_FIRST",
]
