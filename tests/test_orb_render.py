"""Tests du rendu lisse de l'orbe (Pillow) et des fenetres transparentes.

Sans Pillow (ou hors Windows pour les fenetres), les tests concernes sortent
silencieusement : l'orbe garde alors son dessin Tkinter de secours.
"""

from __future__ import annotations

from jarvis_core import layered, orb_render



def _inner(renderer):
    """Rendu sous la coque de verre (orb_render.GlassRenderer)."""
    return getattr(renderer, "inner", renderer)

def test_orb_frames_are_round_and_transparent_outside():
    if not orb_render.available():
        return
    renderer = orb_render.OrbRenderer(168, 42)
    for state in ("ready", "listening", "thinking", "speaking", "inconnu"):
        image = renderer.frame(state, 1.0)
        assert image.size == (168, 168) and image.mode == "RGBA"
        assert image.getpixel((0, 0))[3] == 0        # coin : transparent
        assert image.getpixel((84, 84))[3] == 255    # centre : sphere opaque
        halo = image.getpixel((84, 84 - 42 - 10))[3]
        assert 0 < halo < 255                        # halo : semi-transparent


def test_orb_animation_changes_and_is_cached():
    if not orb_render.available():
        return
    renderer = orb_render.OrbRenderer(120, 30)
    first = renderer.frame("speaking", 0.0)
    assert renderer.frame("speaking", 0.0) is first          # cache
    assert renderer.frame("speaking", 1.5).tobytes() != first.tobytes()


def test_bubble_wraps_long_text_and_keeps_short_text_compact():
    if not orb_render.available():
        return
    short = orb_render.render_bubble("Oui ?")
    long = orb_render.render_bubble("mot " * 80, max_width=200)
    assert short.width < long.width or short.height < long.height
    assert long.height > short.height * 3
    font = orb_render._font(15)
    lines = orb_render.wrap("un deux trois quatre cinq six sept", font, 60)
    assert len(lines) > 1 and all(font.getlength(line) <= 60 or " " not in line
                                  for line in lines)


def test_premultiplied_bgra_layout():
    if not orb_render.available():
        return
    from PIL import Image

    pixel = Image.new("RGBA", (1, 1), (200, 100, 50, 128))
    b, g, r, a = layered.premultiplied_bgra(pixel)
    assert a == 128
    assert abs(r - 100) <= 1 and abs(g - 50) <= 1 and abs(b - 25) <= 1


def test_fancy_orb_draws_and_shows_bubble():
    if not (orb_render.available() and layered.supported()):
        return
    from jarvis_core import orb as O
    from jarvis_core.i18n import STRINGS
    from jarvis_core.web import JarvisWeb

    if O.tk is None:
        return
    try:
        root = O.tk.Tk()
    except Exception:
        return

    class _Args:
        ability, max_words, retries, history_path, lang = "x", 40, 1, None, "fr"

    class _Chain:
        tools, tools_enabled = [], False

        def label(self):
            return "test"

    class _Speech:
        def begin(self): pass
        def say(self, _t): pass
        def cancel(self): pass
        def close(self): pass

    app = JarvisWeb(_Args(), STRINGS["fr"], None, _Speech(), _Chain(), [], greet=False)
    orb = O.Orb(root, app, STRINGS["fr"], fancy=True)
    try:
        orb.state = "thinking"
        orb.draw()
        assert orb.layer.size == (orb.size, orb.size)
        orb.show_bubble("Bonjour, je suis Jarvis.")
        assert orb._bubble_message == "Bonjour, je suis Jarvis."
        assert orb._bubble_layer.size[0] > 0
    finally:
        orb.close()


def test_jarvis_hud_theme_is_round_light_and_legible():
    if not orb_render.available():
        return
    renderer = orb_render.make_renderer("jarvis", 168, 42)
    assert isinstance(_inner(renderer), orb_render.HudRenderer)
    for state in ("ready", "listening", "thinking", "speaking"):
        image = renderer.frame(state, 2.0)
        assert image.size == (168, 168)
        assert image.getpixel((0, 0))[3] == 0          # coins transparents
        assert image.getpixel((84, 84))[3] > 200       # coeur lumineux
        assert image.getpixel((84, 84 - 30))[3] > 100  # ecran sombre derriere les anneaux
    # demarrage : l'orbe apparait progressivement
    booting = renderer.frame("ready", 0.05).getpixel((84, 84))[3]
    assert booting < renderer.frame("ready", 2.0).getpixel((84, 84))[3]
    assert isinstance(_inner(orb_render.make_renderer("siri", 100, 25)), orb_render.OrbRenderer)


def test_hud_rotation_cache_stays_bounded():
    if not orb_render.available():
        return
    renderer = orb_render.HudRenderer(64, 16)
    for state in ("ready", "listening", "thinking", "speaking"):
        for k in range(200):
            renderer.frame(state, k * 0.04)
    assert len({key[0] for key in renderer._rotated}) <= renderer.KEEP_STATES


def test_hud_bubble_has_header_and_wraps():
    if not orb_render.available():
        return
    short = orb_render.make_bubble("jarvis", "Oui ?")
    long = orb_render.make_bubble("jarvis", "mot " * 60)
    assert long.height > short.height
    assert short.getpixel((0, 0))[3] == 0              # coin biseaute transparent
    assert orb_render.make_bubble("siri", "Oui ?").size != short.size


def test_organic_themes_are_soft_round_shapes():
    from jarvis_core import orb_blob

    if not orb_blob.available():
        return
    for theme in ("aurore", "opale", "nebuleuse"):
        renderer = orb_render.make_renderer(theme, 168, 42)
        assert isinstance(_inner(renderer), orb_blob.BlobRenderer)
        for state in ("ready", "listening", "thinking", "speaking"):
            image = renderer.frame(state, 2.0, 0.5)
            assert image.size == (168, 168)
            assert image.getpixel((0, 0))[3] == 0         # coin transparent
            assert image.getpixel((84, 84))[3] > 230      # coeur plein
        # la forme ondule dans le temps
        assert renderer.frame("ready", 1.0).tobytes() != renderer.frame("ready", 3.0).tobytes()


def test_organic_states_change_colour_and_voice_changes_shape():
    from jarvis_core import orb_blob

    if not orb_blob.available():
        return
    renderer = orb_blob.BlobRenderer("aurore", 120, 30)
    ready = renderer.frame("ready", 2.0).getpixel((60, 60))
    thinking = renderer.frame("thinking", 2.0).getpixel((60, 60))
    assert ready[:3] != thinking[:3]
    quiet = renderer.frame("speaking", 2.0, 0.0)
    loud = renderer.frame("speaking", 2.0, 1.0)
    covered = lambda im: sum(1 for a in im.getchannel("A").getdata() if a > 128)
    assert covered(loud) > covered(quiet)        # la voix fait gonfler la forme


def test_light_bubble_for_pastel_themes():
    from jarvis_core import orb_blob

    if not orb_blob.available():
        return
    light = orb_render.make_bubble("aurore", "Bonjour")
    dark = orb_render.make_bubble("nebuleuse", "Bonjour")
    centre = (light.width // 2, light.height // 2)
    assert sum(light.getpixel(centre)[:3]) > sum(dark.getpixel((dark.width // 2,
                                                                dark.height // 2))[:3])


def test_organic_orb_is_alive():
    from jarvis_core import orb_blob

    if not orb_blob.available():
        return
    covered = lambda im: sum(1 for a in im.getchannel("A").getdata() if a > 128)
    renderer = orb_blob.BlobRenderer("opale", 120, 30)
    calm = renderer.frame("ready", 2.0)
    assert covered(renderer.frame("ready", 2.0, pulse=1.0)) > covered(calm)   # sursaut
    assert covered(renderer.frame("ready", 2.0, hover=1.0)) > covered(calm)   # survol
    # levitation : le centre de la forme bouge au fil du temps
    def centre_y(image):
        alpha = image.getchannel("A")
        rows = [y for y in range(image.height)
                if any(alpha.getpixel((x, y)) > 128 for x in range(0, image.width, 4))]
        return (rows[0] + rows[-1]) / 2
    fresh = orb_blob.BlobRenderer("opale", 120, 30)
    assert centre_y(fresh.frame("ready", 1.0)) != centre_y(fresh.frame("ready", 3.0))
    # l'ecoute reagit au volume du micro
    assert covered(renderer.frame("listening", 2.0, 1.0)) >         covered(renderer.frame("listening", 2.0, 0.0))


def test_organic_colour_changes_gradually():
    from jarvis_core import orb_blob

    if not orb_blob.available():
        return
    renderer = orb_blob.BlobRenderer("opale", 80, 20)
    renderer.frame("ready", 1.0)
    start = renderer._base.copy()
    renderer.frame("thinking", 1.04)
    step = renderer._base.copy()
    target = renderer._palette("thinking")[0]
    for _ in range(60):
        renderer.frame("thinking", 1.0)
    assert abs(step - start).sum() < abs(renderer._base - start).sum()   # glisse
    assert all(abs(a - b) < 1 for a, b in zip(renderer._base, target))  # puis arrive


def test_ultra_quality_uses_the_graphics_card_when_possible():
    from jarvis_core import orb_blob, orb_gpu

    if not orb_blob.available():
        return
    standard = orb_render.make_renderer("opale", 120, 30, quality="standard")
    assert isinstance(_inner(standard), orb_blob.BlobRenderer)
    hud = orb_render.make_renderer("jarvis", 120, 30, quality="ultra")
    assert isinstance(_inner(hud), orb_render.HudRenderer)  # le HUD reste sur le processeur
    if not orb_gpu.available():
        return                                          # pas de carte graphique (CI)
    for theme in ("opale", "plasma", "aurore", "nebuleuse"):
        renderer = orb_render.make_renderer(theme, 120, 30, quality="ultra")
        assert isinstance(renderer, orb_gpu.GpuRenderer)
        image = renderer.frame("speaking", 2.0, 0.6, pulse=0.5)
        assert image.size == (120, 120) and image.mode == "RGBA"
        assert image.getpixel((0, 0))[3] < 40           # coin (presque) transparent
        assert image.getpixel((60, 60))[3] > 200        # sphere opaque au centre
    a = renderer.frame("ready", 1.0).tobytes()
    assert a != renderer.frame("ready", 2.5).tobytes()  # anime

