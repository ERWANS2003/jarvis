"""Tests de la memoire longue duree (Horizon 2)."""

from __future__ import annotations

from jarvis_core import memory as M


def test_extract_explicit_remember():
    assert M.extract_explicit("remember that I like tea") == ("remember", "I like tea")
    assert M.extract_explicit("souviens-toi que j'aime le thé") == (
        "remember", "j'aime le thé"
    )
    assert M.extract_explicit("retiens que mon code est 1234") == (
        "remember", "mon code est 1234"
    )
    assert M.extract_explicit("note: la réunion est à 14h") == (
        "remember", "la réunion est à 14h"
    )


def test_extract_explicit_forget():
    assert M.extract_explicit("forget about the tea") == ("forget", "the tea")
    assert M.extract_explicit("oublie que j'aime le thé") == ("forget", "j'aime le thé")


def test_extract_explicit_none():
    assert M.extract_explicit("what is the weather") == (None, "")
    assert M.extract_explicit("") == (None, "")


def test_extract_profile():
    facts = dict(M.extract_profile("My name is Erwan and I live in Lyon"))
    assert facts.get("name") == "Erwan"
    assert facts.get("location") == "Lyon"

    fr = dict(M.extract_profile("Je m'appelle Erwan et j'habite à Lyon"))
    assert fr.get("name") == "Erwan"
    assert "Lyon" in fr.get("location", "")

    prefs = dict(M.extract_profile("I really love pizza"))
    assert prefs.get("preference") == "pizza"


def test_remember_and_search():
    with M.MemoryStore() as store:
        store.remember("The user loves hiking in the Alps", kind=M.FACT)
        store.remember("The user has a cat named Milou", kind=M.FACT)
        hits = store.search("does the user like hiking")
        assert hits, "aucun souvenir trouve"
        assert "hiking" in hits[0].text
        assert store.search("zzqqxx") == []


def test_remember_dedupes():
    with M.MemoryStore() as store:
        first = store.remember("the user likes tea")
        second = store.remember("the user likes tea")
        assert first == second
        assert store.count() == 1


def test_forget_matching():
    with M.MemoryStore() as store:
        store.remember("the wifi password is hunter2")
        store.remember("the user likes tea")
        removed = store.forget_matching("the wifi password is hunter2")
        assert removed == 1
        assert store.count() == 1


def test_profile_and_recall_blocks():
    from jarvis_core.i18n import STRINGS

    en = STRINGS["en"]
    with M.MemoryStore() as store:
        store.remember("The user's name is Erwan", kind=M.PROFILE)
        store.remember("The user lives in Lyon", kind=M.PROFILE)
        store.remember("The user prefers short answers", kind=M.FACT)
        profile = store.profile_block(en)
        assert en["profile_header"] in profile
        assert "Erwan" in profile

        recall = store.recall_block("what does the user prefer",
                                    en, k=3)
        assert en["memory_header"] in recall


def test_summarize_stores_episode():
    with M.MemoryStore() as store:
        from jarvis_core.i18n import STRINGS

        transcript = "User: hello there my friend\nJarvis: hi!\n" * 5
        summary = store.summarize(lambda prompt: "The user greeted Jarvis.",
                                  transcript, STRINGS["en"])
        assert summary == "The user greeted Jarvis."
        assert store.count(M.EPISODE) == 1


def test_persistence_roundtrip():
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "mem.db"
        with M.MemoryStore(path) as store:
            store.remember("persistent fact about kayaking", kind=M.FACT)
        with M.MemoryStore(path) as store:
            assert store.count() == 1
            assert "kayaking" in store.all()[0].text
