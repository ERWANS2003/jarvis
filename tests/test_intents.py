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
                 "Quelle heure est-il à Tokyo ?",
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

