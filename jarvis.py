"""Jarvis - assistant vocal.

Point d'entree du programme : il relie la logique reutilisable de
:mod:`jarvis_core` a une boucle de conversation (micro -> modele -> voix).

Horizons couverts
-----------------
1. Base : voix locale (SAPI5 via pyttsx3), reconnaissance (Google), mot
   d'activation tolerant aux fautes, barge-in, historique JSON.
2. Memoire longue duree : souvenirs persistants (SQLite), profil utilisateur,
   recherche de souvenirs, resumes automatiques de conversation.
3. Outils et actions : meteo, heure, calcul, minuteur/rappel, Wikipedia,
   recherche web, ouverture d'applications (graphe ReAct).
4. Mode local : reconnaissance hors-ligne (faster-whisper), voix hors-ligne
   (c'est deja le cas), modele local (Ollama) et bascule automatique
   cloud -> local quand la cle est epuisee ou le reseau tombe.
5. Voix temps reel : detection d'activite vocale (end-pointing), latence
   reduite et interruption instantanee.
6. Application : configuration par fichier, plugins, interface graphique,
   demarrage automatique, installation en un clic.

Utilisation rapide
------------------
    .venv\\Scripts\\python.exe jarvis.py --text          # mode texte
    .venv\\Scripts\\python.exe jarvis.py --lang fr       # en francais
    .venv\\Scripts\\python.exe jarvis.py --vad           # end-pointing VAD
    .venv\\Scripts\\python.exe jarvis.py --help
"""

from __future__ import annotations

import argparse
import contextlib
import sys
import threading
import time
from pathlib import Path

# Certaines consoles Windows n'acceptent pas tous les caracteres (et une sortie
# redirigee vers un fichier peut planter) : on remplace au lieu d'echouer.
for _stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(Exception):
        _stream.reconfigure(errors="replace")

from dotenv import find_dotenv, load_dotenv

_ = load_dotenv(find_dotenv())

from langchain_core.messages import AIMessage, HumanMessage  # noqa: E402

from jarvis_core import config as config_mod  # noqa: E402
from jarvis_core import graph as graphs  # noqa: E402
from jarvis_core import intents  # noqa: E402
from jarvis_core import orb_themes  # noqa: E402
from jarvis_core import quiz as quiz_mod  # noqa: E402
from jarvis_core import hearing as hearing_mod  # noqa: E402
from jarvis_core import smart  # noqa: E402
from jarvis_core.text import is_daily_quota, is_offline, quota_reset  # noqa: E402
from jarvis_core import notify as notify_mod  # noqa: E402
from jarvis_core import plugins as plugins_mod  # noqa: E402
from jarvis_core import providers  # noqa: E402
from jarvis_core import stt as stt_mod  # noqa: E402
from jarvis_core import tools as tools_mod  # noqa: E402
from jarvis_core import tts as tts_mod  # noqa: E402
from jarvis_core import vision as vision_mod  # noqa: E402
from jarvis_core.i18n import STRINGS  # noqa: E402
from jarvis_core.memory import (  # noqa: E402
    FACT,
    PROFILE,
    MemoryStore,
    extract_explicit,
    extract_profile,
)
from jarvis_core.reminders import ReminderScheduler, ReminderStore  # noqa: E402
from jarvis_core.text import (  # noqa: E402
    clean_text,
    is_exit_phrase,
    is_fatal,
    log,
    make_messages,
    rms,
    status_code,
    strip_wake,
    take_sentences,
)
from jarvis_core.vad import VADConfig  # noqa: E402

try:  # la reconnaissance vocale est inutile en mode texte
    import speech_recognition as sr
except Exception:  # pragma: no cover - depend de la machine
    sr = None

__version__ = "2.1.0"

DEFAULT_BASE_URL = providers.OPENAI_DEFAULT
HISTORY_FILE = Path(__file__).resolve().with_name(".jarvis_history.json")
MEMORY_FILE = Path(__file__).resolve().with_name(".jarvis_memory.db")
PLUGIN_DIR = Path(__file__).resolve().parent / "plugins"
REMINDERS_FILE = Path(__file__).resolve().with_name(".jarvis_reminders.json")

SUMMARY_EVERY = 6      # resume automatique tous les N tours
RETRY_PRIMARY_AFTER = 600.0  # secondes sur un repli avant de retenter le principal
EXPERT_DEADLINE = 75.0       # le modele expert raisonne : on lui laisse plus de temps
SUMMARY_MIN_TURNS = 4  # ... et seulement si la conversation est assez longue

# Outils de memoire : inutile d'annoncer « un instant » pour eux.
MEMORY_TOOLS = {"remember_fact", "recall_memory", "forget_memory"}

QUIT_WORDS = {"exit", "quit", "bye", "stop", "au revoir", "quitter", "quitte"}

# --------------------------------------------------------------------------- #
# Re-exports : jarvis_core est la source de verite, mais ces noms restent
# accessibles sous « jarvis.<nom> » (compatibilite du code et des tests).
# --------------------------------------------------------------------------- #
list_voices = tts_mod.list_voices
pick_voice = tts_mod.pick_voice
Speech = tts_mod.Speech
SilentSpeech = tts_mod.SilentSpeech
SpeechToText = stt_mod.SpeechToText
VADSpeechToText = stt_mod.VADSpeechToText
Transcriber = stt_mod.Transcriber
build_graph = graphs.build_graph
stream_reply = graphs.stream_reply
run_sync = graphs.run_sync
save_history = graphs.save_history
load_history = graphs.load_history
make_turn_messages = graphs.make_turn_messages
build_system_prompt = graphs.build_system_prompt
transcript = graphs.transcript


# --------------------------------------------------------------------------- #
# Configuration : CLI > environnement > fichier > defauts
# --------------------------------------------------------------------------- #
def _prescan(argv: list[str] | None, flag: str) -> str | None:
    """Lit une option avant le passage a argparse (pour --config)."""
    items = list(sys.argv[1:] if argv is None else argv)
    for index, item in enumerate(items):
        if item == flag and index + 1 < len(items):
            return items[index + 1]
        if item.startswith(flag + "="):
            return item.split("=", 1)[1]
    return None


def _base_config(argv: list[str] | None = None) -> tuple[dict, Path | None, list[str]]:
    """Defauts finaux : defauts < fichier de config < variables JARVIS_*."""
    start = _prescan(argv, "--config")
    file_config, path = config_mod.load_config(start)
    base = config_mod.merged_defaults(file_config)
    warnings = list(config_mod.normalise(file_config)[1])
    env_clean, env_warnings = config_mod.normalise(config_mod.env_overrides())
    base.update(env_clean)
    warnings.extend(env_warnings)
    return base, path, warnings


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    base, config_path, config_warnings = _base_config(argv)

    # Le mot d'activation reste une chaine cote CLI (compatibilite) ; le fichier
    # de config peut fournir une liste via `wake_words`.
    default_wake = "jarvis"
    if not base.get("wake", True):
        default_wake = ""
    else:
        words = base.get("wake_words")
        if isinstance(words, str) and words.strip():
            default_wake = words.strip()
        elif isinstance(words, (list, tuple)) and words:
            default_wake = ",".join(str(word) for word in words)

    temperature = base.get("temperature")
    # `volume` peut valoir 0.0 (muet) : un `or` l'ecraserait a tort.
    default_volume = base.get("volume")
    default_volume = 1.0 if default_volume is None else float(default_volume)

    parser = argparse.ArgumentParser(
        prog="jarvis",
        description="Assistant vocal : voix, memoire, outils, hors-ligne, plugins.",
        epilog=(
            "Exemples :\n"
            "  jarvis.py                             interface graphique\n"
            "  jarvis.py --orb                       orbe flottante sur le bureau\n"
            "  jarvis.py --web                       interface dans le navigateur\n"
            "  jarvis.py --no-gui                    console avec micro\n"
            "  jarvis.py --text                      mode texte (sans micro)\n"
            "  jarvis.py --lang fr --vad             voix francaise + VAD\n"
            "  jarvis.py --resume                    reprend la conversation\n"
            "  jarvis.py --model llama3.2 \\\n"
            "      --base_url http://localhost:11434/v1   tout en local\n"
            "  jarvis.py --show_config               affiche la config resolue\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    voice = parser.add_argument_group("voix et boucle")
    voice.add_argument("--lang", choices=sorted(STRINGS),
                       default=base.get("lang") or "en",
                       help="langue de l'interface (prompt, voix, reconnaissance)")
    voice.add_argument("--voice", default=base.get("voice"),
                       help="identifiant de voix TTS (voir --list_voices)")
    voice.add_argument("--tts", choices=("auto", "kokoro", "piper", "sapi", "pyttsx3"),
                       default=base.get("tts") or "auto",
                       help="moteur vocal (auto = Piper si une voix est "
                            "installee, sinon la voix Windows)")
    voice.add_argument("--piper_voice", default=base.get("piper_voice"),
                       help="voix Piper (nom ou chemin .onnx dans voices/)")
    voice.add_argument("--rate", type=int,
                       default=base.get("rate") or tts_mod.DEFAULT_RATE,
                       help="vitesse de la voix en mots/minute")
    voice.add_argument("--volume", type=float, default=default_volume,
                       help="volume 0..1")
    voice.add_argument("--max_speak", type=float,
                       default=float(base.get("max_speak") or 0.0),
                       help="garde-fou TTS en secondes (0 = desactive)")
    voice.add_argument("--wake", default=default_wake,
                       help="mots d'activation separes par des virgules")
    voice.add_argument("--no-wake", dest="wake", action="store_const", const="",
                       help="desactive le mot d'activation")
    voice.add_argument("--no-bargein", dest="bargein", action="store_false",
                       default=bool(base.get("bargein", True)),
                       help="interdit de couper la parole a Jarvis")
    voice.add_argument("--vad", action="store_true", default=bool(base.get("vad")),
                       help="end-pointing par detection de voix (Horizon 5)")
    voice.add_argument("--ptt", action="store_true", default=bool(base.get("ptt")),
                       help="appuyer sur Entree avant chaque question")
    voice.add_argument("--resume", action="store_true",
                       default=bool(base.get("resume")),
                       help="reprend l'historique au lieu de saluer")
    voice.add_argument("--text", action="store_true", default=bool(base.get("text")),
                       help="mode texte : ni micro ni synthese vocale")
    voice.add_argument("--max_words", type=int, default=base.get("max_words", 40),
                       help="longueur maximale des reponses")
    voice.add_argument("--ability", default=base.get("ability") or "general knowledge",
                       help="role donne a Jarvis (ex: un professeur de math)")
    voice.add_argument("--retries", type=int, default=base.get("retries", 3),
                       help="tentatives sur le modele")
    voice.add_argument("--phrase_limit", type=float,
                       default=base.get("phrase_limit", 15.0),
                       help="delai maximal de reconnaissance par phrase")

    model = parser.add_argument_group("modele et fournisseur")
    model.add_argument("--api_key", default=base.get("api_key"),
                       help="cle API (sinon JARVIS_API_KEY / OPENROUTER_API_KEY ...)")
    model.add_argument("--model", default=base.get("model") or "gpt-3.5-turbo",
                       help="nom du modele de chat")
    model.add_argument("--base_url", default=base.get("base_url") or DEFAULT_BASE_URL,
                       help="URL compatible OpenAI du fournisseur")
    model.add_argument("--temperature", type=float, default=temperature,
                       help="creativite du modele (defaut du fournisseur sinon)")
    model.add_argument("--local_model", default=base.get("local_model"),
                       help="modele de repli hors-ligne (Ollama)")
    model.add_argument("--local_base_url", default=base.get("local_base_url"),
                       help="URL du modele local (defaut "
                            + providers.OLLAMA_DEFAULT + ")")
    model.add_argument("--no-fallback", dest="no_fallback", action="store_true",
                       default=bool(base.get("no_fallback")),
                       help="desactive la bascule automatique vers le local")

    horizon = parser.add_argument_group("memoire, outils, application")
    horizon.add_argument("--no-memory", dest="memory", action="store_false",
                         default=bool(base.get("memory", True)),
                         help="desactive la memoire longue duree")
    horizon.add_argument("--memory_path", default=base.get("memory_path"),
                         help="fichier SQLite de memoire")
    horizon.add_argument("--no-tools", dest="tools", action="store_false",
                         default=bool(base.get("tools", True)),
                         help="desactive les outils (graphe simple)")
    horizon.add_argument("--plugins", dest="plugins", action="store_true",
                         default=bool(base.get("plugins", True)),
                         help="charge les plugins du dossier plugins/")
    horizon.add_argument("--no-plugins", dest="plugins", action="store_false",
                         help="desactive les plugins")
    horizon.add_argument("--plugins_dir",
                         default=base.get("plugins_dir") or str(PLUGIN_DIR),
                         help="dossier des plugins")
    horizon.add_argument("--history_path", default=base.get("history_path"),
                         help="fichier d'historique JSON")
    horizon.add_argument("--gui", dest="gui", action="store_true",
                         default=bool(base.get("gui", True)),
                         help="interface graphique (defaut)")
    horizon.add_argument("--no-gui", dest="gui", action="store_false",
                         help="rester en console au lieu d'ouvrir la fenetre")
    horizon.add_argument("--web", dest="web", action="store_true",
                         default=bool(base.get("web")),
                         help="interface dans le navigateur (au lieu de la fenetre)")
    horizon.add_argument("--orb", dest="orb", action="store_true",
                         default=bool(base.get("orb")),
                         help="orbe flottante sur le bureau (clic pour parler)")
    horizon.add_argument("--no-vision", dest="vision", action="store_false",
                         default=bool(base.get("vision", True)),
                         help="retire l'outil qui regarde l'ecran")
    horizon.add_argument("--vision_model", default=base.get("vision_model"),
                         help="modele qui comprend les images (defaut sur "
                              "OpenRouter : nemotron-3.5-super-vl gratuit)")
    horizon.add_argument("--orb_quality", choices=("ultra", "standard"),
                         default=base.get("orb_quality") or "ultra",
                         help="orbe : ultra = rendu 3D sur la carte graphique (repli "
                              "automatique), standard = processeur")
    horizon.add_argument("--auto_hide", type=int,
                         default=int(base.get("auto_hide", 60) or 0),
                         help="orbe : se masque apres N secondes d'inactivite "
                              "(0 = jamais ; « Jarvis » ou le raccourci la rappellent)")
    horizon.add_argument("--no-expert", dest="expert", action="store_false",
                         default=bool(base.get("expert", True)),
                         help="ne pas basculer vers le modele expert (maths, code, analyse)")
    horizon.add_argument("--no-proactive", dest="proactive", action="store_false",
                         default=bool(base.get("proactive", True)),
                         help="ne pas prevenir de soi-meme (batterie, pluie, pause)")
    horizon.add_argument("--no-follow-up", dest="follow_up", action="store_false",
                         default=bool(base.get("follow_up", True)),
                         help="orbe : ne pas reecouter apres une reponse vocale")
    horizon.add_argument("--orb_theme",
                         choices=("opale", "plasma", "aurore", "nebuleuse", "jarvis", "siri")
                         + tuple(orb_themes.CATALOG),
                         default=base.get("orb_theme") or "opale",
                         help="style de l'orbe : opale, plasma, aurore, nebuleuse "
                              "(formes organiques), jarvis (HUD), siri (sphere)")
    horizon.add_argument("--no-wake-word", dest="wake_word", action="store_false",
                         default=bool(base.get("wake_word", True)),
                         help="orbe : desactive l'ecoute locale de « Hey Jarvis »")
    horizon.add_argument("--wake_threshold", type=float,
                         default=float(base.get("wake_threshold") or 0.5),
                         help="sensibilite du mot d'activation (0.1..0.95, "
                              "plus bas = plus sensible)")
    horizon.add_argument("--hotkey", default=base.get("hotkey", "ctrl+space"),
                         help="raccourci global pour parler (\"\" = aucun)")
    horizon.add_argument("--port", dest="web_port", type=int,
                         default=int(base.get("web_port") or 8765),
                         help="port local de l'interface web (defaut 8765)")
    horizon.add_argument("--config", "--config_path", dest="config_path",
                         default=None,
                         help="fichier de configuration (sinon recherche "
                              "automatique de jarvis.yaml/json/toml)")

    stt_group = parser.add_argument_group("reconnaissance vocale")
    stt_group.add_argument("--stt", choices=("auto", "google", "whisper", "local"),
                           default=base.get("stt") or "auto",
                           help="moteur de reconnaissance (auto = cloud puis local)")
    stt_group.add_argument("--whisper_model",
                           default=base.get("whisper_model") or "base",
                           help="taille du modele faster-whisper (tiny..large)")

    actions = parser.add_argument_group("actions immediates")
    actions.add_argument("--list_voices", action="store_true",
                         help="liste les voix TTS puis quitte")
    actions.add_argument("--test_voice", action="store_true",
                         help="prononce une phrase de test puis quitte")
    actions.add_argument("--list_tools", action="store_true",
                         help="liste les outils disponibles puis quitte")
    actions.add_argument("--show_config", action="store_true",
                         help="affiche la configuration resolue puis quitte")
    actions.add_argument("--version", action="version",
                         version=f"jarvis {__version__}")

    args = parser.parse_args(argv)

    # `--config` a deja ete applique comme base avant les defauts : il ne reste
    # qu'a normaliser les bornes numeriques.
    try:
        args.max_speak = max(0.0, float(args.max_speak))
    except (TypeError, ValueError):
        args.max_speak = 0.0
    args.volume = min(max(float(args.volume), 0.0), 1.0)
    if args.rate:
        args.rate = min(max(int(args.rate), 50), 400)
    args.max_words = max(1, int(args.max_words))
    args.retries = max(0, int(args.retries))

    # Pas d'option CLI pour `allow_apps` : seul le fichier de config la fournit.
    args.allow_apps = base.get("allow_apps") or {}

    args.config_path = str(config_path) if config_path else None
    args.config_warnings = config_warnings
    return args


# --------------------------------------------------------------------------- #
# Chaine de fournisseurs (Horizon 4)
# --------------------------------------------------------------------------- #
class ModelChain:
    """Fournisseur principal, puis replis joignables (local, autres gratuits).

    La bascule est manuelle (`advance()`) : elle n'a lieu que lorsqu'un tour a
    echoue, et on reste ensuite sur le repli plutot que de retenter le cloud a
    chaque phrase.
    """

    def __init__(self, specs, tools=None, temperature=None, expert=None):
        self.expert = list(expert or [])   # modele qui raisonne (questions difficiles)
        self.quota_until = 0.0             # quota du jour epuise (epoch) : OpenRouter en pause
        self.last_expert = False
        self._expert_off_until = 0.0
        self.specs = list(specs) or [
            providers.ProviderSpec(name="openai", model="gpt-4o-mini")
        ]
        self.tools = list(tools or [])
        self.temperature = temperature
        self.index = 0
        self._graphs: dict[int, object] = {}
        self._llms: dict[int, object] = {}
        self._switched_at = 0.0
        self.force_tools = lambda: False   # vrai pendant un quiz (noter chaque reponse)

    @property
    def spec(self):
        return self.specs[self.index]

    @property
    def tools_enabled(self) -> bool:
        return bool(self.tools)

    def llm(self):
        if self.index not in self._llms:
            self._llms[self.index] = providers.build_llm(
                self.spec, temperature=self.temperature
            )
        return self._llms[self.index]

    @property
    def graph(self):
        self.maybe_restore()
        if self.index not in self._graphs:
            self._graphs[self.index] = graphs.build_graph(
                self.llm(), tools=self.tools
            )
        return self._graphs[self.index]

    @property
    def chat_graph(self):
        """Meme modele sans les outils : ~2 s de moins pour une conversation."""
        self.maybe_restore()
        key = ("chat", self.index)
        if key not in self._graphs:
            self._graphs[key] = graphs.build_graph(self.llm(), tools=[])
        return self._graphs[key]

    @property
    def expert_graph(self):
        """Graphe du modele expert, avec tous les outils."""
        if "expert" not in self._graphs:
            llm = providers.build_llm(self.expert[0], temperature=self.temperature,
                                      timeout=EXPERT_DEADLINE)
            self._graphs["expert"] = graphs.build_graph(llm, tools=self.tools)
        return self._graphs["expert"]

    def graph_for(self, text: str):
        """Graphe adapte a la question : expert pour raisonner, outils si utiles."""
        self.last_expert = False
        expert_ready = (self.expert and time.monotonic() >= self._expert_off_until
                        and not self._blocked(self.expert[0]))
        if expert_ready and smart.needs_expert(text):
            self.last_expert = True
            log(f"[llm] question difficile : modele expert ({self.expert[0].model})")
            return self.expert_graph, bool(self.tools)
        if self.tools and (intents.needs_tools(text) or self.force_tools()):
            return self.graph, True
        return self.chat_graph, False

    @property
    def expert_slow(self) -> bool:
        """L'expert met ~20 s (OpenRouter) : on previent ; sur Groq (~2 s), non."""
        return bool(self.expert) and "groq.com" not in (self.expert[0].base_url or "")

    def quota_exhausted(self) -> bool:
        return time.time() < self.quota_until

    def _blocked(self, spec) -> bool:
        return self.quota_exhausted() and providers.is_openrouter(spec.base_url)

    def maybe_restore(self, now: float | None = None) -> bool:
        """Revient au fournisseur principal quelque temps apres une bascule.

        Un modele gratuit sature ou une coupure reseau sont souvent passagers :
        rester indefiniment sur le repli ferait perdre le meilleur modele.
        """
        if self.index and self._blocked(self.specs[0]):
            return False                   # quota du jour : pas avant le renouvellement
        now = time.monotonic() if now is None else now
        if self.index and now - self._switched_at >= RETRY_PRIMARY_AFTER:
            self.index = 0
            log(f"[llm] nouvel essai du fournisseur principal ({self.spec.label()})")
            return True
        return False

    def advance(self, error=None) -> bool:
        """Passe au fournisseur suivant, en sautant les replis injoignables.

        Quota du jour epuise : tous les modeles OpenRouter partagent ce quota,
        on les saute jusqu'au renouvellement (Groq ou local s'il y en a).
        Pas de reseau : tous les modeles en ligne echoueraient, on va droit au
        modele local (Ollama).
        """
        if is_offline(error):
            self.last_expert = False
            self._expert_off_until = time.monotonic() + 120
            for index, spec in enumerate(self.specs):
                if spec.is_local and index != self.index and providers.ollama_reachable(
                        spec.base_url or providers.OLLAMA_DEFAULT):
                    self.index, self._switched_at = index, time.monotonic()
                    log(f"[llm] pas de reseau : modele local {spec.label()}")
                    return True
            log("[llm] pas de reseau et aucun modele local joignable")
            return False
        if is_daily_quota(error):
            reset = quota_reset(error)
            if reset is None:              # a defaut : minuit UTC
                now = time.time()
                reset = now - now % 86400 + 86400
            self.quota_until = reset
            self.last_expert = False
            log("[llm] quota gratuit du jour epuise jusqu'a "
                + time.strftime("%H:%M", time.localtime(reset)))
            for index, spec in enumerate(self.specs):
                if not self._blocked(spec) and index != self.index:
                    if spec.is_local and not providers.ollama_reachable(
                            spec.base_url or providers.OLLAMA_DEFAULT):
                        continue
                    self.index, self._switched_at = index, time.monotonic()
                    log(f"[llm] bascule sur {spec.label()}")
                    return True
            return False
        if self.last_expert:
            # L'expert a echoue (sature, trop lent) : modele rapide, expert en pause 5 min.
            self.last_expert = False
            self._expert_off_until = time.monotonic() + 300
            log("[llm] expert indisponible : modele rapide")
            return True
        self._switched_at = time.monotonic()
        while self.index + 1 < len(self.specs):
            self.index += 1
            spec = self.spec
            if self._blocked(spec):
                continue
            if spec.is_local and not providers.ollama_reachable(
                spec.base_url or providers.OLLAMA_DEFAULT
            ):
                log(f"[llm] {spec.label()} injoignable, fournisseur suivant")
                continue
            log(f"[llm] bascule sur {spec.label()}")
            return True
        return False

    def warm(self) -> None:
        """Ouvre la connexion au modele des le lancement : la 1re reponse ne paie
        plus la poignee de main TLS (~1 s mesuree sur Groq)."""
        def run() -> None:
            try:
                client = getattr(self.llm(), "root_client", None)
                if client is not None:
                    client.models.list()
            except Exception:
                pass

        threading.Thread(target=run, name="jarvis-llm-chauffe", daemon=True).start()

    def ask(self, prompt: str) -> str:
        """Appel simple, sans outils (utilise par les resumes de memoire)."""
        if self._blocked(self.spec):
            raise RuntimeError("quota gratuit du jour epuise")
        message = self.llm().invoke([HumanMessage(content=prompt)])
        return graphs.message_text(message)

    def label(self) -> str:
        return self.spec.label()


# --------------------------------------------------------------------------- #
# Utilitaires d'ecran
# --------------------------------------------------------------------------- #
def describe_microphone() -> str:
    try:
        import pyaudio

        audio = pyaudio.PyAudio()
        try:
            info = audio.get_default_input_device_info()
            return str(info.get("name", "?"))
        finally:
            audio.terminate()
    except Exception:
        return "inconnu"


def draw_banner(args, strings, chain, tool_list, memory) -> None:
    print(f"--- Jarvis {__version__} ---")
    print(f"langue      : {args.lang}")
    print(f"modele      : {chain.label()}")
    if args.no_fallback:
        print("repli       : desactive")
    elif len(chain.specs) > 1:
        # Replis locaux et autres modeles gratuits du cloud, dans l'ordre.
        others = ", ".join(spec.label() for spec in chain.specs[1:])
        print(f"repli       : {others}")
    print(f"outils      : {len(tool_list)}" if tool_list else "outils      : aucun")
    if memory is not None:
        print(f"memoire     : {memory.count()} souvenir(s) -> {memory.path}")
    else:
        print("memoire     : desactivee")
    if args.config_path:
        print(f"config      : {args.config_path}")
    if args.text:
        print("entree      : texte")
    else:
        print(f"entree      : micro ({describe_microphone()})"
              + (" + VAD" if args.vad else ""))
    print("-" * 34, flush=True)


# --------------------------------------------------------------------------- #
# Memoire (Horizon 2)
# --------------------------------------------------------------------------- #
def remember_turn(memory, text: str, strings: dict) -> None:
    """Retient ce que l'utilisateur a explicitement demande ou revele."""
    if memory is None:
        return
    action, payload = extract_explicit(text)
    try:
        if action == "remember" and payload:
            memory.remember(payload, kind=FACT, source="explicit")
            log(f"[memoire] + {payload}")
        elif action == "forget" and payload:
            removed = memory.forget_matching(payload)
            log(f"[memoire] {removed} souvenir(s) efface(s)" if removed
                else "[memoire] rien a effacer")
        for label, value in extract_profile(text):
            memory.remember(f"{label}: {value}", kind=PROFILE, source="auto")
    except Exception as exc:  # la memoire ne doit jamais casser un tour
        log(f"[memoire] {exc}")


def maybe_summarise(memory, chain, history, strings) -> None:
    """Resume la conversation en cours et le stocke (Horizon 2)."""
    if memory is None:
        return
    text = graphs.transcript(history, limit=30)
    if len(text) < 200:
        return
    summary = memory.summarize(chain.ask, text, strings)
    if summary:
        log(f"[memoire] resume: {summary[:120]}")


# --------------------------------------------------------------------------- #
# Reconnaissance vocale (Horizons 1, 4 et 5)
# --------------------------------------------------------------------------- #
def build_listener(args, strings):
    """Ouvre le micro et construit l'ecouteur (classique ou VAD)."""
    if sr is None:
        raise RuntimeError("speech_recognition n'est pas installe")
    recognizer = sr.Recognizer()
    recognizer.energy_threshold = 300
    recognizer.dynamic_energy_threshold = True
    # Fin de phrase detectee apres 0,65 s de silence (0,8 s par defaut) :
    # la reponse part plus tot, sans couper les petites hesitations.
    recognizer.pause_threshold = 0.65
    recognizer.non_speaking_duration = 0.4
    microphone = sr.Microphone()
    microphone.__enter__()  # reste ouvert ; _reopen() le rouvre si besoin

    transcriber = stt_mod.build_transcriber(recognizer, strings, mode=args.stt,
                                            whisper_model=args.whisper_model,
                                            groq_key=providers.groq_key())
    if args.stt in ("whisper", "local") and strings.get("whisper_loading"):
        print(strings["whisper_loading"], flush=True)

    config = VADConfig(
        silence_ms=600,
        start_timeout_ms=max(3000, int(args.phrase_limit * 1000)),
        max_speech_ms=20000,
    )
    if args.vad:
        listener = stt_mod.VADSpeechToText(
            recognizer, microphone, strings["google_lang"], config=config,
            phrase_limit=args.phrase_limit, transcriber=transcriber,
            strings=strings,
        )
    else:
        listener = stt_mod.SpeechToText(
            recognizer, microphone, strings["google_lang"],
            phrase_limit=args.phrase_limit, transcriber=transcriber,
            strings=strings,
        )
    return microphone, listener


# --------------------------------------------------------------------------- #
# Boucle de conversation
# --------------------------------------------------------------------------- #
def _turn_extra(args, voice) -> str:
    """Consignes du tour : message dicte (comprendre l'intention) et quiz en cours."""
    from jarvis_core import context as app_context

    parts = (hearing_mod.guidance(voice, args.lang), app_context.context_line(args.lang),
             quiz_mod.rules_for(args))
    return "\n\n".join(part for part in parts if part)


def run_conversation(args, strings, listener, speech, chain, history,
                     memory=None, greet: bool = True) -> None:
    wake_words = [word for word in
                  (item.strip().lower() for item in (args.wake or "").split(","))
                  if word]
    use_wake = bool(wake_words) and not args.text
    base_prompt = strings["system"].format(ability=args.ability,
                                           words=args.max_words)
    misses = 0
    turn = 0
    history_path = args.history_path or HISTORY_FILE

    speech.begin()
    if greet:
        speech.say(strings["greeting"])

    while True:
        if args.ptt:
            try:
                input("Appuie sur Entree pour parler...")
            except EOFError:
                break

        voice = None   # hearing.Heard quand le message a ete dicte
        if args.text:
            try:
                text = input("You: ").strip()
            except EOFError:
                break
            if not text:
                continue
        else:
            if use_wake:
                print(f"{strings['listening']} (mot d'activation : "
                      f"{', '.join(wake_words)})", flush=True)
            else:
                print(strings["listening"], flush=True)
            heard, error = listener.listen()
            if heard is None:
                if error and error.startswith("network:"):
                    speech.say(strings["stt_error"])
                elif error and error.startswith("mic:"):
                    speech.say(strings["mic_error"])
                continue
            if use_wake:
                matched, text = strip_wake(heard, wake_words)
                if not matched:
                    misses += 1
                    if misses == 1:
                        log(f"[wake] mot d'activation absent dans « {heard} »")
                    continue
                misses = 0
                if not text:
                    speech.begin()
                    speech.say(strings["yes"])
                    continue
            else:
                text = heard
            voice = getattr(getattr(listener, "transcriber", None), "last_heard", None)
            if voice is not None and text.strip() not in voice.text:
                voice = None

        print(f"You: {text}")

        if is_exit_phrase(text, strings["exit_phrases"]) or \
                text.strip().lower() in QUIT_WORDS:
            speech.begin()
            speech.say(strings["goodbye"])
            break

        turn += 1
        ctx = getattr(args, "tool_ctx", None)
        quick = None
        # Dictee : les autres transcriptions de Google peuvent aussi etre une commande.
        for candidate in [text] + (list(voice.alternatives[:3]) if voice else []):
            try:
                quick = intents.quick_answer(candidate, args.lang, strings,
                                             args.allow_apps or None,
                                             timers=getattr(ctx, "timers", None),
                                             reminders=getattr(ctx, "reminders", None),
                                             selection_api=intents.selection_for(ctx))
            except Exception as exc:  # une commande rapide ne casse jamais un tour
                log(f"[rapide] {exc}")
                quick = None
            if quick:
                break
        if quick:
            speech.begin()
            speech.say(quick)
            history += [HumanMessage(content=text), AIMessage(content=quick)]
            graphs.save_history(history, history_path)
            continue

        graph, with_tools = chain.graph_for(text)
        system_prompt = graphs.build_system_prompt(
            base_prompt, memory=memory, query=text, strings=strings,
            with_tools=with_tools, extra=_turn_extra(args, voice),
        )
        messages = graphs.make_turn_messages(system_prompt, history, text)

        announced = {"done": False}

        def on_tool(name: str) -> None:
            log(f"[outil] {name}")
            if announced["done"] or name in MEMORY_TOOLS:
                return
            announced["done"] = True
            hint = strings.get("tool_running")
            if hint:
                print(hint, flush=True)  # affiche, sans retarder la reponse parlee

        speech.begin()
        expert = getattr(chain, "last_expert", False)
        if expert and chain.expert_slow:
            speech.say(smart.EXPERT_HINT.get(args.lang, smart.EXPERT_HINT["en"]))
        result = graphs.stream_reply(graph, messages,
                                     on_sentence=speech.say,
                                     retries=args.retries, on_tool=on_tool,
                                     deadline=EXPERT_DEADLINE if expert else graphs.TURN_DEADLINE)

        if (not result.ok or result.empty) and chain.advance(result.error):
            # Bascule automatique cloud -> local (Horizon 4), puis un essai.
            speech.begin()
            speech.say(strings.get("fallback_used", ""))
            graph, with_tools = chain.graph_for(text)
            system_prompt = graphs.build_system_prompt(
                base_prompt, memory=memory, query=text, strings=strings,
                with_tools=with_tools, extra=_turn_extra(args, voice),
            )
            messages = graphs.make_turn_messages(system_prompt, history, text)
            speech.begin()
            result = graphs.stream_reply(graph, messages,
                                         on_sentence=speech.say,
                                         retries=args.retries, on_tool=on_tool)

        if not result.ok:
            log(f"[llm] {result.error}")
            speech.begin()
            speech.say(graphs.error_message(result.error, strings))
            continue

        if result.empty:
            # Modele de raisonnement sans texte final : on le dit au lieu de
            # rester muet, sans perdre ce que l'utilisateur a demande de retenir.
            log("[llm] reponse vide")
            speech.begin()
            speech.say(strings["empty_reply"])
            history.append(messages[-1])
            remember_turn(memory, text, strings)
            graphs.save_history(history, history_path)
            continue

        history.append(messages[-1])      # la question de l'utilisateur
        history.extend(result.messages)   # reponse (et resultats d'outils)
        remember_turn(memory, text, strings)
        smart.learn_async(memory, chain.ask, text,
                          graphs.message_text(result.messages[-1]) if result.messages else "",
                          args.lang)
        graphs.save_history(history, history_path)

        if memory is not None and turn % SUMMARY_EVERY == 0 and \
                len(history) >= SUMMARY_MIN_TURNS * 2:
            maybe_summarise(memory, chain, history, strings)


# --------------------------------------------------------------------------- #
# Programme principal
# --------------------------------------------------------------------------- #
def _resolve_config_warnings(args) -> None:
    for warning in getattr(args, "config_warnings", []) or []:
        log(f"[config] {warning}")


def _report_plugins(plugin_infos) -> None:
    for info in plugin_infos:
        if info.ok:
            log(f"[plugin] {info.name}: {', '.join(info.tools) or 'aucun outil'}")
        else:
            log(f"[plugin] {info.name} ignore ({info.error})")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    strings = STRINGS[args.lang]
    _resolve_config_warnings(args)

    # -- actions immediates ------------------------------------------------- #
    if args.list_voices:
        voices = tts_mod.list_voices()
        if not voices:
            print("Aucune voix TTS disponible sur cette machine.")
        for voice_id, name in voices:
            print(f"{voice_id}\t{name}")
        return 0

    if args.test_voice:
        speech = tts_mod.build_speech(args, strings)
        speech.begin()
        speech.say(strings["greeting"])
        speech.close()
        return 0

    # -- fournisseur -------------------------------------------------------- #
    problem = providers.api_key_problem(args)
    specs = providers.build_provider_chain(args)
    if problem and not any(spec.is_local for spec in specs):
        log(f"[config] {problem}")
        return 2

    # -- memoire ------------------------------------------------------------ #
    memory = None
    if args.memory:
        path = Path(args.memory_path).expanduser() if args.memory_path \
            else MEMORY_FILE
        try:
            memory = MemoryStore(path)
        except Exception as exc:
            log(f"[memoire] indisponible ({exc}) : Jarvis continue sans memoire")

    # -- outils et plugins -------------------------------------------------- #
    speech_holder: dict = {"speech": None}

    def announce(text: str) -> None:
        speech = speech_holder["speech"]
        if speech is not None and text:
            speech.say(text)

    def alert(text: str, speak: bool = True) -> None:
        """Rappel, minuteur, alerte : notification Windows + voix."""
        notify_mod.notify("Jarvis", text)
        if speak:
            announce(text)

    tool_list: list = []
    scheduler = None
    reminders = None
    if args.tools:
        reminders = ReminderStore(REMINDERS_FILE)
        ctx = tools_mod.ToolContext(
            lang=args.lang, strings=strings, memory=memory, speak=alert,
            allow_apps={**tools_mod.DEFAULT_APPS, **args.allow_apps},
            reminders=reminders,
            vision=(vision_mod.make_vision(specs[0], args.vision_model, args.lang)
                    if args.vision and specs else None),
        )

        def announce_reminder(item: dict, late: bool) -> None:
            key = "reminder_late" if late else "reminder_due"
            log(f"[rappel] {item['text']}")
            tools_mod._beep()
            alert(strings[key].format(text=item["text"]))

        scheduler = ReminderScheduler(reminders, announce_reminder)
        tool_list = tools_mod.build_tools(ctx)
        args.tool_ctx = ctx  # minuteurs et rappels partages avec les commandes rapides
        if args.plugins:
            plugin_tools, plugin_infos = plugins_mod.load_plugins(
                args.plugins_dir, ctx
            )
            _report_plugins(plugin_infos)
            tool_list = tool_list + plugin_tools

    if args.list_tools:
        print(f"{len(tool_list)} outil(s) :")
        for item in tool_list:
            print(f"  {item.name}\t{(item.description or '').splitlines()[0] if item.description else ''}")
        return 0

    if args.show_config:
        chain = ModelChain(specs, tool_list, args.temperature)
        draw_banner(args, strings, chain, tool_list, memory)
        print("\nConfiguration resolue :")
        for key in sorted(vars(args)):
            if key in ("config_warnings",):
                continue
            print(f"  {key} = {getattr(args, key)!r}")
        if memory is not None:
            memory.close()
        return 0

    # -- voix et micro ------------------------------------------------------ #
    # La fenetre graphique est le mode par defaut ; `--text` et `--no-gui`
    # ramenent a la console. On decide *avant* d'ouvrir le micro pour que la
    # fenetre reste utilisable au clavier meme si le micro est pris.
    use_orb = bool(args.orb) and not args.text
    if use_orb:
        from jarvis_core import orb as orb_settings

        orb_settings.apply_saved_settings(args)  # voix, theme... choisis au menu
    use_web = bool(args.web) and not args.text and not use_orb
    use_gui = bool(args.gui) and not args.text and not use_web and not use_orb
    windowed = use_gui or use_web or use_orb
    microphone = None
    listener = None
    if not args.text:
        if sr is None:
            if windowed:
                log("[stt] speech_recognition absent : saisie clavier seule")
            else:
                log("[stt] speech_recognition absent : passage en mode texte")
                args.text = True
        else:
            try:
                microphone, listener = build_listener(args, strings)
            except Exception as exc:
                if windowed:
                    log(f"[stt] micro indisponible ({exc}) : saisie clavier seule")
                else:
                    log(f"[stt] micro indisponible ({exc}) : passage en mode texte")
                    args.text = True

    # Dans la fenetre, l'interruption se fait au bouton « Stop » : on ne laisse
    # pas la veille vocale lire le micro en meme temps que le bouton « Parler ».
    speech = tts_mod.build_speech(args, strings,
                                  source=None if windowed else microphone)
    speech_holder["speech"] = speech
    if args.vad and listener is not None:
        with contextlib.suppress(Exception):
            listener.calibrate(0.5)

    # -- graphe ------------------------------------------------------------- #
    chain = ModelChain(specs, tool_list, args.temperature,
                       expert=providers.expert_specs(specs) if args.expert else None)
    chain.force_tools = lambda: quiz_mod.active_quiz(args) is not None
    chain.warm()
    if args.proactive:
        from jarvis_core import briefing as briefing_mod
        from jarvis_core import proactive

        proactive.Watcher(args.lang, alert,
                          city=lambda: briefing_mod.profile_facts(memory).get("location")
                          ).start()
    if scheduler is not None:
        scheduler.start()  # apres la voix : un rappel en retard est annonce
    draw_banner(args, strings, chain, tool_list, memory)

    # -- historique --------------------------------------------------------- #
    history = []
    greet = True
    if args.resume:
        history = graphs.load_history(args.history_path or HISTORY_FILE)
        if history:
            greet = False
            print(f"[historique] {len(history)} message(s) repris "
                  f"({int(len(history) / 2)} echange(s))\n", flush=True)

    # -- interface graphique ou console ------------------------------------- #
    status = 0
    try:
        if use_orb:
            from jarvis_core import orb as orb_mod

            started = orb_mod.run(args, strings, listener, speech, chain, history,
                                  memory, greet, reminders=reminders)
            if started is None:
                log("[orbe] retour au mode console")
                run_conversation(args, strings, listener, speech, chain, history,
                                 memory=memory, greet=greet)
            else:
                status = started
        elif use_web:
            from jarvis_core import web as web_mod

            status = web_mod.run(args, strings, listener, speech, chain, history,
                                 memory, greet, port=args.web_port)
        elif use_gui:
            from jarvis_core import gui as gui_mod

            started = gui_mod.run(args, strings, listener, speech, chain, history,
                                  memory, greet)
            if started is None:
                log("[gui] retour au mode console")
                run_conversation(args, strings, listener, speech, chain, history,
                                 memory=memory, greet=greet)
            else:
                status = started
        else:
            run_conversation(args, strings, listener, speech, chain, history,
                             memory=memory, greet=greet)
    except KeyboardInterrupt:
        print()
        log(strings["goodbye"])
    finally:
        with contextlib.suppress(Exception):
            speech.close()
        if memory is not None:
            # L'historique a deja ete sauvegarde a chaque tour ; inutile de
            # reecrire le fichier ici (et de doubler le message de log).
            with contextlib.suppress(Exception):
                memory.close()
        if microphone is not None:
            with contextlib.suppress(Exception):
                microphone.__exit__(None, None, None)
    return status


if __name__ == "__main__":
    sys.exit(main())
