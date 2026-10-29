"""Tests de la vie de l'orbe : balades, lancer, gestes, sommeil, discretion.

Aucune fenetre : `orb_life.Life` est pure, on la fait vivre image par image.
"""

from __future__ import annotations

import math
import random

from jarvis_core import orb_life as L

AREA = (0, 0, 1920, 1040)
DT = 0.04


def _life(home=(1700, 800), calm=False, seed=3):
    return L.Life(home, 112, AREA, rng=random.Random(seed), calm=calm)


def _run(life, seconds, world=None, every=None):
    world = world or L.World()
    positions = []
    for _ in range(int(seconds / DT)):
        if every:
            every(life, world)
        positions.append(life.step(DT, world))
    return positions


def test_the_orb_goes_for_a_stroll_then_comes_home():
    life = _life()
    positions = _run(life, 110)
    distances = [math.dist(p, life.home) for p in positions]
    assert max(distances) > 50                       # elle est partie se promener
    assert distances[-1] < 3 or life.mode != "home"  # ... et revient (ou repart)
    for x, y in positions:                           # toujours dans l'ecran
        assert 0 <= x <= 1920 - 112 and 0 <= y <= 1040 - 112 + 15
    steps = [math.dist(a, b) for a, b in zip(positions, positions[1:])]
    assert max(steps) < 40                           # deplacement doux, jamais de saut


def test_no_stroll_while_busy_hovered_or_calm():
    for world in (L.World(state="speaking"), L.World(hovered=True)):
        life = _life()
        assert {p for p in _run(life, 90, world)} <= {(1700, 800)}
    calm = _life(calm=True)
    assert set(_run(calm, 90)) == {(1700, 800)}


def test_strolls_never_head_for_the_mouse():
    life = _life()
    mouse = life.center()
    for _ in range(40):
        spot = life._stroll_spot(mouse)
        assert spot is None or math.dist(life.center(spot), mouse) >= L.MOUSE_KEEP_AWAY


def test_a_thrown_orb_slides_bounces_and_settles():
    life = _life(home=(900, 500))
    assert not life.throw(900, 500, 100, 0)          # simple lacher : pas de glissade
    assert life.throw(900, 500, 4000, -600)
    positions = _run(life, 4)
    xs = [x for x, _ in positions]
    assert max(xs) == 1920 - 112                      # touche le bord droit...
    assert xs[-1] < max(xs)                           # ... et rebondit
    assert life.mode == "home" and "settled" in life.take_events()
    assert life.home == tuple(map(float, life.pos))   # nouvelle maison la ou elle s'arrete


def test_yes_and_no_gestures():
    assert L.gesture_for("Oui, c'est fait.") == "nod"
    assert L.gesture_for("C'est fait.") == "nod"
    assert L.gesture_for("Désolé, je ne peux pas.") == "shake"
    assert L.gesture_for("Haha, très drôle !") == "giggle"
    assert L.gesture_for("Il est midi.") is None
    life = _life(calm=True)
    life.play("shake")
    xs = [x for x, _ in _run(life, 1.0)]
    assert max(xs) > 1700 and min(xs) < 1700 and xs[-1] == 1700   # va-et-vient puis repos


def test_it_falls_asleep_when_nobody_is_there_and_wakes_up():
    life = _life()
    away = L.World(user_idle=L.SLEEP_USER_AWAY + 10)
    life.quiet_for = L.SLEEP_AFTER
    _run(life, 3, away)
    assert life.asleep and "sleep" in life.take_events()
    y_asleep = _run(life, 3, away)[-1][1]
    assert y_asleep > 800                            # elle s'est affaissee
    _run(life, 0.2, L.World(state="listening"))      # on l'appelle
    assert not life.asleep and "wake" in life.take_events()


def test_it_greets_the_user_coming_back():
    life = _life()
    _run(life, 0.2, L.World(user_idle=L.WELCOME_AWAY + 5))
    _run(life, 0.2, L.World(user_idle=0.5))
    assert "welcome" in life.take_events()


def test_it_moves_away_from_the_text_caret_then_returns():
    life = _life(home=(900, 500), calm=True)         # meme en mode calme
    caret = (940, 540, 942, 560)                      # on tape juste sous l'orbe
    assert set(_run(life, 2, L.World(caret=caret, user_idle=60))) == {(900, 500)}  # sans frappe
    positions = _run(life, 3, L.World(caret=caret, user_idle=0.2))
    last = positions[-1]
    assert not life._rect_hits(last, caret, 0)        # la zone de saisie est libre
    assert math.dist(last, (900, 500)) <= L.CARET_MAX_MOVE
    _run(life, 2, L.World(caret=None))
    assert life.mode == "dodge"                       # attend que la place soit libre 4 s
    _run(life, 5, L.World(caret=None))
    assert math.dist(life.pos, life.home) < 3         # et elle revient chez elle


def test_curious_lean_toward_a_nearby_mouse():
    life = _life(home=(900, 500), calm=False)
    life.timer = 1e9                                  # pas de balade pendant le test
    cx, cy = life.center()
    x, y = _run(life, 1.5, L.World(mouse=(cx + 150, cy)))[-1]
    assert 900 < x <= 900 + L.CURIOUS_LEAN + 1 and abs(y - 500) <= 1
