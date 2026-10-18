"""Tests du module texte (Horizon 1, deplace dans jarvis_core)."""

from __future__ import annotations

from jarvis_core import text as T


def test_take_sentences():
    assert T.take_sentences("Hello there. How are") == (["Hello there."], "How are")
    assert T.take_sentences("Hello") == ([], "Hello")
    assert T.take_sentences("One! Two? Three. Four") == (["One!", "Two?", "Three."], "Four")
    assert T.take_sentences("Done. ") == (["Done."], "")


def test_clean_text():
    assert T.clean_text(" **Bold** and\n\nnew line ") == "Bold and new line"
    assert "🌍" not in T.clean_text("Hello 🌍 world")
    assert T.clean_text("emoji 😊 ok") == "emoji ok"


def test_strip_wake():
    wake = ["jarvis"]
    assert T.strip_wake("Jarvis, what time is it", wake) == (True, "what time is it")
    assert T.strip_wake("jarvis", wake) == (True, "")
    assert T.strip_wake("what time is it", wake) == (False, "")
    assert T.strip_wake("hey jarvis tell me a joke", wake) == (True, "tell me a joke")
    assert T.strip_wake("I saw jarvis yesterday", wake) == (False, "")
    assert T.strip_wake("Jarves, open the door", wake) == (True, "open the door")
    assert T.strip_wake("anything", []) == (True, "anything")
    assert T.strip_wake("jarvis.", wake) == (True, "")
    assert T.strip_wake("the jarvis file", wake) == (False, "")


def test_is_exit_phrase():
    phrases = T.STRINGS["en"]["exit_phrases"]
    assert T.is_exit_phrase("Thank you for your help", phrases) is True
    assert T.is_exit_phrase("thank you for your halp", phrases) is True
    assert T.is_exit_phrase("tell me about python", phrases) is False


def test_status_code_and_fatal():
    class Fake(Exception):
        status_code = 429

    assert T.status_code(Fake()) == 429
    assert T.status_code(ValueError("x")) is None
    assert T.is_fatal(Fake()) is False
    assert T.is_fatal(Exception("insufficient_quota")) is True


def test_make_messages():
    messages = T.make_messages("SYS", True, "hello")
    assert [type(m).__name__ for m in messages] == ["SystemMessage", "HumanMessage"]
    assert (messages[0].id, messages[1].id is not None) == ("system-prompt", True)
    assert [type(m).__name__ for m in T.make_messages("SYS", False, "hello")] == [
        "HumanMessage"
    ]
    refreshed = T.make_messages("SYS2", False, "hello", refresh_system=True)
    assert [type(m).__name__ for m in refreshed] == ["SystemMessage", "HumanMessage"]
    assert refreshed[0].content == "SYS2"


def test_rms():
    import array

    assert T.rms(bytes(2048)) == 0.0
    loud = array.array("h", [30000, -30000] * 512)
    assert round(T.rms(loud.tobytes()), 1) == 30000.0


def test_normalize_and_tokenize():
    assert T.normalize("Éléphant") == "elephant"
    tokens = T.tokenize("Je préfère le café noir")
    assert "prefere" in tokens and "cafe" in tokens
    assert "le" not in tokens


def test_jaccard():
    assert T.jaccard(["a", "b"], ["a", "b"]) == 1.0
    assert T.jaccard(["a"], ["b"]) == 0.0
    assert T.jaccard([], ["b"]) == 0.0
