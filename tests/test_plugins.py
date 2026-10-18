"""Tests du systeme de plugins (Horizon 6)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from langchain_core.tools import tool

from jarvis_core import plugins as P
from jarvis_core.tools import ToolContext

REPO_PLUGINS = Path(__file__).resolve().parent.parent / "plugins"


def test_discover_skips_private_files():
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "good.py").write_text("TOOLS = []\n", encoding="utf-8")
        Path(tmp, "_private.py").write_text("TOOLS = []\n", encoding="utf-8")
        Path(tmp, "notes.txt").write_text("hi", encoding="utf-8")
        names = [path.name for path in P.discover(tmp)]
        assert names == ["good.py"]


def test_discover_missing_directory():
    assert P.discover(Path("no-such-dir-xyz")) == []


def test_load_bundled_plugin():
    tools, infos = P.load_plugins(REPO_PLUGINS, ToolContext(lang="en"))
    names = sorted(t.name for t in tools)
    assert names == ["get_disk_usage", "get_system_info"]
    assert infos and all(info.ok for info in infos)
    assert infos[0].name == "system_info"


def test_bundled_plugin_callable():
    tools, _ = P.load_plugins(REPO_PLUGINS, ToolContext(lang="fr"))
    by_name = {t.name: t for t in tools}
    assert "coeurs" in by_name["get_system_info"].invoke({})
    assert "Go" in by_name["get_disk_usage"].invoke({"path": "."})


def test_plugin_with_build_tools():
    source = (
        "from langchain_core.tools import tool\n"
        "def build_tools(ctx):\n"
        "    @tool\n"
        "    def hello() -> str:\n"
        "        '''Say hello.'''\n"
        "        return 'hi'\n"
        "    return [hello]\n"
    )
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "greeter.py").write_text(source, encoding="utf-8")
        tools, infos = P.load_plugins(tmp, ToolContext())
    assert [t.name for t in tools] == ["hello"]
    assert infos[0].ok is True


def test_plugin_with_tools_list():
    source = (
        "from langchain_core.tools import tool\n"
        "@tool\n"
        "def ping() -> str:\n"
        "    '''Ping.'''\n"
        "    return 'pong'\n"
        "TOOLS = [ping]\n"
    )
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "pinger.py").write_text(source, encoding="utf-8")
        tools, infos = P.load_plugins(tmp, ToolContext())
    assert [t.name for t in tools] == ["ping"]


def test_broken_plugin_is_reported_not_raised():
    source = "this is not python at all(((\n"
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "broken.py").write_text(source, encoding="utf-8")
        Path(tmp, "fine.py").write_text("TOOLS = []\n", encoding="utf-8")
        tools, infos = P.load_plugins(tmp, ToolContext())
    by_name = {info.name: info for info in infos}
    assert by_name["broken"].ok is False
    assert "SyntaxError" in by_name["broken"].error
    assert by_name["fine"].ok is True


def test_plugin_without_interface_errors():
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "empty.py").write_text("x = 1\n", encoding="utf-8")
        tools, infos = P.load_plugins(tmp, ToolContext())
    assert tools == []
    assert infos[0].ok is False
    assert "build_tools" in infos[0].error


def test_collect_rejects_non_tools():
    class Module:
        TOOLS = ["not a tool", 42]

    assert P.collect(Module(), ToolContext()) == []


def test_exclude_plugins():
    tools, infos = P.load_plugins(REPO_PLUGINS, ToolContext(),
                                  exclude={"system_info"})
    assert tools == []
    assert infos == []
