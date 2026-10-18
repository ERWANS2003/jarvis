"""Tests des chaines traduites (Horizon 6 : parite en/fr).

Le mode bilingue impose que chaque langue expose exactement les memes cles.
On verifie aussi que toutes les cles lues par l'interface graphique existent
dans les deux langues : c'est exactement le type d'oubli qui casse l'UI en
anglais alors qu'elle marche en francais.
"""

from __future__ import annotations

import re
from pathlib import Path

from jarvis_core.i18n import STRINGS

GUI = Path(__file__).resolve().parent.parent / "jarvis_core" / "gui.py"

# self.s["cle"], self.s.get("cle", ...), strings["cle"], strings.get("cle")
_KEY_USE = re.compile(r'(?:self\.s|strings)(?:\.get)?[\(\[]\s*"([A-Za-z0-9_]+)"')


def test_en_and_fr_expose_the_same_keys():
    assert set(STRINGS["en"]) == set(STRINGS["fr"])


def test_gui_keys_exist_in_both_languages():
    source = GUI.read_text(encoding="utf-8")
    keys = set(_KEY_USE.findall(source))
    assert keys, "aucune cle detectee : le motif de recherche a peut-etre derive"
    for lang in ("en", "fr"):
        missing = sorted(k for k in keys if k not in STRINGS[lang])
        assert not missing, f"cles absentes en {lang} : {missing}"
