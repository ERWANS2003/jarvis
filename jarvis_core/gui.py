"""Horizon 6 - interface graphique (Tkinter, bibliotheque standard).

Objectif : utiliser Jarvis comme une vraie application, sans console.

Principes de conception :

  * **Jamais de gel.** L'ecoute du micro et la reflexion du modele tournent
    dans un fil d'execution separe ; la fenetre reste reactive en permanence.
    Tkinter n'etant pas *thread-safe*, le fil de travail ne touche jamais aux
    widgets : il decharge des evenements dans une file, que le fil principal
    consomme periodiquement (`after`).
  * **Barre d'etat vivante** : une pastille coloree indique si Jarvis est pret,
    en train d'ecouter, de reflechir ou de parler ; elle *pulse* pendant un
    tour et les points d'etat s'animent, pour que l'inactivite soit lisible.
  * **Chrome utile** : en-tete avec avatar + raccourcis d'action, puces de
    suggestions tant que la conversation est vide, horloge sur chaque bulle,
    barre d'etat en pied de fenetre (modele, langue, outils, memoire) et
    raccourcis clavier documentes.
  * **Defensif** : si Tkinter ou l'affichage sont indisponibles, `run()`
    retourne ``None`` et `jarvis.py` reprend la boucle console.
"""

from __future__ import annotations

import queue
import threading
import time
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage

from . import graph as graphs
from . import intents
from . import quiz as quiz_mod
from . import hearing
from . import smart
from .text import is_exit_phrase, log

# Les outils de memoire ne doivent pas declencher « Un instant » : ils sont
# instantanes et ne justifient pas d'interrompre la conversation.
MEMORY_TOOLS = {"remember_fact", "recall_memory", "forget_memory"}
EXPERT_DEADLINE = 75.0   # secondes laissees au modele expert (il raisonne)

# --- Palette (theme sombre, inspiration Siri) ------------------------------ #
# Fond quasi noir, bleu Siri (#0a84ff) et violet (#5e5ce6) comme accents :
# c'est le contraste bas + les accents froids qui donnent l'impression d'un
# objet flottant plutot que d'une application « barre d'outils ».
BG = "#000000"
PANEL = "#08080c"
HEADER = "#000000"
FOOTER = "#000000"
BUBBLE_USER = "#0a84ff"
BUBBLE_JARVIS = "#16161d"
FG = "#f5f5f7"
FG_DIM = "#86868b"
FG_USER_NAME = "#cfe4ff"
ACCENT = "#0a84ff"
BTN = "#1c1c22"
BTN_HI = "#26262e"
BTN_OFF = "#15151a"        # bouton a demi eteint (envoyer sans texte)
CHIP = "#141419"           # pastille de l'en-tete (modele)
PILL = "#111116"           # fond de la pastille de saisie
STOP = "#ff453a"           # Stop energise pendant un tour
AVATAR_USER = "#0a84ff"    # pastille « Vous »
AVATAR_JARVIS = "#2c2c34"  # pastille « Jarvis »
DOT_READY = "#30d158"
DOT_BUSY = "#ff9f0a"
DOT_SPEAK = "#64d2ff"
DOT_LISTEN = "#0a84ff"

FONT = "Segoe UI"

# Couleurs de la pastille selon l'etat.
STATE_COLORS = {
    "ready": DOT_READY,
    "thinking": DOT_BUSY,
    "speaking": DOT_SPEAK,
    "listening": DOT_LISTEN,
}

# Degrade de l'orbe facon Siri : (anneau externe, anneau interne, noyau).
# L'orbe est le seul « personnage » de l'interface ; sa couleur dit l'etat.
ORB_COLORS = {
    "ready": ("#1b2a6b", "#0a84ff", "#d6e4ff"),
    "thinking": ("#5e3a12", "#ff9f0a", "#ffe9c7"),
    "speaking": ("#123a5e", "#64d2ff", "#dff4ff"),
    "listening": ("#0d4a2b", "#30d158", "#dbfbe6"),
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
        heard = getattr(turn, "heard", None)        # message dicte (hypotheses, confiance)
        turn.heard = None
        # 1. Commande simple (heure, ouvre YouTube, pause...) : sans le modele.
        #    Dictee : on essaie aussi les autres transcriptions (« met » / « mets »).
        quick = None
        candidates = [text] + (list(heard.alternatives[:3]) if heard is not None else [])
        ctx = getattr(args, "tool_ctx", None)
        for candidate in candidates:
            try:
                quick = intents.quick_answer(candidate, getattr(args, "lang", "fr"), strings,
                                             getattr(args, "allow_apps", None) or None,
                                             timers=getattr(ctx, "timers", None),
                                             reminders=getattr(ctx, "reminders", None),
                                             selection_api=intents.selection_for(ctx))
            except Exception as exc:  # une commande rapide ne casse jamais un tour
                log(f"[rapide] {exc}")
                quick = None
            if quick:
                if candidate != text:
                    log(f"[rapide] compris grace a l'hypothese « {candidate} »")
                break
        if quick:
            log(f"[rapide] {quick}")
            on_sentence(quick)
            history.append(HumanMessage(content=text))
            history.append(AIMessage(content=quick))
            graphs.save_history(history, args.history_path or _default_history())
            return

        # 2. Sinon le modele, avec ses outils seulement si la question en a besoin.
        def pick_graph():
            chooser = getattr(chain, "graph_for", None)
            return chooser(text) if chooser else (chain.graph, chain.tools_enabled)

        lang = "fr" if getattr(args, "lang", "fr") == "fr" else "en"
        graph, with_tools = pick_graph()
        expert = bool(getattr(chain, "last_expert", False))
        detailed = smart.needs_detail(text)
        base_prompt = strings["system"].format(
            ability=args.ability, words=args.max_words
        )
        extra = "\n\n".join(part for part in (
            hearing.guidance(heard, lang),
            quiz_mod.rules_for(args), smart.DETAIL_RULES[lang] if detailed else "",
            strings.get("verify_guidance" if with_tools else "honesty_guidance", "")) if part)
        system_prompt = graphs.build_system_prompt(
            base_prompt, memory=memory, query=text, strings=strings,
            with_tools=with_tools, extra=extra,
        )
        messages = graphs.make_turn_messages(system_prompt, history, text)
        announced = {"done": False}

        used: set[str] = set()

        def tool_hook(name: str) -> None:
            log(f"[outil] {name}")
            used.add(name)
            if not announced["done"] and name not in MEMORY_TOOLS:
                announced["done"] = True
                hint = strings.get("tool_running", "")
                if hint:
                    on_status(hint)
            on_tool(name)

        # Reponse detaillee : le resume est dit, le detail part a l'ecran.
        speaker = smart.DetailSplitter(on_sentence) if detailed else on_sentence
        if expert:
            on_sentence(smart.EXPERT_HINT[lang])   # le modele expert met ~20 s
        result = graphs.stream_reply(graph, messages,
                                     on_sentence=speaker,
                                     retries=args.retries, on_tool=tool_hook,
                                     deadline=EXPERT_DEADLINE if expert else graphs.TURN_DEADLINE)
        # Un tour peut « reussir » sans rien dire : les modeles de raisonnement
        # gratuits remplissent `reasoning` et laissent `content` vide. On tente
        # alors le repli suivant, exactement comme pour une vraie panne.
        if (not result.ok or result.empty) and chain.advance():
            if not expert:   # l'expert qui echoue repasse au modele rapide, sans annonce
                on_status(strings.get("fallback_used", ""))
            graph, _with_tools = pick_graph()
            result = graphs.stream_reply(graph, messages,
                                         on_sentence=speaker,
                                         retries=args.retries, on_tool=tool_hook)
        if not result.ok:
            log(f"[llm] {result.error}")
            on_status(strings["llm_error"])
            return
        if result.empty:
            # Plus rien a tenter : on annonce l'echec au lieu de rester muet.
            log("[llm] reponse vide")
            on_sentence(strings["empty_reply"])
            history.append(messages[-1])
            graphs.save_history(history, args.history_path or _default_history())
            return

        from .memory import FACT, PROFILE, extract_explicit, extract_profile

        reply = graphs.message_text(result.messages[-1]) if result.messages else ""
        if detailed:
            markdown = speaker.finish()
            if smart.DETAIL_MARK in reply:      # texte d'origine : sauts de ligne intacts
                markdown = reply.split(smart.DETAIL_MARK, 1)[1].strip()
            if markdown and turn.on_detail is not None:
                turn.on_detail(markdown)
        history.append(messages[-1])
        history.extend(result.messages)
        if "remember_fact" not in used:          # le modele a deja retenu ce qu'il fallait
            smart.learn_async(memory, getattr(chain, "ask", None), text, reply, lang)
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

    turn.on_detail = None   # fenetre de detail (branchee par l'interface)
    turn.heard = None       # hearing.Heard du message dicte (pose par l'interface)
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
        self._state_text = self.s["gui_state_ready"]   # dernier libelle d'etat
        self._follow = True                            # suit le bas du fil
        self._pulse_step = 0

        self._bubbles: list = []              # labels dont la largeur s'adapte
        self._transcript: list[tuple[str, str]] = []
        self._stream_body = None
        self._stream_text = ""

        self._build()

    # -- construction ------------------------------------------------------- #
    def _build(self) -> None:
        root = self.root
        root.title("Jarvis")
        root.geometry("900x640")
        root.minsize(560, 420)
        root.configure(bg=BG)
        self._set_icon()

        self._build_header()
        self._build_chat()
        self._build_chips()
        self._build_input()
        self._build_footer()

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.bind("<Escape>", lambda _e: self.on_stop())
        root.bind("<Control-l>", lambda _e: self.on_clear())
        root.bind("<Control-e>", lambda _e: self.on_export())
        root.bind("<Control-m>", lambda _e: self._toggle_mute())
        root.bind("<Control-q>", lambda _e: self.on_close())
        root.bind_all("<MouseWheel>", self._on_wheel)

    def _set_icon(self) -> None:
        """Fabrique l'icone de la fenetre (cercle + J) sans fichier externe."""
        if tk is None:
            return
        try:
            size = 32
            cx = cy = (size - 1) / 2.0
            radius = 13.0
            grid = [[HEADER] * size for _ in range(size)]
            for y in range(size):
                for x in range(size):
                    if (x - cx) ** 2 + (y - cy) ** 2 <= radius ** 2:
                        grid[y][x] = ACCENT

            def rect(x1: int, y1: int, x2: int, y2: int, color: str) -> None:
                for yy in range(max(0, y1), min(size, y2)):
                    for xx in range(max(0, x1), min(size, x2)):
                        grid[yy][xx] = color

            rect(11, 7, 22, 10, "#ffffff")   # barre haute du J
            rect(16, 8, 19, 22, "#ffffff")   # fut vertical
            rect(13, 21, 20, 23, "#ffffff")  # courbe basse
            rect(12, 23, 18, 25, "#ffffff")

            img = tk.PhotoImage(width=size, height=size)
            img.put(tuple(tuple(row) for row in grid))
            self._icon_img = img              # reference a garder
            self.root.iconphoto(True, img)
        except Exception as exc:              # jamais bloquant
            log(f"[gui] icone: {exc}")

    def _build_header(self) -> None:
        header = tkf(self.root, bg=HEADER, height=96)
        header.pack(fill="x")
        header.pack_propagate(False)

        # L'orbe : le seul « personnage » de l'ecran. Trois anneaux concentriques
        # font un halo et le noyau porte la teinte de l'etat. Les anneaux sont
        # memorises pour que _pulse() et _set_state() puissent les animer.
        self.dot = tk.Canvas(header, width=72, height=72, bg=HEADER,
                             highlightthickness=0)
        self.dot.pack(side="left", padx=(24, 16))
        ready = ORB_COLORS["ready"]
        self._orb_rings = [
            self.dot.create_oval(*self._orb_box(31), fill=ready[0], outline=""),
            self.dot.create_oval(*self._orb_box(24), fill=ready[1], outline=""),
            self.dot.create_oval(*self._orb_box(17), fill=ready[2], outline=""),
        ]
        self.dot_item = self.dot.create_oval(*self._orb_box(10),
                                             fill=ACCENT, outline="")

        # Titre + modele + libelle d'etat (remplace l'ancienne pastille).
        titles = tkf(header, bg=HEADER)
        titles.pack(side="left")
        top = tkf(titles, bg=HEADER)
        top.pack(fill="x")
        tk.Label(top, text="JARVIS", bg=HEADER, fg=FG,
                 font=(FONT, 21, "bold")).pack(side="left")
        tk.Label(top, text=self._subtitle(), bg=CHIP, fg=FG_DIM,
                 font=(FONT, 8), padx=7, pady=1).pack(side="left",
                                                      padx=(10, 0))
        self.status = tk.StringVar(value=self._state_text)
        tk.Label(titles, textvariable=self.status, bg=HEADER, fg=FG_DIM,
                 font=(FONT, 10)).pack(anchor="w", pady=(3, 0))

        # Cote droit : actions discretes, sans cadre. L'ordre de empilement a
        # droite donne, de gauche a droite : « ? », effacer, exporter, mute.
        self.mute_var = tk.BooleanVar(value=False)
        self.btn_mute = tkc(header, text=self.s["gui_mute"],
                            variable=self.mute_var, command=self.on_mute,
                            indicatoron=0, bg=BTN_HI, fg=FG_DIM,
                            activebackground=ACCENT, activeforeground="#ffffff",
                            selectcolor=ACCENT, font=(FONT, 9, "bold"),
                            relief="flat", bd=0, padx=12, pady=4,
                            cursor="hand2")
        self.btn_mute.pack(side="right", padx=(0, 22))
        self._header_button(header, self.s["gui_export_short"],
                            self.on_export).pack(side="right", padx=(0, 8))
        self._header_button(header, self.s["gui_clear"],
                            self.on_clear).pack(side="right", padx=(0, 8))
        self._header_button(header, "?", self.on_about).pack(
            side="right", padx=(0, 8))

    @staticmethod
    def _orb_box(radius: float, spread: int = 0):
        """Boite englobante d'un anneau de l'orbe (canevas 72x72, centre 36)."""
        r = radius + spread
        return (36 - r, 36 - r, 36 + r, 36 + r)

    @staticmethod
    def _header_button(parent, text, command):
        return tk.Button(parent, text=text, command=command, bg=BTN_HI,
                         fg=FG_DIM, activebackground=ACCENT,
                         activeforeground="#ffffff", relief="flat", bd=0,
                         font=(FONT, 9, "bold"), padx=10, pady=4,
                         cursor="hand2")

    def _build_chat(self) -> None:
        body = tkf(self.root, bg=PANEL)
        body.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(body, bg=PANEL, highlightthickness=0, bd=0)
        bar = tksb(body, orient="vertical", command=self._on_scrollbar)
        self.canvas.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.msg_frame = tkf(self.canvas, bg=PANEL)
        self.canvas_window = self.canvas.create_window((0, 0),
                                                       window=self.msg_frame,
                                                       anchor="nw")
        self.msg_frame.bind("<Configure>", self._on_frame_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        # Bouton « derniers messages » : visible seulement si l'on a remonte.
        self.btn_down = tk.Button(body, text="\u2193",
                                  command=self._jump_end, bg=ACCENT,
                                  fg="#ffffff", activebackground=ACCENT,
                                  relief="flat", bd=0, font=(FONT, 12,
                                                             "bold"),
                                  width=2, height=1, cursor="hand2")
        self.btn_down.place_forget()

    def _build_chips(self) -> None:
        """Suggestions cliquables : la conversation commence plus vite."""
        self._chip_frame = tkf(self.root, bg=BG)
        self._chip_frame.pack(fill="x")
        tk.Label(self._chip_frame, text=self.s["gui_suggest_title"], bg=BG,
                 fg=FG_DIM, font=(FONT, 9)).pack(side="left",
                                                 padx=(16, 8), pady=(7, 0))
        for text in (self.s["gui_suggest_1"], self.s["gui_suggest_2"],
                     self.s["gui_suggest_3"]):
            tk.Button(self._chip_frame, text=text,
                      command=lambda t=text: self._use_suggestion(t),
                      bg=BTN, fg=FG_DIM, activebackground=BTN_HI,
                      activeforeground=FG, relief="flat", bd=0,
                      font=(FONT, 9), padx=10, pady=2,
                      cursor="hand2").pack(side="left", padx=(0, 6),
                                           pady=(6, 0))

    def _build_input(self) -> None:
        bar = tkf(self.root, bg=BG, height=72)
        bar.pack(fill="x")
        bar.pack_propagate(False)

        # Pastille arrondie : Tkinter n'arrondit pas les widgets, on dessine
        # donc le fond au canevas et on pose la saisie et les boutons dessus
        # (create_window), repositionnes a chaque redimensionnement.
        self.pill_canvas = tk.Canvas(bar, bg=BG, highlightthickness=0, bd=0)
        self.pill_canvas.pack(fill="both", expand=True)
        self.pill_canvas.bind("<Configure>", self._on_pill_configure)

        self.entry = tke(self.pill_canvas, bg=PILL, fg=FG_DIM,
                         insertbackground=FG, relief="flat", font=(FONT, 12),
                         highlightthickness=0, bd=0)
        self._placeholder_active = True
        self.entry.insert(0, self.s["gui_placeholder"])
        self.entry.bind("<Return>", self.on_send)
        self.entry.bind("<FocusIn>", self._on_focus_in)
        self.entry.bind("<FocusOut>", self._on_focus_out)
        self.entry.bind("<KeyRelease>", self._refresh_send)
        self._pill_entry = self.pill_canvas.create_window(
            0, 0, anchor="w", window=self.entry, height=34)

        self.btn_send = self._button(self.pill_canvas, self.s["gui_send"],
                                     self.on_send, BTN_OFF, FG_DIM)
        self._pill_send = self.pill_canvas.create_window(
            0, 0, anchor="e", window=self.btn_send)

        self.btn_listen = None
        if self.listener is not None:
            self.btn_listen = self._button(self.pill_canvas,
                                           self.s["gui_listen"], self.on_listen,
                                           BTN_HI, FG)
            self._pill_listen = self.pill_canvas.create_window(
                0, 0, anchor="e", window=self.btn_listen)

        self.btn_stop = self._button(self.pill_canvas, self.s["gui_stop"],
                                     self.on_stop, BTN_HI, FG)
        self._pill_stop = self.pill_canvas.create_window(
            0, 0, anchor="e", window=self.btn_stop)

    @staticmethod
    def _round_rect_points(x1, y1, x2, y2, r):
        """Points d'un rectangle arrondi (pour create_polygon smooth=True)."""
        r = max(0.0, min(r, (x2 - x1) / 2.0, (y2 - y1) / 2.0))
        return [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r,
                x2, y2, x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r,
                x1, y1 + r, x1, y1]

    def _on_pill_configure(self, _event=None) -> None:
        """Redessine la pastille et replace la saisie quand la fenetre bouge."""
        canvas = getattr(self, "pill_canvas", None)
        if canvas is None:
            return
        canvas.delete("pill")
        width = canvas.winfo_width()
        height = canvas.winfo_height()
        if width < 60 or height < 34:
            return
        try:
            canvas.create_polygon(
                self._round_rect_points(4, 4, width - 4, height - 4,
                                        (height - 8) / 2.0),
                smooth=True, splinesteps=24, fill=PILL, outline=BTN_HI,
                width=1, tags="pill")
            canvas.tag_lower("pill")
            canvas.update_idletasks()

            cy = height // 2
            right = width - 18
            canvas.coords(self._pill_send, right, cy)
            right -= self.btn_send.winfo_reqwidth() + 8
            if self.btn_listen is not None:
                canvas.coords(self._pill_listen, right, cy)
                right -= self.btn_listen.winfo_reqwidth() + 8
            canvas.coords(self._pill_stop, right, cy)
            right -= self.btn_stop.winfo_reqwidth() + 10
            canvas.coords(self._pill_entry, 34, cy)
            canvas.itemconfigure(self._pill_entry, width=max(120, right - 34))
        except Exception:  # jamais bloquant : la fenetre peut se fermer
            pass

    def _build_footer(self) -> None:
        """Pied de fenetre : ce que Jarvis a sous la main + raccourcis."""
        bar = tkf(self.root, bg=FOOTER, height=26)
        bar.pack(fill="x", side="bottom")
        bar.pack_propagate(False)

        tools = getattr(self.chain, "tools", None) or []
        facts = [
            f"{self.s['gui_model']} : {getattr(self.args, 'model', '-')}",
            f"{self.s['gui_lang']} : {getattr(self.args, 'lang', '-')}",
            f"{self.s['gui_tools_word']} : "
            f"{len(tools) if tools else self.s['gui_none']}",
            f"{self.s['gui_memory_word']} : "
            f"{self.s['gui_on'] if self.memory is not None else self.s['gui_off']}",
        ]
        tk.Label(bar, text="   \u00b7   ".join(facts), bg=FOOTER, fg=FG_DIM,
                 font=(FONT, 8)).pack(side="left", padx=(16, 0))
        tk.Label(bar, text=self.s["gui_hints"], bg=FOOTER, fg="#5f5f78",
                 font=(FONT, 8)).pack(side="right", padx=(0, 16))

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
        self._pulse()
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
        self._state_text = text
        self.status.set(text)
        # L'orbe entier change de teinte : anneaux du halo puis noyau central.
        ring, inner, core = ORB_COLORS.get(state, ORB_COLORS["ready"])
        for item, fill in zip(getattr(self, "_orb_rings", ()),
                              (ring, inner, core)):
            try:
                self.dot.itemconfigure(item, fill=fill)
            except Exception:
                pass
        self.dot.itemconfigure(self.dot_item, fill=STATE_COLORS.get(state, DOT_READY))

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        state = "disabled" if busy else "normal"
        for button in (self.btn_send, self.btn_listen):
            if button is not None:
                button.configure(state=state)
        if self.btn_stop is not None:
            self.btn_stop.configure(bg=STOP if busy else BTN_HI,
                                    fg="#ffffff" if busy else FG)
        if not busy:
            self._set_state("ready")

    def _pulse(self) -> None:
        """Fait respirer l'orbe et avancer les points pendant un tour.

        Un tour dure plusieurs secondes : sans mouvement, on ne sait pas si
        Jarvis travaille encore. Les anneaux s'ecartent puis se resserrent et
        les points de suspension avancent, sans jamais toucher aux fils de
        travail.
        """
        if self.closing or self.dot is None:
            return
        try:
            rings = getattr(self, "_orb_rings", ())
            if self.state in ("thinking", "speaking", "listening"):
                self._pulse_step = (self._pulse_step + 1) % 4
                spread = (0, 2, 4, 2)[self._pulse_step]
                base = self._state_text.rstrip(". ")
                self.status.set(f"{base}{'.' * (self._pulse_step % 3 + 1)}")
            else:
                spread = 0
                if self.status.get() != self._state_text:
                    self.status.set(self._state_text)
            for item, radius in zip(rings, (31, 24, 17)):
                try:
                    self.dot.coords(item, *self._orb_box(radius, spread))
                except Exception:
                    pass
            try:
                self.dot.coords(self.dot_item, *self._orb_box(10, spread // 2))
            except Exception:
                pass
            self.root.after(450, self._pulse)
        except Exception:  # fenetre fermee pendant l'animation
            self.closing = True

    # -- conversation ------------------------------------------------------- #
    def on_send(self, _event=None) -> None:
        text = self._entry_text()
        if not text:
            return
        self._reset_entry()
        self._refresh_send()
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
        self._refresh_send()
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
        if getattr(self, "btn_mute", None) is not None:
            self.btn_mute.configure(bg=ACCENT if self.muted else BTN_HI,
                                    fg="#ffffff" if self.muted else FG_DIM)
        if self.muted:
            self.on_stop()

    def _toggle_mute(self) -> None:
        self.mute_var.set(not self.mute_var.get())
        self.on_mute()

    def _use_suggestion(self, text: str) -> None:
        """Remplit le champ avec une suggestion (l'envoi reste au clavier)."""
        self.entry.delete(0, "end")
        self._placeholder_active = False
        self.entry.configure(fg=FG)
        self.entry.insert(0, text)
        self.entry.focus_set()
        self._refresh_send()

    def on_clear(self) -> None:
        for child in self.msg_frame.winfo_children():
            child.destroy()
        self._bubbles.clear()
        self._transcript.clear()
        self._stream_body = None
        self._stream_text = ""
        self._follow = True
        self._scroll_end()
        self._refresh_send()

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

    def _refresh_send(self, _event=None) -> None:
        """Le bouton Envoyer ne s'allume que lorsqu'il y a quelque chose a dire."""
        if getattr(self, "btn_send", None) is None:
            return
        ready = bool(self._entry_text())
        self.btn_send.configure(bg=ACCENT if ready else BTN_OFF,
                                fg="#ffffff" if ready else FG_DIM)

    def _reset_entry(self) -> None:
        self.entry.delete(0, "end")
        self._placeholder_active = False
        self.entry.configure(fg=FG)
        self._refresh_send()

    def _on_focus_in(self, _event=None) -> None:
        if self._placeholder_active:
            self.entry.delete(0, "end")
            self.entry.configure(fg=FG)
            self._placeholder_active = False
        self._refresh_send()

    def _on_focus_out(self, _event=None) -> None:
        if not self.entry.get().strip():
            self.entry.insert(0, self.s["gui_placeholder"])
            self.entry.configure(fg=FG_DIM)
            self._placeholder_active = True
        self._refresh_send()

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
        row.pack(fill="x", pady=(4, 4))
        color = BUBBLE_USER if kind == "user" else BUBBLE_JARVIS
        fg = "#ffffff" if kind == "user" else FG
        name_fg = FG_USER_NAME if kind == "user" else FG_DIM

        line = tkf(row, bg=PANEL)
        line.pack(anchor="e" if kind == "user" else "w",
                  padx=(64, 16) if kind == "user" else (16, 64))
        avatar = tk.Canvas(line, width=28, height=28, bg=PANEL,
                           highlightthickness=0)
        if kind != "user":
            avatar.pack(side="left", padx=(0, 8), anchor="n")
            self._draw_avatar(avatar, AVATAR_JARVIS, "J")
        bubble = tkf(line, bg=color)
        bubble.pack(side="left")
        if kind == "user":
            avatar.pack(side="left", padx=(8, 0), anchor="n")
            self._draw_avatar(avatar, AVATAR_USER,
                              (author or "?").strip()[:1].upper() or "?")

        head = tkf(bubble, bg=color)
        head.pack(fill="x", padx=12, pady=(7, 0))
        tk.Label(head, text=author, bg=color, fg=name_fg,
                 font=(FONT, 8, "bold")).pack(side="left")
        tk.Label(head, text=time.strftime("%H:%M"), bg=color, fg=name_fg,
                 font=(FONT, 8)).pack(side="right")

        body = tk.Label(bubble, text="", bg=color, fg=fg, font=(FONT, 10),
                        justify="left", anchor="w", wraplength=460)
        body.pack(fill="x", padx=12, pady=(2, 8))
        self._bubbles.append(body)
        return body

    @staticmethod
    def _draw_avatar(canvas, color: str, letter: str) -> None:
        canvas.create_oval(0, 0, 26, 26, fill=color, outline="")
        canvas.create_text(13, 13, text=letter, fill="#ffffff",
                           font=(FONT, 10, "bold"))

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
        if self._follow:
            self.canvas.yview_moveto(1.0)
        self._refresh_down()

    def _on_scrollbar(self, *args) -> None:
        self.canvas.yview(*args)
        self._update_follow()

    def _update_follow(self) -> None:
        """Sait si l'on regarde la fin du fil (sinon, on ne force plus)."""
        try:
            _top, bottom = self.canvas.yview()
            self._follow = bottom >= 0.99
        except Exception:
            self._follow = True
        self._refresh_down()

    def _refresh_down(self) -> None:
        if getattr(self, "btn_down", None) is None:
            return
        try:
            if self._follow:
                self.btn_down.place_forget()
            else:
                self.btn_down.place(relx=1.0, rely=1.0, x=-18, y=-14,
                                    anchor="se")
        except Exception:
            pass

    def _jump_end(self) -> None:
        self._follow = True
        self._scroll_end()

    def _on_frame_configure(self, _event=None) -> None:
        box = self.canvas.bbox("all")
        if box:
            self.canvas.configure(scrollregion=box)

    def _on_canvas_configure(self, event) -> None:
        self.canvas.itemconfigure(self.canvas_window, width=event.width)
        limit = max(220, event.width - 240)
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
        self._update_follow()


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
