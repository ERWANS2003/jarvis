"""Tests de l'interface graphique (Horizon 6).

On ne cree jamais de vraie fenetre ici : les tests doivent tourner en console,
sans affichage. On verifie seulement le contrat du module (API publique et
detection defensive de Tkinter).
"""

from __future__ import annotations

from jarvis_core import gui as G


def test_gui_exports_run_and_available():
    assert callable(G.run)
    assert callable(G.available)


def test_gui_available_returns_bool():
    assert isinstance(G.available(), bool)


def test_gui_marks_memory_tools_as_silent():
    # Les outils de memoire ne doivent pas declencher le message « un instant ».
    assert "remember_fact" in G.MEMORY_TOOLS
    assert "recall_memory" in G.MEMORY_TOOLS
    assert "get_weather" not in G.MEMORY_TOOLS
