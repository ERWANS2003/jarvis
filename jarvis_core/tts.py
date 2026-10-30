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

import math
import queue
import sys
import threading
import time
from pathlib import Path

from .i18n import STRINGS
from .speakable import speakable
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


class SapiEngine:
    """Voix Windows (SAPI5) pilotee directement, sans pyttsx3.

    pyttsx3 a deux defauts genants sous Windows : apres le premier
    `runAndWait()`, les suivants rendent la main sans parler, et `stop()`
    depuis un autre fil peut tout bloquer. Ici, la phrase est lancee en mode
    asynchrone puis surveillee par petits pas : `stop()` (appelable depuis
    n'importe quel fil) leve un drapeau, et le fil vocal purge la file SAPI.
    Meme interface que le moteur pyttsx3 (`say`, `runAndWait`, `stop`).
    """

    SPEAK_ASYNC = 1
    PURGE = 2 | 1  # SVSFPurgeBeforeSpeak | SVSFlagsAsync

    def __init__(self, voice=None, volume: float = DEFAULT_VOLUME,
                 rate: int = DEFAULT_RATE, voice_id: str | None = None):
        if voice is None:
            import comtypes.client

            voice = comtypes.client.CreateObject("SAPI.SpVoice")
        self.voice = voice
        self._pending: list[str] = []
        self._stop = threading.Event()
        self.voice.Volume = round(min(max(volume, 0.0), 1.0) * 100)
        self.voice.Rate = self.sapi_rate(rate)
        if voice_id:
            self.select_voice(voice_id)

    @staticmethod
    def sapi_rate(words_per_minute: int) -> int:
        """Mots/minute -> echelle SAPI (-10..10, 0 ~ 200 mots/minute)."""
        wpm = max(int(words_per_minute or DEFAULT_RATE), 20)
        return max(-10, min(10, round(10 * math.log2(wpm / DEFAULT_RATE))))

    def select_voice(self, voice_id: str) -> bool:
        tokens = self.voice.GetVoices()
        for index in range(tokens.Count):
            token = tokens.Item(index)
            if token.Id == voice_id or token.Id.endswith("\\" + voice_id):
                self.voice.Voice = token
                return True
        log(f"[tts] voix '{voice_id}' introuvable")
        return False

    def say(self, text: str) -> None:
        self._pending.append(text)

    def runAndWait(self) -> None:  # noqa: N802 - interface pyttsx3
        self._stop.clear()
        pending, self._pending = self._pending, []
        for text in pending:
            self.voice.Speak(text, self.SPEAK_ASYNC)
            while not self.voice.WaitUntilDone(50):
                if self._stop.is_set():
                    self.voice.Speak("", self.PURGE)
                    return
            if self._stop.is_set():
                return

    def stop(self) -> None:
        self._pending = []
        self._stop.set()


def sapi_available() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import comtypes.client  # noqa: F401  (installe avec pyttsx3)
    except Exception:
        return False
    return True


# --------------------------------------------------------------------------- #
# Piper : voix neuronale, naturelle et hors-ligne
# --------------------------------------------------------------------------- #
VOICES_DIR = Path(__file__).resolve().parent.parent / "voices"
PIPER_DEFAULT_VOICES = {"fr": "fr_FR-siwis-medium", "en": "en_US-lessac-medium"}


def find_piper_voice(lang: str, explicit: str | None = None,
                     directory: Path | None = None) -> Path | None:
    """Modele Piper (.onnx) a utiliser : explicite, sinon le premier de la langue.

    `explicit` peut etre un chemin ou un simple nom (`fr_FR-siwis-medium`)
    cherche dans le dossier `voices/` du projet.
    """
    directory = Path(directory or VOICES_DIR)
    if explicit:
        path = Path(explicit)
        candidates = [path, directory / path, directory / f"{explicit}.onnx"]
        for candidate in candidates:
            if candidate.suffix == ".onnx" and candidate.is_file():
                return candidate
        return None
    if not directory.is_dir():
        return None
    preferred = directory / f"{PIPER_DEFAULT_VOICES.get(lang, '')}.onnx"
    if preferred.is_file():
        return preferred
    prefix = f"{lang}_"
    matches = sorted(child for child in directory.glob("*.onnx")
                     if child.name.lower().startswith(prefix))
    return matches[0] if matches else None


def split_voice(spec: str | None) -> tuple[str | None, str | None]:
    """« fr_FR-upmc-medium:pierre » -> ("fr_FR-upmc-medium", "pierre").

    Un chemin Windows (« C:\\voix\\x.onnx ») n'est pas coupe sur son « : ».
    """
    if not spec:
        return None, None
    head, sep, tail = spec.rpartition(":")
    if sep and head and tail and "\\" not in tail and "/" not in tail \
            and not tail.lower().endswith(".onnx") and len(head) > 1:
        return head, tail
    return spec, None


def piper_speaker_id(model_path, speaker: str | int | None) -> int | None:
    """Numero du locuteur `speaker` (nom ou numero) dans une voix multi-locuteurs."""
    if speaker is None or speaker == "":
        return None
    if isinstance(speaker, int) or str(speaker).isdigit():
        return int(speaker)
    try:
        import json

        config = json.loads(Path(f"{model_path}.json").read_text(encoding="utf-8"))
    except Exception:
        return None
    mapping = {str(k).lower(): v for k, v in (config.get("speaker_id_map") or {}).items()}
    return mapping.get(str(speaker).lower())


def installed_voices(lang: str, directory: Path | None = None,
                     max_speakers: int = 4) -> list[tuple[str, str]]:
    """Voix Piper de la langue presentes dans voices/ : [(libelle, spec), ...].

    Les voix a quelques locuteurs (upmc : jessica, pierre) sont detaillees ;
    celles qui en ont des dizaines (mls) sont proposees avec leur voix par defaut.
    """
    import json

    from . import voice_kokoro

    directory = Path(directory or VOICES_DIR)
    voices: list[tuple[str, str]] = voice_kokoro.voices_for(lang) if directory == VOICES_DIR \
        else []
    if not directory.is_dir():
        return voices
    for model in sorted(directory.glob(f"{lang}_*.onnx")):
        name = model.stem
        short = name.split("-")[1] if "-" in name else name
        try:
            config = json.loads(Path(f"{model}.json").read_text(encoding="utf-8"))
        except Exception:
            config = {}
        speakers = list((config.get("speaker_id_map") or {}).keys())
        if 1 < len(speakers) <= max_speakers:
            voices += [(f"{short} · {speaker}", f"{name}:{speaker}") for speaker in speakers]
        else:
            voices.append((short, name))
    return voices


def factory_for(spec: str, args, lang: str):
    """Fabrique de moteur pour un choix du menu (« sapi » ou « modele:locuteur »)."""
    volume = getattr(args, "volume", DEFAULT_VOLUME)
    rate = getattr(args, "rate", DEFAULT_RATE) or DEFAULT_RATE
    if spec == "sapi":
        voice_id = getattr(args, "voice", None)
        if not voice_id:
            try:
                voice_id = pick_voice(_init_for_voices(), lang)
            except Exception:
                voice_id = None
        return make_engine_factory(voice_id, volume, rate, backend="sapi")
    if spec.startswith("kokoro:"):
        return make_engine_factory(None, volume, rate, backend="auto",
                                   piper_model=find_piper_voice(lang, None),
                                   kokoro_voice=spec.split(":", 1)[1], lang=lang)
    name, speaker = split_voice(spec)
    model = find_piper_voice(lang, name)
    if model is None:
        raise ValueError(f"voix introuvable : {spec}")
    return make_engine_factory(None, volume, rate, backend="piper", piper_model=model,
                               piper_speaker=piper_speaker_id(model, speaker))


def piper_available() -> bool:
    try:
        import piper  # noqa: F401
        import pyaudio  # noqa: F401
    except Exception:
        return False
    return True


class PiperEngine:
    """Voix Piper jouee par PyAudio, avec la meme interface que pyttsx3.

    Le modele est charge une seule fois. Le son est ecrit par petits blocs :
    `stop()` (appelable depuis n'importe quel fil) coupe donc la phrase en
    moins d'un dixieme de seconde.
    """

    BLOCK_FRAMES = 1024
    # Reglages « naturels » (ecoutes le 29/10/2026) : un peu plus de variation
    # d'intonation et de duree des sons que le defaut (0,667 / 0,8), un debit a
    # peine plus pose, et une respiration entre deux phrases.
    NOISE_SCALE = 0.75
    NOISE_W_SCALE = 0.9
    PACE = 1.05
    SENTENCE_PAUSE = 0.22      # secondes de silence apres chaque phrase

    def __init__(self, model_path, volume: float = DEFAULT_VOLUME,
                 rate: int = DEFAULT_RATE, voice=None, audio=None,
                 speaker_id: int | None = None):
        if voice is None:
            from piper import PiperVoice

            voice = PiperVoice.load(str(model_path))
        if audio is None:
            import pyaudio

            audio = pyaudio.PyAudio()
        self.voice = voice
        self.audio = audio
        self.volume = min(max(volume, 0.0), 1.0)
        # Plus `length_scale` est grand, plus la voix est lente.
        self.length_scale = DEFAULT_RATE / max(int(rate or DEFAULT_RATE), 20)
        self.speaker_id = speaker_id   # voix a plusieurs locuteurs (None = defaut)
        self.sample_rate = int(voice.config.sample_rate)
        self._pending: list[str] = []
        self._stop = threading.Event()
        self.level = 0.0  # volume du bloc en cours (0..1), pour animer l'orbe

    def say(self, text: str) -> None:
        self._pending.append(text)

    def _chunks(self, text: str):
        config = None
        try:
            from piper import SynthesisConfig

            config = SynthesisConfig(length_scale=self.length_scale * self.PACE,
                                     noise_scale=self.NOISE_SCALE,
                                     noise_w_scale=self.NOISE_W_SCALE,
                                     volume=self.volume, speaker_id=self.speaker_id)
        except Exception:
            config = None
        for chunk in self.voice.synthesize(text, syn_config=config):
            yield chunk.audio_int16_bytes

    def runAndWait(self) -> None:  # noqa: N802 - interface pyttsx3
        self._stop.clear()
        pending, self._pending = self._pending, []
        if not pending:
            return
        stream = self.audio.open(format=8, channels=1, rate=self.sample_rate,
                                 output=True)  # 8 = paInt16
        try:
            block = self.BLOCK_FRAMES * 2
            for text in pending:
                for audio in self._chunks(text):
                    for start in range(0, len(audio), block):
                        if self._stop.is_set():
                            return
                        chunk = audio[start:start + block]
                        self.level = audio_level(chunk)
                        stream.write(chunk)
                if self._stop.is_set():
                    return
                self.level = 0.0
                stream.write(b"\x00\x00" * int(self.sample_rate * self.SENTENCE_PAUSE))
        finally:
            self.level = 0.0
            try:
                stream.stop_stream()
                stream.close()
            except Exception:
                pass

    def stop(self) -> None:
        self._pending = []
        self._stop.set()


def audio_level(chunk: bytes) -> float:
    """Volume (0..1) d'un bloc PCM 16 bits : racine de la moyenne des carres."""
    import array

    samples = array.array("h", chunk[: len(chunk) - len(chunk) % 2])
    if not samples:
        return 0.0
    rms = math.sqrt(sum(x * x for x in samples) / len(samples))
    return min(1.0, rms / 7000.0)


def make_engine_factory(voice_id: str | None, volume: float = DEFAULT_VOLUME,
                        rate: int = DEFAULT_RATE, backend: str = "auto",
                        piper_model=None, piper_speaker: int | None = None,
                        kokoro_voice: str | None = None, lang: str = "fr"):
    """Retourne une fabrique de moteurs vocaux preconfiguree.

    `backend` : ``"piper"`` (voix neuronale, `piper_model` requis), ``"sapi"``
    (voix Windows en direct), ``"pyttsx3"``, ou ``"auto"`` : Piper si un
    modele est fourni, sinon SAPI sous Windows, sinon pyttsx3. Chaque etape
    retombe sur la suivante en cas d'echec.
    """
    volume = min(max(volume, 0.0), 1.0)
    rate = min(max(int(rate), 20), 500)
    use_piper = backend == "piper" or (backend == "auto" and piper_model is not None)
    use_sapi = backend == "sapi" or (backend in ("auto", "piper") and sapi_available())

    def factory():
        if kokoro_voice and backend in ("auto", "kokoro"):
            try:
                from .voice_kokoro import KokoroEngine

                return KokoroEngine(kokoro_voice, lang=lang, rate=rate, volume=volume)
            except Exception as exc:
                log(f"[tts] Kokoro indisponible ({exc}) : voix Piper")
        if use_piper and piper_model is not None:
            try:
                return PiperEngine(piper_model, volume=volume, rate=rate,
                                   speaker_id=piper_speaker)
            except Exception as exc:
                log(f"[tts] Piper indisponible ({exc}) : voix Windows")
        if use_sapi:
            try:
                return SapiEngine(volume=volume, rate=rate, voice_id=voice_id)
            except Exception as exc:
                if backend == "sapi":
                    raise
                log(f"[tts] SAPI indisponible ({exc}) : repli sur pyttsx3")
        import pyttsx3

        # `pyttsx3.init()` renvoie un moteur deja cree s'il en existe un, peut-
        # etre dans un autre fil : on en construit un neuf quand c'est possible.
        engine_class = getattr(pyttsx3, "Engine", None)
        engine = engine_class() if engine_class is not None else pyttsx3.init()
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
def _com_init() -> None:
    """Prepare COM pour SAPI5 dans le fil courant (Windows ; sinon rien)."""
    try:
        import comtypes

        comtypes.CoInitialize()
    except Exception:
        pass


class Speech:
    """Encapsule pyttsx3 : parle phrase par phrase, coupe si on l'interrompt.

    SAPI5 (Windows) ne parle que dans le fil qui a cree le moteur : appele
    depuis un autre fil, `runAndWait()` rend la main sans un son. Or la
    fenetre, la page web et l'orbe jouent chaque tour dans un fil different.
    Un fil vocal dedie cree donc le moteur et execute *tous* ses appels ;
    `say()` lui confie la phrase et attend qu'elle soit prononcee.
    """

    def __init__(self, engine_factory, source=None, bargein: bool = True,
                 watchdog_seconds: float = 30.0, lang: str = "fr"):
        self.lang = lang          # langue de la forme parlee (speakable)
        self.pace = load_pace()   # debit choisi a la voix (« parle plus lentement »)
        self._factory = engine_factory
        self._jobs: queue.Queue = queue.Queue()
        self._voice_thread = threading.Thread(target=self._voice_loop,
                                              name="jarvis-voice", daemon=True)
        self._voice_thread.start()
        self.engine = self._run(engine_factory)
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

    # -- fil vocal ---------------------------------------------------------- #
    def _voice_loop(self) -> None:
        _com_init()
        while True:
            job = self._jobs.get()
            if job is None:
                return
            func, box, done = job
            try:
                box["value"] = func()
            except BaseException as exc:  # renvoye a l'appelant
                box["error"] = exc
            finally:
                done.set()

    def _run(self, func):
        """Execute `func` dans le fil vocal et renvoie son resultat."""
        if threading.current_thread() is self._voice_thread:
            return func()
        box: dict = {}
        done = threading.Event()
        self._jobs.put((func, box, done))
        done.wait()
        if "error" in box:
            raise box["error"]
        return box.get("value")

    def _speak_now(self, text: str) -> None:
        apply_pace(self.engine, getattr(self, "pace", 1.0))
        self.engine.say(text)
        self.engine.runAndWait()

    def change_pace(self, factor: float) -> float:
        """« Parle plus lentement / plus vite » : multiplie le debit, le retient."""
        self.pace = min(max(getattr(self, "pace", 1.0) * factor, PACE_MIN), PACE_MAX)
        save_pace(self.pace)
        return self.pace

    def prefetch(self, text: str) -> None:
        """Annonce la phrase suivante : un moteur lent (Kokoro) la calcule pendant
        que la phrase en cours est dite. Sans effet pour les autres voix."""
        engine = getattr(self, "engine", None)
        if engine is None or not hasattr(engine, "prefetch") or self.interrupted.is_set():
            return
        text = clean_text(text)
        if text:
            try:
                engine.prefetch(speakable(text, getattr(self, "lang", "fr")) or text)
            except Exception as exc:
                log(f"[tts] anticipation impossible : {exc}")

    def set_factory(self, factory) -> None:
        """Change de voix : le nouveau moteur est cree au prochain `begin()`."""
        self._factory = factory
        self._reinit = True

    @property
    def level(self) -> float | None:
        """Volume de la voix en cours (0..1), ou None si le moteur ne le dit pas."""
        value = getattr(self.engine, "level", None)
        return None if value is None else float(value)

    # -- cycle d'une reponse ------------------------------------------------ #
    def begin(self) -> None:
        """Appele au debut de chaque reponse : rearme l'interruption."""
        self.interrupted.clear()
        if self._reinit and not self._closed:
            self._reinit = False
            try:
                self.engine = self._run(self._factory)
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
        spoken = speakable(text, getattr(self, "lang", "fr")) or text   # ce qu'on dit vraiment
        self.speaking = True
        self._arm()
        try:
            with self._lock:
                self._run(lambda: self._speak_now(spoken))
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
        self._jobs.put(None)  # termine le fil vocal

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


PACE_MIN, PACE_MAX = 0.7, 1.4
PACE_FILE = Path(__file__).resolve().parent.parent / ".jarvis_voice.json"


def load_pace() -> float:
    import json

    try:
        value = float(json.loads(PACE_FILE.read_text(encoding="utf-8")).get("pace", 1.0))
    except Exception:
        return 1.0
    return min(max(value, PACE_MIN), PACE_MAX)


def save_pace(pace: float) -> None:
    import json

    try:
        PACE_FILE.write_text(json.dumps({"pace": round(pace, 3)}), encoding="utf-8")
    except Exception:
        pass


def apply_pace(engine, pace: float) -> None:
    """Applique le debit choisi au moteur courant (Kokoro : vitesse, Piper : duree)."""
    if engine is None:
        return
    if hasattr(engine, "speed"):                       # Kokoro
        base = getattr(engine, "_base_speed", None)
        if base is None:
            base = engine._base_speed = engine.speed
        engine.speed = base * pace
    elif hasattr(engine, "length_scale"):              # Piper
        base = getattr(engine, "_base_length", None)
        if base is None:
            base = engine._base_length = engine.length_scale
        engine.length_scale = base / pace


class SpeechPipe:
    """Fait parler `speech` phrase apres phrase, dans un fil a part.

    Le tour peut ainsi continuer a lire la reponse du modele pendant que Jarvis
    parle, et chaque nouvelle phrase est annoncee d'avance (`prefetch`) : avec
    Kokoro, plus de blanc entre deux phrases. `close()` attend la fin.
    """

    def __init__(self, speech):
        self.speech = speech
        self._queue: queue.Queue = queue.Queue()
        self._thread = threading.Thread(target=self._run, name="jarvis-pipe", daemon=True)
        self._thread.start()

    def push(self, text: str) -> None:
        prefetch = getattr(self.speech, "prefetch", None)
        if prefetch is not None:
            prefetch(text)
        self._queue.put(text)

    def _run(self) -> None:
        while True:
            text = self._queue.get()
            if text is None:
                return
            try:
                self.speech.say(text)
            except Exception as exc:
                log(f"[tts] {exc}")

    def close(self, timeout: float | None = None) -> None:
        self._queue.put(None)
        self._thread.join(timeout)


def build_speech(args, strings, source=None) -> object:
    """Choisit ``Speech`` ou ``SilentSpeech`` selon ce que la machine propose."""
    from . import tts as _self

    if not _self.available():
        log("[tts] aucun moteur vocal : Jarvis repond a l'ecrit")
        return SilentSpeech("pyttsx3 indisponible")

    voice_id = args.voice or pick_voice(_init_for_voices(), args.lang)
    backend = getattr(args, "tts", None) or "auto"
    piper_model = None
    piper_speaker = None
    kokoro_voice = None
    chosen = getattr(args, "piper_voice", None) or ""
    if backend == "kokoro" or (backend == "auto" and chosen.startswith("kokoro:")):
        from . import voice_kokoro

        if voice_kokoro.available():
            kokoro_voice = chosen.split(":", 1)[1] if chosen.startswith("kokoro:") \
                else voice_kokoro.DEFAULT_VOICE.get(args.lang, "ff_siwis")
            log(f"[tts] voix Kokoro : {kokoro_voice} (reseau de neurones local)")
        else:
            log("[tts] Kokoro non installe : voix Piper")
        chosen = ""
    if backend in ("auto", "piper", "kokoro") and piper_available():
        name, speaker = split_voice(chosen or None)
        piper_model = find_piper_voice(args.lang, name)
        if piper_model is not None:
            piper_speaker = piper_speaker_id(piper_model, speaker)
            if speaker and piper_speaker is None:
                log(f"[tts] locuteur « {speaker} » inconnu dans {piper_model.stem}")
            log(f"[tts] voix Piper{' (secours)' if kokoro_voice else ''} : {piper_model.stem}"
                + (f" ({speaker})" if piper_speaker is not None else ""))
        elif backend == "piper":
            log("[tts] aucun modele Piper dans voices/ : voix Windows")
    factory = make_engine_factory(voice_id, args.volume, args.rate,
                                  backend="auto" if backend == "kokoro" else backend,
                                  piper_model=piper_model, piper_speaker=piper_speaker,
                                  kokoro_voice=kokoro_voice, lang=args.lang)
    return Speech(
        factory,
        source=source,
        bargein=bool(args.bargein) and source is not None,
        watchdog_seconds=args.max_speak,
        lang=getattr(args, "lang", "fr"),
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
