"""Tests des commandes instantanees, de l'aiguillage et du delai maximal.

Aucune touche, aucun navigateur, aucun modele : doublures partout.
"""

from __future__ import annotations

import datetime as dt
import time

from langchain_core.messages import HumanMessage

from jarvis_core import graph as G
from jarvis_core import intents as I
from jarvis_core import pc
from jarvis_core.i18n import STRINGS

NOW = dt.datetime(2026, 10, 29, 9, 5)
FR = STRINGS["fr"]


def _ask(text, opened=None):
    return I.quick_answer(text, "fr", FR, now=NOW,
                          opener=((lambda url: opened.append(url) or True)
                                  if opened is not None else None))


def test_time_and_date_answer_instantly():
    assert _ask("Jarvis, quelle heure est-il ?") == "Il est 9 h 05."
    assert _ask("Il est quelle heure") == "Il est 9 h 05."
    assert _ask("On est quel jour ?") == "Nous sommes jeudi 29 octobre 2026."
    assert I.quick_answer("what time is it", "en", STRINGS["en"], now=NOW) == "It is 9:05 AM."


def test_open_and_search_websites_instantly():
    opened = []
    assert _ask("Ouvre YouTube", opened) == "J'ouvre Youtube."
    assert _ask("peux-tu lancer le site github", opened) == "J'ouvre Github."
    assert _ask("Cherche des tutos python sur YouTube", opened) == \
        "Voici les résultats pour des tutos python sur Youtube."
    assert opened == ["https://www.youtube.com", "https://github.com",
                      "https://www.youtube.com/results?search_query=des+tutos+python"]


def test_media_and_volume_commands():
    pressed = []
    original = pc.press
    pc.press = pressed.append
    try:
        assert _ask("Mets pause") == FR["pc_done"]
        assert _ask("chanson suivante") == FR["pc_done"]
        assert _ask("monte le son") == FR["pc_done"]
        assert _ask("mets le volume à 30 %") == "Volume réglé à 30 %."
        assert pressed[:2] == [pc.VK_MEDIA_PLAY_PAUSE, pc.VK_MEDIA_NEXT]
    finally:
        pc.press = original


def test_rich_requests_are_left_to_the_model():
    opened = []
    for text in ("Ouvre YouTube et mets une musique calme",
                 "Raconte-moi une blague",
                 "Quelle heure est-il sur Mars ?",
                 "Ouvre un site imaginaire"):
        assert _ask(text, opened) is None, text
    assert opened == []


def test_tools_only_when_the_question_needs_them():
    for text in ("Quelle est la météo à Lyon ?", "Rappelle-moi demain à 9 h",
                 "combien font 12 x 7", "ouvre mon dernier PDF", "What's the weather?"):
        assert I.needs_tools(text), text
    for text in ("Raconte-moi une blague", "Explique la photosynthèse simplement",
                 "Tu préfères les chats ou les chiens ?", "Merci beaucoup"):
        assert not I.needs_tools(text), text


class _FrozenGraph:
    """Modele gratuit fige : ne repond jamais."""

    def __init__(self):
        self.calls = 0

    def stream(self, _inputs, stream_mode=None):
        self.calls += 1
        time.sleep(5)
        yield from ()


def test_a_frozen_model_is_abandoned_after_the_deadline():
    graph = _FrozenGraph()
    started = time.monotonic()
    result = G.stream_reply(graph, [HumanMessage(content="q")], lambda _s: None,
                            retries=1, deadline=0.3)
    assert not result.ok and isinstance(result.error, TimeoutError)
    assert time.monotonic() - started < 2


def test_weather_for_a_city_is_instant():
    asked = []

    def weather(city, lang, timeout):
        asked.append(city)
        return f"À {city.title()}, il fait 12 °C."

    ask = lambda text: I.quick_answer(text, "fr", FR, now=NOW, weather_fn=weather)
    assert ask("Quelle est la météo à Paris ?") == "À Paris, il fait 12 °C."
    assert ask("quel temps fait-il à Ouagadougou") == "À Ouagadougou, il fait 12 °C."
    assert ask("La météo") is None                     # sans ville : le modele
    assert asked == ["paris", "ouagadougou"]

    def offline(*_args):
        raise ConnectionError

    assert I.quick_answer("météo à Lyon", "fr", FR, weather_fn=offline) is None



def test_spoken_durations():
    for text, seconds in (("10 minutes", 600), ("une demi-heure", 1800), ("1 h 30", 5400),
                          ("2 minutes et 30 secondes", 150), ("deux minutes 30", 150),
                          ("1 h et demie", 5400), ("quarante-cinq secondes", 45),
                          ("an hour", 3600), ("un quart d'heure", 900)):
        assert I.parse_duration(text) == seconds, text
    assert I.parse_duration("dix minutes de") is None
    assert I.say_duration(5400, "fr") == "1 heure 30 minutes"


class _Timers:
    def __init__(self):
        self.started = []

    def set_timer(self, seconds, label=""):
        self.started.append((seconds, label))
        return len(self.started)


def test_timers_start_instantly():
    timers = _Timers()
    ask = lambda text: I.quick_answer(text, "fr", FR, now=NOW, timers=timers)
    assert ask("Mets un minuteur de 5 minutes") == "C'est parti pour 5 minutes."
    assert ask("Jarvis, lance un chrono de 30 secondes") == "C'est parti pour 30 secondes."
    assert timers.started == [(300, "Minuteur de 5 minutes terminé."),
                              (30, "Minuteur de 30 secondes terminé.")]
    # Sans registre (outils coupes), le modele garde la main.
    assert I.quick_answer("minuteur 5 minutes", "fr", FR, now=NOW) is None


def test_reminders_are_saved_instantly_with_accents():
    from jarvis_core.reminders import ReminderStore

    store = ReminderStore()
    ask = lambda text: I.quick_answer(text, "fr", FR, now=NOW, reminders=store)
    assert ask("Rappelle-moi dans 10 minutes de sortir le linge.") == \
        "C'est noté, je te le rappelle à 9 h 15."
    assert ask("Rappelle-moi dans une demi-heure d'éteindre le four") == \
        "C'est noté, je te le rappelle à 9 h 35."
    assert ask("rappelle-moi à 8 h d'appeler Paul") == \
        "C'est noté, je te le rappelle demain à 8 h."          # 8 h est passe
    assert ask("Rappelle-moi demain à 9 h 30 qu'il faut payer l'électricité") == \
        "C'est noté, je te le rappelle demain à 9 h 30."
    assert ask("Rappelle-moi de faire les courses") is None     # sans heure : le modele
    assert [(r["when"], r["text"]) for r in store.list()] == [
        ("2026-10-29T09:15:00", "sortir le linge"),
        ("2026-10-29T09:35:00", "éteindre le four"),
        ("2026-10-30T08:00:00", "appeler Paul"),
        ("2026-10-30T09:30:00", "payer l'électricité"),
    ]


def test_repeat_says_the_last_answer_again_without_the_model():
    import tempfile
    from pathlib import Path

    from langchain_core.messages import AIMessage

    from jarvis_core import gui

    for text in ("Répète", "Tu peux répéter s'il te plaît ?", "Qu'est-ce que tu as dit ?",
                 "Pardon ?", "Je n'ai pas bien entendu"):
        assert I.repeat_request(text), text
    assert not I.repeat_request("Répète après moi : bonjour")

    class Args:
        lang, ability, max_words, retries, allow_apps = "fr", "x", 40, 1, None
        history_path = str(Path(tempfile.mkdtemp()) / "h.json")

    class Chain:          # aucun modele : un appel ferait echouer le test
        tools, tools_enabled = [], False

    turn = gui._make_turn(Args, FR, Chain(), None)
    history = [HumanMessage(content="météo ?"),
               AIMessage(content="Il fait 30 degrés.---DETAIL---## Détail")]
    said = []
    turn("Tu peux répéter ?", history, on_sentence=said.append, on_tool=lambda n: None,
         on_status=lambda s: None)
    assert said == ["Il fait 30 degrés."] and len(history) == 2


def test_weather_without_a_city_uses_the_home_city():
    asked = []
    weather = lambda city, lang, timeout: asked.append(city) or f"À {city}, 30 °C."
    ask = lambda text, home: I.quick_answer(text, "fr", FR, now=NOW, weather_fn=weather,
                                            home_city=home)
    assert ask("Quel temps fait-il ?", "Ouagadougou") == "À Ouagadougou, 30 °C."
    assert ask("Il fait chaud dehors ?", "Ouagadougou")
    assert ask("la météo aujourd'hui", "Ouagadougou")
    assert ask("Quel temps fait-il ?", None) is None              # ville inconnue : le modele
    assert ask("Quel temps fait-il à Lyon ?", "Ouagadougou")       # ville precisee : celle-la
    assert asked == ["Ouagadougou", "Ouagadougou", "Ouagadougou", "lyon"]


def test_timers_left_cancel_and_reminders_list_are_instant():
    from jarvis_core.reminders import ReminderStore
    from jarvis_core.tools import TimerRegistry

    timers = TimerRegistry(speak=None)
    ask = lambda text, **kw: I.quick_answer(text, "fr", FR, now=NOW, timers=timers, **kw)
    assert ask("Combien de temps reste-t-il ?") == FR["no_timers"]
    timers.set_timer(600, "pâtes")                          # jamais declenche : annule plus bas
    timers.set_timer(1200, "lessive")
    left = ask("Il reste combien ?")
    assert left.startswith("Il reste 9 minutes") or left.startswith("Il reste 10 minutes")
    assert "1 autre(s) minuteur(s)" in left
    assert ask("Annule le minuteur") == FR["cancelled_timers"].format(count=2)
    assert timers.remaining() == []

    store = ReminderStore()
    assert ask("Quels sont mes rappels ?", reminders=store) == FR["no_reminders"]
    store.add(NOW.replace(hour=18, minute=0), "appeler Paul")
    store.add(NOW.replace(day=30, hour=8, minute=0), "partir tôt")
    assert ask("quels sont mes rappels ?", reminders=store) == \
        "Vous avez 2 rappels : à 18 h, appeler Paul ; demain à 8 h, partir tôt."


def test_time_anywhere_in_the_world_is_exact():
    from jarvis_core import worldtime

    noon_utc = dt.datetime(2026, 10, 30, 12, 0, tzinfo=dt.timezone.utc)
    assert worldtime.time_in("Tokyo", noon_utc).hour == 21                  # UTC+9
    assert worldtime.time_in("New York", noon_utc).hour == 8                # UTC-4 (heure d'ete)
    assert worldtime.time_in("Ouagadougou", noon_utc).hour == 12
    assert worldtime.time_in("Trifouillis", noon_utc) is None
    answer = I.quick_answer("Quelle heure est-il au Japon ?", "fr", FR)
    assert answer.startswith("Il est ") and answer.endswith(" au Japon.")
    assert I.quick_answer("Quelle heure est-il à Trifouillis ?", "fr", FR) is None
