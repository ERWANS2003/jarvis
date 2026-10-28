"""Tests de la recherche et de l'ouverture de fichiers (Horizon 3).

Tout se passe dans un dossier temporaire : rien n'est ouvert pour de vrai.
"""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

from jarvis_core import files as F


def _tree(root: Path) -> None:
    (root / "Cours").mkdir()
    (root / "node_modules").mkdir()
    for name, age in (("Rapport_final.pdf", 30), ("rapport-brouillon.docx", 20),
                      ("Cours/Réseaux chapitre 2.pdf", 10), ("photo.jpg", 5),
                      ("installer.exe", 1), ("node_modules/rapport.pdf", 0)):
        path = root / name
        path.write_bytes(b"x")
        stamp = time.time() - age * 3600
        os.utime(path, (stamp, stamp))


def test_find_files_by_name_and_kind_newest_first():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _tree(root)
        names = [f.path.name for f in F.find_files("rapport", folders=[root])]
        assert names == ["rapport-brouillon.docx", "Rapport_final.pdf"]  # pas node_modules
        pdfs = [f.path.name for f in F.find_files("", "pdf", folders=[root])]
        assert pdfs == ["Réseaux chapitre 2.pdf", "Rapport_final.pdf"]
        # accents et majuscules ignores
        assert F.find_files("reseaux", folders=[root])[0].path.name == "Réseaux chapitre 2.pdf"
        assert F.find_files("introuvable", folders=[root]) == []


def test_kind_aliases():
    assert F.kind_suffixes("PDF") == {".pdf"}
    assert ".xlsx" in F.kind_suffixes("tableur")
    assert ".jpg" in F.kind_suffixes("photos")
    assert F.kind_suffixes("mp3") == {".mp3"}
    assert F.kind_suffixes(None) is None


def test_only_harmless_files_inside_personal_folders_can_be_opened():
    with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as other:
        root = Path(tmp)
        _tree(root)
        outside = Path(other) / "secret.pdf"
        outside.write_bytes(b"x")
        opened = []
        assert F.open_file(root / "Rapport_final.pdf", [root], opened.append)
        assert not F.open_file(root / "installer.exe", [root], opened.append)
        assert not F.open_file(outside, [root], opened.append)
        assert not F.open_file(root / "absent.pdf", [root], opened.append)
        assert len(opened) == 1 and opened[0].endswith("Rapport_final.pdf")
