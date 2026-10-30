"""Horizon 6 - orbe flottante sur le bureau (Tkinter, bibliotheque standard).

Jarvis tient dans une simple sphere, sans fenetre ni navigateur :

  * **clic** : Jarvis ecoute le micro puis repond a voix haute ; un clic
    pendant qu'il parle coupe la voix ;
  * **glisser** : deplace l'orbe (la position est retenue) ;
  * **double-clic** : historique des derniers echanges ;
  * **clic droit** : menu (ecrire un message, couper la voix, quitter) ;
  * **« Hey Jarvis »** (detection locale, voir `wake.py`) ou le raccourci
    global **Ctrl+Espace** (`hotkey.py`) : comme un clic, sans viser l'orbe.

La couleur de l'orbe dit l'etat (bleu pret, vert ecoute, orange reflexion,
cyan parole) et une bulle discrete affiche la question et la reponse, puis
s'efface d'elle-meme.

Le « cerveau » est la meme session que l'interface web (`web.JarvisWeb`) :
memoire, outils, repli de modele et voix sont donc identiques. Tkinter n'etant
pas *thread-safe*, l'orbe ne recoit les evenements des fils de travail que par
une file, consommee periodiquement par `after`.
"""

from __future__ import annotations

import json
import math
import queue
import random
import threading
import time
from pathlib import Path

from . import briefing, layered
from . import orb_themes
from . import tray as tray_mod
from . import orb_life
from . import orb_mood
from . import orb_render
from . import wake as wake_mod
from .gui import tk
from .hotkey import GlobalHotkey
from .text import log
from .web import JarvisWeb

SIZE = 112                 # cote de la fenetre (pixels), dessin de secours
FANCY_SIZE = 168           # rendu lisse : place pour le halo
FANCY_RADIUS = 42
RADIUS = 40                # rayon de la sphere au repos
KEY = "#010203"            # couleur rendue transparente (Windows)
RINGS = 22                 # anneaux du degrade (effet de volume)
TICK_MS = 40
BUBBLE_HIDE_MS = 9000
DRAG_THRESHOLD = 4
CLICK_DELAY_MS = 260       # attente d'un eventuel double-clic
FOLLOW_UP_DELAY_MS = 350   # pause avant de reecouter apres une reponse
PULSE_DECAY = 0.9          # amortissement d'un sursaut a chaque image
SIGH_EVERY = (8.0, 16.0)   # respiration spontanee au repos (secondes)
SIGH_ENERGY = 0.3
AUTO_HIDE_CHOICES = (0, 30, 60, 300)   # secondes (0 = jamais)
FADE_OUT_STEP = 0.06       # fondu de disparition (~0,7 s)
FADE_IN_STEP = 0.1
ULTRA_TICK_MS = 25         # 40 images/s quand la carte graphique dessine
HISTORY_ITEMS = 40
POSITION_FILE = Path(__file__).resolve().parent.parent / ".jarvis_orb.json"

# (bord, milieu, reflet) : la meme palette que la fenetre et la page web.
PALETTE = {
    "ready": ("#14205a", "#0a84ff", "#d6e4ff"),
    "listening": ("#0b3d24", "#30d158", "#dbfbe6"),
    "thinking": ("#4d2f0e", "#ff9f0a", "#ffe9c7"),
    "speaking": ("#0f3150", "#64d2ff", "#dff4ff"),
}
BUBBLE_BG = "#16161d"
BUBBLE_FG = "#f5f5f7"
BUBBLE_DIM = "#8e8e99"
# Couleurs des panneaux Tk (historique, saisie, menu) par theme.
THEME_COLORS = {
    "jarvis": {"bg": "#06101e", "fg": "#def6ff", "dim": "#78aac4", "accent": "#1ec8ff",
               "active": "#0d2a44"},
    "siri": {"bg": BUBBLE_BG, "fg": BUBBLE_FG, "dim": BUBBLE_DIM, "accent": "#0a84ff",
             "active": "#26262e"},
    "aurore": {"bg": "#f5f7fc", "fg": "#1c2030", "dim": "#6e7486", "accent": "#5b7cfa",
               "active": "#e3e9fb"},
    "opale": {"bg": "#fbf8fc", "fg": "#2a2230", "dim": "#7a7086", "accent": "#b07cf0",
              "active": "#f1e8f8"},
    "nebuleuse": {"bg": "#0f0d24", "fg": "#ece8ff", "dim": "#8f88b8", "accent": "#5ad8ff",
                  "active": "#221d4a"},
    "plasma": {"bg": "#0b0f1e", "fg": "#e6f6ff", "dim": "#8aa2c0", "accent": "#36e0ea",
               "active": "#1a2342"},
}
orb_themes.register({}, {}, THEME_COLORS)
FONT = "Segoe UI"
LIFE_TEXT = {"fr": {"welcome": "Re-bonjour !", "sleep": "Zzz…"},
             "en": {"welcome": "Welcome back!", "sleep": "Zzz…"}}


def _mix(a: str, b: str, t: float) -> str:
    """Couleur intermediaire entre `a` et `b` (0 <= t <= 1)."""
    t = min(max(t, 0.0), 1.0)
    ca = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(ca, cb))


def sphere_rings(state: str, radius: float, cx: float, cy: float) -> list:
    """Cercles concentriques (x1, y1, x2, y2, couleur) qui dessinent la sphere.

    Chaque anneau est plus petit, plus clair et decale vers le haut a gauche :
    l'empilement donne une sphere eclairee, sans aucune image.
    """
    edge, mid, core = PALETTE.get(state, PALETTE["ready"])
    rings = []
    for index in range(RINGS):
        t = index / (RINGS - 1)
        r = radius * (1.0 - 0.82 * t)
        shift = radius * 0.30 * t
        color = _mix(edge, mid, t / 0.55) if t < 0.55 else _mix(mid, core, (t - 0.55) / 0.45)
        x, y = cx - shift, cy - shift
        rings.append((x - r, y - r, x + r, y + r, color))
    return rings


def load_settings() -> dict:
    """Reglages de l'orbe (position, voix, theme...) ; {} si absents."""
    try:
        data = json.loads(POSITION_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_settings(**updates) -> None:
    data = load_settings()
    data.update(updates)
    try:
        POSITION_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def apply_saved_settings(args) -> None:
    """Le dernier choix fait dans le menu de l'orbe l'emporte au lancement."""
    settings = load_settings()
    voice = settings.get("voice")
    if voice == "sapi":
        args.tts = "sapi"
    elif voice:
        args.tts, args.piper_voice = "auto", voice
    if settings.get("theme") in THEME_COLORS:
        args.orb_theme = settings["theme"]
    if isinstance(settings.get("follow_up"), bool):
        args.follow_up = settings["follow_up"]
    if settings.get("quality") in ("ultra", "standard"):
        args.orb_quality = settings["quality"]
    if isinstance(settings.get("auto_hide"), (int, float)):
        args.auto_hide = settings["auto_hide"]


def load_position() -> tuple[int, int] | None:
    data = load_settings()
    try:
        return int(data["x"]), int(data["y"])
    except Exception:
        return None


def save_position(x: int, y: int) -> None:
    save_settings(x=x, y=y)


class Orb:
    """Fenetre ronde, sans bordure, toujours au premier plan."""

    def __init__(self, root, app: JarvisWeb, strings: dict, fancy: bool = False,
                 theme: str = "opale", quality: str = "ultra"):
        self.root = root
        self.quality = quality if quality in ("ultra", "standard") else "ultra"
        self.theme = theme if theme in THEME_COLORS else "opale"
        self.colors = THEME_COLORS[self.theme]
        # Rendu lisse (Pillow + fenetre transparente Windows) ou dessin Tk.
        self.fancy = bool(fancy)
        self.scale = 1.0
        if self.fancy:
            try:
                self.scale = max(1.0, float(root.winfo_fpixels("1i")) / 96.0)
            except Exception:
                self.scale = 1.0
        self.size = round(FANCY_SIZE * self.scale) if self.fancy else SIZE
        self.renderer = None
        self.layer = None
        self._bubble_layer = None
        self._bubble_message = ""
        self.app = app
        self.s = strings
        self.reminders = None     # ReminderStore, pour le journal
        self._journal = None
        self.inbox: queue.Queue = app.bus.subscribe()
        # Declencheurs venus d'autres fils (mot d'activation, raccourci).
        self.actions: queue.Queue = queue.Queue()
        self.detector = None
        self.wake_label = "Jarvis"
        self.state = "ready"
        self.phase = 0.0
        self.closing = False
        self._press = None        # (x, y) du clic, pour distinguer clic et glisser
        self._dragged = False
        self._bubble = None
        self._bubble_text = None
        self._hide_job = None
        self._reply = ""
        self._prompt = None
        self._history = None
        self._click_job = None
        self._skip_release = False
        self._level = 0.0
        self.voice_turn = False       # la conversation en cours a commence a la voix
        self._pulse = 0.0             # sursaut en cours (0..1), s'amortit
        self._hover = 0.0             # souris au-dessus (lisse)
        self._hover_target = 0.0
        self._next_sigh = random.uniform(*SIGH_EVERY)
        self.auto_hide = 0.0          # secondes d'inactivite avant masquage (0 = jamais)
        self.can_recall = False       # « Jarvis », raccourci ou icone pour la rappeler
        self._last_active = time.monotonic()
        self._fade = 1.0              # opacite globale (fondus)
        self._fading_out = False
        self.tick_ms = TICK_MS
        self.follow_up = True         # reecouter apres chaque reponse vocale

        root.title("Jarvis")
        root.overrideredirect(True)
        root.configure(bg=KEY)
        attributes = [("-topmost", True)]
        if not self.fancy:
            attributes.append(("-transparentcolor", KEY))
        for attribute, value in attributes:
            try:
                root.attributes(attribute, value)
            except Exception:  # transparence indisponible hors Windows
                pass

        self.canvas = tk.Canvas(root, width=self.size, height=self.size, bg=KEY,
                                highlightthickness=0, bd=0, cursor="hand2")
        self.canvas.pack()
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Double-Button-1>", self._on_double)
        self.canvas.bind("<Button-3>", self._on_menu)
        self.canvas.bind("<Enter>", self._on_enter)
        self.canvas.bind("<Leave>", lambda _e: setattr(self, "_hover_target", 0.0))
        root.bind("<Escape>", lambda _e: self.app.stop())

        self.mute_var = tk.BooleanVar(value=app.muted)
        self.wake_var = tk.BooleanVar(value=True)
        self.follow_var = tk.BooleanVar(value=True)
        self.args = None
        self.tray = None
        self.hidden = False
        self.settings_menu = None
        self.menu_panel = None          # orb_menu.OrbMenu ouvert
        self.voices: list = []          # [(libelle, spec)] des voix installees
        self.voice_choice = ""
        self.intro_choice = load_settings().get("intro", "anneaux")
        self.auto_hide_choices = AUTO_HIDE_CHOICES
        self.glass = load_settings().get("glass", True) is not False   # coque de verre
        self.moods = load_settings().get("moods", True) is not False   # teinte heure / meteo
        self.mood = None

        self._place()
        # Vie de l'orbe : balades, physique, gestes, sommeil (voir orb_life).
        self.behavior = load_settings().get("behavior", "vivante")
        self.life = None
        self._life_clock = time.monotonic()
        self._sensed = {"at": 0.0, "idle": 0.0, "caret": None}
        self._drag_trace: list[tuple[float, int, int]] = []
        self._reply_started = False
        if self.fancy:
            self._make_renderer()
            self.layer = layered.LayeredWindow(root)

    # -- position ----------------------------------------------------------- #
    def _place(self) -> None:
        self.root.update_idletasks()
        width, height = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        position = load_position()
        if position is None:
            position = (width - self.size - 40, height - self.size - 90)
        x = min(max(position[0], 0), width - self.size)
        y = min(max(position[1], 0), height - self.size)
        self.root.geometry(f"{self.size}x{self.size}+{x}+{y}")

    # -- dessin ------------------------------------------------------------- #
    def draw(self) -> None:
        if self.fancy:
            depth = self.life.sleep_depth if self.life is not None else 0.0
            self.phase += self.tick_ms / 1000.0 * (1.0 - 0.7 * depth)   # endormie : lente
            self._animate()
            image = self.renderer.frame(self.state, self.phase, self._voice_level(),
                                        hover=self._hover, pulse=self._pulse)
            if self.moods and self.mood is not None:
                image = orb_mood.apply_tint(image, *self.mood.current())
            fade = max(0.0, self._fade) * (1.0 - 0.35 * depth)          # endormie : pale
            if fade < 1.0:
                image = image.copy()
                image.putalpha(image.getchannel("A").point(lambda v: int(v * fade)))
            self.layer.show(image)
            return
        canvas = self.canvas
        canvas.delete("all")
        busy = self.state != "ready"
        speed = {"ready": 0.05, "listening": 0.22, "thinking": 0.16,
                 "speaking": 0.30}.get(self.state, 0.05)
        self.phase += speed
        pulse = math.sin(self.phase) * (3.0 if busy else 1.5)
        center = SIZE / 2
        radius = RADIUS + pulse
        for x1, y1, x2, y2, color in sphere_rings(self.state, radius, center, center):
            canvas.create_oval(x1, y1, x2, y2, fill=color, outline="")
        if busy:  # arc lumineux qui tourne autour de la sphere
            _edge, mid, core = PALETTE[self.state]
            r = RADIUS + 9
            start = (self.phase * 40) % 360
            canvas.create_arc(center - r, center - r, center + r, center + r,
                              start=start, extent=110, style="arc",
                              outline=core, width=3)
            canvas.create_arc(center - r, center - r, center + r, center + r,
                              start=start + 180, extent=60, style="arc",
                              outline=mid, width=2)

    def _voice_level(self) -> float | None:
        """Volume lisse (monte vite, retombe doucement) : la voix de Jarvis
        quand il parle, celle de l'utilisateur (micro) quand il ecoute."""
        if self.state == "speaking":
            raw = getattr(self.app.speech, "level", None)
        elif self.state == "listening":
            raw = getattr(self.detector, "level", None)
        else:
            self._level = 0.0
            return None
        if raw is None:
            return None
        self._level = max(float(raw), self._level * 0.82)
        return self._level

    def bump(self, energy: float = 1.0) -> None:
        """Petit sursaut de l'orbe (mot entendu, clic, debut de reponse...)."""
        self._pulse = max(self._pulse, energy)

    def _animate(self) -> None:
        """Fait vivre l'orbe : sursauts qui s'amortissent, survol, respirations."""
        self._pulse *= PULSE_DECAY
        self._hover += (self._hover_target - self._hover) * 0.2
        if self.state == "ready" and not self.hidden and self.phase >= self._next_sigh:
            self.bump(SIGH_ENERGY)
            self._next_sigh = self.phase + random.uniform(*SIGH_EVERY)

    def tick(self) -> None:
        if self.closing:
            return
        try:
            while True:
                self.handle(self.inbox.get_nowait())
        except queue.Empty:
            pass
        try:
            while True:
                self.trigger(self.actions.get_nowait())
        except queue.Empty:
            pass
        if self.closing:
            return
        self._auto_hide_step()
        if not self.hidden:
            self._live()
            self.draw()
        self.root.after(self.tick_ms, self.tick)

    # -- vie autonome ------------------------------------------------------- #
    def _ensure_life(self):
        if self.life is None:
            self.root.update_idletasks()
            x, y = self.root.winfo_x(), self.root.winfo_y()
            screen = (self.root.winfo_screenwidth(), self.root.winfo_screenheight())
            self.life = orb_life.Life((x, y), self.size,
                                      orb_life.work_area(x + self.size // 2, y + self.size // 2,
                                                         screen),
                                      scale=self.scale, calm=self.behavior == "calme")
        return self.life

    def _live(self) -> None:
        """Une image de vie : la fenetre suit la position calculee par orb_life."""
        life = self._ensure_life()
        now = time.monotonic()
        dt, self._life_clock = now - self._life_clock, now
        if now - self._sensed["at"] > 0.3:           # capteurs : 3 fois par seconde
            from .proactive import idle_seconds

            self._sensed = {"at": now, "idle": idle_seconds(), "caret": orb_life.caret_rect()}
        try:
            mouse = self.root.winfo_pointerxy()
        except Exception:
            mouse = None
        busy = (self._press is not None or self._prompt is not None
                or (self.menu_panel is not None and self.menu_panel.alive()))
        world = orb_life.World(state=self.state, hovered=self._hover_target > 0.5, busy=busy,
                               mouse=mouse, user_idle=self._sensed["idle"],
                               caret=None if busy else self._sensed["caret"],
                               hour=time.localtime().tm_hour)
        x, y = life.step(dt, world)
        if (x, y) != (self.root.winfo_x(), self.root.winfo_y()) and self._press is None:
            self.root.geometry(f"+{x}+{y}")
            if self._bubble is not None and self._bubble.winfo_viewable():
                self._move_bubble()
        for event in life.take_events():
            if event == "settled":
                save_position(int(life.home[0]), int(life.home[1]))
            elif event == "welcome":
                self.show_bubble(LIFE_TEXT[self._lang()]["welcome"], dim=True)
            elif event == "sleep":
                self.show_bubble(LIFE_TEXT[self._lang()]["sleep"], dim=True)
            elif event == "wake":
                self.bump(0.9)

    def _lang(self) -> str:
        return "fr" if getattr(self.app.args, "lang", "fr") == "fr" else "en"

    def set_behavior(self, behavior: str) -> None:
        """Vivante (balades, curiosite, sommeil) ou Calme ; retenu."""
        self.behavior = "calme" if behavior == "calme" else "vivante"
        save_settings(behavior=self.behavior)
        if self.life is not None:
            self.life.calm = self.behavior == "calme"
            if self.life.calm:
                self.life.asleep = False
                self.life.mode, self.life.target = "back", self.life.home

    # -- masquage automatique ------------------------------------------------ #
    def touch(self) -> None:
        """Note une activite : repousse le masquage automatique."""
        self._last_active = time.monotonic()
        self._fading_out = False

    def _on_enter(self, _event=None) -> None:
        self._hover_target = 1.0
        self.touch()

    def is_idle(self, now: float | None = None) -> bool:
        """Vrai quand rien ne se passe depuis `auto_hide` secondes."""
        if not self.auto_hide or self.hidden or not self.can_recall:
            return False
        if self.state != "ready" or self.app._busy.locked():
            return False
        if self._prompt is not None or self._history is not None:
            return False
        if self._bubble is not None and self._bubble.winfo_viewable():
            return False
        now = time.monotonic() if now is None else now
        return now - self._last_active >= self.auto_hide

    def _auto_hide_step(self) -> None:
        if not self._fading_out and self.is_idle():
            self._fading_out = True
        if self._fading_out:
            if not self.fancy:
                self.hide()
                return
            self._fade -= FADE_OUT_STEP
            if self._fade <= 0:
                self.hide()
        elif self._fade < 1.0:
            self._fade = min(1.0, self._fade + FADE_IN_STEP)

    # -- evenements de la session ------------------------------------------- #
    def handle(self, event: dict) -> None:
        kind = event.get("type")
        self.touch()
        if self.life is not None and kind in ("state", "user", "reply"):
            self.life.interact()
        if kind == "user":
            self._reply_started = False
        elif kind == "reply" and not self._reply_started and self.life is not None:
            self._reply_started = True
            gesture = orb_life.gesture_for(event.get("text", ""))   # « Oui » : hochement
            if gesture:
                self.life.play(gesture)
        if kind == "state":
            self.state = event.get("state", "ready")
            if self.state == "listening":
                self.show_bubble(self.s["orb_listening"], dim=True, keep=True)
        elif kind == "user":
            self._reply = ""
            self.show_bubble(f"« {event.get('text', '')} »", dim=True, keep=True)
        elif kind == "reply":
            self._reply = (self._reply + " " + event.get("text", "")).strip()
            self.show_bubble(self._reply, keep=True)
        elif kind == "system":
            text = event.get("text", "")
            if text and not self._reply:
                self.show_bubble(text, dim=True, keep=True)
        elif kind == "finished":
            self.state = "ready"
            if event.get("heard", True) and self.voice_turn and self.follow_up:
                self.root.after(FOLLOW_UP_DELAY_MS, self._follow_up)
            else:
                self.voice_turn = False
            if self._bubble is not None and self._bubble.winfo_viewable():
                self._schedule_hide()
        elif kind == "detail":
            self.show_detail(event.get("text", ""))
        elif kind == "closed":
            self.close()

    # -- souris ------------------------------------------------------------- #
    def _on_press(self, event) -> None:
        self.close_menu()
        self.touch()
        self._press = (event.x_root, event.y_root, self.root.winfo_x(),
                       self.root.winfo_y())
        self._dragged = False
        self._drag_trace = [(time.monotonic(), event.x_root, event.y_root)]
        if self.life is not None:
            self.life.interact()

    def _on_drag(self, event) -> None:
        if self._press is None:
            return
        x0, y0, wx, wy = self._press
        dx, dy = event.x_root - x0, event.y_root - y0
        if not self._dragged and abs(dx) + abs(dy) < DRAG_THRESHOLD:
            return
        self._dragged = True
        self.root.geometry(f"+{wx + dx}+{wy + dy}")
        self._move_bubble()
        now = time.monotonic()
        self._drag_trace = [p for p in self._drag_trace if now - p[0] < 0.12]
        self._drag_trace.append((now, event.x_root, event.y_root))

    def _on_release(self, _event) -> None:
        if self._dragged:
            x, y = self.root.winfo_x(), self.root.winfo_y()
            vx = vy = 0.0
            if len(self._drag_trace) >= 2:                 # vitesse des 120 dernieres ms
                (t0, x0, y0), (t1, x1, y1) = self._drag_trace[0], self._drag_trace[-1]
                if t1 - t0 > 0.01:
                    vx, vy = (x1 - x0) / (t1 - t0), (y1 - y0) / (t1 - t0)
            thrown = self._ensure_life().throw(x, y, vx, vy)
            if not thrown:
                save_position(x, y)
        elif self._skip_release:
            self._skip_release = False     # fin d'un double-clic
        else:
            # Le clic simple attend un instant : un double-clic l'annule.
            self._click_job = self.root.after(CLICK_DELAY_MS, self._single_click)
        self._press = None
        self._dragged = False

    def _single_click(self) -> None:
        self._click_job = None
        self.on_click()

    def _on_double(self, _event) -> None:
        if self._click_job is not None:
            self.root.after_cancel(self._click_job)
            self._click_job = None
        self._skip_release = True
        self.toggle_history()

    # -- historique --------------------------------------------------------- #
    def toggle_history(self) -> None:
        """Affiche (ou ferme) la liste des derniers echanges."""
        c = self.colors
        if self._history is not None:
            self._history.destroy()
            self._history = None
            return
        panel = tk.Toplevel(self.root)
        panel.overrideredirect(True)
        panel.attributes("-topmost", True)
        panel.configure(bg=c["bg"], padx=2, pady=2, highlightthickness=1,
                        highlightbackground=c["accent"], highlightcolor=c["accent"])
        header = tk.Frame(panel, bg=c["bg"])
        header.pack(fill="x")
        tk.Label(header, text=self.s["orb_history"], bg=c["bg"], fg=c["fg"],
                 font=(FONT, 11, "bold"), padx=12, pady=8).pack(side="left")
        close = tk.Label(header, text="\u2715", bg=c["bg"], fg=c["dim"],
                         font=(FONT, 11), padx=12, cursor="hand2")
        close.pack(side="right")
        close.bind("<Button-1>", lambda _e: self.toggle_history())
        text = tk.Text(panel, width=46, height=18, wrap="word", bg=c["bg"],
                       fg=c["fg"], relief="flat", font=(FONT, 10), padx=12,
                       pady=4, highlightthickness=0, cursor="arrow")
        text.pack(fill="both", expand=True)
        text.tag_configure("who", foreground=c["accent"], font=(FONT, 9, "bold"),
                           spacing1=8)
        text.tag_configure("system", foreground=c["dim"])
        names = {"user": self.s["gui_you"], "jarvis": self.s["gui_jarvis"]}
        items = self.app.transcript[-HISTORY_ITEMS:]
        if not items:
            text.insert("end", self.s["orb_history_empty"], "system")
        for item in items:
            kind = item.get("kind")
            if kind in names:
                text.insert("end", names[kind] + "\n", "who")
                text.insert("end", item.get("text", "") + "\n")
            else:
                text.insert("end", item.get("text", "") + "\n", "system")
        text.configure(state="disabled")
        text.see("end")
        panel.bind("<Escape>", lambda _e: self.toggle_history())
        self._history = panel
        panel.update_idletasks()
        x, y = self._side_position(panel.winfo_reqwidth(), panel.winfo_reqheight())
        panel.geometry(f"+{x}+{y}")
        panel.focus_force()

    def intro_accent(self) -> str:
        """Couleur vive de l'intro : celle du theme (cyan pour les themes clairs)."""
        accent = self.colors.get("accent", "#1ec8ff")
        return "#1ec8ff" if self.theme in orb_render.LIGHT_BUBBLE_THEMES else accent

    def show_detail(self, markdown: str) -> None:
        """Fenetre de la reponse complete (titres, listes) pres de l'orbe."""
        from .journal import DetailView

        if not markdown.strip():
            return
        if getattr(self, "_detail_view", None) is not None and self._detail_view.alive():
            self._detail_view.close()
        self._detail_view = DetailView(self.root, markdown, self.colors,
                                       getattr(self.app.args, "lang", "fr"))

    def open_journal(self) -> None:
        """Fenetre « Journal » : conversations, rappels a venir, souvenirs."""
        from .journal import Journal

        if self._journal is not None and self._journal.alive():
            self._journal.lift()
            return
        self._journal = Journal(self.root, self.app, self.colors,
                                getattr(self.app.args, "lang", "fr"), self.reminders)

    def _on_menu(self, event) -> None:
        self.touch()
        self.open_menu(event.x_root, event.y_root)

    def open_menu(self, x: int, y: int):
        """Panneau graphique du clic droit (voir orb_menu)."""
        from .orb_menu import OrbMenu

        self.close_menu()
        self.menu_panel = OrbMenu(self, x, y)
        return self.menu_panel

    def close_menu(self) -> None:
        if self.menu_panel is not None:
            self.menu_panel.close()
            self.menu_panel = None

    # -- actions ------------------------------------------------------------ #
    def on_click(self) -> None:
        """Clic : ecouter ; pendant une reponse, couper la voix."""
        self.bump(0.8)
        if self.state in ("thinking", "speaking", "listening"):
            self.app.stop()
            return
        if self.app.listener is None:
            self.open_prompt()
            return
        if not self.app.listen():
            self.show_bubble(self.s["web_busy"], dim=True)

    def trigger(self, source) -> None:
        """Mot d'activation ou raccourci : ecouter (le raccourci coupe aussi).

        `source` vaut "hotkey", "wake", ou ("wake", audio) quand la question
        a ete dite dans la foulee du mot : on y repond sans reecouter.
        """
        self.touch()
        if source == "show":
            self.show()
            return
        if source == "quit":
            self.quit()
            return
        self.show()  # appelee alors qu'elle etait masquee : elle revient
        question = b""
        if isinstance(source, tuple) and source[0] == "brief":
            self.bump(0.7)
            self.show_bubble(source[1] + (source[2] if len(source) > 2 else ""))
            self.app.announce(source[1])
            return
        if isinstance(source, tuple):
            source, question = source
        if self.state != "ready":
            if source == "hotkey":
                self.app.stop()
            return
        if self.app.listener is None:
            self.open_prompt()
            return
        _chime()
        self.bump(1.0)
        self.voice_turn = True
        if question:
            self.app.answer_audio(question)
        else:
            self.app.listen()

    def _follow_up(self) -> None:
        """Ecoute de nouveau apres une reponse vocale, sans mot d'activation."""
        if self.closing or self.state != "ready" or not self.voice_turn:
            return
        if not self.app.listen(follow_up=True):
            self.voice_turn = False

    # -- reglages ----------------------------------------------------------- #
    def build_settings(self, args, current_voice: str | None) -> None:
        """Prepare les reglages du menu : voix installees, choix courants."""
        from . import tts as tts_mod

        self.args = args
        self.follow_var.set(bool(self.follow_up))
        voices = tts_mod.installed_voices(getattr(args, "lang", "fr"))
        if voices and hasattr(self.app.speech, "set_factory"):
            self.voices = voices + [(self.s["orb_voice_windows"], "sapi")]
        self.voice_choice = current_voice or ""

    def auto_hide_label(self, seconds: int) -> str:
        if not seconds:
            return self.s["orb_never"]
        if seconds >= 60:
            return self.s["orb_minutes"].format(n=seconds // 60).split(" ", 1)[-1]
        return self.s["orb_seconds"].format(n=seconds).split(" ", 1)[-1]

    def set_moods(self, on: bool) -> None:
        """Humeurs : teinte discrete selon l'heure et la meteo, retenue."""
        self.moods = bool(on)
        save_settings(moods=self.moods)

    def set_glass(self, on: bool) -> None:
        """Active ou retire l'effet verre, a chaud, et le retient."""
        self.glass = bool(on)
        save_settings(glass=self.glass)
        if self.fancy:
            self._make_renderer()

    def set_intro(self, style: str) -> None:
        """Choisit l'intro du demarrage, la retient, et la montre tout de suite."""
        from . import cinematic

        self.intro_choice = style
        save_settings(intro=style)
        if self.fancy and style in cinematic.STYLES:
            self.root.update_idletasks()
            center = (self.root.winfo_x() + self.size // 2, self.root.winfo_y() + self.size // 2)
            cinematic.play(self.root, style, center, self.size, self.intro_accent(),
                           getattr(self.args, "lang", "fr"),
                           cinematic.system_lines(getattr(self.args, "lang", "fr"), 0, "", "", True))

    def set_voice(self, spec: str) -> None:
        """Change la voix tout de suite, la retient, et la fait entendre."""
        from . import tts as tts_mod

        try:
            factory = tts_mod.factory_for(spec, self.args, getattr(self.args, "lang", "fr"))
        except Exception as exc:
            log(f"[tts] {exc}")
            return
        self.app.speech.set_factory(factory)
        self.voice_choice = spec
        save_settings(voice=spec)
        log(f"[tts] nouvelle voix : {spec}")
        self.app.announce(self.s["orb_voice_sample"])

    def set_theme(self, theme: str) -> None:
        """Change l'apparence a chaud (orbe, bulle, menus) et la retient."""
        if theme not in THEME_COLORS:
            return
        self.theme = theme
        self.colors = THEME_COLORS[theme]
        if self.fancy:
            self._make_renderer()
        save_settings(theme=theme)

    def _make_renderer(self) -> None:
        self.renderer = orb_render.make_renderer(self.theme, self.size,
                                                 round(FANCY_RADIUS * self.scale),
                                                 quality=self.quality, glass=self.glass)
        gpu = type(self.renderer).__name__ == "GpuRenderer"
        # Rendu sur la carte graphique : animation plus fluide.
        self.tick_ms = ULTRA_TICK_MS if gpu else TICK_MS

    def set_quality(self, quality: str) -> None:
        """Ultra (carte graphique) ou Standard (processeur), a chaud."""
        if quality not in ("ultra", "standard"):
            return
        self.quality = quality
        if self.fancy:
            self._make_renderer()
        save_settings(quality=quality)

    def set_auto_hide(self, seconds: float) -> None:
        self.auto_hide = float(seconds)
        self.touch()
        save_settings(auto_hide=int(seconds))

    def _on_follow_toggle(self) -> None:
        self.follow_up = bool(self.follow_var.get())
        save_settings(follow_up=self.follow_up)

    # -- masquer / afficher (icone de notification) ------------------------- #
    def hide(self) -> None:
        self.hidden = True
        self._fading_out = False
        self._fade = 0.0
        self.hide_bubble()
        if self._history is not None:
            self.toggle_history()
        self.root.withdraw()

    def show(self) -> None:
        if not self.hidden:
            return
        self.hidden = False
        self._fade = 0.0 if self.fancy else 1.0   # reapparait en fondu
        self.touch()
        self.root.deiconify()
        self.root.attributes("-topmost", True)

    def attach_detector(self, detector) -> None:
        """Ajoute au menu l'interrupteur du mot d'activation."""
        self.detector = detector

    def _on_wake_toggle(self) -> None:
        if self.detector is not None:
            self.detector.enabled = bool(self.wake_var.get())

    def is_listening_paused(self) -> bool:
        """Le detecteur se tait pendant que Jarvis ecoute, pense ou parle."""
        return (self.state != "ready" or self.app._busy.locked()
                or bool(getattr(self.app.speech, "speaking", False)))

    def _on_mute(self) -> None:
        self.app.set_muted(bool(self.mute_var.get()))

    def open_prompt(self) -> None:
        """Petit champ de saisie colle a l'orbe (Entree envoie, Echap ferme)."""
        c = self.colors
        if self._prompt is not None:
            self._prompt.focus_force()
            return
        prompt = tk.Toplevel(self.root)
        prompt.overrideredirect(True)
        prompt.attributes("-topmost", True)
        prompt.configure(bg=c["bg"], padx=10, pady=8, highlightthickness=1,
                         highlightbackground=c["accent"], highlightcolor=c["accent"])
        entry = tk.Entry(prompt, width=34, bg=c["bg"], fg=c["fg"],
                         insertbackground=c["fg"], relief="flat",
                         font=(FONT, 11))
        entry.pack()
        entry.insert(0, "")

        def send(_event=None) -> None:
            text = entry.get().strip()
            close()
            if text and not self.app.send(text):
                self.show_bubble(self.s["web_busy"], dim=True)

        def close(_event=None) -> None:
            prompt.destroy()
            self._prompt = None

        entry.bind("<Return>", send)
        entry.bind("<Escape>", close)
        entry.bind("<FocusOut>", close)
        self._prompt = prompt
        x, y = self._side_position(300, 40)
        prompt.geometry(f"+{x}+{y}")
        prompt.after(30, entry.focus_force)

    def quit(self) -> None:
        self.app.quit(say_goodbye=True)

    def close(self) -> None:
        if self.closing:
            return
        self.closing = True
        self.app.bus.unsubscribe(self.inbox)
        try:
            self.root.destroy()
        except Exception:
            pass

    # -- bulle -------------------------------------------------------------- #
    def _side_position(self, width: int, height: int) -> tuple[int, int]:
        """Place un element a gauche de l'orbe (a droite si pas de place)."""
        ox, oy = self.root.winfo_x(), self.root.winfo_y()
        x = ox - width - 6
        if x < 0:
            x = ox + self.size + 6
        y = oy + self.size // 2 - height // 2
        screen_h = self.root.winfo_screenheight()
        return x, min(max(y, 0), screen_h - height)

    def show_bubble(self, text: str, dim: bool = False, keep: bool = False) -> None:
        self.touch()
        c = self.colors
        self._bubble_message = text
        if self._bubble is None:
            bubble = tk.Toplevel(self.root)
            bubble.overrideredirect(True)
            bubble.attributes("-topmost", True)
            bubble.configure(bg=c["bg"])
            bubble.bind("<Button-1>", lambda _e: self.hide_bubble())
            if self.fancy:
                self._bubble_layer = layered.LayeredWindow(bubble)
            else:
                label = tk.Label(bubble, bg=c["bg"], fg=c["fg"], justify="left",
                                 wraplength=300, font=(FONT, 11), padx=14, pady=10)
                label.pack()
                label.bind("<Button-1>", lambda _e: self.hide_bubble())
                self._bubble_text = label
            self._bubble = bubble
        self._bubble.deiconify()
        if self.fancy:
            image = orb_render.make_bubble(self.theme, text, dim=dim, scale=self.scale)
            self._bubble_layer.show(image)
        else:
            self._bubble_text.configure(text=text, fg=c["dim"] if dim else c["fg"])
        self._move_bubble()
        if self._hide_job is not None:
            self.root.after_cancel(self._hide_job)
            self._hide_job = None
        if not keep:
            self._schedule_hide()

    def _move_bubble(self) -> None:
        if self._bubble is None:
            return
        if self.fancy and self._bubble_layer is not None:
            width, height = self._bubble_layer.size
        else:
            self._bubble.update_idletasks()
            width = self._bubble.winfo_reqwidth()
            height = self._bubble.winfo_reqheight()
        x, y = self._side_position(width, height)
        self._bubble.geometry(f"+{x}+{y}")

    def _schedule_hide(self) -> None:
        if self._hide_job is not None:
            self.root.after_cancel(self._hide_job)
        self._hide_job = self.root.after(BUBBLE_HIDE_MS, self.hide_bubble)

    def hide_bubble(self) -> None:
        self._hide_job = None
        if self._bubble is not None:
            self._bubble.withdraw()


def pretty_hotkey(combo: str, lang: str = "fr") -> str:
    """« ctrl+space » -> « Ctrl+Espace » (ou « Ctrl+Space » en anglais)."""
    names = {"space": "Espace" if lang == "fr" else "Space", "ctrl": "Ctrl",
             "control": "Ctrl", "alt": "Alt", "shift": "Maj" if lang == "fr" else "Shift",
             "win": "Win", "enter": "Entrée" if lang == "fr" else "Enter"}
    parts = [part.strip().lower() for part in (combo or "").split("+") if part.strip()]
    return "+".join(names.get(part, part.upper()) for part in parts)


def _chime() -> None:
    """Petit son discret : « je t'ecoute » (Windows ; sinon rien)."""
    try:
        import winsound

        winsound.PlaySound("SystemAsterisk",
                           winsound.SND_ALIAS | winsound.SND_ASYNC)
    except Exception:
        pass


def start_triggers(orb, args, listener):
    """Demarre le mot d'activation et le raccourci. Retourne ce qui tourne."""
    running = []
    words = [w.strip() for w in (getattr(args, "wake", "") or "").split(",")
             if w.strip()] or ["jarvis"]
    model = wake_mod.find_vosk_model(getattr(args, "lang", "fr")) \
        if wake_mod.vosk_available() else None
    if getattr(args, "wake_word", True) and listener is not None and model:
        detector = wake_mod.SpokenWakeDetector(
            on_wake=lambda question: orb.actions.put(("wake", question)),
            words=words, model_path=model, is_paused=orb.is_listening_paused,
        )
        detector.start()
        orb.wake_label = words[0].capitalize()
        orb.attach_detector(detector)
        running.append(detector)
    elif getattr(args, "wake_word", True) and listener is not None:
        if wake_mod.available():
            orb.wake_label = "Hey Jarvis"
            detector = wake_mod.WakeWordDetector(
                on_wake=lambda: orb.actions.put("wake"),
                is_paused=orb.is_listening_paused,
                threshold=float(getattr(args, "wake_threshold", None)
                                or wake_mod.DEFAULT_THRESHOLD),
            )
            detector.start()
            orb.attach_detector(detector)
            running.append(detector)
        else:
            log("[reveil] openWakeWord absent : clic ou raccourci seulement "
                "(pip install -r requirements-optional.txt)")
    combo = getattr(args, "hotkey", "") or ""
    if combo:
        try:
            hotkey = GlobalHotkey(combo, lambda: orb.actions.put("hotkey"))
            if hotkey.start():
                running.append(hotkey)
        except ValueError as exc:
            log(f"[raccourci] {exc}")
    return running


def run(args, strings, listener, speech, chain, history, memory=None, greet=True,
        reminders=None):
    """Affiche l'orbe jusqu'a « Quitter ». ``None`` si Tkinter est indisponible."""
    if tk is None:
        log("[orbe] Tkinter indisponible : retour au mode console")
        return None
    fancy = orb_render.available() and layered.supported()
    if fancy:
        layered.enable_dpi_awareness()  # avant la creation de la fenetre
    try:
        root = tk.Tk()
    except Exception as exc:  # pragma: no cover - pas d'affichage
        log(f"[orbe] fenetre impossible ({exc})")
        return None

    # Pas de salutation fixe : l'orbe annonce un briefing (heure, meteo...).
    app = JarvisWeb(args, strings, listener, speech, chain, history, memory, False)
    try:
        theme = getattr(args, "orb_theme", "opale") or "opale"
        orb = Orb(root, app, strings, fancy=fancy, theme=theme,
                  quality=getattr(args, "orb_quality", "ultra") or "ultra")
        orb.mood = orb_mood.Mood(city=lambda: briefing.profile_facts(memory).get("location"))
    except Exception as exc:  # rendu lisse impossible : dessin de secours
        log(f"[orbe] rendu lisse indisponible ({exc})")
        root.destroy()
        root = tk.Tk()
        orb = Orb(root, app, strings)
    log(strings["orb_hint"])
    orb.follow_up = bool(getattr(args, "follow_up", True))
    orb.reminders = reminders
    running = start_triggers(orb, args, listener)
    if tray_mod.available():
        icon = orb_render.make_renderer("jarvis", 64, 18, glass=False).frame("ready", 3.0) \
            if orb_render.available() else None
        if icon is not None:
            orb.tray = tray_mod.Tray(orb.actions, icon,
                                     {"show": strings["orb_show"], "quit": strings["orb_quit"]})
            if orb.tray.start():
                running.append(orb.tray)
                from . import notify

                notify.set_backend(orb.tray.notify)
            else:
                orb.tray = None
    orb.can_recall = bool(running)  # sans moyen de la rappeler, jamais de masquage auto
    orb.auto_hide = float(getattr(args, "auto_hide", 0) or 0) if orb.can_recall else 0.0
    current = getattr(args, "piper_voice", None) or ("sapi" if args.tts == "sapi" else None)
    orb.build_settings(args, current)
    if orb.fancy and orb.quality == "ultra":
        from .orb_menu import warm_previews

        warm_previews(root, round(30 * orb.scale), orb_render.THEMES)
    if greet:
        hints = []
        if orb.detector is not None:
            hints.append(strings["orb_say_hey"].format(word=orb.wake_label))
        if any(isinstance(item, GlobalHotkey) for item in running):
            hints.append(strings["orb_press_key"].format(key=pretty_hotkey(args.hotkey,
                                                                           args.lang)))
        tip = ("\n" + strings["orb_or"].join(hints) + ".") if hints else ""

        intro_done = threading.Event()
        from . import cinematic

        intro = load_settings().get("intro", cinematic.DEFAULT_STYLE)
        cinematic_on = orb.fancy and intro in cinematic.STYLES
        if cinematic_on:
            lines = cinematic.system_lines(
                args.lang, len(getattr(chain, "tools", []) or []),
                getattr(getattr(chain, "spec", None), "model", ""),
                (current or "piper").split(":")[0], orb.detector is not None)
            root.update_idletasks()
            center = (root.winfo_x() + orb.size // 2, root.winfo_y() + orb.size // 2)
            cinematic.play(root, intro, center, orb.size, orb.intro_accent(), args.lang,
                           lines, on_done=intro_done.set)
        else:
            intro_done.set()

        def prepare_briefing() -> None:
            try:
                from . import news

                text = briefing.gather(args.lang, memory, reminders,
                                       news_fn=news.fetch_headlines)
            except Exception as exc:
                log(f"[briefing] {exc}")
                text = strings["greeting"]
            intro_done.wait(8.0)
            if cinematic_on:
                from .cinematic import OPERATIONAL

                text = OPERATIONAL.get(args.lang, OPERATIONAL["en"]) + " " + text
            orb.actions.put(("brief", text, tip))

        threading.Thread(target=prepare_briefing, daemon=True).start()
    orb.tick()
    try:
        root.mainloop()
    finally:
        app.closed.set()
        for item in running:
            item.stop()
    return 0


__all__ = ["Orb", "PALETTE", "sphere_rings", "load_position", "save_position",
           "run"]
