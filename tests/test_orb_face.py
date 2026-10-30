"""Tests du visage de l'orbe : regard, clignements, emotions, caresses, petites phrases."""

from __future__ import annotations

import random

from jarvis_core import orb_face as F


def _run(face, seconds=1.0, **kw):
    for _ in range(int(seconds / 0.03)):
        face.step(0.03, **kw)
    return face.look


def test_eyes_follow_a_nearby_mouse_only():
    face = F.Face(random.Random(1))
    assert _run(face, mouse=(200, 0)).gaze_x > 0.8
    assert _run(face, mouse=(-200, 0)).gaze_x < -0.8
    assert _run(face, mouse=(0, -200)).gaze_y < -0.8


def test_blinks_happen_and_reopen():
    face = F.Face(random.Random(2))
    seen = []
    for _ in range(int(20 / 0.03)):
        face.step(0.03)
        seen.append(face.openness)
    assert min(seen) < 0.5 and seen[-1] > 0.5 or max(seen) > 0.9
    assert sum(1 for value in seen if value < 0.5) < len(seen) / 4   # les yeux restent ouverts


def test_mouth_follows_the_voice_only_when_speaking():
    face = F.Face(random.Random(3))
    assert _run(face, state="speaking", level=0.6).mouth > 0.7
    assert _run(face, state="speaking", level=0.0).mouth < 0.1
    assert _run(face, state="ready", level=0.9).mouth < 0.1


def test_emotions_fade_back():
    face = F.Face(random.Random(4))
    face.feel("happy", 0.5)
    assert face.expression("ready") == "happy"
    assert _run(face, 0.3).arcs > 0.5
    _run(face, 1.0)
    assert face.emotion is None and face.expression("ready") == "neutral"
    face.feel("inconnue")
    assert face.emotion is None


def test_sleep_closes_the_eyes():
    face = F.Face(random.Random(5))
    _run(face, sleep_depth=1.0)
    assert face.openness < 0.05
    assert face.expression("ready", 1.0) == "asleep"


def test_emotion_detection():
    assert F.emotion_for("Désolé, je ne peux pas le faire.") == "sad"
    assert F.emotion_for("Bravo, c'est parfait !") == "happy"
    assert F.emotion_for("C'est incroyable.") == "surprised"
    assert F.emotion_for("Il est 9 h.") is None
    assert F.emotion_for_user("Merci Jarvis") == "shy"
    assert F.emotion_for_user("tu es nul") == "sad"
    assert F.emotion_for_user("Salut !") == "happy"
    assert F.emotion_for_user("ouvre youtube") is None


def test_petting_needs_back_and_forth():
    pets = F.PetDetector()
    now, x, hits = 0.0, 100, []
    for step in range(30):
        x += 20 if step % 3 else -60
        now += 0.05
        hits.append(pets.update(now, x))
    assert hits.count(True) == 1                     # une reaction, puis du repos
    calm = F.PetDetector()
    assert not any(calm.update(i * 0.05, 100 + i * 10) for i in range(30))   # simple passage
    assert not calm.update(5.0, None)


def test_musings_follow_the_moment():
    rng = random.Random(1)
    assert F.musing(8, 1, "fr", rng) in F.MUSINGS["fr"]["morning"]
    assert F.musing(1, 1, "fr", rng) in F.MUSINGS["fr"]["night"]
    assert F.musing(16, 4, "fr", rng) in F.MUSINGS["fr"]["friday"]
    assert F.reaction("pet", "en", rng) in F.REACTIONS["en"]["pet"]


def test_drawing_keeps_size_and_original_image():
    from PIL import Image

    base = Image.new("RGBA", (168, 168), (40, 60, 90, 255))
    face = F.Face(random.Random(1))
    for name in F.EXPRESSIONS:
        face.feel(name, 9)
        _run(face, 0.5, sleep_depth=1.0 if name == "asleep" else 0.0)
        drawn = face.draw(base, 42)
        assert drawn.size == base.size and drawn is not base
    assert base.getpixel((84, 84)) == (40, 60, 90, 255)
