"""Intros de demarrage : une courte animation discrete autour de l'orbe.

Sept styles au choix (menu de l'orbe -> Réglages -> Intro), plus « Aucune » :

  anneaux        anneaux HUD qui tournent puis se referment sur l'orbe
  onde           trois ondes qui partent de l'orbe et s'effacent
  constellation  des particules qui tourbillonnent et convergent
  radar          un balayage radar qui fait un tour, puis un eclair
  eclosion       des petales de lumiere qui s'ouvrent et se referment
  terminal       une petite console qui verifie les systemes
  minimal        « JARVIS » qui apparait lettre a lettre sous l'orbe

Pas de voile plein ecran : l'animation est dessinee sur une fenetre
transparente (alpha par pixel) centree sur l'orbe, en ~2,6 s, puis Jarvis
dit « Tous les systemes sont operationnels » avec son briefing.
"""

from __future__ import annotations

import math
import random
import time

DURATION = 2.6
FADE = 0.45
SUPERSAMPLE = 2
STYLES = ("anneaux", "onde", "constellation", "radar", "eclosion", "terminal", "minimal")
DEFAULT_STYLE = "anneaux"
LABELS = {
    "fr": {"anneaux": "Anneaux HUD", "onde": "Onde", "constellation": "Constellation",
           "radar": "Radar", "eclosion": "Éclosion", "terminal": "Terminal",
           "minimal": "Minimal", "aucune": "Aucune"},
    "en": {"anneaux": "HUD rings", "onde": "Wave", "constellation": "Constellation",
           "radar": "Radar", "eclosion": "Bloom", "terminal": "Terminal",
           "minimal": "Minimal", "aucune": "None"},
}
OPERATIONAL = {"fr": "Tous les systèmes sont opérationnels.",
               "en": "All systems are operational."}


def system_lines(lang: str, tools: int, model: str, voice: str, wake: bool) -> list[str]:
    """Lignes de la console (style « terminal »)."""
    fr = lang == "fr"
    model = (model or "").split("/")[-1].replace(":free", "")[:22]
    return [
        "> " + ("voix" if fr else "voice") + f" ......... {voice or 'ok'}",
        "> " + ("modèle" if fr else "model") + f" ........ {model or 'ok'}",
        "> " + ("outils" if fr else "tools") + f" ........ {tools}",
        "> " + ("mémoire" if fr else "memory") + " ....... ok",
        "> " + ("réveil" if fr else "wake word") + " ........ " + ("« jarvis »" if wake else "—"),
        "> " + ("en ligne" if fr else "online"),
    ]


def _rgb(hex_color: str):
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))


def _font(size: int, mono: bool = False):
    from PIL import ImageFont

    for name in (("consola.ttf", "cour.ttf") if mono else ("segoeuib.ttf", "segoeui.ttf")):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _ease(x: float) -> float:
    x = min(max(x, 0.0), 1.0)
    return 1 - (1 - x) ** 3


class Painter:
    """Dessine une image RGBA de l'intro `style` au temps `t` (pure, testable)."""

    def __init__(self, style: str, size: int, orb: int, accent: str, lang: str = "fr",
                 lines: list[str] | None = None):
        self.style = style if style in STYLES else DEFAULT_STYLE
        self.size = int(size)
        self.orb = int(orb)
        self.accent = _rgb(accent)
        self.lang = "fr" if lang == "fr" else "en"
        self.lines = lines or []
        rng = random.Random(7)
        self.particles = [(rng.uniform(0, 2 * math.pi), rng.uniform(0.55, 1.0),
                           rng.uniform(0.6, 1.4), rng.uniform(1.0, 2.4)) for _ in range(90)]

    def frame(self, t: float):
        from PIL import Image, ImageDraw

        k = SUPERSAMPLE
        big = self.size * k
        image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        fade = min(1.0, t / 0.25) * min(1.0, max(0.0, (DURATION - t) / FADE))
        getattr(self, "_" + self.style)(draw, t, big / 2, big / 2, k, fade)
        return image.resize((self.size, self.size), Image.LANCZOS)

    def _col(self, alpha: float, light: float = 0.0):
        r, g, b = (int(c + (255 - c) * light) for c in self.accent)
        return (r, g, b, int(255 * max(0.0, min(1.0, alpha))))

    # -- styles -------------------------------------------------------------- #
    def _anneaux(self, d, t, cx, cy, k, fade):
        base = self.orb * k * 0.62
        open_ = _ease(t / 0.8) * (1 - _ease((t - 1.7) / 0.8))
        for i, (scale, speed, extent, width) in enumerate(
                ((1.25, 140, 250, 3), (1.5, -90, 170, 2), (1.8, 60, 110, 5), (2.1, -40, 280, 1))):
            r = base * (1 + (scale - 1) * open_)
            start = (t * speed + i * 60) % 360
            d.arc((cx - r, cy - r, cx + r, cy + r), start, start + extent,
                  fill=self._col(fade * 0.9, 0.2 * i), width=width * k)
        r = base * (1 + 1.25 * open_)
        for n in range(60):
            a = math.radians(n * 6 + t * 30)
            inner = r - (7 if n % 5 == 0 else 3) * k
            d.line((cx + inner * math.cos(a), cy + inner * math.sin(a),
                    cx + r * math.cos(a), cy + r * math.sin(a)), fill=self._col(fade * 0.6), width=k)
        self._caption(d, cx, cy + base * 2.35, fade * open_, "JARVIS · EN LIGNE"
                      if self.lang == "fr" else "JARVIS · ONLINE", k)

    def _onde(self, d, t, cx, cy, k, fade):
        base = self.orb * k * 0.6
        for i in range(3):
            x = (t - i * 0.35) / 1.6
            if 0 < x < 1:
                r = base * (1 + 1.6 * _ease(x))
                d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=self._col(fade * (1 - x)),
                          width=max(1, int((4 - 3 * x) * k)))

    def _constellation(self, d, t, cx, cy, k, fade):
        base = self.orb * k * 0.6
        gather = _ease(t / 2.0)
        for angle, dist, speed, size in self.particles:
            a = angle + t * speed * 2.2
            r = base * (0.9 + 2.3 * dist * (1 - gather))
            x, y = cx + r * math.cos(a), cy + r * math.sin(a)
            s = size * k
            d.ellipse((x - s, y - s, x + s, y + s), fill=self._col(fade * (0.4 + 0.6 * gather), 0.4))
        if gather > 0.85:
            glow = (gather - 0.85) / 0.15
            r = base * (1 + 0.25 * glow)
            d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=self._col(fade * glow, 0.5),
                      width=2 * k)

    def _radar(self, d, t, cx, cy, k, fade):
        r = self.orb * k * 1.35
        d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=self._col(fade * 0.5), width=k)
        r2 = r * 0.72
        d.ellipse((cx - r2, cy - r2, cx + r2, cy + r2), outline=self._col(fade * 0.25), width=k)
        sweep = min(1.0, t / 1.8) * 360 - 90
        for step in range(24):                                 # traine du balayage
            alpha = fade * (1 - step / 24) * 0.35
            d.pieslice((cx - r, cy - r, cx + r, cy + r), sweep - (step + 1) * 3, sweep - step * 3,
                       fill=self._col(alpha))
        a = math.radians(sweep)
        d.line((cx, cy, cx + r * math.cos(a), cy + r * math.sin(a)),
               fill=self._col(fade, 0.3), width=2 * k)
        if t > 1.8:
            x = (t - 1.8) / 0.6
            rr = r * (0.6 + 0.6 * x)
            d.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), outline=self._col(fade * (1 - x), 0.6),
                      width=3 * k)

    def _eclosion(self, d, t, cx, cy, k, fade):
        bloom = _ease(t / 1.0) * (1 - _ease((t - 1.6) / 0.9))
        length = self.orb * k * (0.32 + 0.38 * bloom)         # demi-grand axe
        width = self.orb * k * 0.12 * (0.4 + bloom)            # demi-petit axe
        steps = [i * 2 * math.pi / 48 for i in range(49)]
        for n in range(8):
            angle = math.radians(n * 45 + t * 25)
            ca, sa = math.cos(angle), math.sin(angle)
            points = []
            for u in steps:                                    # ellipse partant du centre
                x, y = length * (1 + math.cos(u)), width * math.sin(u)
                points.append((cx + x * ca - y * sa, cy + x * sa + y * ca))
            d.line(points, fill=self._col(fade * 0.8, 0.15 * (n % 3)), width=2 * k, joint="curve")

    def _terminal(self, d, t, cx, cy, k, fade):
        font = _font(10 * k, mono=True)
        step = 13 * k
        w = self.size * k * 0.92
        h = len(self.lines) * step + 16 * k
        x0, y0 = cx - w / 2, max(4 * k, cy - self.orb * k * 0.62 - h)   # au-dessus de l'orbe
        d.rounded_rectangle((x0, y0, x0 + w, y0 + h), radius=8 * k,
                            fill=(8, 12, 20, int(190 * fade)), outline=self._col(fade * 0.6), width=k)
        shown = t / 2.0 * len(self.lines)
        for i, line in enumerate(self.lines):
            part = shown - i
            if part <= 0:
                break
            text = line[: int(len(line) * min(1.0, part * 1.5))]
            d.text((x0 + 10 * k, y0 + 8 * k + i * step), text, font=font,
                   fill=self._col(fade, 0.55 if i < len(self.lines) - 1 else 0.0))

    def _minimal(self, d, t, cx, cy, k, fade):
        word = "J A R V I S"
        letters = int(_ease(t / 1.4) * len(word) + 0.5)
        y = cy + self.orb * k * 0.95
        self._caption(d, cx, y, fade, word[:letters], k, size=18)
        span = self.orb * k * 1.4 * _ease(t / 1.6)
        d.line((cx - span / 2, y + 22 * k, cx + span / 2, y + 22 * k),
               fill=self._col(fade * 0.8), width=k)

    def _caption(self, d, cx, y, alpha, text, k, size=11):
        if not text or alpha <= 0:
            return
        font = _font(size * k)
        box = d.textbbox((0, 0), text, font=font)
        d.text((cx - (box[2] - box[0]) / 2, y), text, font=font, fill=self._col(alpha, 0.5))


class Intro:
    """Fenetre transparente centree sur l'orbe ; se ferme seule."""

    def __init__(self, root, center: tuple[int, int], orb: int, painter: Painter, on_done=None):
        import tkinter as tk

        from . import layered

        self.root = root
        self.painter = painter
        self.on_done = on_done
        self.done = False
        size = painter.size
        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        x, y = center[0] - size // 2, center[1] - size // 2
        self.win.geometry(f"{size}x{size}+{x}+{y}")
        self.layer = layered.LayeredWindow(self.win)
        self.win.bind("<Button-1>", lambda _e: self.finish())
        self.started = time.monotonic()
        self._step()

    def _step(self) -> None:
        if self.done:
            return
        t = time.monotonic() - self.started
        if t >= DURATION:
            self.finish()
            return
        try:
            self.layer.show(self.painter.frame(t))
        except Exception:
            self.finish()
            return
        self.root.after(30, self._step)

    def finish(self) -> None:
        if self.done:
            return
        self.done = True
        try:
            self.win.destroy()
        except Exception:
            pass
        if self.on_done:
            self.on_done()


def play(root, style: str, center: tuple[int, int], orb: int, accent: str, lang: str,
         lines: list[str] | None = None, on_done=None):
    """Lance l'intro `style` ; appelle `on_done` a la fin (tout de suite si « aucune »)."""
    if style not in STYLES:
        if on_done:
            on_done()
        return None
    try:
        size = int(orb * 3.4)
        painter = Painter(style, size, orb, accent, lang, lines)
        return Intro(root, center, orb, painter, on_done)
    except Exception:
        if on_done:
            on_done()
        return None


__all__ = ["play", "Painter", "system_lines", "STYLES", "LABELS", "OPERATIONAL",
           "DEFAULT_STYLE", "DURATION"]
