"""Horizon 4 - fournisseurs de modele et bascule local / hors-ligne.

Le modele est toujours joint via une API compatible OpenAI, ce qui permet de
passer d'un fournisseur cloud (OpenAI, OpenRouter, Groq, ...) a un modele local
(Ollama, llama.cpp, vLLM) sans changer une ligne du graphe.

La chaine de fournisseurs est ordonnee : le premier est le principal, les
suivants servent de repli automatique quand le principal echoue (quota epuise,
reseau coupe, cle invalide).
"""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass, field
from urllib.parse import urlparse

OPENAI_DEFAULT = "https://api.openai.com/v1"
OLLAMA_DEFAULT = "http://localhost:11434/v1"
OPENROUTER_HOST = "openrouter.ai"

# Modeles gratuits OpenRouter proposes en repli. Meme URL et meme cle que le
# modele principal : seul le nom change, ce qui suffit a repartir quand le
# modele courant est sature ou retire du tier gratuit. Ordre retenu apres un
# essai reel (28/10/2026 : francais, appel d'outil, temps de reponse) ; le
# catalogue gratuit change souvent, `JARVIS_FALLBACK_MODELS` permet d'ajuster.
OPENROUTER_FREE_FALLBACKS = (
    "nvidia/nemotron-3.5-super-vl:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "google/gemma-4-26b-a4b-it:free",
    "google/gemma-4-31b-it:free",
)
# nemotron-3.5-lightning retire le 29/10/2026 : 75 s de reponse puis blocage.

# Groq : memes modeles ouverts, servis sur puces LPU (~1 s avant la premiere
# phrase contre 4 a 8 s pour les modeles gratuits d'OpenRouter). Palier gratuit
# avec une cle personnelle (console.groq.com/keys). Quand GROQ_API_KEY existe,
# Groq passe en tete et OpenRouter devient le repli.
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
# Catalogue Groq verifie le 29/10/2026 (llama-3.3-70b n'y est plus) : gpt-oss-120b
# repond en ~1,4 s en bon francais, appelle les outils et sait raisonner
# (probleme des trains juste en 1,8 s) ; qwen3.8-27b (~1 s) sert de secours.
GROQ_DEFAULT_MODEL = "openai/gpt-oss-120b"
GROQ_FALLBACK_MODELS = ("qwen/qwen3.8-27b",)

# Ordre de recherche des cles quand l'URL n'est pas celle d'OpenAI.
GENERIC_KEY_ENV = ("JARVIS_API_KEY", "OPENROUTER_API_KEY", "GROQ_API_KEY",
                   "OPENAI_API_KEY")


@dataclass
class ProviderSpec:
    """Description complete d'un fournisseur joignable."""

    name: str
    model: str
    base_url: str | None = None
    api_key: str | None = None
    local: bool = False
    temperature: float | None = None
    extra: dict = field(default_factory=dict)

    @property
    def is_local(self) -> bool:
        return self.local or is_local_url(self.base_url or "")

    def label(self) -> str:
        suffix = " (local)" if self.is_local else ""
        return f"{self.name}:{self.model}{suffix}"


def is_openai_default(base_url: str | None) -> bool:
    if not base_url:
        return True
    return base_url.rstrip("/").lower().startswith("https://api.openai.com")


def is_local_url(base_url: str) -> bool:
    """Vrai pour une adresse locale (localhost, 127.0.0.1, ::1)."""
    if not base_url:
        return False
    host = (urlparse(base_url).hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def resolve_api_key(base_url: str | None, explicit: str | None = None,
                    env: dict | None = None) -> str | None:
    """Trouve la cle API a utiliser, ou None si elle est obligatoire et absente.

    * URL OpenAI par defaut  -> OPENAI_API_KEY obligatoire.
    * autre URL             -> cle explicite, puis variables d'environnement.
    * URL locale            -> une cle factice suffit.
    """
    env = os.environ if env is None else env
    if explicit:
        return explicit
    if is_local_url(base_url or ""):
        return env.get("JARVIS_API_KEY") or "local"
    if is_openai_default(base_url):
        return env.get("OPENAI_API_KEY")
    for name in GENERIC_KEY_ENV:
        if env.get(name):
            return env[name]
    return "sk-no_key"


def port_open(host: str, port: int, timeout: float = 0.6) -> bool:
    """Test TCP rapide (pas de HTTP) pour savoir si un service local repond."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def ollama_reachable(base_url: str = OLLAMA_DEFAULT, timeout: float = 0.6) -> bool:
    parsed = urlparse(base_url)
    host = parsed.hostname or "localhost"
    port = parsed.port or 11434
    return port_open(host, port, timeout)


def build_llm(spec: ProviderSpec, max_tokens: int | None = None, **overrides):
    """Construit le client de chat pour un fournisseur donne."""
    from langchain_openai import ChatOpenAI

    kwargs: dict = {
        "model": spec.model,
        "base_url": spec.base_url,
        "api_key": spec.api_key or "sk-no_key",
        "timeout": overrides.pop("timeout", 60.0),
        "max_retries": overrides.pop("max_retries", 0),
    }
    temperature = overrides.pop("temperature", spec.temperature)
    if temperature is not None:
        kwargs["temperature"] = temperature
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    kwargs.update(spec.extra)
    kwargs.update(overrides)
    return ChatOpenAI(**kwargs)


def fallback_specs(env: dict | None = None, local_model: str | None = None,
                   local_base_url: str | None = None) -> list[ProviderSpec]:
    """Fournisseurs de repli, du plus local au plus distant."""
    env = os.environ if env is None else env
    specs: list[ProviderSpec] = []
    base = local_base_url or env.get("JARVIS_LOCAL_BASE_URL") or OLLAMA_DEFAULT
    model = local_model or env.get("JARVIS_LOCAL_MODEL")
    if model:
        specs.append(
            ProviderSpec(
                name="ollama", model=model, base_url=base,
                api_key="local", local=True,
            )
        )
    return specs


def is_openrouter(base_url: str | None) -> bool:
    """Vrai si l'URL pointe vers OpenRouter (le seul a offrir des modeles gratuits)."""
    host = (urlparse(base_url or "").hostname or "").lower()
    return host == OPENROUTER_HOST or host.endswith("." + OPENROUTER_HOST)


def cloud_fallback_specs(primary: ProviderSpec,
                         env: dict | None = None) -> list[ProviderSpec]:
    """Autres modeles gratuits du meme fournisseur cloud.

    Quand la cle pointe vers OpenRouter, un modele gratuit peut etre sature ou
    retire du catalogue sans que la cle change : on enchaine donc d'autres
    modeles gratuits, avec la meme URL et la meme cle. `JARVIS_FALLBACK_MODELS`
    (noms separes par des virgules) remplace la liste par defaut. Aucun repli
    n'est propose pour les autres fournisseurs : on ne connait pas leurs
    modeles gratuits et une bascule silencieuse vers un modele payant serait
    une mauvaise surprise.
    """
    env = os.environ if env is None else env
    if not is_openrouter(primary.base_url):
        return []
    raw = (env.get("JARVIS_FALLBACK_MODELS") or "").strip()
    models = [m.strip() for m in raw.split(",")] if raw \
        else list(OPENROUTER_FREE_FALLBACKS)
    specs: list[ProviderSpec] = []
    for model in models:
        if not model or model == primary.model:
            continue
        specs.append(
            ProviderSpec(
                name=primary.name,
                model=model,
                base_url=primary.base_url,
                api_key=primary.api_key,
                temperature=primary.temperature,
            )
        )
    return specs


def groq_key(env: dict | None = None) -> str:
    """Cle Groq utilisable ("" si absente ou Groq desactive par JARVIS_GROQ=0)."""
    env = os.environ if env is None else env
    if env.get("JARVIS_GROQ", "1").strip().lower() in {"0", "false", "non", "no"}:
        return ""
    return (env.get("GROQ_API_KEY") or "").strip().strip('"').strip("'")


def groq_specs(primary: ProviderSpec, env: dict | None = None) -> list[ProviderSpec]:
    """Groq en tete de chaine quand GROQ_API_KEY est renseignee.

    `JARVIS_GROQ_MODEL` choisit le modele, `JARVIS_GROQ=0` desactive Groq.
    Le secours Groq a ses propres limites : il prend le relais avant OpenRouter.
    """
    env = os.environ if env is None else env
    key = groq_key(env)
    if not key or "groq.com" in (primary.base_url or ""):
        return []  # pas de cle, ou Groq est deja le fournisseur principal
    model = (env.get("JARVIS_GROQ_MODEL") or GROQ_DEFAULT_MODEL).strip()
    models = [model] + [m for m in GROQ_FALLBACK_MODELS if m != model]
    return [ProviderSpec(name="groq", model=name, base_url=GROQ_BASE_URL, api_key=key,
                         temperature=primary.temperature) for name in models]


# Modele « expert » pour les questions difficiles (maths, code, analyse) :
# teste le 29/10/2026, seul a trouver juste un probleme de trains (20 s).
EXPERT_DEFAULT_MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"


def expert_specs(chain: list[ProviderSpec], env: dict | None = None) -> list[ProviderSpec]:
    """Modele qui raisonne : Groq (gpt-oss-120b, reflexion poussee, ~2 s) si la cle
    existe, sinon le meme OpenRouter que la chaine. [] si impossible.

    `JARVIS_EXPERT_MODEL` change le modele, `JARVIS_EXPERT=0` le desactive.
    """
    env = os.environ if env is None else env
    if env.get("JARVIS_EXPERT", "1").strip().lower() in {"0", "false", "non", "no"}:
        return []
    groq = next((spec for spec in chain if "groq.com" in (spec.base_url or "")), None)
    if groq is not None:
        return [ProviderSpec(name="expert", model=(env.get("JARVIS_EXPERT_MODEL")
                                                   or GROQ_DEFAULT_MODEL).strip(),
                             base_url=GROQ_BASE_URL, api_key=groq.api_key,
                             temperature=groq.temperature,
                             extra={"reasoning_effort": "high"})]
    base = next((spec for spec in chain if is_openrouter(spec.base_url)), None)
    if base is None:
        return []
    model = (env.get("JARVIS_EXPERT_MODEL") or EXPERT_DEFAULT_MODEL).strip()
    return [ProviderSpec(name="expert", model=model, base_url=base.base_url,
                         api_key=base.api_key, temperature=base.temperature)]


def build_provider_chain(args, env: dict | None = None) -> list[ProviderSpec]:
    """Chaine ordonnee : principal, replis locaux, puis autres modeles cloud.

    `args` est l'espace de noms argparse de jarvis.py (model, base_url, api_key,
    temperature, local_model, local_base_url, no_fallback).
    """
    env = os.environ if env is None else env
    base_url = getattr(args, "base_url", None) or env.get("JARVIS_BASE_URL") \
        or OPENAI_DEFAULT
    model = getattr(args, "model", None) or env.get("JARVIS_MODEL") \
        or "gpt-4o-mini"
    explicit = getattr(args, "api_key", None) or env.get("JARVIS_API_KEY")

    primary = ProviderSpec(
        name="openai" if is_openai_default(base_url) else "cloud",
        model=model,
        base_url=base_url,
        api_key=resolve_api_key(base_url, explicit, env),
        temperature=getattr(args, "temperature", None),
    )

    chain = groq_specs(primary, env) + [primary]
    if not getattr(args, "no_fallback", False):
        # Local d'abord (gratuit, prive, souvent deja lance), puis les autres
        # modeles gratuits du cloud : la panne d'un modele ne coupe pas Jarvis.
        chain += fallback_specs(env, getattr(args, "local_model", None),
                                getattr(args, "local_base_url", None))
        chain += cloud_fallback_specs(primary, env)
    return chain


def api_key_problem(args, env: dict | None = None) -> str | None:
    """Retourne un message d'erreur si la cle du fournisseur principal manque."""
    env = os.environ if env is None else env
    base_url = getattr(args, "base_url", None) or env.get("JARVIS_BASE_URL") \
        or OPENAI_DEFAULT
    if is_openai_default(base_url):
        if not (getattr(args, "api_key", None) or env.get("OPENAI_API_KEY")):
            return ("OPENAI_API_KEY est introuvable. Renseigne-la dans .env "
                    "ou passe --api_key.")
    return None


__all__ = [
    "OPENAI_DEFAULT",
    "OLLAMA_DEFAULT",
    "OPENROUTER_HOST",
    "OPENROUTER_FREE_FALLBACKS",
    "ProviderSpec",
    "is_openai_default",
    "is_local_url",
    "is_openrouter",
    "resolve_api_key",
    "port_open",
    "ollama_reachable",
    "build_llm",
    "fallback_specs",
    "cloud_fallback_specs",
    "build_provider_chain",
    "groq_specs",
    "groq_key",
    "expert_specs",
    "GROQ_BASE_URL",
    "api_key_problem",
]
