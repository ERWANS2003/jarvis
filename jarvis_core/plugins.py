"""Horizon 6 - systeme de plugins.

Un plugin est un simple fichier ``.py`` depose dans le dossier ``plugins/``.
Il peut exposer l'une de ces interfaces :

  * ``build_tools(ctx) -> list[BaseTool]``  (recommande)
  * ``register(ctx) -> list[BaseTool]``
  * ``TOOLS = [...]``  (liste de tools deja construite)

Un plugin fautif est signale mais ne fait jamais planter Jarvis.
"""

from __future__ import annotations

import importlib.util
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path

from langchain_core.tools import BaseTool

DEFAULT_PLUGIN_DIR = "plugins"


@dataclass
class PluginInfo:
    name: str
    path: str
    tools: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def discover(directory: Path | str) -> list[Path]:
    """Liste les fichiers de plugin (.py, hors __init__ et _prives)."""
    path = Path(directory)
    if not path.is_dir():
        return []
    return sorted(
        child for child in path.glob("*.py")
        if not child.name.startswith("_")
    )


def _load_module(path: Path):
    module_name = f"jarvis_plugin_{path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"impossible de charger {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def collect(module, ctx) -> list[BaseTool]:
    """Extrait les outils d'un module de plugin selon son interface."""
    for attr in ("build_tools", "register"):
        builder = getattr(module, attr, None)
        if callable(builder):
            tools = builder(ctx) or []
            return [tool for tool in tools if isinstance(tool, BaseTool)]
    tools = getattr(module, "TOOLS", None)
    if isinstance(tools, (list, tuple)):
        return [tool for tool in tools if isinstance(tool, BaseTool)]
    raise AttributeError(
        "le plugin doit definir build_tools(ctx), register(ctx) ou TOOLS"
    )


def load_plugins(directory: Path | str | None, ctx,
                 exclude: set[str] | None = None) -> tuple[list[BaseTool], list[PluginInfo]]:
    """Charge tous les plugins du dossier. Retourne (outils, infos)."""
    directory = directory or DEFAULT_PLUGIN_DIR
    exclude = exclude or set()
    tools: list[BaseTool] = []
    infos: list[PluginInfo] = []
    for path in discover(directory):
        if path.stem in exclude:
            continue
        info = PluginInfo(name=path.stem, path=str(path))
        try:
            module = _load_module(path)
            loaded = collect(module, ctx)
            info.tools = [tool.name for tool in loaded]
            tools.extend(loaded)
        except Exception as exc:
            info.error = f"{type(exc).__name__}: {exc}"
            if "--debug-plugins" in sys.argv:
                traceback.print_exc()
        infos.append(info)
    return tools, infos


__all__ = [
    "DEFAULT_PLUGIN_DIR",
    "PluginInfo",
    "discover",
    "collect",
    "load_plugins",
]
