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
from pathlib import Path

from . import briefing, layered
from . import tray as tray_mod
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
}
FONT = "Segoe UI"


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
                 theme: str = "opale"):
        self.root = root
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
        self.canvas.bind("<Enter>", lambda _e: setattr(self, "_hover_target", 1.0))
        self.canvas.bind("<Leave>", lambda _e: setattr(self, "_hover_target", 0.0))
        root.bind("<Escape>", lambda _e: self.app.stop())

        self.mute_var = tk.BooleanVar(value=app.muted)
        c = self.colors
        self.menu = tk.Menu(root, tearoff=False, bg=c["bg"], fg=c["fg"],
                            activebackground=c["active"], activeforeground=c["accent"],
                            selectcolor=c["accent"], bd=0, relief="flat",
                            font=(FONT, 10))
        self.menu.add_command(label=strings["orb_speak"], command=self.on_click)
        self.menu.add_command(label=strings["orb_type"], command=self.open_prompt)
        self.menu.add_command(label=strings["orb_history"], command=self.toggle_history)
        self.menu.add_command(label=strings["orb_stop"], command=self.app.stop)
        self.menu.add_checkbutton(label=strings["orb_mute"], variable=self.mute_var,
                                  command=self._on_mute)
        self.wake_var = tk.BooleanVar(value=True)
        self._wake_menu_added = False
        self.args = None
        self.tray = None
        self.hidden = False
        self.settings_menu = None
        self.menu.add_separator()
        self._quit_index = self.menu.index("end") + 1
        self.menu.add_command(label=strings["orb_quit"], command=self.quit)

        self._place()
        if self.fancy:
            self.renderer = orb_render.make_renderer(self.theme, self.size,
                                                     round(FANCY_RADIUS * self.scale))
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
            self.phase += TICK_MS / 1000.0
            self._animate()
            self.layer.show(self.renderer.frame(self.state, self.phase, self._voice_level(),
                                                hover=self._hover, pulse=self._pulse))
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
        self.draw()
        self.root.after(TICK_MS, self.tick)

    # -- evenements de la session ------------------------------------------- #
    def handle(self, event: dict) -> None:
        kind = event.get("type")
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
        elif kind == "closed":
            self.close()

    # -- souris ------------------------------------------------------------- #
    def _on_press(self, event) -> None:
        self._press = (event.x_root, event.y_root, self.root.winfo_x(),
                       self.root.winfo_y())
        self._dragged = False

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

    def _on_release(self, _event) -> None:
        if self._dragged:
            save_position(self.root.winfo_x(), self.root.winfo_y())
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

    def _on_menu(self, event) -> None:
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

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
    def _styled_menu(self, parent):
        c = self.colors
        return tk.Menu(parent, tearoff=False, bg=c["bg"], fg=c["fg"],
                       activebackground=c["active"], activeforeground=c["accent"],
                       selectcolor=c["accent"], bd=0, relief="flat", font=(FONT, 10))

    def build_settings(self, args, current_voice: str | None) -> None:
        """Sous-menu Reglages : voix, theme, conversation continue, masquer."""
        from . import tts as tts_mod

        self.args = args
        menu = self._styled_menu(self.menu)
        voices = tts_mod.installed_voices(getattr(args, "lang", "fr"))
        if voices and hasattr(self.app.speech, "set_factory"):
            voice_menu = self._styled_menu(menu)
            self.voice_var = tk.StringVar(value=current_voice or "")
            for label, spec in voices + [(self.s["orb_voice_windows"], "sapi")]:
                voice_menu.add_radiobutton(label=label, value=spec, variable=self.voice_var,
                                           command=lambda s=spec: self.set_voice(s))
            menu.add_cascade(label=self.s["orb_voice"], menu=voice_menu)
        theme_menu = self._styled_menu(menu)
        self.theme_var = tk.StringVar(value=self.theme)
        for key in orb_render.THEMES:
            theme_menu.add_radiobutton(label=self.s[f"orb_theme_{key}"], value=key,
                                       variable=self.theme_var,
                                       command=lambda k=key: self.set_theme(k))
        menu.add_cascade(label=self.s["orb_theme"], menu=theme_menu)
        self.follow_var = tk.BooleanVar(value=self.follow_up)
        menu.add_checkbutton(label=self.s["orb_follow_up"], variable=self.follow_var,
                             command=self._on_follow_toggle)
        if self.tray is not None:
            menu.add_separator()
            menu.add_command(label=self.s["orb_hide"], command=self.hide)
        self.settings_menu = menu
        self.menu.insert_cascade(self._quit_index - 1, label=self.s["orb_settings"],
                                 menu=menu)

    def set_voice(self, spec: str) -> None:
        """Change la voix tout de suite, la retient, et la fait entendre."""
        from . import tts as tts_mod

        try:
            factory = tts_mod.factory_for(spec, self.args, getattr(self.args, "lang", "fr"))
        except Exception as exc:
            log(f"[tts] {exc}")
            return
        self.app.speech.set_factory(factory)
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
            self.renderer = orb_render.make_renderer(theme, self.size,
                                                     round(FANCY_RADIUS * self.scale))
        c = self.colors
        for menu in [self.menu, self.settings_menu] + list(self._submenus()):
            if menu is not None:
                menu.configure(bg=c["bg"], fg=c["fg"], activebackground=c["active"],
                               activeforeground=c["accent"], selectcolor=c["accent"])
        save_settings(theme=theme)

    def _submenus(self):
        if self.settings_menu is None:
            return []
        found = []
        for index in range(self.settings_menu.index("end") + 1):
            if self.settings_menu.type(index) == "cascade":
                found.append(self.settings_menu.nametowidget(
                    self.settings_menu.entrycget(index, "menu")))
        return found

    def _on_follow_toggle(self) -> None:
        self.follow_up = bool(self.follow_var.get())
        save_settings(follow_up=self.follow_up)

    # -- masquer / afficher (icone de notification) ------------------------- #
    def hide(self) -> None:
        self.hidden = True
        self.hide_bubble()
        if self._history is not None:
            self.toggle_history()
        self.root.withdraw()

    def show(self) -> None:
        if not self.hidden:
            return
        self.hidden = False
        self.root.deiconify()
        self.root.attributes("-topmost", True)

    def attach_detector(self, detector) -> None:
        """Ajoute au menu l'interrupteur du mot d'activation."""
        self.detector = detector
        if not self._wake_menu_added:
            self.menu.insert_checkbutton(3, label=self.s["orb_wake_menu"].format(
                                             word=self.wake_label),
                                         variable=self.wake_var,
                                         command=self._on_wake_toggle)
            self._wake_menu_added = True

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
        orb = Orb(root, app, strings, fancy=fancy, theme=theme)
    except Exception as exc:  # rendu lisse impossible : dessin de secours
        log(f"[orbe] rendu lisse indisponible ({exc})")
        root.destroy()
        root = tk.Tk()
        orb = Orb(root, app, strings)
    log(strings["orb_hint"])
    orb.follow_up = bool(getattr(args, "follow_up", True))
    running = start_triggers(orb, args, listener)
    if tray_mod.available():
        icon = orb_render.make_renderer("jarvis", 64, 18).frame("ready", 3.0) \
            if orb_render.available() else None
        if icon is not None:
            orb.tray = tray_mod.Tray(orb.actions, icon,
                                     {"show": strings["orb_show"], "quit": strings["orb_quit"]})
            if orb.tray.start():
                running.append(orb.tray)
            else:
                orb.tray = None
    current = getattr(args, "piper_voice", None) or ("sapi" if args.tts == "sapi" else None)
    orb.build_settings(args, current)
    if greet:
        hints = []
        if orb.detector is not None:
            hints.append(strings["orb_say_hey"].format(word=orb.wake_label))
        if any(isinstance(item, GlobalHotkey) for item in running):
            hints.append(strings["orb_press_key"].format(key=pretty_hotkey(args.hotkey,
                                                                           args.lang)))
        tip = ("\n" + strings["orb_or"].join(hints) + ".") if hints else ""

        def prepare_briefing() -> None:
            try:
                text = briefing.gather(args.lang, memory, reminders)
            except Exception as exc:
                log(f"[briefing] {exc}")
                text = strings["greeting"]
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
