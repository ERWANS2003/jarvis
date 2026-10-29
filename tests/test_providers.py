"""Tests des fournisseurs et de la bascule local/cloud (Horizon 4)."""

from __future__ import annotations

import argparse

from jarvis_core import providers as P


def test_is_openai_default():
    assert P.is_openai_default(None) is True
    assert P.is_openai_default("https://api.openai.com/v1") is True
    assert P.is_openai_default("https://openrouter.ai/api/v1") is False


def test_is_local_url():
    assert P.is_local_url("http://localhost:11434/v1") is True
    assert P.is_local_url("http://127.0.0.1:8080/v1") is True
    assert P.is_local_url("https://api.openai.com/v1") is False
    assert P.is_local_url("") is False


def test_resolve_api_key_openai_requires_openai_key():
    assert P.resolve_api_key(None, None, {}) is None
    assert P.resolve_api_key(None, None, {"OPENAI_API_KEY": "sk-abc"}) == "sk-abc"
    # une cle OpenRouter ne doit pas servir pour OpenAI
    assert P.resolve_api_key(
        "https://api.openai.com/v1", None, {"OPENROUTER_API_KEY": "sk-or"}
    ) is None


def test_resolve_api_key_generic_url():
    env = {"OPENROUTER_API_KEY": "sk-or-x"}
    assert P.resolve_api_key("https://openrouter.ai/api/v1", None, env) == "sk-or-x"
    assert P.resolve_api_key("https://openrouter.ai/api/v1", "explicit", env) == "explicit"
    assert P.resolve_api_key("https://openrouter.ai/api/v1", None, {}) == "sk-no_key"


def test_resolve_api_key_prefers_jarvis_then_openrouter():
    env = {"JARVIS_API_KEY": "j", "OPENROUTER_API_KEY": "o"}
    assert P.resolve_api_key("https://openrouter.ai/api/v1", None, env) == "j"


def test_resolve_api_key_local():
    assert P.resolve_api_key("http://localhost:11434/v1", None, {}) == "local"


def test_port_open_false_on_unused_port():
    assert P.port_open("127.0.0.1", 1, timeout=0.2) is False


def test_ollama_reachable_false_there():
    assert P.ollama_reachable("http://127.0.0.1:1", timeout=0.2) is False


def test_build_provider_chain_primary_only():
    args = argparse.Namespace(model="m", base_url="https://openrouter.ai/api/v1",
                              api_key="k", temperature=0.2, no_fallback=True)
    chain = P.build_provider_chain(args, env={})
    assert len(chain) == 1
    assert chain[0].model == "m"
    assert chain[0].api_key == "k"
    assert chain[0].is_local is False


def test_build_provider_chain_with_local_fallback():
    args = argparse.Namespace(model="cloud-m", base_url=None, api_key=None,
                              temperature=None, no_fallback=False,
                              local_model="llama3.2", local_base_url=None)
    env = {"OPENAI_API_KEY": "sk-openai"}
    chain = P.build_provider_chain(args, env=env)
    assert [s.name for s in chain] == ["openai", "ollama"]
    assert chain[0].model == "cloud-m"
    assert chain[1].is_local is True
    assert chain[1].api_key == "local"


def test_build_provider_chain_no_local_without_model():
    args = argparse.Namespace(model="m", base_url=None, api_key=None,
                              temperature=None, no_fallback=False,
                              local_model=None, local_base_url=None)
    chain = P.build_provider_chain(args, env={"OPENAI_API_KEY": "sk-x"})
    assert [s.name for s in chain] == ["openai"]


def test_api_key_problem():
    args = argparse.Namespace(base_url=None, api_key=None)
    assert P.api_key_problem(args, env={}) is not None
    assert P.api_key_problem(args, env={"OPENAI_API_KEY": "sk-x"}) is None
    other = argparse.Namespace(base_url="https://openrouter.ai/api/v1", api_key=None)
    assert P.api_key_problem(other, env={}) is None


def test_build_llm_signature():
    spec = P.ProviderSpec(name="test", model="test-model",
                          base_url="http://localhost:11434/v1",
                          api_key="local", local=True, temperature=0.3)
    llm = P.build_llm(spec)
    assert llm.model_name == "test-model"
    assert str(llm.openai_api_base).startswith("http://localhost")


def test_build_llm_omits_temperature_when_none():
    spec = P.ProviderSpec(name="test", model="m", api_key="k", temperature=None)
    llm = P.build_llm(spec)
    assert llm.temperature is None


def test_provider_label():
    spec = P.ProviderSpec(name="ollama", model="llama3.2",
                          base_url="http://localhost:11434/v1", api_key="local")
    assert spec.is_local is True
    assert "(local)" in spec.label()


def test_groq_goes_first_when_its_key_exists():
    args = argparse.Namespace(model="m", base_url="https://openrouter.ai/api/v1",
                              api_key="k", temperature=None, no_fallback=True)
    chain = P.build_provider_chain(args, env={"GROQ_API_KEY": "gsk_test"})
    assert [s.name for s in chain] == ["groq", "groq", "cloud"]   # Groq + son secours
    assert chain[0].base_url == P.GROQ_BASE_URL and chain[0].api_key == "gsk_test"
    assert chain[0].model == P.GROQ_DEFAULT_MODEL
    assert chain[1].model == P.GROQ_FALLBACK_MODELS[0]
    [expert] = P.expert_specs(chain, env={})
    assert expert.base_url == P.GROQ_BASE_URL and expert.extra == {"reasoning_effort": "high"}
    env = {"GROQ_API_KEY": "gsk_test", "JARVIS_GROQ_MODEL": "qwen/qwen3-32b"}
    assert P.build_provider_chain(args, env=env)[0].model == "qwen/qwen3-32b"
    env = {"GROQ_API_KEY": "gsk_test", "JARVIS_GROQ": "0"}
    assert [s.name for s in P.build_provider_chain(args, env=env)] == ["cloud"]
    assert [s.name for s in P.build_provider_chain(args, env={})] == ["cloud"]
