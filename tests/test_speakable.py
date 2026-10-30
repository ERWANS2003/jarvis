"""Tests de la forme parlee du texte (ce que la voix prononce vraiment)."""

from __future__ import annotations

from jarvis_core.speakable import speakable


def test_weather_units_and_decimals_are_spoken():
    assert speakable("Il fait 26.7 °C, vent 4.0 km/h.") == \
        "Il fait 26,7 degrés, vent 4 kilomètres heure."
    assert speakable("30°C et 80% d'humidité") == "30 degrés et 80 pour cent d'humidité"


def test_times_dates_ordinals_and_titles():
    assert speakable("Rendez-vous à 16:17 le 30/10/2026 au 2e étage avec M. Dupont.") == \
        "Rendez-vous à 16 h 17 le 30 octobre 2026 au deuxième étage avec Monsieur Dupont."
    assert speakable("le 01/05/2026 à 9:00") == "le premier mai 2026 à 9 h"


def test_maths_money_and_asides():
    assert speakable("x = (25 − 7)/3 = 6.") == "x égale 25 moins 7 divisé par 3 égale 6."
    assert speakable("3 x 4 = 12") == "3 fois 4 égale 12"
    assert speakable("12 500 FCFA (environ 19 €) ; remise de 15 %.") == \
        "12500 francs CFA, environ 19 euros, remise de 15 pour cent."


def test_markup_links_and_versions_are_left_readable():
    assert speakable("## Titre\n- **un** point") == "Titre un point"
    assert speakable("Voir https://example.com") == "Voir le lien affiché"
    assert speakable("Python 3.11") == "Python 3.11"          # pas « 3 virgule 11 »
    assert speakable("plongent‑ils") == "plongent-ils"


def test_english_forms():
    assert speakable("It is 21.5 °C, 10 km/h wind, 3 x 4 = 12", "en") == \
        "It is 21.5 degrees, 10 kilometres per hour wind, 3 times 4 equals 12"


def test_titles_do_not_cut_a_sentence():
    from jarvis_core.text import take_sentences

    sentences, rest = take_sentences("Rendez-vous avec M. Dupont au 2e étage. Puis le Dr. House. Fin")
    assert sentences == ["Rendez-vous avec M. Dupont au 2e étage.", "Puis le Dr. House."]
    assert rest == "Fin"
    assert take_sentences("Il est midi. Tout va bien. ")[0] == ["Il est midi.", "Tout va bien."]
