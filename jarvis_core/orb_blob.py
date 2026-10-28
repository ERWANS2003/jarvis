"""Horizon 6 - orbe « organique » : une forme douce qui ondule (numpy + Pillow).

Trois declinaisons du meme style, inspire d'une goutte de verre mat :

  * ``aurore``    : cyan, bleu et lavande pastel, matiere douce ;
  * ``opale``     : nacree et irisee (rose, peche, lilas, menthe), reflet brillant ;
  * ``nebuleuse`` : indigo, violet et cyan profonds, halo lumineux (fonds sombres).

Le contour est un cercle deforme par quelques sinusoides qui derivent
lentement ; l'interieur melange des « sources » de couleur qui tournent. Les
bords s'eclaircissent (effet de verre) et un reflet doux eclaire le haut. Tout
est calcule par pixel avec numpy, a la taille finale, avec un bord anticrenele
analytique : ~2 ms par image.

Etats : la teinte glisse vers la menthe (ecoute) ou vers des tons chauds
(reflexion) ; pendant la parole, la forme se gonfle et ondule au rythme du
volume de la voix (`level`).
"""

from __future__ import annotations

import math

BLOB_THEMES = {
    "aurore": {
        "base": (118, 150, 214),
        "sources": [(90, 236, 250), (96, 132, 255), (176, 156, 250), (120, 196, 255)],
        "rim": (226, 246, 255), "rim_strength": 0.42, "shine": 0.18,
        "alpha": 0.96, "glow": 0.0, "wobble": 0.032,
        "tints": {"listening": ((96, 240, 214), 0.35), "thinking": ((206, 150, 255), 0.4)},
    },
    "opale": {
        "base": (214, 196, 232),
        "sources": [(255, 182, 206), (255, 214, 170), (186, 168, 255), (150, 236, 214)],
        "rim": (255, 250, 255), "rim_strength": 0.45, "shine": 0.2,
        "alpha": 0.97, "glow": 0.0, "wobble": 0.03,
        "tints": {"listening": ((140, 240, 200), 0.35), "thinking": ((255, 176, 140), 0.35)},
    },
    "nebuleuse": {
        "base": (34, 30, 92),
        "sources": [(110, 64, 255), (40, 200, 255), (220, 70, 220), (60, 90, 255)],
        "rim": (120, 230, 255), "rim_strength": 0.55, "shine": 0.14,
        "alpha": 0.98, "glow": 0.5, "wobble": 0.035,
        "tints": {"listening": ((40, 230, 200), 0.35), "thinking": ((240, 80, 200), 0.38)},
    },
}
# Teinte ajoutee selon l'etat (part du melange).
STATE_TINT = {"listening": ((84, 240, 190), 0.38), "thinking": ((255, 166, 96), 0.36)}
STATE_SPEED = {"ready": 0.45, "listening": 1.0, "thinking": 1.5, "speaking": 1.2}
TRANSITION = 0.12  # part du chemin vers la nouvelle teinte a chaque image (~0,3 s)


def available() -> bool:
    try:
        import numpy  # noqa: F401
        from PIL import Image  # noqa: F401
    except Exception:
        return False
    return True


class BlobRenderer:
    """Meme interface que les autres rendus : `frame(state, phase, level)`."""

    def __init__(self, theme: str = "aurore", size: int = 168, radius: int = 42):
        import numpy as np

        self.theme = theme if theme in BLOB_THEMES else "aurore"
        self.style = BLOB_THEMES[self.theme]
        self.size = int(size)
        self.radius = float(radius) * 1.08  # pas d'anneaux : la forme occupe la place
        axis = np.arange(self.size, dtype=np.float32) - (self.size - 1) / 2
        self.dx, self.dy = np.meshgrid(axis, axis)
        self.dist = np.hypot(self.dx, self.dy)
        self.angle = np.arctan2(self.dy, self.dx)
        self._base = None      # teinte courante (glisse vers celle de l'etat)
        self._sources = None

    def _palette(self, state: str):
        style = self.style
        tint = style.get("tints", STATE_TINT).get(state)
        sources = style["sources"]
        base = style["base"]
        if tint:
            color, part = tint
            sources = [tuple(a + (b - a) * part for a, b in zip(c, color)) for c in sources]
            base = tuple(a + (b - a) * part * 0.6 for a, b in zip(base, color))
        return base, sources

    def _smooth_palette(self, state: str):
        """Glisse en douceur vers la teinte de l'etat (pas de changement brusque)."""
        import numpy as np

        base, sources = self._palette(state)
        target_base = np.array(base, dtype=np.float32)
        target_sources = np.array(sources, dtype=np.float32)
        if self._base is None:
            self._base, self._sources = target_base, target_sources
        else:
            self._base += (target_base - self._base) * TRANSITION
            self._sources += (target_sources - self._sources) * TRANSITION
        return self._base, self._sources

    def frame(self, state: str, phase: float, level: float | None = None, *,
              hover: float = 0.0, pulse: float = 0.0):
        """Image RGBA de l'orbe.

        `level` : volume de la voix de Jarvis (parole) ou du micro (ecoute),
        0..1 ; `hover` : souris au-dessus (0..1) ; `pulse` : sursaut en cours
        (mot d'activation, clic, respiration spontanee), 0..1.
        """
        import numpy as np
        from PIL import Image

        state = state if state in STATE_SPEED else "ready"
        style = self.style
        t = phase * STATE_SPEED[state]
        voice = (level or 0.0) if state in ("speaking", "listening") else 0.0
        if state == "listening":
            voice *= 0.8
        scale = self.radius / 50.0

        # Levitation : la forme flotte doucement autour du centre.
        ox = 2.2 * scale * math.sin(phase * 0.55)
        oy = 3.6 * scale * math.sin(phase * 0.85 + 0.6)
        dx, dy = self.dx - ox, self.dy - oy
        dist = np.hypot(dx, dy)
        angle = np.arctan2(dy, dx)

        breathe = 1.0 + 0.025 * math.sin(phase * 1.3)
        radius = self.radius * breathe * (1.0 + 0.07 * voice + 0.10 * pulse + 0.05 * hover)
        wobble = style["wobble"] * (1.0 + 1.1 * voice + 2.5 * pulse
                                    + (0.4 if state == "thinking" else 0.0))

        # Contour : cercle deforme par des sinusoides qui derivent.
        edge = np.ones_like(angle)
        # Ondulations fines et douces (pas de lobes) : comme une goutte molle.
        for k, amp, speed, offset in ((2, 0.7, 0.45, 0.0), (3, 0.5, -0.8, 1.7),
                                      (5, 0.3, 1.1, 3.1), (7, 0.2, -1.5, 4.4)):
            edge += wobble * amp * np.sin(k * angle + speed * t + offset)
        edge *= radius
        signed = dist - edge                            # < 0 a l'interieur
        mask = np.clip(0.5 - signed / 1.15, 0.0, 1.0)   # bord anticrenele

        # Couleur : sources qui tournent et ondoient, teinte qui glisse.
        base, sources = self._smooth_palette(state)
        sigma2 = 2 * (radius * 0.62) ** 2
        weight_sum = np.full_like(dist, 0.35)
        rgb = [np.full_like(dist, 0.35 * channel) for channel in base]
        for index, color in enumerate(sources):
            a = t * (0.6 + 0.25 * index) + index * (2 * math.pi / len(sources))
            orbit = radius * (0.55 + 0.12 * math.sin(t * 0.7 + index))
            cx = orbit * math.cos(a) + radius * 0.12 * math.sin(phase * 1.7 + index * 2.3)
            cy = orbit * math.sin(a * 1.1) + radius * 0.10 * math.cos(phase * 1.3 + index)
            w = np.exp(-((dx - cx) ** 2 + (dy - cy) ** 2) / sigma2)
            weight_sum += w
            for channel in range(3):
                rgb[channel] += w * color[channel]
        rgb = [channel / weight_sum for channel in rgb]

        # Bords eclaircis (verre), reflet principal, reflet mobile, ombre en bas.
        rim = np.clip(1.0 + signed / (radius * 0.28), 0.0, 1.0) ** 2 \
            * style["rim_strength"] * (1.0 + 0.4 * pulse)
        shine = np.exp(-((dx + radius * 0.32) ** 2 + (dy + radius * 0.38) ** 2)
                       / (2 * (radius * 0.33) ** 2)) * (style["shine"] + 0.08 * hover)
        drift = phase * 0.5
        gx = -radius * 0.18 + radius * 0.30 * math.cos(drift)
        gy = -radius * 0.30 + radius * 0.14 * math.sin(drift * 1.3)
        glint = np.exp(-((dx - gx) ** 2 + (dy - gy) ** 2) / (2 * (radius * 0.16) ** 2)) \
            * style["shine"] * 0.7
        shade = np.clip(dy / radius, 0.0, 1.0) * 0.10
        out = []
        for channel in range(3):
            value = rgb[channel] * (1 - rim) + style["rim"][channel] * rim
            value = value * (1 - shade) + 255 * (shine + glint)
            out.append(np.clip(value, 0, 255))
        alpha = mask * style["alpha"] * 255

        # Halo (nebuleuse) : lueur autour de la forme.
        if style["glow"]:
            outside = np.clip(signed, 0.0, None)
            halo = np.exp(-outside / (radius * 0.16)) * style["glow"] * (1 - mask)
            halo *= 0.85 + 0.15 * math.sin(phase * 2.0) + 0.3 * voice + 0.4 * pulse
            for channel in range(3):
                out[channel] = out[channel] * mask + style["rim"][channel] * (1 - mask)
            alpha = np.clip(alpha + halo * 255, 0, 255)

        pixels = np.dstack(out + [alpha]).astype(np.uint8)
        return Image.fromarray(pixels, "RGBA")


# --------------------------------------------------------------------------- #
# Bulle claire (aurore, opale)
# --------------------------------------------------------------------------- #
LIGHT_BG = (250, 251, 255, 240)
LIGHT_TEXT = (28, 32, 44, 255)
LIGHT_DIM = (110, 116, 134, 255)


def render_light_bubble(text: str, dim: bool = False, scale: float = 1.0,
                        max_width: int = 300, max_lines: int = 12):
    """Bulle givree claire, coins tres arrondis, ombre douce."""
    from PIL import Image, ImageDraw, ImageFilter

    from .orb_render import _font, wrap

    s = max(scale, 0.5)
    font = _font(round(15 * s))
    pad_x, pad_y, radius, shadow = round(18 * s), round(12 * s), round(22 * s), round(12 * s)
    lines = wrap(text, font, round(max_width * s))
    if len(lines) > max_lines:
        lines = lines[:max_lines - 1] + [lines[max_lines - 1].rstrip() + " …"]
    ascent, descent = font.getmetrics()
    line_h = ascent + descent + round(3 * s)
    width = int(max((font.getlength(line) for line in lines), default=0) + 2 * pad_x)
    height = int(len(lines) * line_h - round(3 * s) + 2 * pad_y)
    canvas = Image.new("RGBA", (width + 2 * shadow, height + 2 * shadow), (0, 0, 0, 0))
    box = (shadow, shadow, shadow + width, shadow + height)
    shade = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(shade).rounded_rectangle((box[0], box[1] + round(4 * s), box[2],
                                             box[3] + round(4 * s)), radius,
                                            fill=(40, 50, 90, 70))
    canvas.alpha_composite(shade.filter(ImageFilter.GaussianBlur(shadow / 2)))
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle(box, radius, fill=LIGHT_BG, outline=(255, 255, 255, 255),
                           width=max(1, round(s)))
    y = shadow + pad_y
    for line in lines:
        draw.text((shadow + pad_x, y), line, font=font, fill=LIGHT_DIM if dim else LIGHT_TEXT)
        y += line_h
    return canvas


__all__ = ["BlobRenderer", "BLOB_THEMES", "available", "render_light_bubble"]
