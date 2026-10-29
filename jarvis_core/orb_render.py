"""Horizon 6 - rendu graphique de l'orbe et de sa bulle (Pillow).

Deux themes :

  * ``jarvis`` (defaut) : HUD holographique - coeur lumineux, anneaux fins
    qui tournent en sens contraires, balayage, egaliseur circulaire quand
    Jarvis parle ; bulle « panneau » aux coins biseautes ;
  * ``siri`` : sphere de verre et nuages de couleur, bulle arrondie.

Chaque image est calculee en RGBA avec une vraie transparence, en double
resolution puis reduite : bords lisses, halo qui se fond dans le bureau.

L'orbe s'inspire de Siri : une sphere de verre sombre, des nuages de couleur
qui tournent a l'interieur, un reflet en haut a gauche, un liseré lumineux et
un halo qui respire. Chaque etat a sa palette et son rythme ; pendant que
Jarvis ecoute, reflechit ou parle, un arc lumineux tourne autour.

Le module ne depend que de Pillow ; `available()` permet a l'orbe de garder
son dessin Tkinter de secours quand Pillow manque.
"""

from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path

SS = 2  # sur-echantillonnage (anticrenelage)

# (profond, principal, clair, accent) par etat.
PALETTES = {
    "ready": ("#0a1238", "#0a84ff", "#a8d4ff", "#7d5cff"),
    "listening": ("#05261a", "#30d158", "#c4f7d2", "#40c8e0"),
    "thinking": ("#341904", "#ff9f0a", "#ffe2b0", "#ff375f"),
    "speaking": ("#06243c", "#64d2ff", "#e2f6ff", "#7d5cff"),
}
# Vitesse de rotation des nuages et de l'arc, par etat.
SPEEDS = {"ready": 0.35, "listening": 1.2, "thinking": 0.9, "speaking": 1.6}

FONT_FILES = ("segoeui.ttf", "seguisb.ttf", "arial.ttf", "DejaVuSans.ttf")
BUBBLE_BG = (24, 24, 32, 246)
BUBBLE_FG = (245, 245, 247, 255)
BUBBLE_DIM = (160, 160, 172, 255)


def available() -> bool:
    try:
        import PIL  # noqa: F401
        from PIL import Image, ImageDraw, ImageFilter  # noqa: F401
    except Exception:
        return False
    return True


def _rgb(color: str) -> tuple[int, int, int]:
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


def _mix(a, b, t: float):
    t = min(max(t, 0.0), 1.0)
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


class OrbRenderer:
    """Fabrique les images de l'orbe. `size` = cote de la fenetre (pixels)."""

    def __init__(self, size: int = 168, radius: int = 42):
        self.size = int(size)
        self.radius = int(radius)
        self._frames: dict = {}
        self._state_cache: dict = {}

    # -- briques precalculees par etat ------------------------------------- #
    def _layers(self, state: str) -> dict:
        if state in self._state_cache:
            return self._state_cache[state]
        from PIL import Image, ImageDraw, ImageFilter

        deep, main, light, accent = (_rgb(c) for c in PALETTES.get(state, PALETTES["ready"]))
        big = self.size * SS
        r = self.radius * SS
        c = big / 2

        # Masque de la sphere.
        mask = Image.new("L", (big, big), 0)
        ImageDraw.Draw(mask).ellipse((c - r, c - r, c + r, c + r), fill=255)

        # Halo exterieur (respire a chaque image).
        glow = Image.new("RGBA", (big, big), (0, 0, 0, 0))
        g = r * 1.22
        ImageDraw.Draw(glow).ellipse((c - g, c - g, c + g, c + g), fill=main + (205,))
        glow = glow.filter(ImageFilter.GaussianBlur(r * 0.34))

        # Corps de verre : degrade radial, plus clair vers le haut a gauche.
        body = Image.new("RGBA", (big, big), (0, 0, 0, 0))
        draw = ImageDraw.Draw(body)
        steps = 48
        for i in range(steps):
            t = i / (steps - 1)
            rr = r * (1.0 - 0.9 * t)
            shift = r * 0.22 * t
            color = _mix(deep, _mix(deep, main, 0.75), t ** 1.3)
            draw.ellipse((c - shift - rr, c - shift - rr, c - shift + rr, c - shift + rr),
                         fill=color + (255,))
        body = body.filter(ImageFilter.GaussianBlur(r * 0.06))

        # Nuages de couleur qui tourneront a l'interieur.
        def blob(color, scale, alpha):
            sprite_r = r * scale
            side = int(sprite_r * 3)
            sprite = Image.new("RGBA", (side, side), (0, 0, 0, 0))
            m = side / 2
            ImageDraw.Draw(sprite).ellipse((m - sprite_r, m - sprite_r, m + sprite_r, m + sprite_r),
                                           fill=color + (alpha,))
            return sprite.filter(ImageFilter.GaussianBlur(sprite_r * 0.45))

        blobs = [blob(main, 0.72, 235), blob(accent, 0.58, 215), blob(light, 0.38, 185)]

        # Reflet (haut gauche) et point speculaire.
        shine = Image.new("RGBA", (big, big), (0, 0, 0, 0))
        sd = ImageDraw.Draw(shine)
        sd.ellipse((c - r * 0.72, c - r * 0.86, c + r * 0.18, c - r * 0.22),
                   fill=(255, 255, 255, 95))
        shine = shine.filter(ImageFilter.GaussianBlur(r * 0.12))
        spot = Image.new("RGBA", (big, big), (0, 0, 0, 0))
        ImageDraw.Draw(spot).ellipse((c - r * 0.48, c - r * 0.62, c - r * 0.22, c - r * 0.44),
                                     fill=(255, 255, 255, 200))
        shine.alpha_composite(spot.filter(ImageFilter.GaussianBlur(r * 0.04)))

        # Liseré lumineux.
        rim = Image.new("RGBA", (big, big), (0, 0, 0, 0))
        ImageDraw.Draw(rim).ellipse((c - r, c - r, c + r, c + r), outline=light + (120,),
                                    width=max(2, SS * 2))
        rim = rim.filter(ImageFilter.GaussianBlur(SS * 0.8))

        layers = {"mask": mask, "glow": glow, "body": body, "blobs": blobs,
                  "shine": shine, "rim": rim, "light": light, "main": main}
        self._state_cache[state] = layers
        return layers

    # -- une image ------------------------------------------------------------ #
    def frame(self, state: str, phase: float, level: float | None = None, **_):
        """Image RGBA (taille `size`) de l'orbe dans `state` au temps `phase`.

        `level` (volume de la voix, 0..1) amplifie le halo pendant la parole.
        """
        from PIL import Image, ImageChops, ImageDraw, ImageFilter

        state = state if state in PALETTES else "ready"
        key = (state, round(phase * 25) % 2000)
        if key in self._frames:
            return self._frames[key]

        layers = self._layers(state)
        big = self.size * SS
        r = self.radius * SS
        c = big / 2
        busy = state != "ready"
        speed = SPEEDS[state]

        out = Image.new("RGBA", (big, big), (0, 0, 0, 0))

        # Halo qui respire.
        breathe = 0.62 + 0.30 * math.sin(phase * (2.2 if busy else 1.1))
        if level is not None and state == "speaking":
            breathe = 0.55 + 0.45 * level
        alpha = layers["glow"].getchannel("A").point(lambda v: int(v * breathe))
        glow = layers["glow"].copy()
        glow.putalpha(alpha)
        out.alpha_composite(glow)

        # Sphere : corps + nuages tournants, decoupes au masque.
        sphere = layers["body"].copy()
        for index, sprite in enumerate(layers["blobs"]):
            angle = phase * speed * (1.0 + 0.35 * index) + index * 2.1
            orbit = r * (0.38 - 0.08 * index)
            x = c + orbit * math.cos(angle) - sprite.width / 2
            y = c + orbit * math.sin(angle * 1.13) - sprite.height / 2
            sphere.alpha_composite(sprite, (int(x), int(y)))
        sphere.alpha_composite(layers["shine"])
        sphere.putalpha(ImageChops.multiply(sphere.getchannel("A"), layers["mask"]))
        out.alpha_composite(sphere)
        out.alpha_composite(layers["rim"])

        # Arc lumineux pendant une activite.
        if busy:
            arc = Image.new("RGBA", (big, big), (0, 0, 0, 0))
            ad = ImageDraw.Draw(arc)
            ar = r + 9 * SS
            start = math.degrees(phase * speed * 2.2) % 360
            box = (c - ar, c - ar, c + ar, c + ar)
            ad.arc(box, start=start, end=start + 110, fill=layers["light"] + (255,), width=3 * SS)
            ad.arc(box, start=start + 180, end=start + 235, fill=layers["main"] + (230,),
                   width=2 * SS)
            glow_arc = arc.filter(ImageFilter.GaussianBlur(3 * SS))
            out.alpha_composite(glow_arc)
            out.alpha_composite(arc)

        image = out.resize((self.size, self.size), Image.LANCZOS)
        if len(self._frames) > 60:
            self._frames.clear()
        self._frames[key] = image
        return image


# --------------------------------------------------------------------------- #
# Bulle
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=8)
def _font(px: int, bold: bool = False):
    from PIL import ImageFont

    names = ("seguisb.ttf", "segoeui.ttf") if bold else FONT_FILES
    for name in names:
        for folder in (Path("C:/Windows/Fonts"), Path("/usr/share/fonts/truetype/dejavu")):
            path = folder / name
            if path.is_file():
                return ImageFont.truetype(str(path), px)
    return ImageFont.load_default()


def wrap(text: str, font, max_width: int) -> list[str]:
    """Coupe le texte en lignes d'au plus `max_width` pixels."""
    lines: list[str] = []
    for paragraph in (text or "").split("\n"):
        line = ""
        for word in paragraph.split():
            candidate = f"{line} {word}".strip()
            if line and font.getlength(candidate) > max_width:
                lines.append(line)
                line = word
            else:
                line = candidate
        lines.append(line)
    return lines or [""]


def render_bubble(text: str, dim: bool = False, scale: float = 1.0,
                  max_width: int = 300, max_lines: int = 12):
    """Bulle arrondie (verre fumé, ombre douce) contenant `text`."""
    from PIL import Image, ImageDraw, ImageFilter

    s = max(scale, 0.5)
    font = _font(round(15 * s))
    pad_x, pad_y, radius, shadow = round(16 * s), round(11 * s), round(18 * s), round(10 * s)
    lines = wrap(text, font, round(max_width * s))
    if len(lines) > max_lines:
        lines = lines[:max_lines - 1] + [lines[max_lines - 1].rstrip() + " …"]
    ascent, descent = font.getmetrics()
    line_h = ascent + descent + round(3 * s)
    text_w = max((font.getlength(line) for line in lines), default=0)
    width = int(text_w + 2 * pad_x)
    height = int(len(lines) * line_h - round(3 * s) + 2 * pad_y)

    canvas = Image.new("RGBA", (width + 2 * shadow, height + 2 * shadow), (0, 0, 0, 0))
    box = (shadow, shadow, shadow + width, shadow + height)
    shade = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(shade).rounded_rectangle((box[0], box[1] + round(3 * s), box[2], box[3] + round(3 * s)),
                                            radius, fill=(0, 0, 0, 130))
    canvas.alpha_composite(shade.filter(ImageFilter.GaussianBlur(shadow / 2)))
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle(box, radius, fill=BUBBLE_BG,
                           outline=(255, 255, 255, 34), width=max(1, round(s)))
    color = BUBBLE_DIM if dim else BUBBLE_FG
    y = shadow + pad_y
    for line in lines:
        draw.text((shadow + pad_x, y), line, font=font, fill=color)
        y += line_h
    return canvas


# --------------------------------------------------------------------------- #
# Theme « jarvis » : HUD holographique
# --------------------------------------------------------------------------- #
# (principal, secondaire, coeur) par etat.
HUD_PALETTES = {
    "ready": ("#1ec8ff", "#0a5cff", "#e8fbff"),
    "listening": ("#3cf5c8", "#1ec8ff", "#f0fffb"),
    "thinking": ("#ffb238", "#ff6a18", "#fff1d6"),
    "speaking": ("#4fdcff", "#1e8fff", "#ffffff"),
}
HUD_SPEEDS = {"ready": 1.0, "listening": 1.8, "thinking": 3.2, "speaking": 2.0}
BOOT_SECONDS = 1.1


class HudRenderer:
    """Orbe facon interface holographique. Meme interface que `OrbRenderer`.

    Pour rester leger (~25 images/s), chaque anneau est dessine une fois en
    double resolution, puis chaque angle utile est calcule a la demande et
    garde : les anneaux sont symetriques (graduations tous les 5 degres,
    tirets tous les 15...), il suffit donc de peu de positions par anneau.
    Une image ne fait ensuite que superposer des calques deja prets.
    """

    # nom -> (periode de symetrie en degres, nombre de positions gardees)
    ROTATIONS = {"ticks": (5.0, 6), "dashes": (15.0, 10), "segments": (120.0, 40),
                 "scanner": (360.0, 90)}
    KEEP_STATES = 2  # angles gardes pour l'etat courant et le precedent (~30 Mo)

    def __init__(self, size: int = 168, radius: int = 42):
        self.size = int(size)
        self.radius = int(radius)
        self._frames: dict = {}
        self._state_cache: dict = {}
        self._rotated: dict = {}

    def _ring_sprite(self, draw_fn, glow: float):
        """Anneau dessine par `draw_fn` (double resolution), avec son halo."""
        from PIL import Image, ImageDraw, ImageFilter

        big = self.size * SS
        sprite = Image.new("RGBA", (big, big), (0, 0, 0, 0))
        draw_fn(ImageDraw.Draw(sprite), big / 2, self.radius * SS)
        halo = sprite.filter(ImageFilter.GaussianBlur(glow * SS))
        halo.alpha_composite(sprite)
        return halo

    def _small(self, image):
        from PIL import Image

        return image.resize((self.size, self.size), Image.LANCZOS)

    def _layers(self, state: str) -> dict:
        if state in self._state_cache:
            return self._state_cache[state]
        from PIL import Image, ImageDraw, ImageFilter

        main, second, core = (_rgb(c) for c in HUD_PALETTES.get(state, HUD_PALETTES["ready"]))
        big = self.size * SS
        r = self.radius * SS
        c = big / 2

        # Ecran holographique : disque sombre translucide (lisible sur un
        # bureau clair) puis halo colore.
        backdrop = Image.new("RGBA", (big, big), (0, 0, 0, 0))
        b = r * 1.16
        ImageDraw.Draw(backdrop).ellipse((c - b, c - b, c + b, c + b), fill=(4, 12, 24, 150))
        backdrop = backdrop.filter(ImageFilter.GaussianBlur(r * 0.1))
        glow = Image.new("RGBA", (big, big), (0, 0, 0, 0))
        g = r * 0.95
        ImageDraw.Draw(glow).ellipse((c - g, c - g, c + g, c + g), fill=second + (120,))
        glow = glow.filter(ImageFilter.GaussianBlur(r * 0.45))

        # Coeur : disque lumineux, blanc au centre.
        heart = Image.new("RGBA", (big, big), (0, 0, 0, 0))
        hd = ImageDraw.Draw(heart)
        steps = 30
        for i in range(steps):
            t = i / (steps - 1)
            rr = r * 0.46 * (1 - 0.85 * t)
            color = _mix(second, _mix(main, core, 0.6), t) if t < 0.7 else _mix(main, core, t)
            hd.ellipse((c - rr, c - rr, c + rr, c + rr), fill=color + (int(120 + 135 * t),))
        heart = heart.filter(ImageFilter.GaussianBlur(r * 0.05))
        core_glow = Image.new("RGBA", (big, big), (0, 0, 0, 0))
        cg = r * 0.5
        ImageDraw.Draw(core_glow).ellipse((c - cg, c - cg, c + cg, c + cg), fill=main + (200,))
        core_glow = core_glow.filter(ImageFilter.GaussianBlur(r * 0.22))
        core_glow.alpha_composite(heart)

        def ticks(d, cx, rad):
            outer, count = rad * 0.98, 72
            for k in range(count):
                a = 2 * math.pi * k / count
                inner = outer - (rad * 0.13 if k % 6 == 0 else rad * 0.06)
                d.line((cx + inner * math.cos(a), cx + inner * math.sin(a),
                        cx + outer * math.cos(a), cx + outer * math.sin(a)),
                       fill=main + (210 if k % 6 == 0 else 130,), width=SS)

        def segments(d, cx, rad):
            rr = rad * 0.76
            box = (cx - rr, cx - rr, cx + rr, cx + rr)
            for begin in (0, 120, 240):
                d.arc(box, start=begin, end=begin + 78, fill=main + (240,), width=3 * SS)
            ri = rad * 0.68
            for begin in (40, 160, 280):
                d.arc((cx - ri, cx - ri, cx + ri, cx + ri), start=begin, end=begin + 26,
                      fill=core + (210,), width=SS)

        def dashes(d, cx, rad):
            rr = rad * 0.58
            box = (cx - rr, cx - rr, cx + rr, cx + rr)
            for k in range(24):
                d.arc(box, start=k * 15, end=k * 15 + 7, fill=main + (160,), width=SS * 2)

        def scanner(d, cx, rad):
            rr = rad * 1.1
            d.ellipse((cx - rr, cx - rr, cx + rr, cx + rr), outline=main + (90,), width=SS)
            d.arc((cx - rr, cx - rr, cx + rr, cx + rr), start=0, end=38,
                  fill=core + (255,), width=3 * SS)
            d.arc((cx - rr, cx - rr, cx + rr, cx + rr), start=180, end=196,
                  fill=main + (220,), width=2 * SS)

        layers = {
            "backdrop": self._small(backdrop), "glow": self._small(glow),
            "core": self._small(core_glow),
            "sprites": {"ticks": self._ring_sprite(ticks, 1.5),
                        "segments": self._ring_sprite(segments, 2.5),
                        "dashes": self._ring_sprite(dashes, 1.5),
                        "scanner": self._ring_sprite(scanner, 3.0)},
            "main": main, "core_rgb": core,
        }
        self._state_cache[state] = layers
        return layers

    def _ring(self, state: str, name: str, angle: float):
        """Anneau `name` tourne de `angle` degres (calcule une seule fois)."""
        from PIL import Image

        period, steps = self.ROTATIONS[name]
        index = round((angle % period) / period * steps) % steps
        key = (state, name, index)
        image = self._rotated.get(key)
        if image is None:
            states = list(dict.fromkeys(k[0] for k in self._rotated))
            if state not in states and len(states) >= self.KEEP_STATES:
                oldest = states[0]
                self._rotated = {k: v for k, v in self._rotated.items() if k[0] != oldest}
            sprite = self._layers(state)["sprites"][name]
            image = self._small(sprite.rotate(index * period / steps, resample=Image.BICUBIC))
            self._rotated[key] = image
        return image

    @staticmethod
    def _faded(image, factor: float):
        faded = image.copy()
        faded.putalpha(faded.getchannel("A").point(lambda v: int(v * factor)))
        return faded

    def frame(self, state: str, phase: float, level: float | None = None, **_):
        """`level` (volume de la voix, 0..1) pilote l'egaliseur et le coeur."""
        from PIL import Image, ImageDraw, ImageFilter

        state = state if state in HUD_PALETTES else "ready"
        if state != "speaking":
            level = None
        key = (state, round(phase * 25) % 2000,
               None if level is None else round(level * 12))
        if key in self._frames:
            return self._frames[key]
        layers = self._layers(state)
        size = self.size
        r = self.radius
        c = size / 2
        speed = HUD_SPEEDS[state]
        out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        out.alpha_composite(layers["backdrop"])
        breathe = 0.7 + 0.3 * math.sin(phase * (3.0 if state != "ready" else 1.4))
        out.alpha_composite(self._faded(layers["glow"], breathe))

        # Ondes qui s'eloignent pendant l'ecoute (dessinees en double resolution).
        if state == "listening":
            big = size * SS
            ripples = Image.new("RGBA", (big, big), (0, 0, 0, 0))
            rd = ImageDraw.Draw(ripples)
            for offset in (0.0, 0.5):
                t = (phase * 0.9 + offset) % 1.0
                rr = r * SS * (0.9 + 0.45 * t)
                rd.ellipse((big / 2 - rr, big / 2 - rr, big / 2 + rr, big / 2 + rr),
                           outline=layers["main"] + (int(230 * (1 - t)),), width=2 * SS)
            small = self._small(ripples)
            out.alpha_composite(small.filter(ImageFilter.GaussianBlur(1)))
            out.alpha_composite(small)

        out.alpha_composite(self._ring(state, "ticks", phase * 8 * speed))
        out.alpha_composite(self._ring(state, "dashes", phase * 25 * speed))
        out.alpha_composite(self._ring(state, "segments", -phase * 40 * speed))
        out.alpha_composite(self._ring(state, "scanner", -phase * 90 * speed))

        # Egaliseur circulaire pendant la parole.
        if state == "speaking":
            big = size * SS
            bars = Image.new("RGBA", (big, big), (0, 0, 0, 0))
            bd = ImageDraw.Draw(bars)
            cb = big / 2
            for k in range(48):
                a = 2 * math.pi * k / 48
                wave = (math.sin(phase * 9 + k * 0.7) + math.sin(phase * 5.3 + k * 1.9)) / 2
                if level is None:  # moteur sans mesure : animation reguliere
                    length = r * SS * (0.05 + 0.2 * max(0.0, wave))
                else:              # suit le volume reel de la voix
                    length = r * SS * (0.03 + 0.34 * level * (0.55 + 0.45 * (wave + 1) / 2))
                inner = r * SS * 1.17
                bd.line((cb + inner * math.cos(a), cb + inner * math.sin(a),
                         cb + (inner + length) * math.cos(a),
                         cb + (inner + length) * math.sin(a)),
                        fill=layers["core_rgb"] + (235,), width=2 * SS)
            small = self._small(bars)
            out.alpha_composite(small.filter(ImageFilter.GaussianBlur(1.2)))
            out.alpha_composite(small)

        pulse = 0.85 + 0.15 * math.sin(phase * (6.0 if state == "thinking" else 2.0))
        if level is not None:
            pulse = 0.75 + 0.25 * level
        out.alpha_composite(self._faded(layers["core"], pulse))

        # Demarrage : les anneaux se deploient depuis le centre.
        if phase < BOOT_SECONDS:
            t = max(phase / BOOT_SECONDS, 0.01)
            ease = 1 - (1 - t) ** 3
            scaled = out.resize((max(1, int(size * ease)),) * 2, Image.LANCZOS)
            out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            out.alpha_composite(scaled, ((size - scaled.width) // 2,) * 2)
            out = self._faded(out, min(1.0, t * 1.4))

        if len(self._frames) > 60:
            self._frames.clear()
        self._frames[key] = out
        return out


HUD_BG = (6, 16, 30, 246)
HUD_BORDER = (30, 200, 255, 190)
HUD_TEXT = (222, 246, 255, 255)
HUD_DIM = (120, 170, 196, 255)


def render_hud_bubble(text: str, dim: bool = False, scale: float = 1.0,
                      max_width: int = 300, max_lines: int = 12, title: str = "JARVIS"):
    """Panneau HUD : coins biseautes, bordure cyan lumineuse, en-tete."""
    from PIL import Image, ImageDraw, ImageFilter

    s = max(scale, 0.5)
    font = _font(round(15 * s))
    small = _font(round(10 * s), bold=True)
    pad_x, pad_y, cut, margin = round(16 * s), round(10 * s), round(12 * s), round(10 * s)
    lines = wrap(text, font, round(max_width * s))
    if len(lines) > max_lines:
        lines = lines[:max_lines - 1] + [lines[max_lines - 1].rstrip() + " …"]
    ascent, descent = font.getmetrics()
    line_h = ascent + descent + round(3 * s)
    header_h = round(18 * s)
    spaced = " ".join(title)
    text_w = max([font.getlength(line) for line in lines] + [small.getlength(spaced) + 20 * s])
    width = int(text_w + 2 * pad_x)
    height = int(header_h + len(lines) * line_h - round(3 * s) + 2 * pad_y)

    canvas = Image.new("RGBA", (width + 2 * margin, height + 2 * margin), (0, 0, 0, 0))
    x0, y0, x1, y1 = margin, margin, margin + width, margin + height
    shape = [(x0 + cut, y0), (x1, y0), (x1, y1 - cut), (x1 - cut, y1), (x0, y1), (x0, y0 + cut)]

    glow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(glow).line(shape + [shape[0]], fill=HUD_BORDER[:3] + (150,),
                              width=round(3 * s))
    canvas.alpha_composite(glow.filter(ImageFilter.GaussianBlur(5 * s)))
    draw = ImageDraw.Draw(canvas)
    draw.polygon(shape, fill=HUD_BG)
    draw.line(shape + [shape[0]], fill=HUD_BORDER, width=max(1, round(1.2 * s)))
    # Equerres plus lumineuses aux deux coins droits.
    arm = round(14 * s)
    bright = HUD_BORDER[:3] + (255,)
    w2 = max(2, round(2 * s))
    draw.line([(x1 - arm, y0), (x1, y0), (x1, y0 + arm)], fill=bright, width=w2)
    draw.line([(x0, y1 - arm), (x0, y1), (x0 + arm, y1)], fill=bright, width=w2)

    # En-tete : point lumineux, titre espace, filet.
    hy = y0 + pad_y
    dot = round(3 * s)
    draw.ellipse((x0 + pad_x, hy + dot, x0 + pad_x + 2 * dot, hy + 3 * dot), fill=bright)
    draw.text((x0 + pad_x + 4 * dot, hy), spaced, font=small, fill=HUD_BORDER[:3] + (235,))
    ly = hy + header_h - round(5 * s)
    draw.line([(x0 + pad_x, ly), (x1 - pad_x, ly)], fill=HUD_BORDER[:3] + (70,), width=1)

    color = HUD_DIM if dim else HUD_TEXT
    y = hy + header_h
    for line in lines:
        draw.text((x0 + pad_x, y), line, font=font, fill=color)
        y += line_h
    return canvas


from . import orb_themes as _catalog  # noqa: E402

THEMES = ("opale", "plasma", "aurore", "nebuleuse", "jarvis", "siri") + tuple(_catalog.CATALOG)
LIGHT_BUBBLE_THEMES = ("aurore", "opale") + _catalog.LIGHT


def glass_overlay(size: int, radius: float):
    """Coque de verre (RGBA) a poser sur une orbe dessinee par le processeur."""
    from PIL import Image, ImageChops, ImageDraw, ImageFilter

    k = 3
    big, r, c = size * k, radius * 1.14 * k, size * k / 2
    shell = Image.new("L", (big, big), 0)
    ImageDraw.Draw(shell).ellipse((c - r, c - r, c + r, c + r), fill=255)
    inner = Image.new("L", (big, big), 0)
    ImageDraw.Draw(inner).ellipse((c - r * 0.86, c - r * 0.86, c + r * 0.86, c + r * 0.86), fill=255)
    rim = ImageChops.subtract(shell, inner.filter(ImageFilter.GaussianBlur(r * 0.09)))
    alpha = rim.point(lambda v: int(v * 0.55))
    spots = Image.new("L", (big, big), 0)
    draw = ImageDraw.Draw(spots)
    draw.ellipse((c - r * 0.62, c - r * 0.72, c - r * 0.14, c - r * 0.42), fill=150)   # fenetre
    draw.arc((c - r * 0.9, c - r * 0.9, c + r * 0.9, c + r * 0.9), 200, 290,
             fill=120, width=int(r * 0.05))                                           # croissant
    spots = spots.filter(ImageFilter.GaussianBlur(r * 0.04))
    alpha = ImageChops.lighter(alpha, ImageChops.multiply(spots, shell))
    layer = Image.new("RGBA", (big, big), (255, 255, 255, 0))
    layer.putalpha(alpha)
    return layer.resize((size, size), Image.LANCZOS)


class GlassRenderer:
    """Ajoute la coque de verre a un rendu processeur (meme interface)."""

    def __init__(self, inner, size: int, radius: float):
        self.inner = inner
        self.glass = 1.0
        self._overlay = glass_overlay(size, radius)

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def frame(self, *args, **kwargs):
        image = self.inner.frame(*args, **kwargs)
        if self.glass and image is not None and image.size == self._overlay.size:
            image = image.convert("RGBA")
            image.alpha_composite(self._overlay)
        return image


def make_renderer(theme: str, size: int, radius: int, quality: str = "standard",
                  glass: bool = True):
    renderer = _make_renderer(theme, size, radius, quality)
    if type(renderer).__name__ == "GpuRenderer":
        renderer.glass = 1.0 if glass else 0.0
        return renderer
    return GlassRenderer(renderer, size, radius) if glass else renderer


def _make_renderer(theme: str, size: int, radius: int, quality: str = "standard"):
    """Rendu de l'orbe. `quality="ultra"` : carte graphique (3D, OpenGL) pour
    les themes organiques, avec repli automatique sur le processeur."""
    from . import orb_blob

    if quality == "ultra":
        from . import orb_gpu

        if theme in orb_gpu.GPU_THEMES and orb_gpu.available():
            try:
                return orb_gpu.GpuRenderer(theme, size, radius)
            except Exception as exc:
                from .text import log

                log(f"[orbe] rendu ultra impossible ({exc}) : rendu standard")

    if theme == "plasma" and orb_blob.available():
        return orb_blob.PlasmaRenderer(size, radius)
    if theme in orb_blob.BLOB_THEMES and orb_blob.available():
        return orb_blob.BlobRenderer(theme, size, radius)
    return OrbRenderer(size, radius) if theme == "siri" else HudRenderer(size, radius)


def make_bubble(theme: str, text: str, dim: bool = False, scale: float = 1.0):
    if theme in LIGHT_BUBBLE_THEMES:
        from .orb_blob import render_light_bubble

        return render_light_bubble(text, dim=dim, scale=scale)
    if theme in ("siri", "nebuleuse", "plasma") or theme in _catalog.CATALOG:
        return render_bubble(text, dim=dim, scale=scale)
    return render_hud_bubble(text, dim=dim, scale=scale)


__all__ = ["available", "OrbRenderer", "HudRenderer", "render_bubble",
           "render_hud_bubble", "wrap", "PALETTES", "HUD_PALETTES", "THEMES",
           "make_renderer", "make_bubble", "glass_overlay", "GlassRenderer"]
