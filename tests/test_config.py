"""Tests de la configuration par fichier (Horizon 6)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from jarvis_core import config as C


def test_defaults_shape():
    for key in ("lang", "wake", "bargein", "max_words", "retries", "memory",
                "tools", "vad", "plugins", "gui"):
        assert key in C.DEFAULTS
    assert C.DEFAULTS["lang"] == "en"


def test_defaults_cover_horizons_4_to_6():
    # Ces cles doivent pouvoir etre reglees par fichier ou JARVIS_* (et non
    # seulement par la ligne de commande).
    for key in ("volume", "stt", "whisper_model", "plugins_dir",
                "history_path", "local_model"):
        assert key in C.DEFAULTS


def test_gui_is_the_default_entry_point():
    # Horizon 6 : la fenetre graphique est le mode par defaut ; `--no-gui` ou
    # `text: true` ramenent a la console.
    assert C.DEFAULTS["gui"] is True
    merged, _ = C.normalise({"gui": False})
    assert merged["gui"] is False
    merged, _ = C.normalise({"text": True})
    assert merged["text"] is True


def test_interface_section_is_flattened():
    assert C._flatten(
        {"interface": {"gui": True, "plugins_dir": "plugins"}}
    ) == {"gui": True, "plugins_dir": "plugins"}


def test_interface_section_can_disable_gui():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "jarvis.yaml"
        path.write_text("interface:\n  gui: false\n", encoding="utf-8")
        assert C.load_config_file(path) == {"gui": False}


def test_shipped_example_config_is_valid():
    """Le fichier d'exemple doit se charger et etre entierement aplati."""
    path = Path(__file__).resolve().parent.parent / "jarvis.example.yaml"
    flat = C.load_config_file(path)
    assert not any(isinstance(value, dict) for value in flat.values())
    assert flat["lang"] == "fr"
    assert flat["gui"] is True


def test_flatten_sections():
    flat = C._flatten({"voice": {"lang": "fr", "max_words": 12},
                       "tools": {"tools": False}, "history_path": "h.json"})
    assert flat == {"lang": "fr", "max_words": 12, "tools": False,
                    "history_path": "h.json"}


def test_load_yaml_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "jarvis.yaml"
        path.write_text("voice:\n  lang: fr\n  max_words: 22\n", encoding="utf-8")
        assert C.load_config_file(path) == {"lang": "fr", "max_words": 22}


def test_load_json_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "jarvis.json"
        path.write_text(json.dumps({"lang": "fr", "retries": 5}), encoding="utf-8")
        assert C.load_config_file(path) == {"lang": "fr", "retries": 5}


def test_load_toml_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "jarvis.toml"
        path.write_text("[voice]\nlang = \"fr\"\nmax_words = 9\n", encoding="utf-8")
        assert C.load_config_file(path) == {"lang": "fr", "max_words": 9}


def test_find_config_prefers_start_dir():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "jarvis.yaml"
        path.write_text("lang: fr\n", encoding="utf-8")
        assert C.find_config(tmp) == path
        config, found = C.load_config(tmp)
        assert found == path and config["lang"] == "fr"


def test_find_config_none_when_empty():
    with tempfile.TemporaryDirectory() as tmp:
        assert C.find_config(tmp) is None


def test_normalise_coerces_language():
    clean, warnings = C.normalise({"lang": "FR"})
    assert clean["lang"] == "fr"
    clean, warnings = C.normalise({"lang": "de"})
    assert clean["lang"] == "en"
    assert warnings and "langue inconnue" in warnings[0]


def test_normalise_clamps_numbers():
    clean, warnings = C.normalise({"max_words": 9999, "retries": -3})
    assert clean["max_words"] == 400
    assert clean["retries"] == 0
    assert len(warnings) == 2


def test_normalise_drops_unknown_keys():
    clean, warnings = C.normalise({"nage": 3, "lang": "fr"})
    assert "nage" not in clean
    assert any("inconnue" in warning for warning in warnings)


def test_normalise_coerces_booleans():
    clean, _ = C.normalise({"wake": "non", "bargein": "true", "vad": 1})
    assert clean["wake"] is False
    assert clean["bargein"] is True
    assert clean["vad"] is True


def test_normalise_negative_form():
    clean, _ = C.normalise({"no_wake": True, "no_bargein": True})
    assert clean["wake"] is False
    assert clean["bargein"] is False


def test_merged_defaults_precedence():
    merged = C.merged_defaults({"lang": "fr", "max_words": 15})
    assert merged["lang"] == "fr"
    assert merged["max_words"] == 15
    assert merged["retries"] == C.DEFAULTS["retries"]
    assert merged["tools"] is True


def test_env_overrides():
    overrides = C.env_overrides({"JARVIS_LANG": "fr", "JARVIS_MODEL": "m",
                                 "IGNORED": "x"})
    assert overrides == {"lang": "fr", "model": "m"}


def test_env_overrides_empty_values_ignored():
    assert C.env_overrides({"JARVIS_LANG": ""}) == {}


def test_env_overrides_horizons_4_to_6():
    overrides = C.env_overrides({"JARVIS_VOLUME": "0.4", "JARVIS_STT": "local",
                                 "JARVIS_WHISPER_MODEL": "small",
                                 "JARVIS_HISTORY_PATH": "h.json"})
    assert overrides == {"volume": "0.4", "stt": "local",
                         "whisper_model": "small", "history_path": "h.json"}
    # ... et elles passent bien le nettoyage.
    clean, _ = C.normalise(overrides)
    assert clean["volume"] == 0.4
    assert clean["stt"] == "local"


def test_normalise_clamps_volume():
    clean, warnings = C.normalise({"volume": 5})
    assert clean["volume"] == 1.0
    assert any("volume" in warning for warning in warnings)
    clean, _ = C.normalise({"volume": 0})
    assert clean["volume"] == 0.0    # 0 reste possible (muet)


def test_normalise_rejects_unknown_stt_engine():
    clean, warnings = C.normalise({"stt": "telepathy"})
    assert clean["stt"] == "auto"
    assert any("reconnaissance" in warning for warning in warnings)
    clean, _ = C.normalise({"stt": "WHISPER"})
    assert clean["stt"] == "whisper"


def test_write_example_config():
    with tempfile.TemporaryDirectory() as tmp:
        path = C.write_example_config(Path(tmp) / "jarvis.example.yaml")
        assert path.is_file()
        loaded = C.load_config_file(path)
        assert loaded["lang"] == "fr"
        assert loaded["wake"] is True


def test_allow_apps_is_read_from_the_config_file():
    clean, warnings = C.normalise({"allow_apps": {"Spotify": "start spotify:"}})
    assert clean["allow_apps"] == {"spotify": "start spotify:"}
    assert not any("allow_apps" in warning for warning in warnings)

    clean, warnings = C.normalise({"allow_apps": ["spotify"]})
    assert "allow_apps" not in clean
    assert warnings


def test_allow_apps_section_is_flattened_from_yaml():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "jarvis.json"
        path.write_text(json.dumps({"tools": {"allow_apps": {"vlc": "start vlc"}}}),
                        encoding="utf-8")
        merged = C.merged_defaults(C.load_config_file(path))
        assert merged["allow_apps"] == {"vlc": "start vlc"}


def test_orb_theme_is_validated():
    assert C.DEFAULTS["orb_theme"] == "opale"
    assert C.normalise({"orb_theme": "SIRI"})[0]["orb_theme"] == "siri"
    assert C.normalise({"orb_theme": "Aurore"})[0]["orb_theme"] == "aurore"
    clean, warnings = C.normalise({"orb_theme": "rose"})
    assert clean["orb_theme"] == "opale" and warnings


def test_auto_hide_is_bounded():
    assert C.DEFAULTS["auto_hide"] == 60
    clean, warnings = C.normalise({"auto_hide": 99999})
    assert clean["auto_hide"] == 3600 and warnings


def test_orb_quality_defaults_to_ultra():
    assert C.DEFAULTS["orb_quality"] == "ultra"
    assert C.normalise({"orb_quality": "Standard"})[0]["orb_quality"] == "standard"
    assert C.normalise({"orb_quality": "max"})[0]["orb_quality"] == "ultra"

