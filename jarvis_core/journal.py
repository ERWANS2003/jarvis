"""Journal de Jarvis : conversations, rappels a venir et souvenirs, dans une fenetre.

Ouvert depuis le menu de l'orbe (clic droit -> « Journal »). Trois onglets :

  * **Conversations** : tout l'historique enregistre, avec une recherche ;
  * **Rappels** : les rappels a venir, annulables un par un ;
  * **Souvenirs** : ce que Jarvis a retenu de toi, effacable un par un.

Les donnees sont lues a l'ouverture et a chaque changement d'onglet : rien
n'est copie, la fenetre montre l'etat reel de Jarvis.
"""

from __future__ import annotations

import datetime as _dt
import re

try:
    import tkinter as tk
except Exception:  # pragma: no cover - Python sans Tk
    tk = None

FONT = "Segoe UI"
LABELS = {
    "fr": {"title": "Journal de Jarvis", "talks": "Conversations", "reminders": "Rappels",
           "memories": "Souvenirs", "search": "Rechercher…", "you": "Toi", "jarvis": "Jarvis",
           "empty_talks": "Aucune conversation enregistrée.",
           "empty_reminders": "Aucun rappel à venir.",
           "empty_memories": "Jarvis n'a encore rien retenu. Dis-lui « retiens que… ».",
           "cancel": "Annuler", "forget": "Oublier", "clear": "Effacer la conversation",
           "count": "{n} message(s)"},
    "en": {"title": "Jarvis journal", "talks": "Conversations", "reminders": "Reminders",
           "memories": "Memories", "search": "Search…", "you": "You", "jarvis": "Jarvis",
           "empty_talks": "No saved conversation.", "empty_reminders": "No upcoming reminder.",
           "empty_memories": "Jarvis remembers nothing yet. Say “remember that…”.",
           "cancel": "Cancel", "forget": "Forget", "clear": "Clear the conversation",
           "count": "{n} message(s)"},
}


def conversation_lines(history, query: str = "") -> list[tuple[str, str]]:
    """[(qui, texte)] depuis l'historique LangChain, filtre par `query`."""
    lines: list[tuple[str, str]] = []
    query = (query or "").strip().lower()
    for message in history or []:
        kind = getattr(message, "type", "")
        text = message.content if isinstance(message.content, str) else ""
        if kind not in ("human", "ai") or not text.strip():
            continue
        if query and query not in text.lower():
            continue
        text = text.replace("---DETAIL---", "\n").strip()    # marque des reponses detaillees
        lines.append(("you" if kind == "human" else "jarvis", text))
    return lines


def reminder_label(item: dict, lang: str) -> str:
    when = _dt.datetime.fromisoformat(item["when"])
    stamp = when.strftime("%d/%m %H:%M")
    return f"{stamp}  ·  {item['text']}"


class Journal:
    def __init__(self, root, app, colors: dict, lang: str = "fr", reminders=None):
        self.app = app
        self.c = colors
        self.reminders = reminders
        self.t = LABELS["fr" if lang == "fr" else "en"]
        self.lang = lang
        self.win = tk.Toplevel(root)
        self.win.title(self.t["title"])
        self.win.geometry("560x620")
        self.win.minsize(420, 360)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=colors["bg"])
        self.win.bind("<Escape>", lambda _e: self.close())
        self.tab = "talks"
        self._build()
        self.show("talks")

    # -- construction ------------------------------------------------------- #
    def _build(self) -> None:
        c = self.c
        bar = tk.Frame(self.win, bg=c["bg"])
        bar.pack(fill="x", padx=12, pady=(12, 6))
        self.tabs = {}
        for key in ("talks", "reminders", "memories"):
            label = tk.Label(bar, text=self.t[key], bg=c["bg"], fg=c["dim"],
                             font=(FONT, 11, "bold"), padx=12, pady=6, cursor="hand2")
            label.pack(side="left")
            label.bind("<Button-1>", lambda _e, k=key: self.show(k))
            self.tabs[key] = label

        self.search_var = tk.StringVar()
        self.search = tk.Entry(self.win, textvariable=self.search_var, relief="flat",
                               bg=c["active"], fg=c["fg"], insertbackground=c["fg"],
                               font=(FONT, 10))
        self.search_var.trace_add("write", lambda *_a: self._fill_talks())

        holder = tk.Frame(self.win, bg=c["bg"])
        holder.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.canvas = tk.Canvas(holder, bg=c["bg"], highlightthickness=0)
        scroll = tk.Scrollbar(holder, orient="vertical", command=self.canvas.yview)
        self.body = tk.Frame(self.canvas, bg=c["bg"])
        self.body.bind("<Configure>", lambda _e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self._body_id = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(
            self._body_id, width=e.width))
        self.canvas.configure(yscrollcommand=scroll.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.win.bind("<MouseWheel>", lambda e: self.canvas.yview_scroll(
            int(-e.delta / 120), "units"))
        self.footer = tk.Frame(self.win, bg=c["bg"])
        self.footer.pack(fill="x", padx=12, pady=(0, 12))

    def _clear_body(self) -> None:
        for child in self.body.winfo_children():
            child.destroy()
        for child in self.footer.winfo_children():
            child.destroy()

    def _note(self, text: str) -> None:
        tk.Label(self.body, text=text, bg=self.c["bg"], fg=self.c["dim"], font=(FONT, 10),
                 anchor="w", justify="left", pady=12).pack(fill="x")

    def _button(self, parent, text: str, command) -> tk.Label:
        button = tk.Label(parent, text=text, bg=self.c["active"], fg=self.c["accent"],
                          font=(FONT, 9, "bold"), padx=10, pady=3, cursor="hand2")
        button.bind("<Button-1>", lambda _e: command())
        return button

    # -- onglets ------------------------------------------------------------ #
    def show(self, tab: str) -> None:
        self.tab = tab
        for key, label in self.tabs.items():
            label.configure(fg=self.c["accent"] if key == tab else self.c["dim"])
        if tab == "talks":
            self.search.pack(fill="x", padx=12, pady=(0, 8), before=self.canvas.master)
            self._fill_talks()
        else:
            self.search.pack_forget()
            (self._fill_reminders if tab == "reminders" else self._fill_memories)()
        self.canvas.yview_moveto(0.0 if tab != "talks" else 1.0)

    def _fill_talks(self) -> None:
        if self.tab != "talks":
            return
        self._clear_body()
        lines = conversation_lines(self.app.history, self.search_var.get())
        if not lines:
            self._note(self.t["empty_talks"])
        wrap = 470
        for who, text in lines:
            tk.Label(self.body, text=self.t[who], bg=self.c["bg"],
                     fg=self.c["accent"] if who == "jarvis" else self.c["dim"],
                     font=(FONT, 9, "bold"), anchor="w").pack(fill="x", pady=(8, 0))
            tk.Label(self.body, text=text, bg=self.c["bg"], fg=self.c["fg"], font=(FONT, 10),
                     anchor="w", justify="left", wraplength=wrap).pack(fill="x")
        tk.Label(self.footer, text=self.t["count"].format(n=len(lines)), bg=self.c["bg"],
                 fg=self.c["dim"], font=(FONT, 9)).pack(side="left")
        self._button(self.footer, self.t["clear"], self._clear_talks).pack(side="right")
        self.win.after(30, lambda: self.canvas.yview_moveto(1.0))

    def _clear_talks(self) -> None:
        if self.app.clear():
            self._fill_talks()

    def _fill_reminders(self) -> None:
        self._clear_body()
        items = self.reminders.list() if self.reminders is not None else []
        if not items:
            self._note(self.t["empty_reminders"])
        for item in items:
            self._row(reminder_label(item, self.lang),
                      self.t["cancel"], lambda i=item: self._cancel(i["id"]))

    def _cancel(self, reminder_id: int) -> None:
        self.reminders.cancel(reminder_id)
        self._fill_reminders()

    def _fill_memories(self) -> None:
        self._clear_body()
        items = self.app.memories()
        if not items:
            self._note(self.t["empty_memories"])
        for item in items:
            self._row(item.get("text", ""), self.t["forget"],
                      lambda i=item: self._forget(i["id"]))

    def _forget(self, mem_id: int) -> None:
        self.app.forget(mem_id)
        self._fill_memories()

    def _row(self, text: str, action: str, command) -> None:
        row = tk.Frame(self.body, bg=self.c["bg"], pady=4)
        row.pack(fill="x")
        self._button(row, action, command).pack(side="right", padx=(8, 0))
        tk.Label(row, text=text, bg=self.c["bg"], fg=self.c["fg"], font=(FONT, 10),
                 anchor="w", justify="left", wraplength=400).pack(side="left", fill="x",
                                                                   expand=True)

    def lift(self) -> None:
        self.win.deiconify()
        self.win.lift()
        self.win.focus_force()

    def close(self) -> None:
        try:
            self.win.destroy()
        except Exception:
            pass

    def alive(self) -> bool:
        try:
            return bool(self.win.winfo_exists())
        except Exception:
            return False


_INLINE = re.compile(r"(\*\*[^*]+\*\*|`[^`]+`)")


def markdown_blocks(markdown: str) -> list[tuple[str, str]]:
    """Markdown simple -> [(style, texte)] : h1, h2, h3, puce, numero, texte, vide."""
    blocks: list[tuple[str, str]] = []
    for raw in (markdown or "").splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            blocks.append(("blank", ""))
        elif stripped.startswith("### "):
            blocks.append(("h3", stripped[4:]))
        elif stripped.startswith("## "):
            blocks.append(("h2", stripped[3:]))
        elif stripped.startswith("# "):
            blocks.append(("h1", stripped[2:]))
        elif re.match(r"^[-*•]\s+", stripped):
            blocks.append(("bullet", re.sub(r"^[-*•]\s+", "", stripped)))
        elif re.match(r"^\d+[.)]\s+", stripped):
            blocks.append(("number", stripped))
        elif set(stripped) <= {"-", "=", "|", ":", " "}:
            continue                                     # regles et separateurs de tableau
        else:
            blocks.append(("text", stripped.strip("|").replace(" | ", "  ·  ")))
    return blocks


class DetailView:
    """Reponse detaillee de Jarvis, mise en forme (titres, listes, gras)."""

    def __init__(self, root, markdown: str, colors: dict, lang: str = "fr"):
        c = colors
        self.markdown = markdown
        self.win = tk.Toplevel(root)
        self.win.title("Jarvis — " + ("réponse détaillée" if lang == "fr" else "detailed answer"))
        self.win.geometry("620x680")
        self.win.minsize(420, 320)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=c["bg"])
        self.win.bind("<Escape>", lambda _e: self.close())
        bar = tk.Frame(self.win, bg=c["bg"])
        bar.pack(fill="x", padx=14, pady=(12, 4))
        tk.Label(bar, text="JARVIS", bg=c["bg"], fg=c["accent"],
                 font=(FONT, 10, "bold")).pack(side="left")
        for label, command in ((("Copier" if lang == "fr" else "Copy"), self.copy),
                               (("Fermer" if lang == "fr" else "Close"), self.close)):
            button = tk.Label(bar, text=label, bg=c["active"], fg=c["accent"], cursor="hand2",
                              font=(FONT, 9, "bold"), padx=10, pady=3)
            button.pack(side="right", padx=(6, 0))
            button.bind("<Button-1>", lambda _e, cmd=command: cmd())
        text = tk.Text(self.win, wrap="word", bg=c["bg"], fg=c["fg"], relief="flat",
                       font=(FONT, 11), padx=22, pady=10, highlightthickness=0,
                       spacing1=2, spacing3=4, cursor="arrow")
        scroll = tk.Scrollbar(self.win, command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        text.pack(fill="both", expand=True)
        text.tag_configure("h1", font=(FONT, 17, "bold"), foreground=c["accent"], spacing1=12)
        text.tag_configure("h2", font=(FONT, 14, "bold"), foreground=c["accent"], spacing1=12)
        text.tag_configure("h3", font=(FONT, 12, "bold"), spacing1=8)
        text.tag_configure("bullet", lmargin1=12, lmargin2=30)
        text.tag_configure("number", lmargin1=12, lmargin2=30)
        text.tag_configure("bold", font=(FONT, 11, "bold"))
        text.tag_configure("code", font=("Consolas", 10), background=c["active"])
        for style, line in markdown_blocks(markdown):
            if style == "blank":
                text.insert("end", "\n")
                continue
            prefix = "•  " if style == "bullet" else ""
            tags = (style,) if style != "text" else ()
            text.insert("end", prefix, tags)
            for part in _INLINE.split(line):
                if part.startswith("**") and part.endswith("**") and len(part) > 4:
                    text.insert("end", part[2:-2], tags + ("bold",))
                elif part.startswith("`") and part.endswith("`") and len(part) > 2:
                    text.insert("end", part[1:-1], tags + ("code",))
                elif part:
                    text.insert("end", part.replace("**", ""), tags)
            text.insert("end", "\n", tags)
        text.configure(state="disabled")
        self.text = text

    def copy(self) -> None:
        self.win.clipboard_clear()
        self.win.clipboard_append(self.markdown)

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


__all__ = ["Journal", "DetailView", "markdown_blocks", "conversation_lines", "reminder_label",
           "LABELS"]
