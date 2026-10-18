"""Synthese vocale (TTS).

`pyttsx3` s'appuie sur SAPI5 sous Windows : la voix fonctionne **hors-ligne**,
sans cle ni compte. C'est donc deja le mode "local" de l'Horizon 4.

Trois fonctions sont exposees :

  * ``Speech``      : parle phrase par phrase, avec veille (watchdog) et
                      interruption (barge-in) quand un micro est ouvert ;
  * ``SilentSpeech``: repli quand aucun moteur TTS n'est disponible (headless,
                      serveur, machine sans voix installee) : Jarvis continue
                      de fonctionner a l'ecrit au lieu de planter ;
  * ``pick_voice``  : choisit une voix adaptee a la langue.
"""

from __future__ import annotations

import threading
import time

from .i18n import STRINGS
from .text import clean_text, log, rms

DEFAULT_RATE = 200
DEFAULT_VOLUME = 1.0


# --------------------------------------------------------------------------- #
# Choix de la voix
# --------------------------------------------------------------------------- #
def pick_voice(engine, lang: str, hints: list[str] | None = None) -> str | None:
    """Choisit une voix adaptee a la langue, a defaut la premiere disponible."""
    voices = engine.getProperty("voices") or []
    if not voices:
        return None

    if hints is None:
        hints = STRINGS.get(lang, STRINGS["en"])["voice_hints"]

    def blob(voice) -> str:
        parts = [str(getattr(voice, "id", "")), str(getattr(voice, "name", ""))]
        parts += [str(item) for item in (getattr(voice, "languages", None) or [])]
        return " ".join(parts).lower()

    for hint in hints:
        for voice in voices:
            if hint in blob(voice):
                return voice.id
    for voice in voices:
        if lang.lower() in blob(voice):
            return voice.id
    return voices[0].id


def make_engine_factory(voice_id: str | None, volume: float = DEFAULT_VOLUME,
                        rate: int = DEFAULT_RATE):
    """Retourne une fabrique de moteurs pyttsx3 preconfiguree."""
    volume = min(max(volume, 0.0), 1.0)
    rate = min(max(int(rate), 20), 500)

    def factory():
        import pyttsx3

        engine = pyttsx3.init()
        engine.setProperty("volume", volume)
        engine.setProperty("rate", rate)
        if voice_id:
            try:
                engine.setProperty("voice", voice_id)
            except Exception as exc:
                log(f"[tts] voix '{voice_id}' refusee: {exc}")
        return engine

    return factory


def list_voices() -> list[tuple[str, str]]:
    """Liste (id, nom) des voix disponibles ; [] si le moteur est absent."""
    try:
        import pyttsx3

        engine = pyttsx3.init()
    except Exception:
        return []
    voices = engine.getProperty("voices") or []
    return [(str(v.id), str(getattr(v, "name", ""))) for v in voices]


def available() -> bool:
    """Vrai si un moteur TTS est utilisable sur cette machine."""
    try:
        import pyttsx3

        pyttsx3.init()
        return True
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# Moteur sans voix (repli)
# --------------------------------------------------------------------------- #
class SilentSpeech:
    """Interface identique a ``Speech`` mais se contente d'ecrire le texte."""

    def __init__(self, reason: str = ""):
        self.reason = reason
        self.interrupted = threading.Event()
        self.speaking = False

    def begin(self) -> None:
        self.interrupted.clear()

    def say(self, text: str) -> None:
        text = clean_text(text)
        if not text or self.interrupted.is_set():
            return
        log("Jarvis: " + text)

    def cancel(self) -> None:
        self.interrupted.set()

    def close(self) -> None:
        self.cancel()


# --------------------------------------------------------------------------- #
# Moteur vocal complet
# --------------------------------------------------------------------------- #
class Speech:
    """Encapsule pyttsx3 : parle phrase par phrase, coupe si on l'interrompt."""

    def __init__(self, engine_factory, source=None, bargein: bool = True,
                 watchdog_seconds: float = 30.0):
        self._factory = engine_factory
        self.engine = engine_factory()
        self.source = source            # Microphone ouvert (None en mode texte)
        self.bargein = bargein
        self.watchdog_seconds = watchdog_seconds
        self.interrupted = threading.Event()
        self.speaking = False
        self._stop = threading.Event()
        self._monitor: threading.Thread | None = None
        self._watchdog: threading.Timer | None = None
        self._reinit = False
        self._muted = False
        self._closed = False
        self._lock = threading.Lock()

    # -- cycle d'une reponse ------------------------------------------------ #
    def begin(self) -> None:
        """Appele au debut de chaque reponse : rearme l'interruption."""
        self.interrupted.clear()
        if self._reinit and not self._closed:
            self._reinit = False
            try:
                self.engine = self._factory()
            except Exception as exc:  # pragma: no cover - depend du driver TTS
                log(f"[tts] reinitialisation impossible: {exc}")

    def say(self, text: str) -> None:
        text = clean_text(text)
        if not text:
            return
        if self.interrupted.is_set():
            if not self._muted:
                self._muted = True
                log("[tts] (reponse coupee par l'utilisateur)")
            return
        self._muted = False
        log("Jarvis: " + text)
        self.speaking = True
        self._arm()
        try:
            with self._lock:
                self.engine.say(text)
                self.engine.runAndWait()
        except Exception as exc:
            log(f"[tts] {exc}")
        finally:
            self.speaking = False
            self._disarm()

    def cancel(self) -> None:
        """Coupe la synthese en cours et ignore les phrases restantes."""
        self.interrupted.set()
        try:
            self.engine.stop()
        except Exception:
            pass
        # pyttsx3 peut laisser le moteur dans un etat fragile apres stop() :
        # on le recree au prochain tour.
        self._reinit = True

    def close(self) -> None:
        self._closed = True
        self.cancel()
        self._disarm()

    # -- armement / desarmement -------------------------------------------- #
    def _arm(self) -> None:
        self._disarm()
        self._stop.clear()
        if self.watchdog_seconds and self.watchdog_seconds > 0:
            self._watchdog = threading.Timer(self.watchdog_seconds, self._on_timeout)
            self._watchdog.daemon = True
            self._watchdog.start()
        if self.bargein and self.source is not None:
            self._monitor = threading.Thread(target=self._monitor_levels, daemon=True)
            self._monitor.start()

    def _disarm(self) -> None:
        self._stop.set()
        if self._watchdog is not None:
            self._watchdog.cancel()
            self._watchdog = None
        if self._monitor is not None and threading.current_thread() is not self._monitor:
            self._monitor.join(timeout=2.0)
            self._monitor = None

    def _on_timeout(self) -> None:
        if not self._stop.is_set():
            log(f"[tts] reponse > {self.watchdog_seconds:.0f}s : coupure")
            self.cancel()

    def _monitor_levels(self) -> None:
        """Detecte la parole de l'utilisateur pendant que Jarvis parle.

        Le seuil est etabli sur les 0.6s initiales (niveau de la voix de
        sortie qui revient dans le micro) puis on attend un depassement
        soutenu. Toute erreur desactive le barge-in sans planter l'appli.
        """
        try:
            stream = self.source.stream
            chunk = 1024
            levels: list[float] = []
            deadline = time.time() + 0.6
            while time.time() < deadline and not self._stop.is_set():
                # MicrophoneStream.read(size) gere lui-meme les overflows
                levels.append(rms(stream.read(chunk)))
            if not levels:
                return
            baseline = sorted(levels)[len(levels) // 2]
            threshold = max(baseline * 1.6, baseline + 400, 900.0)
            above = 0
            while not self._stop.is_set():
                level = rms(stream.read(chunk))
                above = above + 1 if level >= threshold else 0
                if above >= 5:
                    log("[barge-in] interruption detectee")
                    self.cancel()
                    return
        except Exception as exc:
            log(f"[barge-in] desactive: {exc}")
            self.bargein = False


def build_speech(args, strings, source=None) -> object:
    """Choisit ``Speech`` ou ``SilentSpeech`` selon ce que la machine propose."""
    from . import tts as _self

    if not _self.available():
        log("[tts] aucun moteur vocal : Jarvis repond a l'ecrit")
        return SilentSpeech("pyttsx3 indisponible")

    voice_id = args.voice or pick_voice(_init_for_voices(), args.lang)
    factory = make_engine_factory(voice_id, args.volume, args.rate)
    return Speech(
        factory,
        source=source,
        bargein=bool(args.bargein) and source is not None,
        watchdog_seconds=args.max_speak,
    )


def _init_for_voices():
    import pyttsx3

    return pyttsx3.init()


__all__ = [
    "DEFAULT_RATE",
    "DEFAULT_VOLUME",
    "Speech",
    "SilentSpeech",
    "pick_voice",
    "make_engine_factory",
    "list_voices",
    "available",
    "build_speech",
]
