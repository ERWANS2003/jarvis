"""Tests des dix commandes instantanees de extras.py.

Ni reseau, ni batterie reelle, ni minuteur reel : doublures partout.
"""

from __future__ import annotations

import datetime as dt
import random
from types import SimpleNamespace

from jarvis_core import extras as X
from jarvis_core import intents as I
from jarvis_core.i18n import STRINGS

NOW = dt.datetime(2026, 10, 30, 9, 5)
RATES = {("USD", "EUR"): 0.92, ("EUR", "MAD"): 10.97, ("GBP", "EUR"): 1.17}


class FakeTimers:
    def __init__(self):
        self.set, self.cancelled = [], 0

    def set_timer(self, seconds, label):
        self.set.append((seconds, label))

    def cancel(self, _timer_id):
        self.cancelled += 1
        return 1

    def remaining(self):
        return []


class FakeMemory:
    def __init__(self, profile=(), facts=()):
        self.profile, self.facts = profile, facts

    def all(self, kind=None, limit=200):
        texts = self.profile if kind == "profile" else self.facts
        return [SimpleNamespace(text=t) for t in texts]


def _sun(city, lang, offset):
    return {"city": city.title(), "sunrise": dt.datetime(2026, 10, 30, 8, 12),
            "sunset": dt.datetime(2026, 10, 30, 17, 25)}


def _ask(text, lang="fr", **kw):
    options = dict(now=NOW, home_city="Lyon", rate_fn=lambda a, b: RATES[(a, b)], sun_fn=_sun,
                   battery_fn=lambda: (76, False, 7800), rng=random.Random(1))
    options.update(kw)
    return I.quick_answer(text, lang, STRINGS[lang], **options)


def test_calculation_without_model():
    assert _ask("Combien font 18 500 fois 3,5 ?") == "Ça fait 64750."
    assert _ask("combien fait 15 % de 240") == "Ça fait 36."
    assert _ask("calcule la racine carrée de 144") == "Ça fait 12."
    assert _ask("combien font 7 au carré") == "Ça fait 49."
    assert _ask("combien font 10 divisé par 4") == "Ça fait 2,5."
    assert _ask("combien font 10 divisé par 0") == "On ne peut pas diviser par zéro."
    assert _ask("what is 12 times 37", "en") == "That's 444."
    assert _ask("combien font les pompiers") is None


def test_unit_conversions():
    assert _ask("Convertis 5 miles en kilomètres") == "5 miles font 8,05 kilomètres."
    assert _ask("30 degrés Fahrenheit en Celsius") == \
        "30 degrés Fahrenheit font -1,11 degré Celsius."
    assert _ask("combien de minutes dans 3 heures") == "3 heures font 180 minutes."
    assert _ask("100 km/h en mph") == "100 kilomètres heure font 62,14 miles par heure."
    assert _ask("5 livres en kilos") == "5 livres font 2,27 kilos."
    assert _ask("convert 10 inches to cm", "en") == "10 inches are 25.4 centimetres."
    assert _ask("5 kilos en mètres") is None          # categories differentes


def test_currency_conversions_and_offline():
    assert _ask("combien font 50 dollars en euros") == \
        "50 dollars valent environ 46 euros, au cours du jour."
    assert _ask("100 euros en dirhams") == \
        "100 euros valent environ 1097 dirhams, au cours du jour."
    assert _ask("50 livres en euros").startswith("50 livres sterling valent environ 58,5")

    def offline(a, b):
        raise OSError("pas de reseau")

    assert _ask("50 dollars en euros", rate_fn=offline) is None   # le modele prendra le relais


def test_shopping_and_task_lists():
    import tempfile
    from pathlib import Path

    path = Path(tempfile.mkdtemp()) / "lists.json"
    store = X.ListStore(path)
    ask = lambda text, lang="fr": _ask(text, lang, lists=store)   # noqa: E731
    assert ask("Ajoute du lait, des œufs et de la crème fraîche à ma liste de courses") == \
        "C'est noté : lait, œufs et crème fraîche sur votre liste de courses."
    assert ask("ajoute du lait à ma liste de courses") == \
        "Lait, c'est déjà sur votre liste de courses."
    assert ask("retire les oeufs de ma liste de courses") == \
        "J'ai retiré œufs de votre liste de courses."
    assert X.ListStore(path).items("courses") == ["lait", "crème fraîche"]   # conserve
    assert ask("Qu'est-ce qu'il y a sur ma liste de courses ?") == \
        "Sur votre liste de courses : lait et crème fraîche."
    assert ask("mets appeler le plombier sur ma liste de tâches") == \
        "C'est noté : appeler le plombier sur votre liste de tâches."
    assert ask("ajoute un vélo à ma liste de cadeaux") == \
        "C'est noté : vélo sur votre liste de cadeaux."
    assert ask("vide ma liste de courses") == "Votre liste de courses est vidée."
    assert ask("lis ma liste de courses") == "Votre liste de courses est vide."
    assert ask("add milk and eggs to my shopping list", "en") == \
        "Noted: milk and eggs on your shopping list."


def test_dates_and_countdowns():
    assert _ask("Dans combien de jours est Noël ?") == \
        "Il reste 56 jours avant Noël, le vendredi 25 décembre."
    assert _ask("Noël c'est dans combien de jours") == \
        "Il reste 56 jours avant Noël, le vendredi 25 décembre."
    assert _ask("combien de jours avant le 14 juillet") == \
        "Il reste 257 jours avant le 14 juillet 2027, un mercredi."
    assert _ask("quel jour tombe le 14 juillet 2027") == "Le 14 juillet 2027 sera un mercredi."
    assert _ask("le 1er janvier 2027 tombe quel jour") == "Le 1er janvier 2027 sera un vendredi."
    assert _ask("quel jour c'est demain") == "Demain, nous serons le samedi 31 octobre."
    assert _ask("quel jour serons-nous dans 3 semaines") == \
        "Dans 3 semaines, nous serons le vendredi 20 novembre."
    assert _ask("quelle date dans 100 jours") == \
        "Dans 100 jours, nous serons le dimanche 7 février 2027."
    assert _ask("quelle semaine sommes-nous") == "Nous sommes en semaine 44."
    assert _ask("how many days until christmas", "en") == \
        "56 days until Christmas, Friday, December 25."
    # Les commandes existantes ne sont pas detournees.
    assert _ask("quel jour sommes-nous") == "Nous sommes vendredi 30 octobre 2026."


def test_chance():
    assert _ask("lance un dé") in {f"Le dé tombe sur {n}." for n in range(1, 7)}
    assert _ask("lance deux dés").startswith("Les dés donnent ")
    assert _ask("pile ou face") in {"Pile !", "Face !"}
    answer = _ask("choisis un nombre entre 1 et 100")
    assert answer.startswith("Je dis ") and 1 <= int(answer[7:-1]) <= 100
    assert _ask("choisis entre pizza, sushi et crêpes") in {
        "Je choisis : pizza.", "Je choisis : sushi.", "Je choisis : crêpes."}
    assert _ask("flip a coin", "en") in {"Heads!", "Tails!"}


def test_sunrise_and_sunset():
    assert _ask("À quelle heure se couche le soleil ?") == \
        "À Lyon, le soleil se couche à 17 h 25."
    assert _ask("à quelle heure se lève le soleil à Marseille demain") == \
        "À Marseille, le soleil se lèvera à 8 h 12 demain."
    assert _ask("coucher du soleil", home_city=None) is None      # ville inconnue : le modele


def test_battery():
    assert _ask("Combien de batterie il me reste ?") == \
        "Batterie à 76 %, environ 2 heures 10 minutes d'autonomie."
    assert _ask("niveau de batterie", battery_fn=lambda: (100, True, None)) == \
        "Batterie à 100 %, en charge."
    assert _ask("ma batterie", battery_fn=lambda: (12, False, None)) == \
        "Batterie à 12 %. Pensez à brancher le chargeur."
    assert _ask("ma batterie", battery_fn=lambda: None) == \
        "Cet ordinateur n'a pas de batterie : il est sur secteur."


def test_what_do_you_know_about_me():
    memory = FakeMemory(("location: Lyon", "name: Erwan"),
                        ("L'utilisateur aime le jazz.", "L'utilisateur est allergique aux arachides."))
    assert _ask("Qu'est-ce que tu sais sur moi ?", memory=memory) == (
        "Je sais que vous vous appelez Erwan et que vous habitez à Lyon. J'ai aussi retenu "
        "2 choses : L'utilisateur aime le jazz ; L'utilisateur est allergique aux arachides. "
        "Demandez-moi d'oublier ce que vous voulez.")
    assert _ask("que sais-tu de moi", memory=FakeMemory()).startswith("Je ne sais encore rien")


def test_pomodoro():
    timers = FakeTimers()
    assert _ask("lance un pomodoro", timers=timers) == (
        "Pomodoro lancé : 25 minutes de concentration, puis 5 minutes de pause. "
        "Je vous préviens.")
    assert [s for s, _ in timers.set] == [1500, 1800]
    _ask("pomodoro de 50 minutes", timers=timers)
    assert [s for s, _ in timers.set][2:] == [3000, 3600]
    assert _ask("arrête le pomodoro", timers=timers) == "Pomodoro arrêté."
    assert timers.cancelled == 1


def test_existing_commands_still_win():
    assert _ask("quelle heure est-il") == "Il est 9 h 05."
    assert _ask("raconte une blague") is None
    assert X.answer("ouvre youtube", "fr", NOW) is None
    assert X.answer("mets pause", "fr", NOW) is None
    assert X.answer("joue du jazz", "fr", NOW) is None
