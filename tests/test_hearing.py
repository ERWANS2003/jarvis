"""Tests de l'ecoute intelligente : hypotheses, phrases coupees, intention.

Aucun micro ni reseau : un faux reconnaisseur rejoue des reponses de Google.
"""

from __future__ import annotations

from jarvis_core import hearing as H
from jarvis_core import stt
from jarvis_core.i18n import STRINGS

FR = STRINGS["fr"]


def test_unfinished_sentences_are_spotted():
    for text in ("ouvre le fichier de", "rappelle-moi de", "quelle est la capitale du",
                 "mets la musique de", "est-ce que tu peux", "ouvre", "what is the"):
        assert H.seems_unfinished(text), text
    for text in ("quelle heure est-il", "ouvre YouTube", "merci", "joue Daft Punk", ""):
        assert not H.seems_unfinished(text), text


def test_frequent_mishearings_are_corrected():
    assert H.correct("ouvre  you tube") == "ouvre YouTube"
    assert H.correct("jarvisse quelle heure est-il") == "Jarvis, quelle heure est-il"
    assert H.correct("lance spoti fy") == "lance Spotify"


def test_google_hypotheses_and_confidence_are_kept():
    heard = H.from_google({"alternative": [
        {"transcript": "met la musique", "confidence": 0.62},
        {"transcript": "mets la musique"}, {"transcript": "Met la musique"},
        {"transcript": "mais la musique"}]})
    assert heard.text == "met la musique" and heard.confidence == 0.62
    assert heard.alternatives == ["mets la musique", "mais la musique"]   # sans doublon
    assert H.from_google([]) is None and H.from_google({}) is None


def test_guidance_asks_for_the_intent_not_the_letter():
    assert H.guidance(None, "fr") == ""                 # texte tape : pas de consigne
    heard = H.Heard("ouvre le fichier de", ["ouvre le fichier 2"], 0.5)
    text = H.guidance(heard, "fr")
    assert "intention" in text and "« ouvre le fichier 2 »" in text
    assert "peu sûre" in text and "coupée" in text


class _Recognizer:
    """Rejoue une suite de reponses Google, une par prise de son."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.listens = []

    def listen(self, source, phrase_time_limit=None, timeout=None):
        self.listens.append(timeout)
        if not self.replies:
            import speech_recognition as sr

            raise sr.WaitTimeoutError()
        return self.replies[0]

    def recognize_google(self, audio, language=None, show_all=False):
        reply = self.replies.pop(0)
        return reply if show_all else reply["alternative"][0]["transcript"]


def _listener(replies):
    recognizer = _Recognizer(replies)
    transcriber = stt.Transcriber(recognizer, FR, order=("google",))
    return stt.SpeechToText(recognizer, None, "fr-FR", transcriber=transcriber,
                            strings=FR), recognizer


def _google(*texts, confidence=0.9):
    return {"alternative": [{"transcript": texts[0], "confidence": confidence}]
            + [{"transcript": t} for t in texts[1:]]}


def test_a_cut_sentence_is_completed_by_listening_again():
    listener, recognizer = _listener([_google("ouvre le fichier de", "ouvre le fichier 2"),
                                      _google("mon rapport de stage")])
    text, error = listener.listen()
    assert (text, error) == ("ouvre le fichier de mon rapport de stage", None)
    assert recognizer.listens == [None, H.CONTINUE_WAIT]       # seconde ecoute, courte
    heard = listener.transcriber.last_heard
    assert heard.continued and heard.alternatives == ["ouvre le fichier 2 mon rapport de stage"]


def test_a_complete_sentence_is_answered_at_once():
    listener, recognizer = _listener([_google("quelle heure est-il"), _google("ignoré")])
    assert listener.listen() == ("quelle heure est-il", None)
    assert recognizer.listens == [None]


def test_silence_after_a_cut_sentence_keeps_what_was_heard():
    listener, recognizer = _listener([_google("rappelle-moi de")])
    assert listener.listen() == ("rappelle-moi de", None)
    assert len(recognizer.listens) == 2


def test_a_wrong_transcription_can_still_trigger_a_command():
    """« met pose » est faux, mais l'hypothese « mets pause » est une commande."""
    from jarvis_core import gui, pc

    class Args:
        lang, ability, max_words, retries, history_path = "fr", "x", 40, 1, None
        allow_apps = None

    class Chain:
        tools, tools_enabled = [], False

    pressed = []
    original = pc.press
    pc.press = pressed.append
    try:
        import tempfile
        from pathlib import Path

        Args.history_path = str(Path(tempfile.mkdtemp()) / "h.json")
        turn = gui._make_turn(Args, FR, Chain(), None)
        turn.heard = H.Heard("met pose", ["mets pause"], 0.4)
        said = []
        turn("met pose", [], on_sentence=said.append, on_tool=lambda n: None,
             on_status=lambda s: None)
    finally:
        pc.press = original
    assert said == [FR["pc_done"]] and pressed == [pc.VK_MEDIA_PLAY_PAUSE]
    assert turn.heard is None                              # consomme par le tour


def test_dictated_turn_gets_the_hearing_guidance():
    from langchain_core.messages import AIMessage

    from jarvis_core import gui

    seen = {}

    class Graph:
        def stream(self, inputs, stream_mode=None):
            seen["system"] = inputs["messages"][0].content
            yield (AIMessage(content="D'accord."), {})

    class Args:
        lang, ability, max_words, retries, history_path = "fr", "x", 40, 1, None
        allow_apps = None

    class Chain:
        tools, tools_enabled = [], False
        graph = Graph()

        def advance(self):
            return False

    import tempfile
    from pathlib import Path

    Args.history_path = str(Path(tempfile.mkdtemp()) / "h.json")
    turn = gui._make_turn(Args, FR, Chain(), None)
    turn.heard = H.Heard("parle moi de la tour effel", ["parle-moi de la tour Eiffel"], 0.55)
    turn("parle moi de la tour effel", [], on_sentence=lambda s: None,
         on_tool=lambda n: None, on_status=lambda s: None)
    assert "reconnaissance vocale" in seen["system"]
    assert "« parle-moi de la tour Eiffel »" in seen["system"]


class _Audio:
    def get_wav_data(self, convert_rate=None, convert_width=None):
        return b"RIFF"


class _Session:
    def __init__(self, text, delay=0.0, fail=False):
        self.text, self.delay, self.fail, self.sent = text, delay, fail, []

    def post(self, url, headers=None, files=None, data=None, timeout=None):
        import time

        self.sent.append(data)
        time.sleep(self.delay)
        if self.fail:
            raise ConnectionError("reseau coupe")
        session = self

        class Response:
            def raise_for_status(self):
                pass

            def json(self):
                return {"text": session.text}

        return Response()


class _SlowGoogle:
    def __init__(self, reply, delay):
        self.reply, self.delay = reply, delay

    def recognize_google(self, audio, language=None, show_all=False):
        import time

        time.sleep(self.delay)
        return self.reply if show_all else self.reply["alternative"][0]["transcript"]


def _duo(whisper_text, google_reply, google_delay, fail=False):
    groq = stt.GroqWhisperBackend("gsk_test", "fr", H.vocabulary("fr"),
                                  session=_Session(whisper_text, fail=fail))
    return stt.Transcriber(_SlowGoogle(google_reply, google_delay), FR, order=("google",),
                           groq=groq), groq


def test_whisper_leads_and_google_adds_its_hypothesis():
    transcriber, groq = _duo("Mais la chanson Bohemian Rhapsody.",       # commande courte
                             _google("mets la chanson Bohemian Rhapsody"), 0.1)
    transcriber.context = "Que puis-je faire pour vous ?"
    assert transcriber.transcribe(_Audio()) == ("Mais la chanson Bohemian Rhapsody.", None)
    heard = transcriber.last_heard
    assert heard.alternatives[0] == "mets la chanson Bohemian Rhapsody"
    assert "Spotify" in groq._session.sent[0]["prompt"]                 # vocabulaire envoye
    assert "Que puis-je faire" in groq._session.sent[0]["prompt"]       # et le contexte


def test_a_slow_google_never_delays_the_answer():
    import time

    transcriber, _ = _duo("Quelle heure est-il ?", _google("quelle heure est-il"), 3.0)
    started = time.monotonic()
    assert transcriber.transcribe(_Audio())[0] == "Quelle heure est-il ?"
    assert time.monotonic() - started < stt.GOOGLE_GRACE + 0.5


def test_google_takes_over_when_whisper_fails_or_hallucinates():
    transcriber, _ = _duo("", _google("ouvre YouTube"), 0.05, fail=True)
    assert transcriber.transcribe(_Audio()) == ("ouvre YouTube", None)
    transcriber, _ = _duo("Sous-titres réalisés par la communauté d'Amara.org",
                          _google("bonjour"), 0.05)
    assert transcriber.transcribe(_Audio()) == ("bonjour", None)



def test_long_questions_do_not_wait_for_google():
    import time

    transcriber, _ = _duo("Explique-moi pourquoi la mer est salée et pas les rivières.",
                          _google("explique-moi pourquoi la mère est salée"), 0.4)
    started = time.monotonic()
    assert transcriber.transcribe(_Audio())[0].startswith("Explique-moi")
    assert time.monotonic() - started < 0.2                 # le modele corrigera seul


def test_whisper_learns_the_names_jarvis_remembers():
    from jarvis_core.memory import MemoryStore

    store = MemoryStore()
    store.remember("Il fait du vélo le dimanche avec sa sœur Aïcha")
    store.remember("Il étudie à l'Université Joseph Ki-Zerbo de Ouagadougou")
    store.remember("Il déteste le café")
    names = H.personal_vocabulary(store)
    assert "Aïcha" in names and "Ouagadougou" in names and "Ki-Zerbo" in names
    assert "Il" not in names.split(", ")
    assert H.personal_vocabulary(None) == ""
    transcriber, groq = _duo("Appelle Aïcha.", _google("appelle aïcha"), 0.05)
    transcriber.personal = names
    transcriber.transcribe(_Audio())
    assert "Aïcha" in groq._session.sent[0]["prompt"]
