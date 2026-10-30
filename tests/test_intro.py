"""Tests des intros : les deux rendus, jamais de bord visible, l'orbe reste nette."""

from __future__ import annotations

from jarvis_core import cinematic as C

ORB, SIZE = 168, int(168 * 3.4)
LINES = C.system_lines("fr", 34, "openai/gpt-oss-120b", "kokoro", True)


def _gpu(style, size=SIZE):
    try:
        from jarvis_core import intro_gpu, orb_gpu

        if not orb_gpu.available():
            return None
        return intro_gpu.GpuPainter(style, size, ORB, "#1ec8ff", "fr", LINES)
    except Exception:
        return None


def _border_alpha(image):
    width, height = image.size
    edge = [(x, 0) for x in range(width)] + [(x, height - 1) for x in range(width)]
    edge += [(0, y) for y in range(height)] + [(width - 1, y) for y in range(height)]
    return max(image.getpixel(point)[3] for point in edge[::7])


def test_gpu_intros_light_up_and_never_touch_the_window_edge():
    for style in C.STYLES:
        painter = _gpu(style)
        if painter is None:
            return
        try:
            lit = 0
            for moment in (0.4, 1.0, 1.6, 2.1):
                image = painter.frame(moment)
                assert image.size == (SIZE, SIZE)
                assert _border_alpha(image) <= 8, (style, moment)
                lit = max(lit, image.getchannel("A").getextrema()[1])
            assert lit > 60, style
        finally:
            painter.close()


def test_gpu_intros_fade_to_nothing_and_keep_the_orb_clean():
    for style in C.STYLES:
        painter = _gpu(style)
        if painter is None:
            return
        try:
            assert painter.frame(C.DURATION).getchannel("A").getextrema()[1] <= 8, style
            if style not in ("terminal", "minimal"):
                centre = painter.frame(1.0).getpixel((SIZE // 2, SIZE // 2))
                assert centre[3] <= 8, style               # la lumiere ne couvre pas l'orbe
        finally:
            painter.close()


def test_text_follows_the_screen_scale():
    small, big = _gpu("terminal", 571), _gpu("terminal", 1142)
    if small is None or big is None:
        return
    try:
        assert big.zoom == 2 * small.zoom
    finally:
        small.close()
        big.close()


def test_fallback_when_the_graphics_card_is_refused():
    plain = C.make_painter("onde", 300, 90, "#1ec8ff", "fr", gpu=False)
    assert type(plain) is C.Painter
    image = plain.frame(1.0)
    assert image.size == (300, 300) and image.getchannel("A").getextrema()[1] > 30
    for style in C.STYLES:
        assert C.Painter(style, 300, 90, "#1ec8ff", "fr", LINES).frame(1.2).mode == "RGBA"
    assert C.play(None, "aucune", (0, 0), 90, "#1ec8ff", "fr") is None
