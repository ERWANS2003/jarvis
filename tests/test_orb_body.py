"""Tests du corps de l'orbe : respiration, emotions, elan, gestes, reflet."""

from __future__ import annotations

import random

from jarvis_core import orb_body as B


def _run(body, seconds=1.0, **kw):
    values = []
    for _ in range(int(seconds / 0.03)):
        values.append(body.step(0.03, **kw).scale_y)
    return values


def test_breathing_is_faster_when_listening_and_slow_asleep():
    def crossings(**kw):
        values = _run(B.Body(random.Random(1)), 10.0, lively=False, **kw)
        return sum(1 for a, b in zip(values, values[1:]) if (a - 1) * (b - 1) < 0)

    assert crossings(state="listening") > crossings(state="ready") > crossings(sleep_depth=1.0)


def test_voice_makes_it_swell():
    quiet = max(_run(B.Body(random.Random(1)), state="speaking", level=0.0, lively=False))
    loud = max(_run(B.Body(random.Random(1)), state="speaking", level=0.8, lively=False))
    assert loud > quiet


def test_emotions_change_shape_and_colour():
    sad = B.Body(random.Random(1))
    _run(sad, emotion="sad", lively=False)
    assert sad.pose.scale_y < 1.0 and sad.pose.shift_y > 0
    assert sad.pose.tint == B.EMOTION_TINTS["sad"][0] and sad.pose.tint_strength > 0.1
    surprised = B.Body(random.Random(1))
    assert max(_run(surprised, 0.3, emotion="surprised", lively=False)) > 1.05
    shy = B.Body(random.Random(1))
    tilts = [shy.step(0.03, emotion="shy", lively=False).tilt for _ in range(40)]
    assert max(tilts) > 3 and min(tilts) < -3
    _run(shy, 2.0, lively=False)
    assert shy.pose.tint_strength < 0.01                   # l'emotion passe


def test_motion_stretches_along_the_direction():
    body = B.Body(random.Random(1))
    _run(body, 0.6, velocity=(1500.0, 0.0), lively=False)
    assert body.pose.scale_x > 1.05 and body.pose.tilt > 3
    body = B.Body(random.Random(1))
    _run(body, 0.6, velocity=(0.0, 1500.0), lively=False)
    assert body.pose.scale_y > 1.05


def test_glint_follows_the_mouse():
    body = B.Body(random.Random(1))
    _run(body, mouse=(300, 0), lively=False)
    assert body.pose.glint_x > 0.8
    _run(body, mouse=(-300, 0), lively=False)
    assert body.pose.glint_x < -0.8


def test_fidgets_only_when_lively_and_idle():
    def moved(**kw):
        body = B.Body(random.Random(2))
        seen = False
        for _ in range(int(25 / 0.03)):
            body.step(0.03, **kw)
            seen = seen or body._fidget is not None
        return seen

    assert moved(lively=True)
    assert not moved(lively=False)
    assert not moved(lively=True, state="thinking")
    assert not moved(lively=True, sleep_depth=1.0)


def test_apply_keeps_size_and_original_image():
    from PIL import Image

    base = Image.new("RGBA", (168, 168), (0, 0, 0, 0))
    base.paste((40, 60, 90, 255), (60, 60, 108, 108))
    body = B.Body(random.Random(1))
    _run(body, emotion="happy")
    drawn = body.apply(base, 42)
    assert drawn.size == base.size and drawn is not base
    assert drawn.getpixel((2, 2))[3] == 0                  # les coins restent transparents
    assert base.getpixel((84, 84)) == (40, 60, 90, 255)


def test_face_is_off_by_default_and_chosen_per_theme():
    from jarvis_core import orb as O
    from tests.test_settings import _SettingsFile

    with _SettingsFile():
        class Fake:
            theme = "opale"
            face_themes: set = set()
            face_on = O.Orb.face_on
            set_face = O.Orb.set_face

        orb = Fake()
        assert orb.face_on is False
        orb.set_face(True)
        assert orb.face_on is True
        orb.theme = "sakura"
        assert orb.face_on is False
        assert O.load_settings()["face_themes"] == ["opale"]


def test_eye_theme_really_looks_at_the_mouse():
    from jarvis_core import orb_gpu

    if not orb_gpu.available():
        return
    try:
        eye = orb_gpu.GpuRenderer("oeil_celeste", 96, 24)
        plain = orb_gpu.GpuRenderer("opale", 96, 24)
    except Exception:
        return
    assert eye.is_eye and not plain.is_eye

    def dark_centre(image):
        """Abscisse moyenne des pixels sombres : ou se trouve la pupille."""
        points = [x for x in range(image.width) for y in range(image.height)
                  if image.getpixel((x, y))[3] > 200 and sum(image.getpixel((x, y))[:3]) < 90]
        return sum(points) / max(1, len(points))

    eye.set_eye(-1.0, 0.0)
    left = dark_centre(eye.frame("ready", 3.0))
    eye.set_eye(1.0, 0.0)
    right = dark_centre(eye.frame("ready", 3.0))
    assert left < eye.size / 2 < right
    eye.set_eye(0.0, 0.0, openness=0.0)
    closed = eye.frame("ready", 3.0)
    eye.set_eye(0.0, 0.0, openness=1.0)
    assert closed.tobytes() != eye.frame("ready", 3.0).tobytes()
