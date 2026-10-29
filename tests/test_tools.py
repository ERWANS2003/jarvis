"""Tests des outils (Horizon 3)."""

from __future__ import annotations

import time

from jarvis_core import tools as T
from jarvis_core.memory import MemoryStore


def test_safe_eval_basic():
    assert T.safe_eval("12 * (3 + 4)") == 84
    assert T.safe_eval("2 ** 10") == 1024
    assert T.safe_eval("10 / 4") == 2.5
    assert T.safe_eval("-5 + 2") == -3
    assert T.safe_eval("7 % 3") == 1
    assert T.safe_eval("1,5 + 1") == 2.5  # virgule decimale


def test_safe_eval_rejects_code():
    for payload in (
        '__import__("os").system("echo pwn")',
        "open('/etc/passwd')",
        "1 if 1 else 0",
        "[x for x in range(3)]",
        "lambda: 1",
        "globals()",
        "",
        "9" * 300,
    ):
        try:
            T.safe_eval(payload)
        except Exception:
            continue
        raise AssertionError(f"payload accepte a tort: {payload!r}")


def test_describe_weather():
    assert T.describe_weather(0, "en") == "clear sky"
    assert T.describe_weather(61, "fr") == "pluie faible"
    assert T.describe_weather(9999, "en") == "unknown"
    assert T.describe_weather(9999, "fr") == "inconnu"


def test_open_application_denies_unknown():
    assert T.open_application("definitely-not-an-app") == ""
    assert T.open_application("") == ""
    assert T.open_application("rm -rf /") == ""


def test_timer_registry_fires():
    fired: list[str] = []
    registry = T.TimerRegistry(speak=fired.append)
    timer_id = registry.set_timer(0.2, "tea")
    assert timer_id == 1
    assert len(registry.list_timers()) == 1
    deadline = time.time() + 4
    while not fired and time.time() < deadline:
        time.sleep(0.05)
    assert fired == ["tea"], "le minuteur n'a pas sonne"


def test_timer_registry_cancel():
    registry = T.TimerRegistry()
    registry.set_timer(30, "a")
    registry.set_timer(30, "b")
    assert registry.cancel() == 2
    assert registry.list_timers() == []
    assert registry.cancel() == 0


def test_build_tools_without_memory():
    names = [t.name for t in T.build_tools(T.ToolContext())]
    assert "get_weather" in names
    assert "remember_fact" not in names
    assert len(names) == 19  # 9 de base + 4 PC + 4 fichiers + 2 sites


def test_build_tools_with_memory():
    store = MemoryStore()
    names = [t.name for t in T.build_tools(T.ToolContext(memory=store))]
    assert names[-3:] == ["remember_fact", "recall_memory", "forget_memory"]


def test_calculate_tool():
    ctx = T.ToolContext()
    calculate = {t.name: t for t in T.build_tools(ctx)}["calculate"]
    assert calculate.invoke({"expression": "6 * 7"}) == "42"
    assert calculate.invoke({"expression": "nonsense("}).startswith("Cannot")


def test_calculate_tool_french():
    ctx = T.ToolContext(lang="fr")
    calculate = {t.name: t for t in T.build_tools(ctx)}["calculate"]
    assert "impossible" in calculate.invoke({"expression": "??"})


def test_datetime_tool():
    ctx = T.ToolContext()
    tool = {t.name: t for t in T.build_tools(ctx)}["get_current_datetime"]
    out = tool.invoke({})
    assert any(ch.isdigit() for ch in out)


def test_memory_tools_roundtrip():
    store = MemoryStore()
    ctx = T.ToolContext(memory=store, strings={"remembered": "ok"})
    by_name = {t.name: t for t in T.build_tools(ctx)}
    by_name["remember_fact"].invoke({"text": "the user prefers tea over coffee"})
    result = by_name["recall_memory"].invoke({"query": "does the user prefer tea"})
    assert "tea" in result
    by_name["forget_memory"].invoke({"query": "the user prefers tea over coffee"})
    assert store.count() == 0


def test_cancel_timer_tool():
    ctx = T.ToolContext(strings={"cancelled_timers": "{count} timer(s) cancelled."})
    by_name = {t.name: t for t in T.build_tools(ctx)}
    by_name["set_timer"].invoke({"seconds": 30, "label": "pasta"})
    assert by_name["list_timers"].invoke({}).count("pasta") == 1
    assert by_name["cancel_timer"].invoke({"timer_id": 0}) == "1 timer(s) cancelled."
    assert by_name["list_timers"].invoke({}) == "No timer is running."


def test_web_search_parsing_helper():
    assert T._is_french("il fait très beau") is True
    assert T._is_french("it is sunny") is False


def test_timer_registry_cancel_unknown_id_keeps_others():
    registry = T.TimerRegistry()
    first = registry.set_timer(30, "a")
    registry.set_timer(30, "b")
    assert registry.cancel(999) == 0
    assert len(registry.list_timers()) == 2
    assert registry.cancel(first) == 1
    assert [t["label"] for t in registry.list_timers()] == ["b"]
    registry.cancel()


def test_safe_eval_refuses_gigantic_results_quickly():
    import time as _time

    started = _time.monotonic()
    for expression in ("((99**99)**99)**99", "9**99**99", "(10**100)**100"):
        try:
            T.safe_eval(expression)
        except ValueError:
            continue
        raise AssertionError(f"{expression} aurait du etre refuse")
    assert _time.monotonic() - started < 0.5
    assert T.safe_eval("2**100") == 2 ** 100

