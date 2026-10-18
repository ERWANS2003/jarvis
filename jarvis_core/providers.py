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


def build_provider_chain(args, env: dict | None = None) -> list[ProviderSpec]:
    """Chaine ordonnee : fournisseur principal puis replis locaux.

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

    chain = [primary]
    if not getattr(args, "no_fallback", False):
        chain += fallback_specs(env, getattr(args, "local_model", None),
                                getattr(args, "local_base_url", None))
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
    "ProviderSpec",
    "is_openai_default",
    "is_local_url",
    "resolve_api_key",
    "port_open",
    "ollama_reachable",
    "build_llm",
    "fallback_specs",
    "build_provider_chain",
    "api_key_problem",
]
