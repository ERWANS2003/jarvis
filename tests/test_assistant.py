"""Tests des fonctions « assistant » : musique, actualites, texte, quiz, alertes.

Aucun reseau, aucune touche, aucune notification : doublures partout.
"""

from __future__ import annotations

import datetime as dt

from jarvis_core import intents as I
from jarvis_core import news, notify, proactive, websites
from jarvis_core.i18n import STRINGS
from jarvis_core.quiz import QuizSession, rules_for

FR = STRINGS["fr"]
RSS = b"""<?xml version="1.0"?><rss><channel>
<item><title>Premier titre - Le Monde</title></item>
<item><title>Deuxieme titre ?</title></item>
<item><title>Premier titre - Le Figaro</title></item>
<item><title>Troisieme titre</title></item>
</channel></rss>"""


def _opener(opened):
    return lambda url: opened.append(url) or True


def test_music_by_name_starts_the_first_video():
    opened = []
    finder = lambda query: "dQw4w9WgXcQ"
    ask = lambda text: I.quick_answer(text, "fr", FR, opener=_opener(opened),
                                      music_finder=finder)
    assert ask("Joue Daft Punk") == "Je lance Daft Punk."
    assert ask("mets la chanson Bohème de Aznavour") == "Je lance Bohème de Aznavour."
    assert ask("Écoute du jazz sur Spotify") == "Je lance jazz."
    assert opened == ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"] * 2 + [
        "https://open.spotify.com/search/jazz"]


def test_music_falls_back_to_the_search_page():
    opened = []
    assert websites.play_music("lofi", opener=_opener(opened), finder=lambda q: None)
    assert opened == ["https://www.youtube.com/results?search_query=lofi"]
    assert websites.play_music("  ", opener=_opener(opened)) is None


def test_headlines_are_parsed_and_read():
    assert news.parse_titles(RSS, 5) == ["Premier titre", "Deuxieme titre ?", "Troisieme titre"]
    titles = news.fetch_headlines("fr", download=lambda url, timeout: RSS, limit=2)
    assert news.say_headlines(titles, "fr") == \
        "Voici les titres : Premier titre. Deuxieme titre ?"
    asked = []
    news_fn = lambda lang, topic: asked.append(topic) or ["Un but"]
    assert I.quick_answer("les infos sur le football", "fr", FR, news_fn=news_fn) == \
        "Voici les titres sur le football : Un but."
    assert I.quick_answer("Quelles sont les infos ?", "fr", FR, news_fn=news_fn)
    assert asked == ["le football", ""]


def test_headline_in_the_morning_briefing_only():
    from jarvis_core import briefing as B

    news_fn = lambda lang, topic, limit, timeout: ["La une du jour"]
    morning = B.gather("fr", now=dt.datetime(2026, 10, 29, 8, 0), news_fn=news_fn)
    evening = B.gather("fr", now=dt.datetime(2026, 10, 29, 19, 0), news_fn=news_fn)
    assert "À la une : La une du jour." in morning
    assert "À la une" not in evening


class _Selection:
    def __init__(self, text=""):
        self.text, self.pasted = text, []

    def paste_text(self, text):
        self.pasted.append(text)
        return True

    def selection_or_clipboard(self):
        return self.text, "selection"

    def for_speech(self, text, lang):
        return text


def test_read_selection_and_dictation():
    sel = _Selection("Bonjour à tous.")
    ask = lambda text: I.quick_answer(text, "fr", FR, selection_api=sel)
    assert ask("Lis ça") == "Bonjour à tous."
    assert ask("Écris : je serai en retard de dix minutes") == "C'est écrit."
    assert sel.pasted == ["je serai en retard de dix minutes"]
    assert I.quick_answer("lis ça", "fr", FR, selection_api=_Selection("")) == \
        FR["nothing_selected"]
    assert I.quick_answer("lis ça", "fr", FR) is None      # sans outils : le modele


def test_long_text_is_cut_for_speech():
    from jarvis_core import selection

    text = "mot " * 2000
    spoken = selection.for_speech(text, "fr")
    assert len(spoken) < selection.MAX_READ + 80 and spoken.endswith("je m'arrête là.")


def test_quiz_keeps_score_and_rules():
    quiz = QuizSession("fr")
    assert not quiz.active
    assert "question 1/2" in quiz.start("les volcans", 2)

    class Args:
        class tool_ctx:
            pass

    Args.tool_ctx.quiz = quiz
    assert "les volcans" in rules_for(Args)
    assert quiz.record(True).startswith("Score 1/1")
    assert "1/2" in quiz.record(False) and not quiz.active
    assert rules_for(Args) == ""


def test_notifications_use_the_tray_when_available():
    shown = []
    notify.set_backend(lambda title, message: shown.append((title, message)))
    try:
        assert notify.notify("Jarvis", "Rappel :   sortir  le linge")
        assert notify.notify("Jarvis", "   ") is False
    finally:
        notify.set_backend(None)
    assert shown == [("Jarvis", "Rappel : sortir le linge")]


def _watcher(sent, battery=None, idle=0.0, rain=False, city=None):
    return proactive.Watcher("fr", lambda text, speak: sent.append((text, speak)),
                             city=lambda: city,
                             sensors={"battery": lambda: battery, "idle": lambda: idle,
                                      "rain": lambda c: rain})


def test_low_battery_is_announced_once_per_discharge():
    sent = []
    watcher = _watcher(sent, battery=(15, False))
    noon = dt.datetime(2026, 10, 29, 12, 0)
    watcher.check(0, noon)
    watcher.check(60, noon)
    assert sent == [("Ta batterie est à 15 %, pense à brancher le chargeur.", True)]
    watcher.battery = lambda: (15, True)     # branche : on rearme
    watcher.check(120, noon)
    watcher.battery = lambda: (14, False)
    watcher.check(180, noon)
    assert len(sent) == 2


def test_break_reminder_after_two_hours_and_quiet_at_night():
    sent = []
    watcher = _watcher(sent)
    noon = dt.datetime(2026, 10, 29, 12, 0)
    watcher.check(0, noon)
    watcher.check(proactive.WORK_LIMIT - 1, noon)
    assert sent == []
    watcher.check(proactive.WORK_LIMIT + 1, dt.datetime(2026, 10, 29, 23, 0))
    assert sent and sent[0][0].startswith("Tu travailles depuis 2 heures")
    assert sent[0][1] is False                # la nuit : notification seulement
    watcher.idle = lambda: proactive.BREAK_RESET   # vraie pause : compteur remis a zero
    watcher.check(proactive.WORK_LIMIT + 60, noon)
    assert watcher._work_started is None


def test_rain_alert_is_rate_limited():
    sent = []
    watcher = _watcher(sent, rain=True, city="Lyon")
    morning = dt.datetime(2026, 10, 29, 9, 0)
    watcher.check(0, morning)
    watcher.check(600, morning)
    assert [text for text, _ in sent] == [
        "Il risque de pleuvoir dans l'heure à Lyon, prends un parapluie si tu sors."]


def test_relief_themes_have_their_own_material():
    from jarvis_core import orb_gpu, orb_render, orb_themes
    from jarvis_core.orb_materials import MODES

    relief = [k for k, v in orb_themes.CATALOG.items() if v[2] == "relief"]
    assert len(relief) == 20 and len(orb_render.THEMES) == 48
    used = {orb_gpu.GPU_THEMES[k]["mode"] for k in relief}
    assert used == set(MODES.values()) - {MODES["nacre"], MODES["plasma"]}
    if orb_gpu.available():                   # le shader compile et dessine chaque matiere
        for key in ("amethyste", "terre", "magma", "oeil_dragon", "trou_noir", "orage"):
            image = orb_gpu.GpuRenderer(key, 64, 16).frame("ready", 1.0)
            assert image.size == (64, 64) and image.getbbox() is not None


def test_glass_shell_on_every_orb():
    from jarvis_core import orb_gpu, orb_render

    hud = orb_render.make_renderer("jarvis", 120, 30)
    plain = orb_render.make_renderer("jarvis", 120, 30, glass=False)
    edge = (60 + int(30 * 1.1), 60)                     # sur la coque, hors du HUD
    assert hud.frame("ready", 2.0).getpixel(edge)[3] > plain.frame("ready", 2.0).getpixel(edge)[3]
    if orb_gpu.available():
        renderer = orb_render.make_renderer("magma", 120, 30, quality="ultra")
        with_glass = renderer.frame("ready", 1.0).tobytes()
        renderer.glass = 0.0
        assert renderer.frame("ready", 1.0).tobytes() != with_glass


def test_no_headline_in_the_middle_of_the_night():
    from jarvis_core import briefing as B

    news_fn = lambda lang, topic, limit, timeout: ["La une"]
    assert "À la une" not in B.gather("fr", now=dt.datetime(2026, 10, 30, 1, 15), news_fn=news_fn)
    assert "À la une" in B.gather("fr", now=dt.datetime(2026, 10, 30, 7, 30), news_fn=news_fn)
