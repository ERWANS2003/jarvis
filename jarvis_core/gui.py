"""Horizon 6 - interface graphique (Tkinter, bibliotheque standard).

Objectif : utiliser Jarvis comme une vraie application, sans console.

Principes de conception :

  * **Jamais de gel.** L'ecoute du micro et la reflexion du modele tournent
    dans un fil d'execution separe ; la fenetre reste reactive en permanence.
    Tkinter n'etant pas *thread-safe*, le fil de travail ne touche jamais aux
    widgets : il decharge des evenements dans une file, que le fil principal
    consomme periodiquement (`after`).
  * **Barre d'etat vivante** : une pastille coloree indique si Jarvis est pret,
    en train d'ecouter, de reflechir ou de parler.
  * **Defensif** : si Tkinter ou l'affichage sont indisponibles, `run()`
    retourne ``None`` et `jarvis.py` reprend la boucle console.
"""

from __future__ import annotations

import queue
import threading
from pathlib import Path

from . import graph as graphs
from .text import is_exit_phrase, log

# Les outils de memoire ne doivent pas declencher « Un instant » : ils sont
# instantanes et ne justifient pas d'interrompre la conversation.
MEMORY_TOOLS = {"remember_fact", "recall_memory", "forget_memory"}

# --- Palette (theme sombre) ------------------------------------------------ #
BG = "#12121a"
PANEL = "#191924"
HEADER = "#0d0d15"
BUBBLE_USER = "#2f6fed"
BUBBLE_JARVIS = "#262636"
FG = "#e9e9f4"
FG_DIM = "#8b8ba3"
FG_USER_NAME = "#c9dcff"
ACCENT = "#5b8cff"
BTN = "#262636"
BTN_HI = "#33334a"
DOT_READY = "#22c55e"
DOT_BUSY = "#f59e0b"
DOT_SPEAK = "#38bdf8"
DOT_LISTEN = "#5b8cff"

FONT = "Segoe UI"

# Couleurs de la pastille selon l'etat.
STATE_COLORS = {
    "ready": DOT_READY,
    "thinking": DOT_BUSY,
    "speaking": DOT_SPEAK,
    "listening": DOT_LISTEN,
}


def _ensure_tcl() -> None:
    """Repare Tcl/Tk quand l'interpreteur ne trouve pas ses bibliotheques.

    Certaines distributions de Python (Laragon, Python embarque, environnements
    deplaces) rangent Tcl/Tk dans ``<prefix>/tcl/tcl8.6`` au lieu du
    ``<prefix>/lib/tcl8.6`` attendu : `import tkinter` reussit alors que
    l'ouverture de fenetre echoue avec « Can't find a usable init.tcl ».

    On indique donc a Tcl ou se trouvent ses fichiers, sans rien installer.
    """
    import os
    import sys

    if os.environ.get("TCL_LIBRARY") and os.environ.get("TK_LIBRARY"):
        return
    prefixes = {
        getattr(sys, "base_prefix", ""),
        getattr(sys, "prefix", ""),
        getattr(sys, "exec_prefix", ""),
    }
    for prefix in prefixes:
        if not prefix:
            continue
        root = os.path.join(prefix, "tcl")
        for version in ("tcl8.6", "tcl8.5", "tcl8.4"):
            tcl_dir = os.path.join(root, version)
            if not os.path.isfile(os.path.join(tcl_dir, "init.tcl")):
                continue
            os.environ.setdefault("TCL_LIBRARY", tcl_dir)
            tk_dir = os.path.join(root, "tk" + version[3:])
            if os.path.isfile(os.path.join(tk_dir, "tk.tcl")):
                os.environ.setdefault("TK_LIBRARY", tk_dir)
            return


_ensure_tcl()

try:  # import reussi != affichage disponible : on teste vraiment a l'ouverture
    import tkinter as tk
    from tkinter import filedialog, messagebox

    tkf, tksb, tke, tkc = tk.Frame, tk.Scrollbar, tk.Entry, tk.Checkbutton
except Exception:  # pragma: no cover - depend de la machine
    tk = tkf = tksb = tke = tkc = None
    filedialog = messagebox = None


def available() -> bool:
    """Vrai si Tkinter a pu etre importe."""
    return tk is not None


def _default_history() -> Path:
    return Path(__file__).resolve().parent.parent / ".jarvis_history.json"


def _make_turn(args, strings, chain, memory):
    """Fabrique la fonction qui joue un tour (prompt + outils + historique)."""

    def turn(text: str, history: list, on_sentence, on_tool, on_status) -> None:
        base_prompt = strings["system"].format(
            ability=args.ability, words=args.max_words
        )
        system_prompt = graphs.build_system_prompt(
            base_prompt, memory=memory, query=text, strings=strings,
            with_tools=chain.tools_enabled,
        )
        messages = graphs.make_turn_messages(system_prompt, history, text)
        announced = {"done": False}

        def tool_hook(name: str) -> None:
            log(f"[outil] {name}")
            if not announced["done"] and name not in MEMORY_TOOLS:
                announced["done"] = True
                hint = strings.get("tool_running", "")
                if hint:
                    on_status(hint)
            on_tool(name)

        result = graphs.stream_reply(chain.graph, messages,
                                     on_sentence=on_sentence,
                                     retries=args.retries, on_tool=tool_hook)
        if not result.ok and chain.advance():
            on_status(strings.get("fallback_used", ""))
            result = graphs.stream_reply(chain.graph, messages,
                                         on_sentence=on_sentence,
                                         retries=args.retries, on_tool=tool_hook)
        if not result.ok:
            log(f"[llm] {result.error}")
            on_status(strings["llm_error"])
            return

        from .memory import FACT, PROFILE, extract_explicit, extract_profile

        history.append(messages[-1])
        history.extend(result.messages)
        if memory is not None:
            try:
                action, payload = extract_explicit(text)
                if action == "remember" and payload:
                    memory.remember(payload, kind=FACT, source="explicit")
                elif action == "forget" and payload:
                    memory.forget_matching(payload)
                for label, value in extract_profile(text):
                    memory.remember(f"{label}: {value}", kind=PROFILE,
                                    source="auto")
            except Exception as exc:  # la memoire ne casse jamais un tour
                log(f"[memoire] {exc}")
        graphs.save_history(history, args.history_path or _default_history())

    return turn


# --------------------------------------------------------------------------- #
# Fenetre
# --------------------------------------------------------------------------- #
class _Window:
    """Fenetre principale : affiche, ecoute, parle, le tout sans bloquer."""

    def __init__(self, root, args, strings, listener, speech, chain, history,
                 memory, greet):
        self.root = root
        self.args = args
        self.s = strings
        self.listener = listener
        self.speech = speech
        self.chain = chain
        self.history = list(history)
        self.memory = memory
        self.greet = greet
        self.turn = _make_turn(args, strings, chain, memory)

        self.events: queue.Queue = queue.Queue()
        self.busy = False
        self.muted = False
        self.closing = False
        self.state = "ready"

        self._bubbles: list = []              # labels dont la largeur s'adapte
        self._transcript: list[tuple[str, str]] = []
        self._stream_body = None
        self._stream_text = ""

        self._build()

    # -- construction ------------------------------------------------------- #
    def _build(self) -> None:
        root = self.root
        root.title("Jarvis")
        root.geometry("880x620")
        root.minsize(560, 420)
        root.configure(bg=BG)

        self._build_header()
        self._build_chat()
        self._build_input()
        self._build_menu()

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.bind("<Escape>", lambda _e: self.on_stop())
        root.bind("<Control-l>", lambda _e: self.on_clear())
        root.bind_all("<MouseWheel>", self._on_wheel)

    def _build_header(self) -> None:
        header = tkf(self.root, bg=HEADER, height=58)
        header.pack(fill="x")
        header.pack_propagate(False)

        tk.Label(header, text="JARVIS", bg=HEADER, fg=FG,
                 font=(FONT, 16, "bold")).pack(side="left", padx=(18, 10))
        tk.Label(header, text=self._subtitle(), bg=HEADER, fg=FG_DIM,
                 font=(FONT, 9)).pack(side="left")

        self.status = tk.StringVar(value=self.s["gui_state_ready"])
        tk.Label(header, textvariable=self.status, bg=HEADER, fg=FG_DIM,
                 font=(FONT, 10)).pack(side="right", padx=(6, 18))
        self.dot = tk.Canvas(header, width=14, height=14, bg=HEADER,
                             highlightthickness=0)
        self.dot.pack(side="right")
        self.dot_item = self.dot.create_oval(3, 3, 12, 12,
                                             fill=DOT_READY, outline="")

    def _build_chat(self) -> None:
        body = tkf(self.root, bg=PANEL)
        body.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(body, bg=PANEL, highlightthickness=0, bd=0)
        bar = tksb(body, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.msg_frame = tkf(self.canvas, bg=PANEL)
        self.canvas_window = self.canvas.create_window((0, 0),
                                                       window=self.msg_frame,
                                                       anchor="nw")
        self.msg_frame.bind("<Configure>", self._on_frame_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

    def _build_input(self) -> None:
        bar = tkf(self.root, bg=HEADER)
        bar.pack(fill="x")

        self.entry = tke(bar, bg=BTN, fg=FG_DIM, insertbackground=FG,
                         relief="flat", font=(FONT, 11), highlightthickness=1,
                         highlightbackground="#33334a", highlightcolor=ACCENT)
        self.entry.pack(side="left", fill="x", expand=True,
                        padx=(14, 8), pady=12, ipady=7)
        self._placeholder_active = True
        self.entry.insert(0, self.s["gui_placeholder"])
        self.entry.bind("<Return>", self.on_send)
        self.entry.bind("<FocusIn>", self._on_focus_in)
        self.entry.bind("<FocusOut>", self._on_focus_out)

        self.btn_send = self._button(bar, self.s["gui_send"], self.on_send,
                                     ACCENT, "#ffffff")
        self.btn_send.pack(side="left", padx=(0, 6), pady=12)

        self.btn_listen = None
        if self.listener is not None:
            self.btn_listen = self._button(bar, self.s["gui_listen"],
                                           self.on_listen, BTN_HI, FG)
            self.btn_listen.pack(side="left", padx=(0, 6), pady=12)

        self.btn_stop = self._button(bar, self.s["gui_stop"], self.on_stop,
                                     BTN_HI, FG)
        self.btn_stop.pack(side="left", padx=(0, 6), pady=12)

        self.mute_var = tk.BooleanVar(value=False)
        tkc(bar, text=self.s["gui_mute"], variable=self.mute_var,
            command=self.on_mute, bg=HEADER, fg=FG_DIM, selectcolor=HEADER,
            activebackground=HEADER, activeforeground=FG, font=(FONT, 9),
            bd=0, highlightthickness=0).pack(side="right", padx=(0, 14))

    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label=self.s["gui_menu_clear"],
                              command=self.on_clear)
        file_menu.add_command(label=self.s["gui_menu_export"],
                              command=self.on_export)
        file_menu.add_separator()
        file_menu.add_command(label=self.s["gui_menu_quit"],
                              command=self.on_close)
        menubar.add_cascade(label=self.s["gui_menu_file"], menu=file_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label=self.s["gui_about"], command=self.on_about)
        menubar.add_cascade(label=self.s["gui_menu_help"], menu=help_menu)
        self.root.config(menu=menubar)

    @staticmethod
    def _button(parent, text, command, bg, fg):
        return tk.Button(parent, text=text, command=command, bg=bg, fg=fg,
                         activebackground=ACCENT, activeforeground="#ffffff",
                         disabledforeground="#6b6b80", relief="flat", bd=0,
                         font=(FONT, 10, "bold"), padx=16, pady=6,
                         cursor="hand2")

    def _subtitle(self) -> str:
        spec = getattr(self.chain, "spec", None)
        label = spec.label() if spec is not None and hasattr(spec, "label") \
            else str(getattr(self.args, "model", ""))
        return label

    # -- demarrage ---------------------------------------------------------- #
    def start(self) -> None:
        if self.history:
            self._render_history(self.history)
        if self.greet:
            self._add_message(self.s["gui_jarvis"], self.s["greeting"],
                              "jarvis")
            self._transcript.append(("jarvis", self.s["greeting"]))
            self._speak_async(self.s["greeting"])
        self._poll()
        self.root.after(150, self.entry.focus_set)

    def _render_history(self, history) -> None:
        for message in history:
            kind = getattr(message, "type", "")
            content = getattr(message, "content", "")
            if not isinstance(content, str) or not content.strip():
                continue
            if kind == "human":
                self._add_message(self.s["gui_you"], content, "user")
                self._transcript.append(("user", content))
            elif kind == "ai":
                self._add_message(self.s["gui_jarvis"], content, "jarvis")
                self._transcript.append(("jarvis", content))

    # -- boucle d'evenements ------------------------------------------------ #
    def _poll(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                self._handle(kind, payload)
        except queue.Empty:
            pass
        if not self.closing:
            self.root.after(40, self._poll)

    def _handle(self, kind: str, payload) -> None:
        if kind == "user":
            self._add_message(self.s["gui_you"], payload, "user")
            self._transcript.append(("user", payload))
        elif kind == "reply":
            self._append_reply(payload)
        elif kind == "system":
            self._add_message("", payload, "system")
        elif kind == "state":
            self._set_state(payload)
        elif kind == "heard":
            heard, error = payload
            self._on_heard(heard, error)
        elif kind == "finished":
            self._on_finished(payload)
        elif kind == "close":
            self.on_close()

    # -- etat --------------------------------------------------------------- #
    def _set_state(self, state: str) -> None:
        self.state = state
        text = {
            "ready": self.s["gui_state_ready"],
            "thinking": self.s["gui_state_thinking"],
            "speaking": self.s["gui_state_speaking"],
            "listening": self.s["gui_state_listening"],
        }.get(state, self.s["gui_state_ready"])
        self.status.set(text)
        self.dot.itemconfigure(self.dot_item, fill=STATE_COLORS.get(state, DOT_READY))

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        state = "disabled" if busy else "normal"
        for button in (self.btn_send, self.btn_listen):
            if button is not None:
                button.configure(state=state)
        if not busy:
            self._set_state("ready")

    # -- conversation ------------------------------------------------------- #
    def on_send(self, _event=None) -> None:
        text = self._entry_text()
        if not text:
            return
        self._reset_entry()
        self._start_turn(text)

    def on_listen(self) -> None:
        if self.busy or self.listener is None:
            return
        self._set_busy(True)
        self._set_state("listening")
        threading.Thread(target=self._worker_listen, daemon=True).start()

    def _start_turn(self, text: str) -> None:
        if self.busy:
            return
        self._begin_turn(text)

    def _begin_turn(self, text: str) -> None:
        """Lance un tour ; l'appelant garantit qu'aucun autre n'est en cours."""
        self._stream_body = None
        self._stream_text = ""
        self._set_busy(True)
        self._set_state("thinking")
        threading.Thread(target=self._worker_turn, args=(text,),
                         daemon=True).start()

    def _worker_listen(self) -> None:
        heard, error = None, None
        try:
            heard, error = self.listener.listen()
        except Exception as exc:
            log(f"[gui] micro: {exc}")
            error = f"mic:{exc}"
        self.events.put(("heard", (heard, error)))

    def _worker_turn(self, text: str) -> None:
        self.events.put(("user", text))
        first = {"done": False}

        def on_sentence(chunk: str) -> None:
            if not first["done"]:
                first["done"] = True
                self.events.put(("state", "speaking"))
            self.events.put(("reply", chunk))
            if not self.muted:
                self.speech.say(chunk)

        def on_tool(name: str) -> None:
            self.events.put(("system", self.s["gui_tool"].format(name=name)))

        def on_status(text_: str) -> None:
            if text_:
                self.events.put(("system", text_))

        try:
            if not self.muted:
                self.speech.begin()
            self.turn(text, self.history, on_sentence=on_sentence,
                      on_tool=on_tool, on_status=on_status)
        except Exception as exc:  # un tour ne doit jamais tuer la fenetre
            log(f"[gui] {exc}")
            self.events.put(("system", self.s["llm_error"]))
        finally:
            self.events.put(("finished", text))

    def _on_heard(self, heard, error) -> None:
        if heard:
            self._begin_turn(heard)
            return
        if error and error.startswith("network:"):
            self._add_message("", self.s["stt_error"], "system")
        self._set_busy(False)

    def _on_finished(self, text: str) -> None:
        if self._stream_text:
            self._transcript.append(("jarvis", self._stream_text))
        self._stream_body = None
        self._stream_text = ""
        self._set_busy(False)
        if is_exit_phrase(text, self.s["exit_phrases"]):
            self._say_and_close()

    def _say_and_close(self) -> None:
        def run() -> None:
            if not self.muted:
                try:
                    self.speech.begin()
                    self.speech.say(self.s["goodbye"])
                except Exception:
                    pass
            self.events.put(("close", None))

        threading.Thread(target=run, daemon=True).start()

    # -- actions ------------------------------------------------------------ #
    def on_stop(self) -> None:
        try:
            self.speech.cancel()
        except Exception:
            pass
        self._set_state("ready")

    def on_mute(self) -> None:
        self.muted = bool(self.mute_var.get())
        if self.muted:
            self.on_stop()

    def on_clear(self) -> None:
        for child in self.msg_frame.winfo_children():
            child.destroy()
        self._bubbles.clear()
        self._transcript.clear()
        self._stream_body = None
        self._stream_text = ""

    def on_export(self) -> None:
        if not self._transcript:
            messagebox.showinfo(self.s["gui_menu_export"],
                                self.s["gui_export_empty"])
            return
        names = {"user": self.s["gui_you"], "jarvis": self.s["gui_jarvis"],
                 "system": ""}
        lines = []
        for kind, text in self._transcript:
            prefix = names.get(kind, "")
            lines.append(f"{prefix}: {text}" if prefix else text)
        path = filedialog.asksaveasfilename(
            title=self.s["gui_export_title"], defaultextension=".txt",
            filetypes=[(self.s["gui_ft_text"], "*.txt"),
                       (self.s["gui_ft_all"], "*.*")],
        )
        if not path:
            return
        Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
        messagebox.showinfo(self.s["gui_menu_export"], self.s["gui_export_ok"])

    def on_about(self) -> None:
        from . import __version__

        tools = getattr(self.chain, "tools", None) or []
        messagebox.showinfo(self.s["gui_about"], self.s["gui_about_body"].format(
            version=__version__,
            model=getattr(self.args, "model", "-"),
            lang=self.args.lang,
            tools=len(tools) if tools else self.s["gui_none"],
            memory=self.s["gui_on"] if self.memory is not None
            else self.s["gui_off"],
        ))

    def on_close(self) -> None:
        self.closing = True
        for action in (lambda: self.speech.close(),
                       lambda: self.memory and self.memory.close(),
                       self.root.destroy):
            try:
                action()
            except Exception:
                pass

    # -- saisie ------------------------------------------------------------- #
    def _entry_text(self) -> str:
        if self._placeholder_active:
            return ""
        return self.entry.get().strip()

    def _reset_entry(self) -> None:
        self.entry.delete(0, "end")
        self._placeholder_active = False
        self.entry.configure(fg=FG)

    def _on_focus_in(self, _event=None) -> None:
        if self._placeholder_active:
            self.entry.delete(0, "end")
            self.entry.configure(fg=FG)
            self._placeholder_active = False

    def _on_focus_out(self, _event=None) -> None:
        if not self.entry.get().strip():
            self.entry.insert(0, self.s["gui_placeholder"])
            self.entry.configure(fg=FG_DIM)
            self._placeholder_active = True

    # -- rendu -------------------------------------------------------------- #
    def _add_message(self, author: str, text: str, kind: str = "jarvis"):
        if kind == "system":
            label = tk.Label(self.msg_frame, text=text, bg=PANEL, fg=FG_DIM,
                             font=(FONT, 8, "italic"), anchor="w",
                             justify="left", wraplength=640)
            label.pack(anchor="w", padx=22, pady=(2, 2), fill="x")
            self._bubbles.append(label)
            self._scroll_end()
            return label
        body = self._new_bubble(author, kind)
        body.configure(text=text)
        self._scroll_end()
        return body

    def _new_bubble(self, author: str, kind: str):
        row = tkf(self.msg_frame, bg=PANEL)
        row.pack(fill="x", pady=(3, 3))
        color = BUBBLE_USER if kind == "user" else BUBBLE_JARVIS
        fg = "#ffffff" if kind == "user" else FG
        name_fg = FG_USER_NAME if kind == "user" else FG_DIM
        bubble = tkf(row, bg=color)
        bubble.pack(anchor="e" if kind == "user" else "w", padx=22)
        tk.Label(bubble, text=author, bg=color, fg=name_fg,
                 font=(FONT, 8, "bold"), anchor="w").pack(fill="x", padx=12,
                                                          pady=(7, 0))
        body = tk.Label(bubble, text="", bg=color, fg=fg, font=(FONT, 10),
                        justify="left", anchor="w", wraplength=460)
        body.pack(fill="x", padx=12, pady=(2, 8))
        self._bubbles.append(body)
        return body

    def _append_reply(self, chunk: str) -> None:
        chunk = (chunk or "").strip()
        if not chunk:
            return
        if self._stream_body is None:
            self._stream_body = self._new_bubble(self.s["gui_jarvis"], "jarvis")
            self._stream_text = chunk
        else:
            self._stream_text = f"{self._stream_text} {chunk}"
        self._stream_body.configure(text=self._stream_text)
        self._scroll_end()

    def _speak_async(self, text: str) -> None:
        if self.muted:
            return

        def run() -> None:
            try:
                self.speech.begin()
                self.speech.say(text)
            except Exception as exc:
                log(f"[tts] {exc}")

        threading.Thread(target=run, daemon=True).start()

    # -- geometrie ---------------------------------------------------------- #
    def _scroll_end(self) -> None:
        self.msg_frame.update_idletasks()
        box = self.canvas.bbox("all")
        if box:
            self.canvas.configure(scrollregion=box)
        self.canvas.yview_moveto(1.0)

    def _on_frame_configure(self, _event=None) -> None:
        box = self.canvas.bbox("all")
        if box:
            self.canvas.configure(scrollregion=box)

    def _on_canvas_configure(self, event) -> None:
        self.canvas.itemconfigure(self.canvas_window, width=event.width)
        limit = max(220, event.width - 200)
        for label in self._bubbles:
            try:
                label.configure(wraplength=limit)
            except Exception:
                pass

    def _on_wheel(self, event) -> None:
        try:
            self.canvas.yview_scroll(int(-event.delta / 120), "units")
        except Exception:
            pass


def run(args, strings, listener, speech, chain, history, memory=None, greet=True):
    """Affiche la fenetre et boucle jusqu'a sa fermeture.

    Retourne ``0`` normalement, ``None`` si Tkinter ou l'affichage sont
    indisponibles pour que l'appelant retombe sur le mode console.
    """
    if tk is None:
        log("[gui] Tkinter indisponible : retour au mode console")
        return None

    try:
        root = tk.Tk()
    except Exception as exc:  # pragma: no cover - pas d'affichage
        log(f"[gui] fenetre impossible ({exc})")
        return None

    window = _Window(root, args, strings, listener, speech, chain, history,
                     memory, greet)
    window.start()
    root.mainloop()
    return 0


__all__ = ["available", "run"]
