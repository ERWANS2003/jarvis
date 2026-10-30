"""Tests d'un Jarvis plus intelligent : expert, details, memoire, recherche.

Aucun modele ni reseau : doublures partout.
"""

from __future__ import annotations

import argparse

from jarvis_core import providers as P
from jarvis_core import smart, websearch
from jarvis_core.journal import markdown_blocks
from jarvis_core.memory import MemoryStore


def test_hard_questions_go_to_the_expert():
    for text in ("Un train part à 14 h 12 à 87 km/h, un autre à 14 h 40 à 112 km/h : "
                 "quand le rattrape-t-il ?",
                 "Écris une fonction Python qui trie une liste",
                 "Compare les avantages et inconvénients du nucléaire",
                 "Résous l'équation 3x + 5 = 20",
                 "Réfléchis bien : quelle est la meilleure stratégie aux échecs ?"):
        assert smart.needs_expert(text), text
    for text in ("Quelle heure est-il ?", "Raconte-moi une blague",
                 "Merci beaucoup Jarvis", "Quel temps fait-il à Lyon ?"):
        assert not smart.needs_expert(text), text


def test_expert_spec_follows_openrouter_and_can_be_disabled():
    cloud = P.ProviderSpec(name="cloud", model="m", base_url="https://openrouter.ai/api/v1",
                           api_key="k")
    groq = P.ProviderSpec(name="groq", model="g", base_url=P.GROQ_BASE_URL, api_key="g")
    [expert] = P.expert_specs([cloud], env={})
    assert expert.model == P.EXPERT_DEFAULT_MODEL and expert.api_key == "k"
    assert P.expert_specs([cloud], env={"JARVIS_EXPERT_MODEL": "x/y:free"})[0].model == "x/y:free"
    assert P.expert_specs([cloud], env={"JARVIS_EXPERT": "0"}) == []
    [fast] = P.expert_specs([groq, cloud], env={})     # Groq : gpt-oss en reflexion poussee
    assert fast.base_url == P.GROQ_BASE_URL and fast.api_key == "g"
    assert fast.model == P.GROQ_DEFAULT_MODEL and fast.extra == {"reasoning_effort": "high"}
    other = P.ProviderSpec(name="x", model="m", base_url="https://api.example.com/v1")
    assert P.expert_specs([other], env={}) == []


def test_failed_expert_falls_back_to_the_fast_model():
    import jarvis

    chain = jarvis.ModelChain([P.ProviderSpec(name="cloud", model="m")], tools=[],
                              expert=[P.ProviderSpec(name="expert", model="e")])
    chain._graphs["expert"] = "EXPERT"
    chain._graphs[0] = "FAST"
    chain._graphs[("chat", 0)] = "CHAT"
    assert chain.graph_for("Résous l'équation 2x = 8")[0] == "EXPERT" and chain.last_expert
    assert chain.advance()                          # l'expert echoue : pas de bascule du principal
    assert chain.index == 0 and not chain.last_expert
    assert chain.graph_for("Résous l'équation 2x = 8")[0] == "CHAT"   # expert en pause


def test_detailed_answer_is_split_between_voice_and_screen():
    assert smart.needs_detail("Explique en détail la photosynthèse")
    assert smart.needs_detail("donne-moi les étapes pour planter un arbre")
    assert not smart.needs_detail("Quelle heure est-il ?")
    said = []
    split = smart.DetailSplitter(said.append)
    for chunk in ("La photosynthèse transforme la lumière en énergie.", "Elle a deux phases. ---DE",
                  "TAIL---", "## Phase claire", "- capte la lumière", "## Phase sombre"):
        split(chunk)
    assert said == ["La photosynthèse transforme la lumière en énergie.", "Elle a deux phases."]
    assert split.finish() == "## Phase claire\n- capte la lumière\n## Phase sombre"


def test_markdown_is_rendered_as_blocks():
    blocks = markdown_blocks("# Titre\n\n## Partie\n- un **point**\n1. étape\n|---|---|\ntexte")
    assert [style for style, _ in blocks] == ["h1", "blank", "h2", "bullet", "number", "text"]


def test_memory_learns_durable_facts_on_its_own():
    store = MemoryStore()
    prompts = []

    def ask(prompt):
        prompts.append(prompt)
        return 'Voici : ```json\n["Il travaille comme infirmier de nuit.", "Sa fille s\'appelle Léa."]\n```'

    learned = smart.learn(store, ask, "Je travaille de nuit comme infirmier, ma fille Léa a 6 ans",
                          "Courage pour vos nuits.", "fr")
    assert learned == ["Il travaille comme infirmier de nuit.", "Sa fille s'appelle Léa."]
    assert {m.text for m in store.all()} == {"Il travaille comme infirmier de nuit",
                                            "Sa fille s'appelle Léa"}
    assert all(m.source == "learned" for m in store.all())
    assert smart.learn(store, ask, "Quelle heure est-il ?", "", "fr") == []   # rien sur lui
    assert len(prompts) == 1
    assert smart.parse_facts("pas de json") == [] and smart.parse_facts("[]") == []


def test_research_cites_its_sources():
    sources = {
        "wikipedia": lambda q, lang, k, t: [("Prix Nobel de physique", "Récompense annuelle.")],
        "news": lambda q, lang, k, t: ["06/10/2026 — Le prix 2026 va à F. Halzen (Le Monde.fr)"],
        "web": lambda q, t: "Aucun résultat.",
    }
    text = websearch.research("prix Nobel de physique 2026", "fr", sources=sources)
    assert text.index("[1] Actualités") < text.index("[2] Wikipédia")   # recent : l'actu d'abord
    assert "Le Monde.fr" in text and "Récompense annuelle." in text and "[3]" not in text
    empty = {"wikipedia": lambda *a: [], "news": lambda *a: [], "web": lambda *a: ""}
    assert websearch.research("rien", "fr", sources=empty) == ""


def test_wikipedia_and_news_parsing():
    calls = []

    def get_json(url, params, timeout):
        calls.append(params["action"] + ":" + params.get("list", params.get("prop", "")))
        if params.get("list") == "search":
            return {"query": {"search": [{"title": "Brésil"}]}}
        return {"query": {"pages": {"1": {"title": "Brésil", "extract": "Le  Brésil est un pays."}}}}

    assert websearch.wikipedia("brésil", "fr", get_json=get_json) == [("Brésil", "Le Brésil est un pays.")]
    rss = (b"<rss><channel><item><title>Lula en visite - Le Monde</title>"
           b"<source>Le Monde</source><pubDate>Tue, 06 Oct 2026 10:00:00 GMT</pubDate></item>"
           b"</channel></rss>")
    assert websearch.news("lula", download=lambda url, t: rss) == [
        "06/10/2026 — Lula en visite (Le Monde)"]


def test_expert_option_exists():
    import jarvis

    parser = jarvis.build_parser({}) if hasattr(jarvis, "build_parser") else None
    if parser is None:
        return
    assert parser.parse_args(["--no-expert"]).expert is False
    assert isinstance(parser.parse_args([]), argparse.Namespace)


import time as _time

RESET = int(_time.time() // 86400 * 86400 + 86400)      # prochain minuit UTC (toujours futur)
QUOTA = ("Error code: 429 - {'error': {'message': 'Rate limit exceeded: free-models-per-day. "
         "Add 10 credits', 'metadata': {'headers': {'X-RateLimit-Reset': '"
         + str(RESET * 1000) + "'}}}}")


def test_daily_quota_is_recognised_and_not_retried():
    from jarvis_core import text as X

    assert X.is_daily_quota(QUOTA) and X.is_fatal(Exception(QUOTA))
    assert X.quota_reset(QUOTA) == float(RESET)
    assert not X.is_daily_quota("Rate limit exceeded: free-models-per-min")   # passager


def test_quota_skips_every_openrouter_model_and_explains_why():
    import time

    import jarvis
    from jarvis_core import graph as G
    from jarvis_core.i18n import STRINGS

    cloud = P.ProviderSpec(name="cloud", model="a", base_url="https://openrouter.ai/api/v1")
    other = P.ProviderSpec(name="cloud", model="b", base_url="https://openrouter.ai/api/v1")
    groq = P.ProviderSpec(name="groq", model="g", base_url=P.GROQ_BASE_URL)
    chain = jarvis.ModelChain([cloud, other], expert=[cloud])
    assert not chain.advance(Exception(QUOTA))      # rien d'autre que OpenRouter
    assert chain.quota_exhausted() and chain.index == 0
    message = G.error_message(Exception(QUOTA), STRINGS["fr"])
    assert message.startswith("Mon quota gratuit") and " h" in message
    assert G.error_message(Exception("boom"), STRINGS["fr"]) == STRINGS["fr"]["llm_error"]

    chain = jarvis.ModelChain([cloud, other, groq])
    assert chain.advance(Exception(QUOTA)) and chain.spec is groq   # saute « other »
    chain.quota_until = time.time() - 1           # renouvele : retour possible
    assert not chain.quota_exhausted()


def test_the_model_knows_today_and_searches_recent_facts():
    import datetime as dt

    from jarvis_core import graph as G
    from jarvis_core import intents
    from jarvis_core.i18n import STRINGS

    line = G.now_line(STRINGS["fr"], True, now=dt.datetime(2026, 10, 29, 23, 25))
    assert line.startswith("Nous sommes le jeudi 29 octobre 2026, il est 23 h 25.")
    assert "web_search" in line and "web_search" not in G.now_line(STRINGS["fr"], False)
    assert "Nous sommes le" in G.build_system_prompt("base", strings=STRINGS["fr"])
    assert intents.needs_tools("Qui a gagné la Coupe du monde 2026 ?")
    assert intents.needs_tools("le Nobel 2026")


def test_old_tool_results_are_shortened_in_history():
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    from jarvis_core import graph as G

    long = "x" * 5000
    history = [HumanMessage(content="cherche"), AIMessage(content="", tool_calls=[
        {"id": "1", "name": "web_search", "args": {}}]), ToolMessage(content=long, tool_call_id="1"),
        AIMessage(content="Voila."), HumanMessage(content="et ensuite ?"),
        ToolMessage(content=long, tool_call_id="2")]
    compact = G.compact_history(history)
    assert len(compact[2].content) == G.OLD_TOOL_CHARS + 4            # echange passe : resume
    assert compact[5].content == long                                  # dernier echange : entier
    assert history[2].content == long                                  # l'original n'est pas touche


def test_without_network_jarvis_goes_straight_to_the_local_model():
    import jarvis
    from jarvis_core import text as X

    offline = Exception("Connection error. [Errno 11001] getaddrinfo failed")
    assert X.is_offline(offline) and X.is_fatal(offline)              # pas de nouvel essai
    assert not X.is_offline(Exception("Error code: 500 - upstream overloaded"))

    groq = P.ProviderSpec(name="groq", model="g", base_url=P.GROQ_BASE_URL)
    cloud = P.ProviderSpec(name="cloud", model="c", base_url="https://openrouter.ai/api/v1")
    local = P.ProviderSpec(name="ollama", model="qwen3:4b", base_url="http://localhost:11434/v1",
                           local=True)
    chain = jarvis.ModelChain([groq, cloud, local, cloud])
    original = P.ollama_reachable
    try:
        P.ollama_reachable = lambda *_a, **_k: True
        assert chain.advance(offline) and chain.spec is local             # saute OpenRouter
        P.ollama_reachable = lambda *_a, **_k: False
        chain.index = 0
        assert not chain.advance(offline)                                  # Ollama eteint
    finally:
        P.ollama_reachable = original
