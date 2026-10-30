"""Tests du briefing, de la conversation continue et de l'orbe synchronisee.

Aucun micro, aucune voix, aucun reseau : tout passe par des doublures.
"""

from __future__ import annotations

import datetime as dt
import struct

from jarvis_core import briefing as B
from jarvis_core import orb_render, tts
from jarvis_core.i18n import STRINGS
from jarvis_core.memory import PROFILE, MemoryStore
from jarvis_core.reminders import ReminderStore
from jarvis_core import web as W
from jarvis_core.web import JarvisWeb

MORNING = dt.datetime(2026, 10, 28, 9, 5)


# --------------------------------------------------------------------------- #
# Briefing
# --------------------------------------------------------------------------- #
def test_compose_french_briefing_with_everything():
    text = B.compose("fr", MORNING, "Erwan", "À Lyon, il fait 12 °C, ciel dégagé.",
                     [{"when": "2026-10-28T14:00", "text": "appeler Paul"},
                      {"when": "2026-10-28T08:00", "text": "deja passe"},
                      {"when": "2026-10-29T09:00", "text": "demain"}])
    assert text.startswith("Bonjour, Erwan. Il est 9 h 05, nous sommes mercredi 28 octobre.")
    assert "il fait 12 °C" in text
    assert "Un rappel aujourd'hui, à 14 h : appeler Paul." in text
    assert text.endswith("Que puis-je faire pour vous ?")


def test_compose_adapts_to_time_language_and_missing_facts():
    evening = B.compose("fr", dt.datetime(2026, 10, 28, 20, 0))
    assert evening.startswith("Bonsoir. Il est 20 h,")
    english = B.compose("en", dt.datetime(2026, 10, 28, 15, 30), "Ada", None,
                        [{"when": "2026-10-28T16:00", "text": "a"},
                         {"when": "2026-10-28T17:00", "text": "b"}])
    assert english.startswith("Good afternoon, Ada. It is 3:30 PM, Wednesday, October 28.")
    assert "You have 2 reminders today, the next one at 4:00 PM: a." in english


def test_gather_reads_profile_weather_and_reminders():
    memory = MemoryStore()
    memory.remember("name: Erwan", kind=PROFILE, source="auto")
    memory.remember("location: Lyon", kind=PROFILE, source="auto")
    reminders = ReminderStore()
    reminders.add(dt.datetime(2026, 10, 28, 18, 0), "sport")
    asked = []

    def weather(city, lang, timeout):
        asked.append((city, lang))
        return "À Lyon, il fait 12 °C."

    text = B.gather("fr", memory, reminders, now=MORNING, weather_fn=weather)
    assert asked == [("Lyon", "fr")]
    assert "Erwan" in text and "12 °C" in text and "sport" in text


def test_gather_survives_a_weather_failure():
    memory = MemoryStore()
    memory.remember("location: Atlantide", kind=PROFILE, source="auto")

    def broken(*_args):
        raise ConnectionError("pas de reseau")

    text = B.gather("fr", memory, None, now=MORNING, weather_fn=broken)
    assert text.startswith("Bonjour.") and "°C" not in text


# --------------------------------------------------------------------------- #
# Conversation continue
# --------------------------------------------------------------------------- #
class _Args:
    ability, max_words, retries, history_path, lang = "x", 40, 1, None, "fr"


class _Chain:
    tools, tools_enabled = [], False

    def label(self):
        return "test"


class _Speech:
    def __init__(self):
        self.said = []

    def begin(self):
        pass

    def say(self, text):
        self.said.append(text)

    def cancel(self):
        pass

    def close(self):
        pass


class _Listener:
    def __init__(self, answers):
        self.answers = list(answers)
        self.timeouts = []

    def listen(self, timeout=None):
        self.timeouts.append(timeout)
        return self.answers.pop(0) if self.answers else (None, None)


def _events_until(inbox, kind):
    while True:
        event = inbox.get(timeout=5)
        if event["type"] == kind:
            return event


def test_follow_up_listens_briefly_and_ends_silently():
    listener = _Listener([(None, None)])
    app = JarvisWeb(_Args(), STRINGS["fr"], listener, _Speech(), _Chain(), [], greet=False)
    inbox = app.bus.subscribe()
    assert app.listen(follow_up=True)
    event = _events_until(inbox, "finished")
    assert event.get("heard") is False
    assert listener.timeouts == [W.FOLLOW_UP_SECONDS]
    assert app.speech.said == []           # pas de « je n'ai rien entendu »
    assert app.listen()                    # le verrou a bien ete rendu


def test_announce_speaks_and_records():
    app = JarvisWeb(_Args(), STRINGS["fr"], None, _Speech(), _Chain(), [], greet=False)
    app.announce("Bonjour, Erwan.")
    assert app.transcript[-1] == {"kind": "jarvis", "text": "Bonjour, Erwan."}


def test_orb_reopens_the_conversation_after_a_voice_answer():
    from jarvis_core import orb as O

    if O.tk is None:
        return
    try:
        root = O.tk.Tk()
    except Exception:
        return
    root.withdraw()
    app = JarvisWeb(_Args(), STRINGS["fr"], _Listener([]), _Speech(), _Chain(), [],
                    greet=False)
    orb = O.Orb(root, app, STRINGS["fr"])
    try:
        calls = []
        app.listen = lambda follow_up=False: calls.append(follow_up) or True
        orb.trigger("hotkey")                   # tour lance a la voix
        assert calls == [False] and orb.voice_turn
        orb.handle({"type": "finished", "heard": True})
        orb._follow_up()
        assert calls == [False, True]           # on reecoute sans mot d'activation
        orb.handle({"type": "finished", "heard": False})
        assert not orb.voice_turn               # silence : fin de conversation
        orb.trigger(("brief", "Bonjour.", ""))
        assert app.transcript[-1]["text"] == "Bonjour."
    finally:
        orb.close()


# --------------------------------------------------------------------------- #
# Orbe synchronisee a la voix
# --------------------------------------------------------------------------- #
def test_audio_level_follows_loudness():
    silence = b"\x00\x00" * 512
    loud = struct.pack("<512h", *([12000, -12000] * 256))
    assert tts.audio_level(silence) == 0.0
    assert tts.audio_level(loud) == 1.0
    assert 0 < tts.audio_level(struct.pack("<4h", 2000, -2000, 2000, -2000)) < 0.5


def test_hud_equalizer_follows_the_voice_level():
    if not orb_render.available():
        return
    renderer = orb_render.HudRenderer(120, 30)
    quiet = renderer.frame("speaking", 5.0, level=0.0)
    loud = renderer.frame("speaking", 5.0, level=1.0)
    assert quiet.tobytes() != loud.tobytes()
    # hors parole, le volume est ignore (et l'image reste en cache)
    assert renderer.frame("ready", 5.0, level=1.0) is renderer.frame("ready", 5.0)


def test_speech_exposes_engine_level():
    class _Engine:
        level = 0.4

        def say(self, _text):
            pass

        def runAndWait(self):
            pass

        def stop(self):
            pass

    speech = tts.Speech(lambda: _Engine(), source=None, bargein=False, watchdog_seconds=0)
    assert speech.level == 0.4
    speech.close()
