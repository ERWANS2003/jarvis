"""Menu du clic droit de l'orbe : un panneau graphique sur mesure.

Le menu natif de Windows ne se laisse presque pas styliser ; ce panneau est
dessine par Jarvis, aux couleurs du theme :

  * en-tete : mini-orbe du theme, nom, etat ;
  * quatre tuiles : Parler, Ecrire, Stop, Muet ;
  * lignes : Historique, Journal, interrupteurs « Ecouter Jarvis » et
    « Conversation continue » ;
  * grille de pastilles pour les 28 themes (survol = nom, clic = applique) ;
  * page « Reglages » : voix, intro (avec apercu), qualite, masquage auto ;
  * pied : Masquer, Quitter.

Il se ferme en cliquant ailleurs, avec Echap, ou apres une action.
"""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont

from . import cinematic, orb_render, orb_themes

FONT = "Segoe UI"
COLUMNS = 8
TEXT = {
    "fr": {"ready": "Prêt", "listening": "À l'écoute…", "thinking": "Réflexion…",
           "speaking": "Parle…", "write": "Écrire", "stop": "Stop", "mute": "Muet",
           "speak": "Parler", "themes": "Thème", "settings": "Réglages", "intro": "Intro au démarrage",
           "back": "Réglages", "quality": "Qualité", "ultra": "Ultra 3D", "standard": "Standard",
           "hide_after": "Masquage auto", "hide": "Masquer", "quit": "Quitter",
           "voice": "Voix", "preview": "Clic = aperçu"},
    "en": {"ready": "Ready", "listening": "Listening…", "thinking": "Thinking…",
           "speaking": "Speaking…", "write": "Type", "stop": "Stop", "mute": "Mute",
           "speak": "Talk", "themes": "Theme", "settings": "Settings", "intro": "Startup intro",
           "back": "Settings", "quality": "Quality", "ultra": "Ultra 3D", "standard": "Standard",
           "hide_after": "Auto-hide", "hide": "Hide", "quit": "Quit",
           "voice": "Voice", "preview": "Click = preview"},
}
# Glyphes Segoe Fluent Icons / Segoe MDL2 Assets (repli : caracteres simples).
GLYPHS = {"speak": "", "write": "", "stop": "", "mute": "",
          "volume": "", "history": "", "journal": "", "wake": "",
          "follow": "", "settings": "", "hide": "", "quit": "",
          "back": "", "more": "", "theme": ""}
FALLBACK = {"speak": "●", "write": "✎", "stop": "■", "mute": "✕", "volume": "♪",
            "history": "≡", "journal": "▤", "wake": "◉", "follow": "↻", "settings": "⚙",
            "hide": "–", "quit": "⏻", "back": "‹", "more": "›", "theme": "◐"}
_icon_font: str | None = None
_PHOTOS: dict = {}               # pastilles deja converties pour Tk (reouverture rapide)


def icon_font() -> str | None:
    global _icon_font
    if _icon_font is None:
        try:
            families = set(tkfont.families())
        except Exception:
            families = set()
        _icon_font = next((f for f in ("Segoe Fluent Icons", "Segoe MDL2 Assets")
                           if f in families), "")
    return _icon_font or None


def glyph(name: str) -> str:
    return GLYPHS[name] if icon_font() else FALLBACK[name]


def swatch_image(colors, size: int, ring=None):
    """Pastille ronde : melange des 4 couleurs du theme + reflet (Pillow)."""
    from PIL import Image, ImageDraw, ImageFilter

    k = 4
    big = size * k
    layer = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    paint = Image.new("RGBA", (big, big), tuple(colors[0]) + (255,))
    draw = ImageDraw.Draw(paint)
    spots = ((0.75, 0.25), (0.25, 0.8), (0.8, 0.8), (0.3, 0.3))
    for (fx, fy), color in zip(spots, colors[1:] + colors[:1]):
        r = big * 0.42
        draw.ellipse((fx * big - r, fy * big - r, fx * big + r, fy * big + r),
                     fill=tuple(color) + (255,))
    paint = paint.filter(ImageFilter.GaussianBlur(big * 0.12))
    shine = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    ImageDraw.Draw(shine).ellipse((big * 0.22, big * 0.14, big * 0.5, big * 0.38),
                                  fill=(255, 255, 255, 120))
    paint.alpha_composite(shine.filter(ImageFilter.GaussianBlur(big * 0.05)))
    mask = Image.new("L", (big, big), 0)
    margin = big * 0.12
    ImageDraw.Draw(mask).ellipse((margin, margin, big - margin, big - margin), fill=255)
    layer.paste(paint, (0, 0), mask)
    if ring:
        ImageDraw.Draw(layer).ellipse((k, k, big - k, big - k), outline=ring, width=2 * k)
    return layer.resize((size, size), Image.LANCZOS)


def theme_preview(key: str, colors, size: int, ring=None, gpu: bool = True):
    from PIL import ImageDraw

    image = None
    if gpu:
        try:
            from . import orb_gpu

            if orb_gpu.available():
                image = orb_gpu.preview(key, size).copy()
        except Exception:
            image = None
    if image is None:
        return swatch_image(colors, size, ring=ring)
    if ring:
        ImageDraw.Draw(image).ellipse((1, 1, size - 2, size - 2), outline=ring, width=2)
    return image


def warm_previews(root, size: int, keys, batch: int = 3) -> None:
    """Prepare les apercus 3D petit a petit, sans figer l'orbe."""
    pending = list(keys)

    def step() -> None:
        try:
            from . import orb_gpu

            for _ in range(batch):
                if not pending:
                    return
                orb_gpu.preview(pending.pop(0), size)
        except Exception:
            return
        root.after(60, step)

    root.after(4000, step)


class OrbMenu:
    def __init__(self, orb, x: int, y: int):
        self.orb = orb
        self.c = orb.colors
        self.lang = "fr" if getattr(getattr(orb.app, "args", None), "lang", "fr") == "fr" else "en"
        self.t = TEXT[self.lang]
        self.scale = max(1.0, float(getattr(orb, "scale", 1.0)))
        self.images: list = []           # references Tk des pastilles
        self.page = "main"
        self.win = tk.Toplevel(orb.root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=self.c["accent"])          # liseré d'une couleur
        self.body = tk.Frame(self.win, bg=self.c["bg"])
        self.body.pack(fill="both", expand=True, padx=1, pady=1)
        self.win.bind("<Escape>", lambda _e: self.close())
        self.win.bind("<FocusOut>", self._maybe_close)
        self.anchor = (x, y)
        self.render()

    # -- outils de dessin ---------------------------------------------------- #
    def px(self, value: float) -> int:
        return int(round(value * self.scale))

    def _icon(self, parent, name: str, size: int = 12, fg=None, bg=None):
        return tk.Label(parent, text=glyph(name), font=(icon_font() or FONT, size),
                        bg=bg or self.c["bg"], fg=fg or self.c["accent"])

    def _hover(self, widgets, normal: str, over: str) -> None:
        def enter(_e):
            for w in widgets:
                w.configure(bg=over)

        def leave(_e):
            for w in widgets:
                w.configure(bg=normal)

        for w in widgets:
            w.bind("<Enter>", enter)
            w.bind("<Leave>", leave)

    def _click(self, widgets, command, close: bool = True) -> None:
        def run(_e):
            if close:
                self.close()
            command()

        for w in widgets:
            w.bind("<Button-1>", run)
            w.configure(cursor="hand2")

    def _section(self, text: str, extra: str = "") -> tk.Label:
        row = tk.Frame(self.body, bg=self.c["bg"])
        row.pack(fill="x", padx=self.px(14), pady=(self.px(10), self.px(4)))
        tk.Label(row, text=text.upper(), bg=self.c["bg"], fg=self.c["dim"],
                 font=(FONT, 8, "bold")).pack(side="left")
        hint = tk.Label(row, text=extra, bg=self.c["bg"], fg=self.c["accent"], font=(FONT, 8))
        hint.pack(side="right")
        return hint

    def _row(self, icon: str, text: str, command=None, switch=None, more: bool = False,
             danger: bool = False) -> None:
        c = self.c
        row = tk.Frame(self.body, bg=c["bg"])
        row.pack(fill="x", padx=self.px(6))
        fg = "#ff5a6a" if danger else c["fg"]
        ic = self._icon(row, icon, 11, fg="#ff5a6a" if danger else c["accent"])
        ic.pack(side="left", padx=(self.px(10), self.px(10)), pady=self.px(7))
        label = tk.Label(row, text=text, bg=c["bg"], fg=fg, font=(FONT, 10), anchor="w")
        label.pack(side="left", fill="x", expand=True)
        widgets = [row, ic, label]
        if switch is not None:
            canvas = self._switch(row, switch[0])
            canvas.pack(side="right", padx=self.px(10))
            widgets.append(canvas)
            self._click(widgets, lambda: (switch[1](), self.render()), close=False)
        elif command is not None:
            if more:
                arrow = self._icon(row, "more", 9, fg=c["dim"])
                arrow.pack(side="right", padx=self.px(10))
                widgets.append(arrow)
            self._click(widgets, command, close=not more)
        self._hover(widgets, c["bg"], c["active"])

    def _switch(self, parent, on: bool) -> tk.Canvas:
        c = self.c
        w, h = self.px(34), self.px(18)
        canvas = tk.Canvas(parent, width=w, height=h, bg=c["bg"], highlightthickness=0)
        fill = c["accent"] if on else c["active"]
        r = h / 2
        canvas.create_oval(0, 0, h, h, fill=fill, outline=fill)
        canvas.create_oval(w - h, 0, w, h, fill=fill, outline=fill)
        canvas.create_rectangle(r, 0, w - r, h, fill=fill, outline=fill)
        knob = (w - h + 3) if on else 3
        canvas.create_oval(knob, 3, knob + h - 6, h - 3, fill="#ffffff", outline="")
        return canvas

    def _chips(self, options, current, command, columns: int = 3) -> None:
        c = self.c
        grid = tk.Frame(self.body, bg=c["bg"])
        grid.pack(fill="x", padx=self.px(12), pady=(0, self.px(4)))
        for index, (value, text) in enumerate(options):
            selected = value == current
            chip = tk.Label(grid, text=text, font=(FONT, 9, "bold" if selected else "normal"),
                            bg=c["accent"] if selected else c["active"],
                            fg=c["bg"] if selected else c["fg"],
                            padx=self.px(8), pady=self.px(4))
            chip.grid(row=index // columns, column=index % columns, sticky="ew",
                      padx=self.px(2), pady=self.px(2))
            self._click([chip], lambda v=value: (command(v), self.render()), close=False)
        for col in range(columns):
            grid.grid_columnconfigure(col, weight=1, uniform="chips")

    # -- pages -------------------------------------------------------------- #
    def render(self) -> None:
        self.c = self.orb.colors
        self.win.configure(bg=self.c["accent"])
        self.body.configure(bg=self.c["bg"])
        for child in self.body.winfo_children():
            child.destroy()
        self.images.clear()
        (self._main if self.page == "main" else self._settings)()
        self._place()
        self.win.after(10, self.win.focus_force)

    def _header(self) -> None:
        c = self.c
        head = tk.Frame(self.body, bg=c["bg"])
        head.pack(fill="x", padx=self.px(14), pady=(self.px(14), self.px(6)))
        colors = orb_themes.swatch(self.orb.theme)
        if colors:
            image = self._photo(self.orb_preview(self.orb.theme, colors, self.px(42)))
            tk.Label(head, image=image, bg=c["bg"]).pack(side="left")
        text = tk.Frame(head, bg=c["bg"])
        text.pack(side="left", padx=self.px(10))
        tk.Label(text, text="JARVIS", bg=c["bg"], fg=c["fg"],
                 font=(FONT, 13, "bold")).pack(anchor="w")
        state = self.t.get(self.orb.state, self.t["ready"])
        theme = orb_themes.label(self.orb.theme, self.lang, self.orb.s)
        self.subtitle = tk.Label(text, text=f"● {state}   ·   {theme}", bg=c["bg"],
                                 fg=c["dim"], font=(FONT, 9))
        self.subtitle.pack(anchor="w")

    def _tiles(self) -> None:
        c = self.c
        bar = tk.Frame(self.body, bg=c["bg"])
        bar.pack(fill="x", padx=self.px(10), pady=(self.px(4), self.px(6)))
        muted = bool(getattr(self.orb.app, "muted", False))
        tiles = (("speak", self.t["speak"], self.orb.on_click, False),
                 ("write", self.t["write"], self.orb.open_prompt, False),
                 ("stop", self.t["stop"], self.orb.app.stop, False),
                 ("mute" if muted else "volume", self.t["mute"], self._toggle_mute, muted))
        for index, (icon, text, command, active) in enumerate(tiles):
            bg = c["accent"] if active else c["active"]
            fg = c["bg"] if active else c["accent"]
            tile = tk.Frame(bar, bg=bg)
            tile.grid(row=0, column=index, sticky="nsew", padx=self.px(3))
            ic = self._icon(tile, icon, 15, fg=fg, bg=bg)
            ic.pack(pady=(self.px(9), self.px(2)))
            label = tk.Label(tile, text=text, bg=bg, fg=c["fg"] if not active else c["bg"],
                             font=(FONT, 8))
            label.pack(pady=(0, self.px(7)))
            self._click([tile, ic, label], command, close=icon != "mute" and icon != "volume")
            if not active:
                self._hover([tile, ic, label], bg, c["bg"])
            bar.grid_columnconfigure(index, weight=1, uniform="tiles")

    def _toggle_mute(self) -> None:
        self.orb.mute_var.set(not bool(getattr(self.orb.app, "muted", False)))
        self.orb._on_mute()
        self.render()

    def _themes(self) -> None:
        c = self.c
        current = self.orb.theme
        hint = self._section(self.t["themes"], orb_themes.label(current, self.lang, self.orb.s))
        grid = tk.Frame(self.body, bg=c["bg"])
        grid.pack(padx=self.px(12), pady=(0, self.px(4)))
        size = self.px(30)
        order = sorted(orb_render.THEMES, key=lambda k: (
            list(orb_themes.FAMILIES["fr"]).index(orb_themes.family(k)),
            orb_render.THEMES.index(k)))
        for index, key in enumerate(order):
            colors = orb_themes.swatch(key)
            if not colors:
                continue
            ring = c["fg"] if key == current else None
            cache_key = (key, size, ring, self.orb.fancy and self.orb.quality == "ultra")
            image = _PHOTOS.get(cache_key)
            if image is None:
                image = _PHOTOS[cache_key] = self._photo(self.orb_preview(key, colors, size, ring))
            cell = tk.Label(grid, image=image, bg=c["bg"], cursor="hand2", bd=0)
            cell.grid(row=index // COLUMNS, column=index % COLUMNS, padx=self.px(2),
                      pady=self.px(2))
            name = orb_themes.label(key, self.lang, self.orb.s)
            cell.bind("<Enter>", lambda _e, n=name, cl=cell: (hint.configure(text=n),
                                                             cl.configure(bg=c["active"])))
            cell.bind("<Leave>", lambda _e, cl=cell: (
                hint.configure(text=orb_themes.label(self.orb.theme, self.lang, self.orb.s)),
                cl.configure(bg=c["bg"])))
            self._click([cell], lambda k=key: (self.orb.set_theme(k), self.render()), close=False)

    def orb_preview(self, key: str, colors, size: int, ring=None):
        """Apercu 3D reel (carte graphique) si possible, sinon pastille degradee."""
        return theme_preview(key, colors, size, ring,
                             gpu=self.orb.fancy and self.orb.quality == "ultra")

    def _separator(self) -> None:
        tk.Frame(self.body, bg=self.c["active"], height=1).pack(
            fill="x", padx=self.px(14), pady=self.px(6))

    def _main(self) -> None:
        orb, s, t = self.orb, self.orb.s, self.t
        self._header()
        self._tiles()
        self._separator()
        self._row("history", s["orb_history"], orb.toggle_history)
        self._row("journal", s["orb_journal"].rstrip("…."), orb.open_journal)
        if orb.detector is not None:
            self._row("wake", s["orb_wake_menu"].format(word=orb.wake_label),
                      switch=(bool(orb.wake_var.get()), self._toggle_wake))
        self._row("follow", s["orb_follow_up"], switch=(bool(orb.follow_up), self._toggle_follow))
        self._themes()
        self._separator()
        self._row("settings", t["settings"], self._open_settings, more=True)
        if orb.tray is not None:
            self._row("hide", t["hide"], orb.hide)
        self._row("quit", t["quit"], orb.quit, danger=True)
        tk.Frame(self.body, bg=self.c["bg"], height=self.px(8)).pack()

    def _settings(self) -> None:
        orb, t = self.orb, self.t
        c = self.c
        top = tk.Frame(self.body, bg=c["bg"])
        top.pack(fill="x", padx=self.px(8), pady=(self.px(10), self.px(2)))
        back = self._icon(top, "back", 11)
        back.pack(side="left", padx=self.px(6))
        title = tk.Label(top, text=t["back"], bg=c["bg"], fg=c["fg"], font=(FONT, 12, "bold"))
        title.pack(side="left")
        self._click([back, title], self._open_main, close=False)
        if orb.voices:
            self._section(t["voice"])
            self._chips([(spec, name) for name, spec in orb.voices], orb.voice_choice,
                        orb.set_voice, columns=2)
        self._section(t["intro"], t["preview"])
        labels = cinematic.LABELS[self.lang]
        options = [(key, labels[key]) for key in cinematic.STYLES] + [("aucune", labels["aucune"])]
        self._chips(options, orb.intro_choice, orb.set_intro, columns=3)
        if orb.fancy:
            self._section(t["quality"])
            self._chips([("ultra", t["ultra"]), ("standard", t["standard"])], orb.quality,
                        orb.set_quality, columns=2)
        if orb.can_recall:
            self._section(t["hide_after"])
            options = [(seconds, orb.auto_hide_label(seconds)) for seconds in orb.auto_hide_choices]
            self._chips(options, int(orb.auto_hide), orb.set_auto_hide, columns=4)
        tk.Frame(self.body, bg=c["bg"], height=self.px(12)).pack()

    def _open_settings(self) -> None:
        self.page = "settings"
        self.render()

    def _open_main(self) -> None:
        self.page = "main"
        self.render()

    def _toggle_wake(self) -> None:
        self.orb.wake_var.set(not bool(self.orb.wake_var.get()))
        self.orb._on_wake_toggle()

    def _toggle_follow(self) -> None:
        self.orb.follow_var.set(not bool(self.orb.follow_up))
        self.orb._on_follow_toggle()

    # -- fenetre ------------------------------------------------------------ #
    def _photo(self, image):
        from PIL import ImageTk

        photo = ImageTk.PhotoImage(image)
        self.images.append(photo)
        return photo

    def _place(self) -> None:
        self.win.update_idletasks()
        width = max(self.px(300), self.win.winfo_reqwidth())
        height = self.win.winfo_reqheight()
        sw, sh = self.win.winfo_screenwidth(), self.win.winfo_screenheight()
        x, y = self.anchor
        x = min(max(4, x - width + self.px(20)), sw - width - 4)
        y = min(max(4, y - height // 2), sh - height - 40)
        self.win.geometry(f"{width}x{height}+{x}+{y}")

    def _maybe_close(self, _event=None) -> None:
        def check() -> None:
            try:
                focus = self.win.focus_get()
            except Exception:
                focus = None
            if focus is None or not str(focus).startswith(str(self.win)):
                self.close()

        self.win.after(120, check)

    def alive(self) -> bool:
        try:
            return bool(self.win.winfo_exists())
        except Exception:
            return False

    def close(self) -> None:
        try:
            self.win.destroy()
        except Exception:
            pass


__all__ = ["OrbMenu", "swatch_image", "glyph", "theme_preview", "warm_previews"]
