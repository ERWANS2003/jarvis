"""Tests du graphe, du prompt systeme et de l'historique (Horizons 1 a 3)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import tool

from jarvis_core import graph as G
from jarvis_core.memory import MemoryStore

STRINGS = {
    "tool_guidance": "You have tools.",
    "memory_guidance": "Remember things.",
    "profile_header": "About the user:",
    "memory_header": "Relevant memories:",
    "episodes_header": "Past conversations:",
}


# --------------------------------------------------------------------------- #
# Prompt systeme
# --------------------------------------------------------------------------- #
def test_build_system_prompt_minimal():
    assert G.build_system_prompt("BASE") == "BASE"


def test_build_system_prompt_with_tools():
    prompt = G.build_system_prompt("BASE", strings=STRINGS, with_tools=True)
    assert prompt.startswith("BASE")
    assert "You have tools." in prompt


def test_build_system_prompt_includes_memory():
    store = MemoryStore()
    store.remember("the user lives in Lyon", kind="profile")
    prompt = G.build_system_prompt("BASE", memory=store, strings=STRINGS,
                                   with_tools=True)
    assert "About the user:" in prompt
    assert "Lyon" in prompt


def test_build_system_prompt_recall_when_query():
    store = MemoryStore()
    store.remember("the user keeps bees on the roof")
    prompt = G.build_system_prompt("BASE", memory=store, query="bees",
                                   strings=STRINGS)
    assert "Relevant memories:" in prompt
    assert "bees" in prompt


# --------------------------------------------------------------------------- #
# Historique
# --------------------------------------------------------------------------- #
def test_trim_history_keeps_last_messages():
    history = [HumanMessage(content=str(i)) for i in range(10)]
    trimmed = G.trim_history(history, keep=3)
    assert [m.content for m in trimmed] == ["7", "8", "9"]


def test_trim_history_does_not_orphan_tool_results():
    history = [
        HumanMessage(content="q1"),
        AIMessage(content="", tool_calls=[{"name": "t", "args": {}, "id": "1"}]),
        ToolMessage(content="result", tool_call_id="1"),
        AIMessage(content="a1"),
        HumanMessage(content="q2"),
        AIMessage(content="a2"),
    ]
    # garder 3 remonterait au ToolMessage : on recule jusqu'a la question
    trimmed = G.trim_history(history, keep=3)
    assert isinstance(trimmed[0], HumanMessage)
    assert trimmed[0].content == "q2"


def test_trim_history_noop_when_short():
    history = [HumanMessage(content="hi")]
    assert G.trim_history(history, keep=40) == history


def test_make_turn_messages_layout():
    history = [HumanMessage(content="old"), AIMessage(content="reply")]
    messages = G.make_turn_messages("SYS", history, "new question", keep=40)
    types = [type(m).__name__ for m in messages]
    assert types == ["SystemMessage", "HumanMessage", "AIMessage", "HumanMessage"]
    assert messages[0].id == G.SYSTEM_ID
    assert messages[-1].content == "new question"


def test_message_text_handles_structured_content():
    assert G.message_text(AIMessage(content="plain")) == "plain"
    structured = AIMessage(content=[{"type": "text", "text": "part1"},
                                    {"type": "text", "text": "part2"}])
    assert G.message_text(structured) == "part1part2"


# --------------------------------------------------------------------------- #
# Graphe simple (sans outils)
# --------------------------------------------------------------------------- #
class FakeLLM:
    def __init__(self, answer="Bonjour."):
        self.answer = answer

    def invoke(self, messages):
        return AIMessage(content=self.answer)


def test_build_graph_without_tools():
    graph = G.build_graph(FakeLLM("42"))
    result = G.run_sync(graph, [HumanMessage(content="question")])
    assert result.ok is True
    assert result.answer == "42"


# --------------------------------------------------------------------------- #
# Graphe ReAct (avec outils)
# --------------------------------------------------------------------------- #
@tool
def get_weather(location: str) -> str:
    """Get the weather for a location."""
    return f"sunny in {location}"


class FakeToolLLM:
    """Modele factice : demande l'outil puis conclut."""

    def __init__(self):
        self.calls = 0

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.calls += 1
        if any(isinstance(m, ToolMessage) for m in messages):
            return AIMessage(content="It is sunny.")
        return AIMessage(content="", tool_calls=[
            {"name": "get_weather", "args": {"location": "Lyon"}, "id": "call_1"}
        ])


def test_react_graph_calls_tool_then_answers():
    graph = G.build_graph(FakeToolLLM(), tools=[get_weather])
    result = G.run_sync(graph, [HumanMessage(content="weather in Lyon?")])
    kinds = [type(m).__name__ for m in result.messages]
    assert "ToolMessage" in kinds
    assert any("sunny in Lyon" in G.message_text(m) for m in result.messages)
    assert result.answer == "It is sunny."


# --------------------------------------------------------------------------- #
# stream_reply (graphe factice scripte)
# --------------------------------------------------------------------------- #
class FakeGraph:
    def __init__(self, script, fail_first: bool = False, error: Exception | None = None):
        self.script = script
        self.fail_first = fail_first
        self.error = error or OSError("boom")
        self.calls = 0

    def stream(self, inputs, stream_mode=None):
        self.calls += 1
        if self.fail_first and self.calls == 1:
            raise self.error
        for item in self.script:
            yield item


def _token(text):
    return ("messages", (AIMessageChunk(content=text),
                         {"langgraph_node": "model"}))


def _tool_chunk(name):
    return ("messages", (AIMessageChunk(content="", tool_call_chunks=[
        {"name": name, "args": "{}", "id": "c1", "index": 0}
    ]), {"langgraph_node": "model"}))


def _update(messages):
    return ("updates", {"model": {"messages": messages}})


def test_stream_reply_speaks_sentences():
    script = [_token("Hello "), _token("there. How "), _token("are you?")]
    spoken = []
    result = G.stream_reply(FakeGraph(script), [HumanMessage(content="hi")],
                            spoken.append, retries=1)
    assert result.ok is True
    assert spoken == ["Hello there.", "How are you?"]


def test_stream_reply_ignores_tool_output():
    script = [
        _tool_chunk("get_weather"),
        ("messages", (ToolMessage(content="SUNNY-IN-LYON", tool_call_id="c1"),
                      {"langgraph_node": "tools"})),
        _token("It is sunny."),
        _update([AIMessage(content="It is sunny.")]),
    ]
    spoken = []
    tools = []
    result = G.stream_reply(FakeGraph(script), [HumanMessage(content="w")],
                            spoken.append, retries=1, on_tool=tools.append)
    assert spoken == ["It is sunny."]
    assert all("SUNNY-IN-LYON" not in piece for piece in spoken)
    assert tools == ["get_weather"]
    assert result.tools_used == ["get_weather"]
    assert result.answer == "It is sunny."


def test_stream_reply_retries_once():
    class _NoSleep:
        def sleep(self, _seconds):
            pass

    script = [_token("Recovered.")]
    graph = FakeGraph(script, fail_first=True)
    spoken = []
    original = G.time
    G.time = _NoSleep()
    try:
        result = G.stream_reply(graph, [HumanMessage(content="q")],
                                spoken.append, retries=2)
    finally:
        G.time = original
    assert graph.calls == 2
    assert result.ok is True
    assert spoken == ["Recovered."]


def test_stream_reply_stops_on_fatal_error():
    class Fatal(Exception):
        status_code = 401

    graph = FakeGraph([_token("never")], fail_first=True, error=Fatal("bad key"))
    result = G.stream_reply(graph, [HumanMessage(content="q")], lambda _: None,
                            retries=5)
    assert graph.calls == 1
    assert result.ok is False
    assert isinstance(result.error, Fatal)


def test_stream_reply_long_unpunctuated_buffer():
    script = [_token("x" * 200), _token("y" * 200)]
    spoken = []
    result = G.stream_reply(FakeGraph(script), [HumanMessage(content="q")],
                            spoken.append, retries=1)
    assert result.ok is True
    assert len("".join(spoken)) == 400


def test_stream_reply_flushes_tail():
    script = [_token("No punctuation here")]
    spoken = []
    result = G.stream_reply(FakeGraph(script), [HumanMessage(content="q")],
                            spoken.append, retries=1)
    assert spoken == ["No punctuation here"]
    # Le texte sans ponctuation part dans la queue : il compte comme parle.
    assert result.spoke is True
    assert result.empty is False


def test_stream_reply_reports_spoke_when_it_speaks():
    script = [_token("Hello there.")]
    result = G.stream_reply(FakeGraph(script), [HumanMessage(content="hi")],
                            lambda _: None, retries=1)
    assert result.ok is True
    assert result.spoke is True
    assert result.empty is False


def test_stream_reply_reports_empty_when_model_says_nothing():
    # Modele de raisonnement : rien dans `content`, aucun appel d'outil.
    script = [_update([AIMessage(content="")])]
    spoken = []
    result = G.stream_reply(FakeGraph(script), [HumanMessage(content="hi")],
                            spoken.append, retries=1)
    assert result.ok is True
    assert spoken == []
    assert result.spoke is False
    assert result.empty is True


def test_functional_answer_is_not_empty():
    # run_sync doit, lui aussi, signaler une reponse exploitable.
    graph = G.build_graph(FakeLLM("42"))
    result = G.run_sync(graph, [HumanMessage(content="question")])
    assert result.spoke is True
    assert result.empty is False


# --------------------------------------------------------------------------- #
# Historique JSON
# --------------------------------------------------------------------------- #
def test_serialise_skips_system_messages():
    data = G.serialise([
        SystemMessage(content="SYS"),
        HumanMessage(content="hi"),
        AIMessage(content="hello"),
    ])
    assert data == [{"type": "HumanMessage", "content": "hi"},
                    {"type": "AIMessage", "content": "hello"}]


def test_save_and_load_history_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "history.json"
        written = G.save_history([
            SystemMessage(content="SYS"),
            HumanMessage(content="bonjour"),
            AIMessage(content="salut"),
        ], path)
        assert written == 2
        restored = G.load_history(path)
        assert [type(m).__name__ for m in restored] == ["HumanMessage", "AIMessage"]
        assert restored[0].content == "bonjour"


def test_load_history_missing_file():
    assert G.load_history(Path("no-such-history-xyz.json")) == []


def test_load_history_tolerates_garbage():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "history.json"
        path.write_text("not json at all", encoding="utf-8")
        assert G.load_history(path) == []


def test_transcript_skips_tool_messages():
    text = G.transcript([
        HumanMessage(content="quelle heure?"),
        AIMessage(content="", tool_calls=[{"name": "t", "args": {}, "id": "1"}]),
        ToolMessage(content="12:00", tool_call_id="1"),
        AIMessage(content="Il est midi."),
    ])
    assert "User: quelle heure?" in text
    assert "Jarvis: Il est midi." in text
    assert "12:00" not in text
