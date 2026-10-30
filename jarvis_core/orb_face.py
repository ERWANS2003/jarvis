"""Un visage pour l'orbe : le regard, les clignements, la bouche et les emotions.

La logique (`Face.step`) ne depend ni de Tk ni de PIL ; `Face.draw` dessine le
visage par-dessus l'image de l'orbe, quel que soit le theme.

  * **regard** : les yeux suivent la souris quand elle est proche, sinon ils se
    posent ici et la, comme quelqu'un qui reflechit ou qui s'ennuie ;
  * **clignements** irreguliers, parfois doubles ;
  * **bouche** : elle s'ouvre au rythme de la voix ;
  * **emotions** : joie, tristesse, surprise, gene, tete qui tourne... chacune dure
    quelques secondes, puis le visage revient doucement a l'etat du moment.

Les transitions sont lissees : rien ne saute d'une expression a l'autre.
"""

from __future__ import annotations

import random
import re
import unicodedata
from dataclasses import dataclass

BLINK_EVERY = (2.2, 6.0)         # secondes entre deux clignements
BLINK_TIME = 0.14
DOUBLE_BLINK = 0.2               # part de clignements doubles
GLANCE_EVERY = (1.2, 4.5)        # le regard change de point au repos
GAZE_RADIUS = 420.0              # au-dela, la souris n'attire plus le regard
SMOOTH = 11.0
EMOTION_TIME = 3.5

# nom : (ouverture des yeux, sourire -1..1, bouche ouverte, taille des pupilles)
EXPRESSIONS = {
    "neutral": (1.0, 0.25, 0.0, 1.0),
    "listening": (1.15, 0.2, 0.0, 1.15),
    "thinking": (0.75, 0.0, 0.0, 0.95),
    "speaking": (1.0, 0.3, 0.0, 1.0),
    "happy": (1.0, 1.0, 0.0, 1.1),
    "sad": (0.7, -0.8, 0.0, 1.05),
    "surprised": (1.3, 0.0, 0.7, 0.7),
    "shy": (0.8, 0.7, 0.0, 1.15),
    "dizzy": (1.0, -0.2, 0.3, 1.0),
    "asleep": (0.0, 0.1, 0.0, 1.0),
}

_RULES = (
    ("sad", r"\b(?:desole|desolee|navre|malheureusement|helas|je ne peux pas|impossible|"
            r"echec|erreur|panne|sorry|unfortunately|i can't|i cannot)\b"),
    ("surprised", r"\b(?:incroyable|etonnant|surprenant|waouh|wow|ca alors|impressionnant|"
                  r"amazing|incredible|surprising)\b"),
    ("happy", r"\b(?:bravo|felicitations|super|genial|parfait|excellent|formidable|bonne nouvelle|"
              r"avec plaisir|haha|ahah|great|awesome|perfect|congratulations|glad|happy to)\b|!\s*$"),
)
_USER_RULES = (
    ("shy", r"\b(?:merci|tu es (?:genial|genial\w*|gentil\w*|forte?|super|intelligent\w*|mignon\w*|"
            r"beau|belle)|je t'aime|bravo|bien joue|thank you|thanks|you are (?:great|awesome|cute)|"
            r"i love you)\b"),
    ("sad", r"\b(?:tu es (?:nul\w*|bete|idiot\w*|stupide)|t'es (?:nul\w*|bete)|ferme[- ]la|tais[- ]toi|"
            r"you (?:are|re) (?:stupid|useless|dumb)|shut up)\b"),
    ("happy", r"\b(?:bonjour|salut|coucou|hello|bonsoir|hey)\b"),
)


def _plain(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").lower().replace("’", "'")
    return "".join(c for c in text if not unicodedata.combining(c))


def _match(rules, text: str) -> str | None:
    low = _plain(text)
    return next((name for name, pattern in rules if re.search(pattern, low)), None)


def emotion_for(reply: str) -> str | None:
    """L'emotion que porte une reponse de Jarvis."""
    return _match(_RULES, reply)


def emotion_for_user(text: str) -> str | None:
    """La reaction a ce que l'utilisateur vient de dire."""
    return _match(_USER_RULES, text)


@dataclass
class Look:
    """Ce qu'il faut dessiner a cette image."""

    eyes: float = 1.0
    smile: float = 0.25
    mouth: float = 0.0
    pupil: float = 1.0
    gaze_x: float = 0.0
    gaze_y: float = 0.0
    arcs: float = 0.0            # yeux en arc de joie (^ ^)
    dizzy: float = 0.0


def _ease(value: float, target: float, dt: float, speed: float = SMOOTH) -> float:
    return value + (target - value) * min(1.0, dt * speed)


class Face:
    def __init__(self, rng: random.Random | None = None):
        self.rng = rng or random.Random()
        self.look = Look()
        self.emotion: str | None = None
        self.emotion_left = 0.0
        self._blink_in = self.rng.uniform(*BLINK_EVERY)
        self._blink_time = 0.0
        self._blink_again = False
        self._glance_in = self.rng.uniform(*GLANCE_EVERY)
        self._glance = (0.0, 0.0)
        self._sprite_key = None
        self._sprite = None

    def feel(self, emotion: str | None, seconds: float = EMOTION_TIME) -> None:
        if emotion in EXPRESSIONS:
            self.emotion, self.emotion_left = emotion, seconds

    def blink(self) -> None:
        self._blink_time = BLINK_TIME

    def _blink_step(self, dt: float) -> float:
        """Renvoie le facteur d'ouverture du aux clignements (0 = ferme)."""
        if self._blink_time > 0.0:
            self._blink_time -= dt
            if self._blink_time <= 0.0 and self._blink_again:
                self._blink_again = False
                self._blink_time = BLINK_TIME
            return abs(self._blink_time / BLINK_TIME * 2.0 - 1.0) if self._blink_time > 0 else 1.0
        self._blink_in -= dt
        if self._blink_in <= 0.0:
            self._blink_in = self.rng.uniform(*BLINK_EVERY)
            self._blink_time = BLINK_TIME
            self._blink_again = self.rng.random() < DOUBLE_BLINK
        return 1.0

    def _gaze_target(self, dt: float, state: str, mouse) -> tuple[float, float]:
        if mouse is not None:
            dx, dy = mouse
            distance = max(1.0, (dx * dx + dy * dy) ** 0.5)
            if distance <= GAZE_RADIUS:
                reach = min(1.0, distance / 120.0)
                return dx / distance * reach, dy / distance * reach
        self._glance_in -= dt
        if self._glance_in <= 0.0:
            self._glance_in = self.rng.uniform(*GLANCE_EVERY)
            if state == "thinking":                    # on cherche ses idees en l'air
                self._glance = (self.rng.choice((-0.7, 0.7)), -0.7)
            elif self.rng.random() < 0.5:
                self._glance = (0.0, 0.0)              # retour au centre : regard pose
            else:
                self._glance = (self.rng.uniform(-0.7, 0.7), self.rng.uniform(-0.4, 0.4))
        return self._glance

    def expression(self, state: str, sleep_depth: float = 0.0) -> str:
        if sleep_depth > 0.5:
            return "asleep"
        if self.emotion:
            return self.emotion
        return state if state in ("listening", "thinking", "speaking") else "neutral"

    def step(self, dt: float, state: str = "ready", mouse=None, sleep_depth: float = 0.0,
             level: float = 0.0) -> Look:
        """Avance d'une image. `mouse` : position de la souris par rapport a l'orbe."""
        if self.emotion_left > 0.0:
            self.emotion_left -= dt
            if self.emotion_left <= 0.0:
                self.emotion = None
        name = self.expression(state, sleep_depth)
        eyes, smile, mouth, pupil = EXPRESSIONS[name]
        if state == "speaking" and name != "asleep":
            mouth = max(mouth, min(1.0, (level or 0.0) * 1.8))     # la bouche suit la voix
        look = self.look
        blink = self._blink_step(dt) if name != "asleep" else 1.0
        look.eyes = _ease(look.eyes, eyes, dt)
        look.smile = _ease(look.smile, smile, dt)
        look.mouth = _ease(look.mouth, mouth, dt, 22.0)
        look.pupil = _ease(look.pupil, pupil, dt)
        look.arcs = _ease(look.arcs, 1.0 if name in ("happy", "shy") else 0.0, dt)
        look.dizzy = _ease(look.dizzy, 1.0 if name == "dizzy" else 0.0, dt)
        gaze = (0.0, 0.3) if name == "asleep" else self._gaze_target(dt, state, mouse)
        look.gaze_x = _ease(look.gaze_x, gaze[0], dt, 16.0)
        look.gaze_y = _ease(look.gaze_y, gaze[1], dt, 16.0)
        self.openness = look.eyes * blink
        return look

    openness = 1.0

    # -- dessin --------------------------------------------------------------- #
    def _draw_sprite(self, radius: float):
        from PIL import Image, ImageDraw

        look = self.look
        ss = 3
        side = int(radius * 2 * ss)
        layer = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        unit = radius * ss
        cx, cy = side / 2, side / 2
        line = max(2, int(unit * 0.055))
        ink, white = (22, 26, 40, 255), (250, 252, 255, 255)
        openness = max(0.0, self.openness)
        halo = max(2, line)

        def stroke(box, start, end) -> None:       # lisible sur un theme clair comme sombre
            draw.arc(box, start, end, fill=white, width=line + halo)
            draw.arc(box, start, end, fill=ink, width=line)

        for side_sign in (-1, 1):
            ex = cx + side_sign * unit * 0.36 + look.gaze_x * unit * 0.05
            ey = cy - unit * 0.12 + look.gaze_y * unit * 0.04
            width, height = unit * 0.19, unit * 0.24
            if look.dizzy > 0.5:                                 # X : la tete tourne
                size = unit * 0.13
                for a, b in ((-1, -1), (-1, 1)):
                    points = (ex + a * size, ey + b * size, ex - a * size, ey - b * size)
                    draw.line(points, fill=white, width=line + halo)
                    draw.line(points, fill=ink, width=line)
                continue
            if look.arcs > 0.5 and openness > 0.2:               # ^ ^ : la joie
                box = (ex - width, ey - height * 0.7, ex + width, ey + height * 1.1)
                stroke(box, 200, 340)
                continue
            if openness < 0.18:                                  # ferme : un trait doux
                box = (ex - width, ey - height * 0.5, ex + width, ey + height * 0.5)
                stroke(box, 20, 160)
                continue
            h = height * min(1.3, openness)
            draw.ellipse((ex - width, ey - h, ex + width, ey + h), fill=white,
                         outline=(22, 26, 40, 120), width=max(1, line // 3))
            px = ex + look.gaze_x * width * 0.42
            py = ey + look.gaze_y * h * 0.38
            pr = width * 0.56 * look.pupil
            pry = min(pr, h * 0.95)
            draw.ellipse((px - pr, py - pry, px + pr, py + pry), fill=ink)
            glint = pr * 0.32
            draw.ellipse((px - pr * 0.45 - glint, py - pry * 0.5 - glint,
                          px - pr * 0.45 + glint, py - pry * 0.5 + glint), fill=white)
        mx, my = cx, cy + unit * 0.36
        width = unit * 0.2
        if look.mouth > 0.08:                                    # bouche ouverte
            h = unit * 0.03 + unit * 0.15 * look.mouth
            w = width * (0.55 + 0.25 * max(0.0, look.smile))
            draw.ellipse((mx - w, my - h, mx + w, my + h), fill=ink, outline=white, width=line)
        else:
            curve = look.smile
            h = unit * 0.14 * abs(curve) + unit * 0.01
            if curve >= 0:
                stroke((mx - width, my - h * 1.4, mx + width, my + h), 15, 165)
            else:
                stroke((mx - width, my - h * 0.2, mx + width, my + h * 2), 195, 345)
        return layer.resize((int(radius * 2), int(radius * 2)), Image.LANCZOS)

    def draw(self, image, radius: float):
        """Pose le visage au centre de `image` (copie seulement si le visage change)."""
        look = self.look
        key = (round(self.openness, 2), round(look.smile, 1), round(look.mouth, 1), round(look.pupil, 1),
               round(look.gaze_x, 1), round(look.gaze_y, 1), look.arcs > 0.5, look.dizzy > 0.5,
               round(radius))
        if key != self._sprite_key:
            self._sprite_key, self._sprite = key, self._draw_sprite(radius)
        result = image.convert("RGBA")
        if result is image:
            result = image.copy()
        sprite = self._sprite
        result.alpha_composite(sprite, ((result.width - sprite.width) // 2,
                                        (result.height - sprite.height) // 2))
        return result


# --------------------------------------------------------------------------- #
# Caresses : la souris qui va et vient sur l'orbe
# --------------------------------------------------------------------------- #
PET_WINDOW = 1.6
PET_TURNS = 4
PET_REST = 8.0


class PetDetector:
    """Compte les changements de sens de la souris au-dessus de l'orbe."""

    def __init__(self):
        self._last_x = None
        self._direction = 0
        self._turns: list[float] = []
        self._rest_until = 0.0

    def update(self, now: float, x: float | None) -> bool:
        if x is None:
            self._last_x, self._direction = None, 0
            return False
        if self._last_x is not None and abs(x - self._last_x) >= 3:
            direction = 1 if x > self._last_x else -1
            if self._direction and direction != self._direction:
                self._turns.append(now)
            self._direction = direction
        self._last_x = x
        self._turns = [t for t in self._turns if now - t <= PET_WINDOW]
        if len(self._turns) >= PET_TURNS and now >= self._rest_until:
            self._turns.clear()
            self._rest_until = now + PET_REST
            return True
        return False


# --------------------------------------------------------------------------- #
# Petites phrases : rares, affichees sans voix, adaptees au moment
# --------------------------------------------------------------------------- #
MUSE_EVERY = (900.0, 2400.0)     # 15 a 40 minutes
MUSINGS = {
    "fr": {
        "morning": ("Bien dormi ?", "Un café, et c'est parti ?"),
        "noon": ("Bientôt l'heure de manger, non ?", "Tu as prévu quoi à midi ?"),
        "afternoon": ("Tout se passe bien ?", "Je suis là si besoin.", "Tu avances bien, on dirait."),
        "evening": ("La journée a été bonne ?", "Encore un peu de travail ?"),
        "night": ("Il se fait tard…", "Tu ne devrais pas dormir ?"),
        "friday": ("C'est bientôt le week-end !",),
    },
    "en": {
        "morning": ("Sleep well?", "Coffee first?"),
        "noon": ("Almost lunch time, isn't it?", "What's for lunch?"),
        "afternoon": ("Everything going well?", "I'm here if you need me."),
        "evening": ("Good day?", "Still working?"),
        "night": ("It's getting late…", "Shouldn't you be asleep?"),
        "friday": ("Almost the weekend!",),
    },
}
REACTIONS = {
    "fr": {"pet": ("Hé, ça chatouille !", "Hihi, encore !", "J'aime bien ça."),
           "thrown": ("Ouh, la tête me tourne…", "Doucement !", "Whaou, quel vol !"),
           "wake": ("Hein ? Je suis là, je suis là !", "Oh, je dormais un peu…")},
    "en": {"pet": ("Hey, that tickles!", "Hehe, more!", "I like that."),
           "thrown": ("Whoa, I'm dizzy…", "Easy!", "What a flight!"),
           "wake": ("Huh? I'm here, I'm here!", "Oh, I dozed off…")},
}


def musing(hour: int, weekday: int, lang: str = "fr", rng=None) -> str:
    """Une petite phrase adaptee a l'heure et au jour."""
    rng = rng or random
    table = MUSINGS["fr" if lang == "fr" else "en"]
    if weekday == 4 and hour >= 15:
        moment = "friday"
    elif 6 <= hour < 11:
        moment = "morning"
    elif 11 <= hour < 14:
        moment = "noon"
    elif 14 <= hour < 18:
        moment = "afternoon"
    elif 18 <= hour < 23:
        moment = "evening"
    else:
        moment = "night"
    return rng.choice(table[moment])


def reaction(kind: str, lang: str = "fr", rng=None) -> str:
    rng = rng or random
    return rng.choice(REACTIONS["fr" if lang == "fr" else "en"][kind])


__all__ = ["Face", "Look", "PetDetector", "emotion_for", "emotion_for_user", "musing", "reaction",
           "EXPRESSIONS", "MUSE_EVERY"]
