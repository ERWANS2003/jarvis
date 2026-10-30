"""Le corps de l'orbe : elle vit et s'exprime sans visage.

  * **respiration** : calme au repos, plus rapide quand elle ecoute, tres lente endormie ;
  * **voix** : elle gonfle et vibre au rythme de ce qu'elle dit ;
  * **elan** : elle s'etire dans le sens ou elle se deplace et penche dans les virages ;
  * **attention** : un reflet lumineux glisse vers la souris, comme un regard sans yeux ;
  * **emotions** : joie (rebonds, teinte doree), tristesse (elle s'affaisse, bleuit),
    surprise (elle sursaute), gene (elle se dandine, rosit), vertige (elle tangue) ;
  * **gestes spontanes** : de temps en temps elle s'etire, frissonne, se dandine
    ou regarde autour d'elle, sans rien demander a personne.

La logique (`Body.step`) ne depend ni de Tk ni de PIL.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

FIDGET_EVERY = (5.0, 16.0)       # secondes entre deux gestes spontanes
FIDGET_TIME = {"stretch": 1.6, "shiver": 0.7, "wiggle": 1.1, "lookaround": 2.2, "bounce": 0.8}
GAZE_RADIUS = 460.0
GLINT_EVERY = (0.8, 3.0)

BREATH = {     # etat : (amplitude, cycles par seconde)
    "ready": (0.022, 0.30),
    "listening": (0.034, 0.75),
    "thinking": (0.014, 1.10),
    "speaking": (0.016, 0.45),
}
SLEEP_BREATH = (0.036, 0.14)
EMOTION_TINTS = {"happy": ((255, 205, 90), 0.20), "sad": ((80, 120, 220), 0.22),
                 "surprised": ((255, 255, 255), 0.26), "shy": ((255, 130, 170), 0.24),
                 "dizzy": ((190, 150, 255), 0.18)}


@dataclass
class Pose:
    """Ce qu'il faut appliquer a l'image a cet instant."""

    scale_x: float = 1.0
    scale_y: float = 1.0
    tilt: float = 0.0            # degres
    shift_x: float = 0.0         # fraction du rayon
    shift_y: float = 0.0
    glint_x: float = 0.0         # -1..1 : ou se pose le reflet
    glint_y: float = 0.0
    tint: tuple = (255, 255, 255)
    tint_strength: float = 0.0


def _ease(value: float, target: float, dt: float, speed: float) -> float:
    return value + (target - value) * min(1.0, dt * speed)


class Body:
    def __init__(self, rng: random.Random | None = None):
        self.rng = rng or random.Random()
        self.pose = Pose()
        self.clock = 0.0
        self._fidget: str | None = None
        self._fidget_left = 0.0
        self._fidget_in = self.rng.uniform(*FIDGET_EVERY)
        self._glance = (0.0, 0.0)
        self._glance_in = 1.0
        self._gaze = [0.0, 0.0]
        self._stretch = 0.0
        self._lean = 0.0
        self._tint_strength = 0.0
        self._tint = (255, 255, 255)
        self._emotion_clock = 0.0
        self._last_emotion = None

    def fidget(self, name: str) -> None:
        self._fidget, self._fidget_left = name, FIDGET_TIME[name]

    def _fidgets(self, dt: float, allowed: bool) -> tuple[float, float, float, float]:
        """(etirement, inclinaison, decalage x, regard x) du geste en cours."""
        if self._fidget is None:
            if allowed:
                self._fidget_in -= dt
                if self._fidget_in <= 0.0:
                    self._fidget_in = self.rng.uniform(*FIDGET_EVERY)
                    self.fidget(self.rng.choice(tuple(FIDGET_TIME)))
            return 0.0, 0.0, 0.0, 0.0
        self._fidget_left -= dt
        total = FIDGET_TIME[self._fidget]
        done = 1.0 - max(0.0, self._fidget_left) / total
        envelope = math.sin(done * math.pi)
        name = self._fidget
        result = (0.0, 0.0, 0.0, 0.0)
        if name == "stretch":
            result = (0.10 * envelope, 0.0, 0.0, 0.0)
        elif name == "shiver":
            result = (0.0, 3.0 * math.sin(self.clock * 55) * envelope, 0.018 * math.sin(self.clock * 70) * envelope, 0.0)
        elif name == "wiggle":
            result = (0.0, 9.0 * math.sin(done * math.pi * 4) * envelope, 0.0, 0.0)
        elif name == "lookaround":
            result = (0.0, 4.0 * math.sin(done * math.pi * 2), 0.0, math.sin(done * math.pi * 2))
        elif name == "bounce":
            result = (0.09 * math.sin(done * math.pi * 3) * envelope, 0.0, 0.0, 0.0)
        if self._fidget_left <= 0.0:
            self._fidget = None
        return result

    def step(self, dt: float, state: str = "ready", emotion: str | None = None, mouse=None,
             sleep_depth: float = 0.0, level: float = 0.0, velocity=(0.0, 0.0),
             lively: bool = True) -> Pose:
        """Avance d'une image. `mouse` : souris par rapport a l'orbe, `velocity` : px/s."""
        self.clock += dt
        now = self.clock
        amp, rate = BREATH.get(state, BREATH["ready"])
        if sleep_depth > 0.0:
            amp = amp + (SLEEP_BREATH[0] - amp) * sleep_depth
            rate = rate + (SLEEP_BREATH[1] - rate) * sleep_depth
        breath = amp * math.sin(now * rate * math.tau)
        stretch = breath
        wide = -breath * 0.7
        tilt, shift_x, shift_y = 0.0, 0.0, 0.0

        if state == "speaking":
            swell = min(1.0, (level or 0.0) * 1.6)
            stretch += 0.05 * swell
            wide += 0.05 * swell
            tilt += 2.0 * swell * math.sin(now * 9.0)
        elif state == "thinking":
            tilt += 3.5 * math.sin(now * 1.4)
            shift_x += 0.03 * math.sin(now * 2.1)

        if emotion != self._last_emotion:
            self._last_emotion, self._emotion_clock = emotion, 0.0
        self._emotion_clock += dt
        since = self._emotion_clock
        if emotion == "happy":
            hop = abs(math.sin(now * 7.0))
            stretch += 0.06 * hop
            wide -= 0.03 * hop
            shift_y -= 0.12 * hop
        elif emotion == "sad":
            stretch -= 0.07
            wide += 0.05
            shift_y += 0.10
        elif emotion == "surprised":
            jolt = math.exp(-since * 3.5)
            stretch += 0.16 * jolt
            wide -= 0.09 * jolt
            shift_y -= 0.10 * jolt
        elif emotion == "shy":
            tilt += 8.0 * math.sin(now * 6.0)
            wide += 0.02
        elif emotion == "dizzy":
            sway = math.exp(-since * 0.7)
            tilt += 16.0 * math.sin(now * 5.0) * sway
            shift_x += 0.10 * math.cos(now * 5.0) * sway

        calm = sleep_depth < 0.2 and state == "ready" and emotion is None
        fid_stretch, fid_tilt, fid_shift, fid_gaze = self._fidgets(dt, lively and calm)
        stretch += fid_stretch
        wide -= fid_stretch * 0.6
        tilt += fid_tilt
        shift_x += fid_shift

        # Elan : etiree dans le sens du mouvement, penchee dans les virages.
        vx, vy = velocity
        speed = min(1.0, (vx * vx + vy * vy) ** 0.5 / 1600.0)
        self._stretch = _ease(self._stretch, speed, dt, 8.0)
        self._lean = _ease(self._lean, max(-1.0, min(1.0, vx / 900.0)), dt, 7.0)
        if speed > 0.0 or self._stretch > 0.01:
            mostly_x = abs(vx) >= abs(vy)
            amount = 0.14 * self._stretch
            wide += amount if mostly_x else -amount * 0.7
            stretch += -amount * 0.7 if mostly_x else amount
        tilt += 9.0 * self._lean

        # Reflet : la souris si elle est proche, sinon il erre.
        target = None
        if mouse is not None:
            distance = max(1.0, (mouse[0] ** 2 + mouse[1] ** 2) ** 0.5)
            if distance <= GAZE_RADIUS:
                reach = min(1.0, distance / 130.0)
                target = (mouse[0] / distance * reach, mouse[1] / distance * reach)
        if target is None:
            self._glance_in -= dt
            if self._glance_in <= 0.0:
                self._glance_in = self.rng.uniform(*GLINT_EVERY)
                self._glance = (self.rng.uniform(-0.7, 0.7), self.rng.uniform(-0.8, 0.2))
            target = (self._glance[0] + fid_gaze, self._glance[1])
            if sleep_depth > 0.5:
                target = (0.0, 0.5)
        self._gaze[0] = _ease(self._gaze[0], target[0], dt, 7.0)
        self._gaze[1] = _ease(self._gaze[1], target[1], dt, 7.0)

        color, strength = EMOTION_TINTS.get(emotion, (self._tint, 0.0))
        self._tint = color
        self._tint_strength = _ease(self._tint_strength, strength, dt, 5.0)

        pose = self.pose
        pose.scale_x, pose.scale_y = 1.0 + wide, 1.0 + stretch
        pose.tilt = tilt
        pose.shift_x, pose.shift_y = shift_x, shift_y
        pose.glint_x, pose.glint_y = self._gaze
        pose.tint, pose.tint_strength = self._tint, self._tint_strength
        return pose

    # -- dessin --------------------------------------------------------------- #
    _glint_sprite = None
    _glint_size = 0

    def _glint(self, radius: float):
        size = max(4, int(radius * 1.1))
        if self._glint_sprite is None or self._glint_size != size:
            from PIL import Image, ImageFilter

            layer = Image.new("L", (size, size), 0)
            from PIL import ImageDraw

            ImageDraw.Draw(layer).ellipse((size * 0.22, size * 0.22, size * 0.78, size * 0.78), fill=135)
            layer = layer.filter(ImageFilter.GaussianBlur(size * 0.14))
            sprite = Image.new("RGBA", (size, size), (255, 255, 255, 0))
            sprite.putalpha(layer)
            self._glint_sprite, self._glint_size = sprite, size
        return self._glint_sprite

    def apply(self, image, radius: float, glint: bool = True):
        """Renvoie l'image deformee, teintee et eclairee selon la pose."""
        from PIL import Image

        pose = self.pose
        result = image.convert("RGBA")
        if result is image:
            result = image.copy()
        if pose.tint_strength > 0.01:
            alpha = result.getchannel("A")
            result = Image.blend(result.convert("RGB"), Image.new("RGB", result.size, pose.tint),
                                 pose.tint_strength)
            result.putalpha(alpha)
        if glint:
            sprite = self._glint(radius)
            cx = result.width / 2 + pose.glint_x * radius * 0.42 - sprite.width / 2
            cy = result.height / 2 + pose.glint_y * radius * 0.42 - sprite.height / 2
            result.alpha_composite(sprite, (max(0, int(cx)), max(0, int(cy))))
        # Transformation inverse : pour chaque pixel d'arrivee, ou lire l'image de depart.
        angle = math.radians(pose.tilt)
        cos, sin = math.cos(angle), math.sin(angle)
        sx, sy = max(0.5, pose.scale_x), max(0.5, pose.scale_y)
        a, b = cos / sx, sin / sx
        d, e = -sin / sy, cos / sy
        cx, cy = result.width / 2, result.height / 2
        ox, oy = cx + pose.shift_x * radius, cy + pose.shift_y * radius
        c = cx - a * ox - b * oy
        f = cy - d * ox - e * oy
        return result.transform(result.size, Image.AFFINE, (a, b, c, d, e, f), Image.BILINEAR)


__all__ = ["Body", "Pose", "EMOTION_TINTS", "FIDGET_TIME"]
