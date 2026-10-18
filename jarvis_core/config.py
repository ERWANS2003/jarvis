"""Horizon 6 - configuration par fichier.

Ordre de priorite (du plus fort au plus faible) :

  1. arguments de la ligne de commande (``--lang fr``)
  2. variables d'environnement (``JARVIS_LANG``, lues ailleurs)
  3. fichier de configuration (``jarvis.yaml`` / ``.json`` / ``.toml``)
  4. valeurs par defaut codées ici

Le fichier peut etre plat ou regroupe en sections (``voice:``, ``memory:``,
``tools:``, ``provider:``) ; les sections sont aplaties avant usage.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

CONFIG_NAMES = ("jarvis.yaml", "jarvis.yml", "jarvis.json", "jarvis.toml")

SECTIONS = ("voice", "memory", "tools", "provider", "realtime", "interface")

# Valeurs par defaut utilisees quand ni la CLI ni le fichier ne disent rien.
DEFAULTS: dict = {
    # voix / boucle
    "lang": "en",
    "text": False,
    "wake": True,
    "wake_words": None,
    "bargein": True,
    "vad": False,
    "ptt": False,
    "resume": False,
    "ability": "general knowledge",
    "max_words": 40,
    "max_speak": 0.0,
    "retries": 3,
    "phrase_limit": 6.0,
    "voice": None,
    "rate": None,
    "volume": 1.0,
    # reconnaissance vocale (horizons 1, 4 et 5)
    "stt": "auto",
    "whisper_model": "base",
    # modele
    "model": None,
    "base_url": None,
    "api_key": None,
    "temperature": None,
    "local_model": None,
    "local_base_url": None,
    "no_fallback": False,
    # horizons 2 et 3
    "memory": True,
    "memory_path": None,
    "tools": True,
    # horizon 6
    "plugins": True,
    "plugins_dir": None,
    "gui": True,
    "history_path": None,
}

KNOWN_KEYS = tuple(DEFAULTS)

_LIMITS = {
    "max_words": (1, 400),
    "retries": (0, 10),
    "max_speak": (0.0, 600.0),
    "phrase_limit": (0.5, 120.0),
    "rate": (50, 400),
    "volume": (0.0, 1.0),
}


def find_config(start: Path | str | None = None) -> Path | None:
    """Cherche un fichier de configuration dans `start` puis dans le cwd."""
    candidates: list[Path] = []
    if start:
        base = Path(start)
        if base.is_file():
            return base
        candidates.append(base)
    candidates.append(Path.cwd())
    candidates.append(Path(__file__).resolve().parent.parent)
    for directory in candidates:
        for name in CONFIG_NAMES:
            candidate = directory / name
            if candidate.is_file():
                return candidate
    return None


def _flatten(raw: dict) -> dict:
    """Aplatit les sections (`voice: {lang: fr}` -> `lang: fr`)."""
    flat: dict = {}
    for key, value in (raw or {}).items():
        if key in SECTIONS and isinstance(value, dict):
            flat.update(value)
        else:
            flat[key] = value
    return flat


def load_config_file(path: Path | str) -> dict:
    """Lit un fichier de config (.yaml/.yml/.json/.toml). Leve si illisible."""
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix == ".json":
        raw = json.loads(text)
    elif suffix == ".toml":
        import tomllib

        raw = tomllib.loads(text)
    else:
        import yaml

        raw = yaml.safe_load(text) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"configuration invalide dans {path}")
    return _flatten(raw)


def load_config(start: Path | str | None = None) -> tuple[dict, Path | None]:
    """Charge la config trouvee ; retourne ({}, None) si aucune."""
    path = find_config(start)
    if path is None:
        return {}, None
    try:
        return load_config_file(path), path
    except Exception:
        return {}, path


def coerce_lang(value) -> str:
    text = str(value or "").strip().lower()
    if text.startswith("fr"):
        return "fr"
    if text.startswith("en"):
        return "en"
    return "en"


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "oui", "vrai"}


def normalise(config: dict) -> tuple[dict, list[str]]:
    """Nettoie et borne les valeurs. Retourne (config, avertissements)."""
    warnings: list[str] = []
    clean: dict = {}

    # Forme negative acceptee dans le fichier : `no_wake: true` -> `wake: false`
    source = dict(config or {})
    for key in ("wake", "bargein", "memory", "tools", "plugins"):
        negative = f"no_{key}"
        if negative in source:
            source[key] = not _as_bool(source.pop(negative))

    for key, value in source.items():
        if key not in KNOWN_KEYS:
            warnings.append(f"cle inconnue ignoree: {key}")
            continue
        clean[key] = value

    if "lang" in clean:
        coerced = coerce_lang(clean["lang"])
        if str(clean["lang"]).strip().lower()[:2] != coerced:
            warnings.append(f"langue inconnue '{clean['lang']}', 'en' utilise")
        clean["lang"] = coerced

    for key, (low, high) in _LIMITS.items():
        if key in clean and clean[key] is not None:
            try:
                number = type(low)(clean[key])
            except (TypeError, ValueError):
                warnings.append(f"{key} invalide, ignore")
                clean.pop(key)
                continue
            if not low <= number <= high:
                clamped = min(max(number, low), high)
                warnings.append(f"{key} borne a {clamped}")
                number = clamped
            clean[key] = number

    for key in ("text", "wake", "bargein", "vad", "ptt", "resume", "memory",
                "tools", "plugins", "gui", "no_fallback"):
        if key in clean and not isinstance(clean[key], bool):
            clean[key] = _as_bool(clean[key])

    if "stt" in clean:
        engine = str(clean["stt"]).strip().lower()
        if engine not in ("auto", "google", "whisper", "local"):
            warnings.append(f"moteur de reconnaissance inconnu '{clean['stt']}', "
                            "'auto' utilise")
            engine = "auto"
        clean["stt"] = engine

    if clean.get("wake_words") is None and "wake_words" in clean:
        clean.pop("wake_words")

    return clean, warnings


def merged_defaults(config: dict | None = None) -> dict:
    """Defauts finaux : DEFAULTS ecrases par le fichier de config."""
    merged = dict(DEFAULTS)
    clean, _ = normalise(config or {})
    merged.update(clean)
    return merged


def env_overrides(env: dict | None = None) -> dict:
    """Variables d'environnement JARVIS_* converties en cles de config."""
    env = os.environ if env is None else env
    mapping = {
        "JARVIS_LANG": "lang",
        "JARVIS_MODEL": "model",
        "JARVIS_BASE_URL": "base_url",
        "JARVIS_API_KEY": "api_key",
        "JARVIS_LOCAL_MODEL": "local_model",
        "JARVIS_LOCAL_BASE_URL": "local_base_url",
        "JARVIS_VOICE": "voice",
        "JARVIS_ABILITY": "ability",
        "JARVIS_MEMORY_PATH": "memory_path",
        "JARVIS_VOLUME": "volume",
        "JARVIS_RATE": "rate",
        "JARVIS_STT": "stt",
        "JARVIS_WHISPER_MODEL": "whisper_model",
        "JARVIS_HISTORY_PATH": "history_path",
        "JARVIS_PLUGINS_DIR": "plugins_dir",
    }
    out: dict = {}
    for var, key in mapping.items():
        value = env.get(var)
        if value:
            out[key] = value
    return out


EXAMPLE_CONFIG = """\
# Configuration de Jarvis (horizons 1 a 6).
# Priorite : ligne de commande > JARVIS_* (env) > ce fichier > defauts.
# Un fichier plat marche aussi : `lang: fr` au lieu de la section `voice`.

voice:
  lang: fr              # en | fr (prompt, voix et reconnaissance)
  wake: true            # exiger le mot d'activation « Jarvis »
  wake_words: [jarvis]  # mots acceptes (fuzzy, tolerant aux fautes)
  bargein: true         # l'utilisateur peut couper la parole
  vad: false            # endpointing par detection de voix (Horizon 5)
  max_words: 40         # longueur maximale des reponses
  max_speak: 0          # garde-fou TTS en secondes (0 = desactive)
  retries: 3            # tentatives sur le modele
  phrase_limit: 6       # delai max de reconnaissance par phrase
  ability: general knowledge
  volume: 1.0           # volume 0..1
  # voice: TTS_MS_FR-FR_HORTENSE_11.0
  # rate: 190
  stt: auto             # auto | google | whisper | local (Horizon 4)
  # whisper_model: base # tiny | base | small | medium | large

provider:
  # model: nvidia/nemotron-3-super-120b-a12b:free
  # base_url: https://openrouter.ai/api/v1
  # api_key: sk-...
  temperature: 0.4
  # local_model: llama3.2      # repli hors-ligne via Ollama
  # local_base_url: http://localhost:11434/v1
  no_fallback: false

memory:
  memory: true
  memory_path: .jarvis_memory.db

tools:
  tools: true
  plugins: true

# history_path: .jarvis_history.json
"""


def write_example_config(path: Path | str = "jarvis.example.yaml") -> Path:
    target = Path(path)
    target.write_text(EXAMPLE_CONFIG, encoding="utf-8")
    return target


__all__ = [
    "CONFIG_NAMES",
    "DEFAULTS",
    "KNOWN_KEYS",
    "EXAMPLE_CONFIG",
    "find_config",
    "load_config_file",
    "load_config",
    "normalise",
    "merged_defaults",
    "env_overrides",
    "coerce_lang",
    "write_example_config",
]
