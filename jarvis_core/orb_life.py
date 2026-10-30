"""La vie de l'orbe : elle bouge seule, reagit, s'endort, s'ecarte.

Tout est calcule ici, sans Tk (donc testable) ; l'orbe se contente d'appeler
`Life.step()` a chaque image et de placer sa fenetre a la position rendue.

Comportements :

  * **physique** : lancee a la souris, elle glisse, freine et rebondit sur les
    bords de l'ecran, puis s'installe la ou elle s'arrete ;
  * **balades** : au repos, elle choisit souvent une intention (flaner, explorer,
    filer, venir voir la souris), regarde ou elle va, part en courbe et enchaine
    parfois plusieurs etapes. Elle evite la souris, le texte en cours de frappe et
    les endroits ou elle vient de passer, se fait discrete quand on travaille,
    ose plus quand on n'est pas la, et s'arrete quand la souris la survole ;
  * **curiosite** : quand la souris passe pres d'elle, elle se penche vers elle ;
  * **gestes** : hochement pour « oui », secousse pour « non », petit bond de joie ;
  * **sommeil** : apres un long moment sans rien (ou la nuit, si l'utilisateur
    n'est plus la), elle s'endort : elle descend un peu, palit, respire
    lentement ; elle se reveille d'un bond quand on l'appelle ;
  * **retour** : quand l'utilisateur revient devant son PC, elle le salue ;
  * **discretion** : si le curseur de saisie (texte en cours de frappe) passe
    sous elle, elle s'ecarte, puis revient quand la place est libre.

`calm=True` (reglage « Calme ») garde les gestes et la physique mais coupe les
balades, la curiosite et le sommeil.
"""

from __future__ import annotations

import math
import os
import random
import sys
from dataclasses import dataclass

# --- reglages --------------------------------------------------------------- #
STROLL_EVERY = (1.5, 6.0)        # secondes de repos avant une balade
LONG_REST = (12.0, 25.0)         # ... et parfois un vrai repos : un rythme irregulier
LONG_REST_CHANCE = 0.08
THINK = (0.35, 0.9)              # elle regarde ou elle va avant de partir
ACTIVE_PACE = 0.7                # l'utilisateur est actif : un peu moins souvent
AWAY_AFTER = 30.0                # sans clavier ni souris : elle ose aller plus loin
CHAIN_CHANCE = 0.7               # enchainer une autre etape (moins, loin de chez elle)
ROAM = 560.0                     # jamais plus loin que ca de sa place (px)
RETURN_SPEED = 380.0             # vitesse du retour (px/s)
LOOK_DISTANCE = 240.0            # « venir voir » s'arrete a cette distance de la souris
LOOK_WALK = 300.0                # ... et ne fait pas plus de chemin que ca
LOOK_RANGE = 800.0               # la souris est trop loin au-dela
GLANCE = 300.0                   # regard vers la destination (comme une souris a 300 px)
MOVES = {
    # nom : (distance px, vitesse px/s, arret s, courbure)
    "flanerie": ((50.0, 160.0), (70.0, 130.0), (1.0, 3.0), 0.25),
    "exploration": ((180.0, 420.0), (140.0, 240.0), (1.5, 4.0), 0.35),
    "elan": ((60.0, 140.0), (300.0, 480.0), (0.8, 2.0), 0.15),
    "approche": ((0.0, 0.0), (120.0, 200.0), (1.5, 3.0), 0.2),
}
MOUSE_KEEP_AWAY = 160.0          # une balade ne passe jamais sur la souris
CURIOUS_RADIUS = 260.0           # la souris attire le regard a cette distance
CURIOUS_LEAN = 12.0              # penchement maximal vers la souris (px)
SLEEP_AFTER = 600.0              # 10 min sans rien -> sommeil
SLEEP_USER_AWAY = 180.0          # ... et l'utilisateur absent depuis 3 min
NIGHT = (23, 7)                  # la nuit, sommeil des 2 min d'absence
WELCOME_AWAY = 300.0             # absent 5 min puis de retour -> salut
CARET_MARGIN = 40.0              # marge autour du curseur de saisie
CARET_TYPING = 3.0               # on ne s'ecarte que si l'utilisateur tape (clavier < 3 s)
CARET_MAX_MOVE = 400.0           # jamais plus loin que ca pour s'ecarter
CARET_RETURN_AFTER = 4.0         # place libre depuis 4 s avant de revenir
THROW_MIN_SPEED = 900.0          # px/s pour qu'un lacher devienne un lancer
FRICTION = 2.6                   # freinage d'un lancer (par seconde)
BOUNCE = 0.55                    # energie gardee a chaque rebond
SPRING = 9.0                     # raideur du deplacement doux (balades, retours)

GESTURES = {
    # nom : (duree, amplitude x, amplitude y, oscillations)
    "nod": (0.9, 0.0, 7.0, 2.0),
    "shake": (0.9, 9.0, 0.0, 3.0),
    "hop": (0.6, 0.0, -16.0, 0.5),
    "wake": (0.7, 0.0, -22.0, 0.5),
    "giggle": (0.8, 4.0, -6.0, 4.0),
}
_YES = ("oui", "d'accord", "c'est fait", "bien sûr", "bien sur", "volontiers", "parfait",
        "avec plaisir", "entendu", "excellent", "absolument", "yes", "sure", "done", "of course")
_NO = ("non", "désolé", "desole", "je ne peux", "impossible", "hélas", "helas",
       "malheureusement", "je n'ai pas", "no", "sorry", "i can't", "unfortunately")
_LAUGH = ("haha", "ha ha", "hihi", "lol", "😄")


def gesture_for(reply: str) -> str | None:
    """Geste qui accompagne le debut d'une reponse (« Oui… » -> hochement)."""
    low = (reply or "").strip().lower()
    if not low:
        return None
    if any(word in low[:40] for word in _LAUGH):
        return "giggle"
    first = low[:24]
    if any(first.startswith(word) for word in _NO):
        return "shake"
    if any(first.startswith(word) for word in _YES):
        return "nod"
    return None


@dataclass
class Path:
    """Un trajet en courbe, avec un petit recul avant de partir."""

    start: tuple[float, float]
    bend: tuple[float, float]
    end: tuple[float, float]
    duration: float
    elapsed: float = 0.0

    @property
    def done(self) -> bool:
        return self.elapsed >= self.duration

    def point(self) -> tuple[float, float]:
        u = min(1.0, self.elapsed / self.duration)
        s = u * u * (3 - 2 * u) - 0.04 * math.sin(math.pi * min(1.0, u / 0.2))
        a, b, c = (1 - s) * (1 - s), 2 * s * (1 - s), s * s
        return (a * self.start[0] + b * self.bend[0] + c * self.end[0],
                a * self.start[1] + b * self.bend[1] + c * self.end[1])


@dataclass
class World:
    """Ce que l'orbe percoit a chaque image."""

    state: str = "ready"           # ready | listening | thinking | speaking
    hovered: bool = False
    busy: bool = False             # menu, saisie, glisser en cours : ne pas bouger
    mouse: tuple[float, float] | None = None
    user_idle: float = 0.0         # secondes sans clavier ni souris
    caret: tuple[float, float, float, float] | None = None   # x1, y1, x2, y2
    hour: int = 12


class Life:
    def __init__(self, home: tuple[float, float], size: int, area: tuple[int, int, int, int],
                 scale: float = 1.0, calm: bool = False, rng: random.Random | None = None):
        self.size = int(size)
        self.area = area                      # zone de travail (x1, y1, x2, y2)
        self.scale = float(scale)
        self.calm = calm
        self.rng = rng or random.Random()
        self.home = self._clamp(home)
        self.pos = list(self.home)
        self.vel = [0.0, 0.0]
        self.target: tuple[float, float] | None = None   # balade ou ecart en cours
        self.mode = "home"                    # home | ponder | stroll | linger | back | thrown | dodge
        self.move = "flanerie"                # intention de la balade en cours
        self.path: Path | None = None
        self.recent: list[tuple[float, float]] = []   # ou elle vient de passer
        self.timer = self._next_stroll()
        self.lean = [0.0, 0.0]
        self.gesture: tuple[str, float] | None = None
        self.asleep = False
        self.sleep_depth = 0.0                # 0 eveillee -> 1 endormie (descente, paleur)
        self.quiet_for = 0.0                  # secondes sans interaction avec Jarvis
        self._was_away = False
        self._caret_clear = 0.0               # depuis quand la maison est libre
        self.events: list[str] = []           # « welcome », « sleep », « wake » (lus par l'orbe)

    # -- outils -------------------------------------------------------------- #
    def _clamp(self, point) -> tuple[float, float]:
        x1, y1, x2, y2 = self.area
        return (min(max(point[0], x1), x2 - self.size), min(max(point[1], y1), y2 - self.size))

    def _next_stroll(self) -> float:
        if self.rng.random() < LONG_REST_CHANCE:
            return self.rng.uniform(*LONG_REST)
        return self.rng.uniform(*STROLL_EVERY)

    def heading(self) -> tuple[float, float] | None:
        """Ou elle regarde pendant une balade (relatif a son centre), sinon None."""
        if self.mode not in ("ponder", "stroll") or self.target is None:
            return None
        dx, dy = self.target[0] - self.pos[0], self.target[1] - self.pos[1]
        distance = math.hypot(dx, dy)
        if distance < 5 * self.scale:
            return None
        return dx / distance * GLANCE * self.scale, dy / distance * GLANCE * self.scale

    def center(self, point=None) -> tuple[float, float]:
        x, y = point if point is not None else self.pos
        return x + self.size / 2, y + self.size / 2

    def _rect_hits(self, point, rect, margin: float) -> bool:
        x, y = point
        x1, y1, x2, y2 = rect
        return not (x + self.size < x1 - margin or x > x2 + margin
                    or y + self.size < y1 - margin or y > y2 + margin)

    # -- commandes ------------------------------------------------------------ #
    def play(self, name: str) -> None:
        if name in GESTURES:
            self.gesture = (name, 0.0)

    def interact(self) -> None:
        """Jarvis est sollicite (clic, mot d'activation, reponse) : reveil."""
        self.quiet_for = 0.0
        if self.asleep:
            self.asleep = False
            self.events.append("wake")
            self.play("wake")

    def moved_by_user(self, x: float, y: float) -> None:
        """Glissee a la main : nouvelle maison, rien d'autre en cours."""
        self.pos = [float(x), float(y)]
        self.home = self._clamp((x, y))
        self.vel = [0.0, 0.0]
        self.mode, self.target, self.path = "home", None, None
        self.timer = self._next_stroll()

    def throw(self, x: float, y: float, vx: float, vy: float) -> bool:
        """Lachee avec elan : vrai si elle part en glissade."""
        self.moved_by_user(x, y)
        if math.hypot(vx, vy) * 1.0 < THROW_MIN_SPEED * self.scale:
            return False
        self.vel = [vx, vy]
        self.mode = "thrown"
        return True

    # -- une image ------------------------------------------------------------ #
    def step(self, dt: float, world: World) -> tuple[int, int]:
        """Avance de `dt` secondes ; renvoie la position de la fenetre."""
        dt = max(0.0, min(dt, 0.1))
        self._watch_user(dt, world)
        if world.busy:
            return self._render(dt, world, move=False)
        if self.mode == "thrown":
            self._slide(dt)
        else:
            self._decide(dt, world)
            self._spring(dt, world.hovered)
        return self._render(dt, world)

    def _watch_user(self, dt: float, world: World) -> None:
        active = world.state != "ready" or world.hovered
        self.quiet_for = 0.0 if active else self.quiet_for + dt
        if active and self.asleep:
            self.interact()
        # Retour de l'utilisateur apres une absence.
        if world.user_idle >= WELCOME_AWAY:
            self._was_away = True
        elif self._was_away and world.user_idle < 2.0:
            self._was_away = False
            if self.asleep:
                self.interact()
            else:
                self.play("hop")
            self.events.append("welcome")
        if self.calm:
            return
        night = world.hour >= NIGHT[0] or world.hour < NIGHT[1]
        away_needed = 120.0 if night else SLEEP_USER_AWAY
        if (not self.asleep and world.state == "ready" and self.quiet_for >= SLEEP_AFTER
                and world.user_idle >= away_needed):
            self.asleep = True
            self.events.append("sleep")
            self.mode, self.target = "back", self.home

    def _decide(self, dt: float, world: World) -> None:
        # On tape juste sous l'orbe : elle s'ecarte (meme en mode calme).
        caret = world.caret if world.user_idle < CARET_TYPING else None
        if caret is not None and self._rect_hits(self.pos, caret, CARET_MARGIN):
            spot = self._free_spot(caret)
            if spot is not None:
                self.mode, self.target, self.path = "dodge", spot, None
                self._caret_clear = 0.0
                return
        if self.mode == "dodge":
            blocked = world.caret is not None and self._rect_hits(self.home, world.caret,
                                                                   CARET_MARGIN)
            self._caret_clear = 0.0 if blocked else self._caret_clear + dt
            if self._caret_clear >= CARET_RETURN_AFTER:
                self.mode, self.target = "back", self.home
            return
        if self.calm or self.asleep or world.state != "ready" or world.hovered:
            if self.mode in ("ponder", "stroll", "linger") and world.state != "ready":
                self.mode, self.target = "back", self.home     # on l'appelle : elle rentre
            return
        active = self.mode == "home" and world.user_idle < CARET_TYPING
        self.timer -= dt * (ACTIVE_PACE if active else 1.0)
        if self.mode == "home" and self.timer <= 0:
            if not self._plan_move(world):
                self.timer = self._next_stroll()
        elif self.mode == "ponder" and self.timer <= 0:
            self.mode, self.path = "stroll", None
        elif self.mode == "stroll" and self._arrived():
            self.mode, self.path = "linger", None
            self.timer = self.rng.uniform(*MOVES[self.move][2])
        elif self.mode == "linger" and self.timer <= 0:
            far = math.dist(self.pos, self.home) / (ROAM * self.scale)
            if self.rng.random() >= CHAIN_CHANCE * (1.0 - far) or not self._plan_move(world):
                self.mode, self.target = "back", self.home
        elif self.mode == "back" and self._arrived():
            self.mode, self.target, self.path = "home", None, None
            self.timer = self._next_stroll()

    def _arrived(self) -> bool:
        if self.target is None:
            return True
        if self.path is not None and not self.path.done:
            return False
        return math.hypot(self.target[0] - self.pos[0], self.target[1] - self.pos[1]) < 2.0

    def _plan_move(self, world: World) -> bool:
        """Choisit une intention et une destination, puis prend le temps de regarder."""
        caret = world.caret if world.user_idle < CARET_TYPING else None
        move = self._choose_move(world, caret)
        spot = None
        if move == "approche":
            spot = self._approach_spot(world.mouse, caret)
        else:
            spot = self._stroll_spot(world.mouse, move, caret)
        if spot is None and move != "flanerie":
            move, spot = "flanerie", self._stroll_spot(world.mouse, "flanerie", caret)
        if spot is None:
            return False
        self.move, self.target, self.path = move, spot, None
        self.mode, self.timer = "ponder", self.rng.uniform(*THINK)
        self.recent = (self.recent + [spot])[-4:]
        return True

    def _choose_move(self, world: World, caret) -> str:
        if caret is not None:
            return "flanerie"                 # on tape : rien de spectaculaire
        weights = {"flanerie": 5, "exploration": 3, "elan": 2, "approche": 0}
        if world.user_idle >= AWAY_AFTER:
            weights["exploration"] = 6
        elif (world.mouse is not None and world.user_idle < 10.0
              and math.dist(self.center(), world.mouse) < LOOK_RANGE * self.scale):
            weights["approche"] = 2
        return self.rng.choices(list(weights), list(weights.values()))[0]

    def _spot_allowed(self, spot, mouse, caret) -> bool:
        if math.dist(spot, self.home) > ROAM * self.scale:
            return False
        if caret is not None and self._rect_hits(spot, caret, CARET_MARGIN):
            return False
        if mouse is None:
            return True
        here, there = self.center(), self.center(spot)
        keep = min(MOUSE_KEEP_AWAY * self.scale, math.dist(here, mouse))
        if math.dist(there, mouse) < MOUSE_KEEP_AWAY * self.scale:
            return False
        return all(math.dist((here[0] + (there[0] - here[0]) * k / 6,
                              here[1] + (there[1] - here[1]) * k / 6), mouse) >= keep
                   for k in range(1, 6))

    def _stroll_spot(self, mouse, move: str = "flanerie", caret=None):
        """Parmi quelques places au hasard, la plus eloignee de ses derniers passages."""
        best = None
        for _ in range(14):
            angle = self.rng.uniform(0, 2 * math.pi)
            reach = self.rng.uniform(*MOVES[move][0]) * self.scale
            spot = self._clamp((self.pos[0] + math.cos(angle) * reach,
                                self.pos[1] + math.sin(angle) * reach))
            if math.dist(spot, self.pos) <= 25 * self.scale or not self._spot_allowed(spot, mouse, caret):
                continue
            score = min(math.dist(spot, seen) for seen in [self.home] + self.recent)
            score += self.rng.uniform(0.0, 120.0 * self.scale)
            if best is None or score > best[0]:
                best = (score, spot)
        return best[1] if best else None

    def _approach_spot(self, mouse, caret):
        """Vient voir la souris, sans jamais aller dessous."""
        if mouse is None:
            return None
        cx, cy = self.center()
        distance = math.dist((cx, cy), mouse)
        walk = min(distance - LOOK_DISTANCE * self.scale, LOOK_WALK * self.scale)
        if walk < 30 * self.scale:
            return None
        spot = self._clamp((self.pos[0] + (mouse[0] - cx) / distance * walk,
                            self.pos[1] + (mouse[1] - cy) / distance * walk))
        return spot if self._spot_allowed(spot, mouse, caret) else None

    def _new_path(self) -> Path:
        start, end = (self.pos[0], self.pos[1]), self.target
        if self.mode == "stroll":
            speed = self.rng.uniform(*MOVES[self.move][1])
            bend = self.rng.uniform(-1.0, 1.0) * MOVES[self.move][3]
        else:
            speed, bend = RETURN_SPEED, self.rng.uniform(-0.2, 0.2)
        dx, dy = end[0] - start[0], end[1] - start[1]
        middle = ((start[0] + end[0]) / 2 - dy * bend, (start[1] + end[1]) / 2 + dx * bend)
        return Path(start, middle, end, max(0.5, math.hypot(dx, dy) / (speed * self.scale)))

    def _free_spot(self, caret):
        """Place la plus proche, hors de la zone du curseur de saisie."""
        x1, y1, x2, y2 = caret
        m = CARET_MARGIN + 10
        candidates = [(self.pos[0], y1 - m - self.size), (self.pos[0], y2 + m),
                      (x1 - m - self.size, self.pos[1]), (x2 + m, self.pos[1])]
        best = None
        for spot in candidates:
            spot = self._clamp(spot)
            if self._rect_hits(spot, caret, CARET_MARGIN):
                continue
            distance = math.dist(spot, self.pos)
            if distance > CARET_MAX_MOVE * self.scale:
                continue
            if best is None or distance < best[0]:
                best = (distance, spot)
        return best[1] if best else None

    def _spring(self, dt: float, hovered: bool = False) -> None:
        if self.mode in ("stroll", "back"):
            if self.path is None or self.path.end != self.target:
                self.path = self._new_path()
            if not (hovered and self.mode == "stroll"):   # survolee : elle se laisse attraper
                self.path.elapsed += dt
            goal = self._clamp(self.path.point())
        elif self.mode == "dodge":
            goal = self.target
        else:
            goal = self.pos if self.mode in ("linger", "ponder") else self.home
        for i in (0, 1):
            # Ressort critique amorti : depart doux, arrivee sans depasser.
            accel = SPRING * SPRING * (goal[i] - self.pos[i]) - 2 * SPRING * self.vel[i]
            self.vel[i] += accel * dt
            self.pos[i] += self.vel[i] * dt

    def _slide(self, dt: float) -> None:
        x1, y1, x2, y2 = self.area
        decay = math.exp(-FRICTION * dt)
        self.vel = [self.vel[0] * decay, self.vel[1] * decay]
        self.pos[0] += self.vel[0] * dt
        self.pos[1] += self.vel[1] * dt
        if self.pos[0] < x1 or self.pos[0] > x2 - self.size:
            self.pos[0] = min(max(self.pos[0], x1), x2 - self.size)
            self.vel[0] = -self.vel[0] * BOUNCE
        if self.pos[1] < y1 or self.pos[1] > y2 - self.size:
            self.pos[1] = min(max(self.pos[1], y1), y2 - self.size)
            self.vel[1] = -self.vel[1] * BOUNCE
        if math.hypot(*self.vel) < 40 * self.scale:
            self.home = self._clamp(self.pos)
            self.vel = [0.0, 0.0]
            self.mode, self.target, self.path = "home", None, None
            self.events.append("settled")

    def _render(self, dt: float, world: World, move: bool = True) -> tuple[int, int]:
        # Sommeil : descente douce de quelques pixels.
        goal = 1.0 if self.asleep else 0.0
        self.sleep_depth += (goal - self.sleep_depth) * min(1.0, dt * 1.5)
        # Curiosite : penchement vers la souris proche.
        lean_goal = (0.0, 0.0)
        if (move and not self.calm and not self.asleep and world.mouse is not None
                and not world.hovered and self.mode in ("home", "linger")):
            cx, cy = self.center()
            dx, dy = world.mouse[0] - cx, world.mouse[1] - cy
            distance = math.hypot(dx, dy)
            reach = CURIOUS_RADIUS * self.scale
            if self.size / 2 < distance < reach:
                pull = (1.0 - distance / reach) * CURIOUS_LEAN * self.scale
                lean_goal = (dx / distance * pull, dy / distance * pull)
        for i in (0, 1):
            self.lean[i] += (lean_goal[i] - self.lean[i]) * min(1.0, dt * 4.0)
        # Gestes : oscillations amorties.
        gx = gy = 0.0
        if self.gesture is not None:
            name, elapsed = self.gesture
            duration, ax, ay, waves = GESTURES[name]
            elapsed += dt
            if elapsed >= duration:
                self.gesture = None
            else:
                self.gesture = (name, elapsed)
                envelope = math.sin(math.pi * elapsed / duration)
                wave = math.sin(2 * math.pi * waves * elapsed / duration)
                if name in ("hop", "wake"):
                    wave = 1.0
                gx, gy = ax * envelope * wave * self.scale, ay * envelope * wave * self.scale
        sink = 10.0 * self.scale * self.sleep_depth
        x = self.pos[0] + self.lean[0] + gx
        y = self.pos[1] + self.lean[1] + gy + sink
        return int(round(x)), int(round(y))

    def take_events(self) -> list[str]:
        events, self.events = self.events, []
        return events


# --------------------------------------------------------------------------- #
# Capteurs Windows (remplacables dans les tests)
# --------------------------------------------------------------------------- #
def work_area(x: int, y: int, fallback: tuple[int, int]) -> tuple[int, int, int, int]:
    """Zone utile (sans la barre des taches) de l'ecran qui contient (x, y)."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class _MonitorInfo(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                            ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

            user32 = ctypes.windll.user32
            user32.MonitorFromPoint.restype = wintypes.HANDLE
            monitor = user32.MonitorFromPoint(wintypes.POINT(int(x), int(y)), 2)
            info = _MonitorInfo()
            info.cbSize = ctypes.sizeof(info)
            if user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                r = info.rcWork
                return r.left, r.top, r.right, r.bottom
        except Exception:
            pass
    return 0, 0, fallback[0], fallback[1]


def caret_rect() -> tuple[int, int, int, int] | None:
    """Rectangle du curseur de saisie de la fenetre active (ecran), ou None."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class _GuiInfo(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
                        ("hwndActive", wintypes.HWND), ("hwndFocus", wintypes.HWND),
                        ("hwndCapture", wintypes.HWND), ("hwndMenuOwner", wintypes.HWND),
                        ("hwndMoveSize", wintypes.HWND), ("hwndCaret", wintypes.HWND),
                        ("rcCaret", wintypes.RECT)]

        info = _GuiInfo()
        info.cbSize = ctypes.sizeof(info)
        user32 = ctypes.windll.user32
        if not user32.GetGUIThreadInfo(0, ctypes.byref(info)) or not info.hwndCaret:
            return None
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(info.hwndCaret, ctypes.byref(pid))
        if pid.value == os.getpid():
            return None                       # nos propres fenetres (saisie de l'orbe...)
        top_left = wintypes.POINT(info.rcCaret.left, info.rcCaret.top)
        bottom_right = wintypes.POINT(info.rcCaret.right, info.rcCaret.bottom)
        user32.ClientToScreen(info.hwndCaret, ctypes.byref(top_left))
        user32.ClientToScreen(info.hwndCaret, ctypes.byref(bottom_right))
        height = bottom_right.y - top_left.y
        width = bottom_right.x - top_left.x
        if not 6 <= height <= 120 or width > 60:
            return None                       # pas un vrai curseur de texte
        return top_left.x, top_left.y, max(bottom_right.x, top_left.x + 2), bottom_right.y
    except Exception:
        return None


__all__ = ["Life", "World", "gesture_for", "work_area", "caret_rect", "GESTURES"]
