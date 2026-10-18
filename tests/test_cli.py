"""Tests de la ligne de commande (Horizon 6).

On verifie surtout le choix du mode d'entree : la fenetre graphique est le
defaut, `--no-gui` et `--text` ramenent a la console.
"""

from __future__ import annotations

import jarvis


def test_gui_is_the_default_mode():
    assert jarvis.parse_args([]).gui is True


def test_no_gui_switches_to_console():
    assert jarvis.parse_args(["--no-gui"]).gui is False


def test_gui_flag_stays_accepted():
    assert jarvis.parse_args(["--gui"]).gui is True


def test_text_mode_forces_console_at_runtime():
    args = jarvis.parse_args(["--text"])
    assert args.text is True
    # C'est la condition utilisee par `main()` pour ouvrir la fenetre.
    assert not (args.gui and not args.text)
    assert jarvis.parse_args([]).text is False


def test_legacy_voice_defaults_unchanged():
    args = jarvis.parse_args([])
    assert args.lang == "en"
    assert args.wake == "jarvis"
    assert args.bargein is True
    assert args.max_words == 40
    assert jarvis.parse_args(["--no-wake"]).wake == ""
