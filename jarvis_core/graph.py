"""Graphe LangGraph : boucle ReAct + memoire + streaming.

Le graphe reste volontairement minimal :

    START -> model -> (tools -> model)* -> END

  * sans outil, il se reduit a un simple appel au modele (Horizon 1) ;
  * avec les outils de l'Horizon 3, il devient un agent ReAct complet.

Contrairement a la version d'origine, l'historique n'est **pas** garde dans le
checkpointer : il est tenu explicitement par l'appelant. Cela permet de
reconstruire le prompt systeme a chaque tour (memoire longue duree a jour),
d'elaguer proprement les vieux messages, et de rendre le tout testable avec un
modele factice.
"""

from __future__ import annotations

import json
import time
from time import monotonic as _monotonic
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.graph import END, START, MessagesState, StateGraph

from .text import clean_text, is_fatal, log, take_sentences

SYSTEM_ID = "system-prompt"
DEFAULT_KEEP = 40

MESSAGE_TYPES = {
    "SystemMessage": SystemMessage,
    "HumanMessage": HumanMessage,
    "AIMessage": AIMessage,
    "ToolMessage": ToolMessage,
}


# --------------------------------------------------------------------------- #
# Prompt systeme (base + memoire)
# --------------------------------------------------------------------------- #
def now_line(strings: dict, with_tools: bool = False, now=None) -> str:
    """Date et heure du jour : sans elles, le modele croit vivre a sa date de coupure
    (« le Nobel 2026 n'est pas encore decerne »)."""
    import datetime as _dt

    from .briefing import DAYS, MONTHS, say_time

    template = strings.get("now_line_tools" if with_tools else "now_line")
    if not template:
        return ""
    lang = "fr" if strings.get("whisper_lang") == "fr" else "en"
    now = now or _dt.datetime.now()
    date = (f"{DAYS[lang][now.weekday()]} {now.day} {MONTHS[lang][now.month - 1]} {now.year}"
            if lang == "fr" else
            f"{DAYS[lang][now.weekday()]}, {MONTHS[lang][now.month - 1]} {now.day}, {now.year}")
    return template.format(date=date, time=say_time(now, lang))


def build_system_prompt(base: str, memory=None, query: str | None = None,
                        strings: dict | None = None, with_tools: bool = False,
                        extra: str = "") -> str:
    """Assemble le prompt systeme du tour : consignes + memoire pertinente.

    `extra` : consigne du moment (par exemple les regles du quiz en cours).
    """
    strings = strings or {}
    parts = [base, now_line(strings, with_tools), extra]

    if with_tools and strings.get("tool_guidance"):
        parts.append(strings["tool_guidance"])
        if memory is not None and strings.get("memory_guidance"):
            parts.append(strings["memory_guidance"])

    if memory is not None:
        try:
            profile = memory.profile_block(strings)
        except Exception:
            profile = ""
        if profile:
            parts.append(profile)
        try:
            if query:
                recalled = memory.recall_block(query, strings)
                if recalled:
                    parts.append(recalled)
            else:
                episodes = memory.episodes_block(strings)
                if episodes:
                    parts.append(episodes)
        except Exception:
            pass

    return "\n\n".join(part for part in parts if part)


def trim_history(history: list[BaseMessage], keep: int = DEFAULT_KEEP) -> list[BaseMessage]:
    """Garde les `keep` derniers messages sans casser un couple outil/resultat."""
    if keep <= 0 or len(history) <= keep:
        return list(history)
    cut = len(history) - keep
    while cut < len(history) and not isinstance(history[cut], HumanMessage):
        cut += 1
    return list(history[cut:])


OLD_TOOL_CHARS = 400   # resultat d'outil d'un echange passe : un resume suffit


def compact_history(history: list[BaseMessage]) -> list[BaseMessage]:
    """Raccourcit les resultats d'outils des echanges passes.

    Une recherche web laisse jusqu'a 7 000 caracteres que le modele relirait a
    chaque tour : seul le dernier echange garde les siens en entier.
    """
    last_question = max((i for i, m in enumerate(history) if isinstance(m, HumanMessage)),
                        default=-1)
    compacted = []
    for index, message in enumerate(history):
        content = message.content if isinstance(message.content, str) else ""
        if (index < last_question and isinstance(message, ToolMessage)
                and len(content) > OLD_TOOL_CHARS):
            message = message.model_copy(update={"content": content[:OLD_TOOL_CHARS] + " […]"})
        compacted.append(message)
    return compacted


def make_turn_messages(system_prompt: str, history: list[BaseMessage], text: str,
                       keep: int = DEFAULT_KEEP) -> list[BaseMessage]:
    """Messages envoyes au graphe pour un tour : systeme + historique + question."""
    messages: list[BaseMessage] = [
        SystemMessage(content=system_prompt, id=SYSTEM_ID)
    ]
    messages.extend(compact_history(trim_history(history, keep)))
    messages.append(HumanMessage(content=text, id=str(uuid.uuid4())))
    return messages


# --------------------------------------------------------------------------- #
# Construction du graphe
# --------------------------------------------------------------------------- #
def build_graph(llm, tools: list | None = None, checkpointer=None):
    """Compile le graphe. `tools` vide -> simple appel au modele."""
    tools = list(tools or [])
    builder = StateGraph(MessagesState)

    if not tools:
        def call_model(state):
            return {"messages": [llm.invoke(state["messages"])]}

        builder.add_node("model", call_model)
        builder.add_edge(START, "model")
        builder.add_edge("model", END)
        return builder.compile(checkpointer=checkpointer)

    from langgraph.prebuilt import ToolNode, tools_condition

    bound = llm.bind_tools(tools)

    def call_model(state):
        return {"messages": [bound.invoke(state["messages"])]}

    builder.add_node("model", call_model)
    builder.add_node("tools", ToolNode(tools))
    builder.add_edge(START, "model")
    builder.add_conditional_edges(
        "model", tools_condition, {"tools": "tools", END: END}
    )
    builder.add_edge("tools", "model")
    return builder.compile(checkpointer=checkpointer)


# --------------------------------------------------------------------------- #
# Streaming d'un tour
# --------------------------------------------------------------------------- #
@dataclass
class TurnResult:
    ok: bool
    messages: list[BaseMessage] = field(default_factory=list)
    error: Exception | None = None
    tools_used: list[str] = field(default_factory=list)
    spoke: bool = False  # au moins une phrase prononcee (reponse non vide)

    @property
    def answer(self) -> str:
        for message in reversed(self.messages):
            if isinstance(message, AIMessage) and not message.tool_calls:
                return message_text(message)
        return ""

    @property
    def empty(self) -> bool:
        """Vrai quand le tour a reussi sans rien avoir a dire.

        C'est le cas des modeles de raisonnement gratuits qui remplissent leur
        champ `reasoning` en laissant `content` vide : sans ce drapeau, Jarvis
        resterait muet et l'utilisateur croirait a une panne.
        """
        return self.ok and not self.spoke


def message_text(message: BaseMessage) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # contenu structure (multimodal)
        chunks = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                chunks.append(item["text"])
            elif isinstance(item, str):
                chunks.append(item)
        return "".join(chunks)
    return ""


def _tool_names(chunk) -> list[str]:
    names = []
    for call in getattr(chunk, "tool_call_chunks", None) or []:
        name = call.get("name") if isinstance(call, dict) else getattr(call, "name", None)
        if name:
            names.append(str(name))
    return names


def _stream_with_deadline(graph, messages, deadline: float):
    """Parcourt `graph.stream` dans un fil ; leve TimeoutError si plus rien
    n'arrive avant `deadline` secondes (un modele gratuit peut se figer)."""
    import queue as _queue
    import threading as _threading

    inbox: _queue.Queue = _queue.Queue()
    done = object()

    def produce():
        try:
            for item in graph.stream({"messages": messages},
                                     stream_mode=["messages", "updates"]):
                inbox.put(item)
        except BaseException as exc:  # renvoye au consommateur
            inbox.put(exc)
        finally:
            inbox.put(done)

    _threading.Thread(target=produce, daemon=True).start()
    limit = _monotonic() + deadline
    while True:
        remaining = limit - _monotonic()
        if remaining <= 0:
            raise TimeoutError(f"pas de reponse en {deadline:.0f} s")
        try:
            item = inbox.get(timeout=remaining)
        except _queue.Empty:
            raise TimeoutError(f"pas de reponse en {deadline:.0f} s") from None
        if item is done:
            return
        if isinstance(item, BaseException):
            raise item
        yield item


TURN_DEADLINE = 30.0  # secondes max pour un essai avant de passer au suivant


def error_message(error, strings: dict) -> str:
    """Phrase a dire quand le modele n'a pas repondu (quota du jour ou panne)."""
    from .text import is_daily_quota, quota_reset

    if is_daily_quota(error) and strings.get("quota_error"):
        reset = quota_reset(error)
        if reset is None:
            now = time.time()
            reset = now - now % 86400 + 86400
        moment = time.localtime(reset)
        when = (f"{moment.tm_hour} h {moment.tm_min:02d}" if moment.tm_min
                else f"{moment.tm_hour} h")
        return strings["quota_error"].format(time=when)
    return strings["llm_error"]


def stream_reply(graph, messages: list[BaseMessage], on_sentence, retries: int = 3,
                 on_tool=None, on_retry=None, deadline: float | None = TURN_DEADLINE) -> TurnResult:
    """Stream la reponse et appelle `on_sentence()` au fil de l'eau.

    Les sorties d'outils ne sont jamais prononcees : seuls les jetons du noeud
    `model` sont transmis. `on_tool(name)` previent l'appelant qu'un outil part.
    """
    attempts = max(1, retries)
    collected: list[BaseMessage] = []
    tools_used: list[str] = []
    produced_any = False
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        buffer = ""
        produced = False
        collected = []
        tools_used = []
        try:
            stream = (_stream_with_deadline(graph, messages, deadline) if deadline
                      else graph.stream({"messages": messages},
                                        stream_mode=["messages", "updates"]))
            for mode, payload in stream:
                if mode == "messages":
                    chunk, metadata = payload
                    if (metadata or {}).get("langgraph_node") != "model":
                        continue
                    if not isinstance(chunk, AIMessageChunk):
                        continue
                    for name in _tool_names(chunk):
                        if name not in tools_used:
                            tools_used.append(name)
                            if on_tool is not None:
                                on_tool(name)
                    content = getattr(chunk, "content", None)
                    if not isinstance(content, str) or not content:
                        continue
                    buffer += content
                    sentences, buffer = take_sentences(buffer)
                    for sentence in sentences:
                        produced = True
                        on_sentence(sentence)
                    if len(buffer) > 300:  # modele sans ponctuation
                        produced = True
                        on_sentence(buffer)
                        buffer = ""
                else:
                    for update in (payload or {}).values():
                        for message in (update or {}).get("messages") or []:
                            collected.append(message)

            tail = clean_text(buffer)
            if tail:
                produced = True
                on_sentence(tail)
            return TurnResult(True, collected, None, tools_used, produced)
        except Exception as exc:
            last_error = exc
            produced_any = produced_any or produced
            if produced_any:
                break  # une partie a deja ete prononcee : inutile de relancer
            if tools_used:
                # Un outil a pu agir (minuteur, application, rappel...) : le
                # rejouer creerait un doublon. Mieux vaut annoncer l'echec.
                break
            if is_fatal(exc):
                break  # erreur fatale (credit epuise, cle invalide...)
            if attempt < attempts:
                delay = 1.5 * (2 ** (attempt - 1))
                log(f"[llm] erreur ({exc}) - tentative {attempt}/{attempts}"
                    f" dans {delay:.1f}s")
                if on_retry is not None:
                    on_retry(attempt, exc)
                time.sleep(delay)

    log(f"[llm] echec: {last_error}")
    return TurnResult(False, collected, last_error, tools_used)


def run_sync(graph, messages: list[BaseMessage]) -> TurnResult:
    """Version non streamee (tests, resumes) : renvoie les nouveaux messages."""
    try:
        state = graph.invoke({"messages": messages})
    except Exception as exc:
        log(f"[llm] echec: {exc}")
        return TurnResult(False, [], exc)
    produced = [
        message for message in state.get("messages", [])
        if not any(message is original for original in messages)
    ]
    spoke = any(
        isinstance(message, AIMessage) and bool(clean_text(message_text(message)))
        for message in produced
    )
    return TurnResult(True, produced, None, [], spoke)


# --------------------------------------------------------------------------- #
# Historique JSON
# --------------------------------------------------------------------------- #
def serialise(messages: list[BaseMessage]) -> list[dict]:
    data = []
    for message in messages:
        if isinstance(message, SystemMessage):
            continue  # reconstruit a chaque tour
        item = {"type": type(message).__name__, "content": message_text(message)}
        if isinstance(message, AIMessage) and message.tool_calls:
            item["tool_calls"] = [
                {"name": call.get("name"), "args": call.get("args"),
                 "id": call.get("id")}
                for call in message.tool_calls
            ]
        if isinstance(message, ToolMessage):
            item["tool_call_id"] = message.tool_call_id
        data.append(item)
    return data


def save_history(messages: list[BaseMessage], path: Path | str) -> int:
    """Ecrit l'historique en JSON. Retourne le nombre de messages sauvegardes."""
    path = Path(path)
    try:
        data = serialise(messages)
        if not data:
            return 0
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        log(f"[history] {len(data)} messages sauvegardes dans {path.name}")
        return len(data)
    except Exception as exc:
        log(f"[history] sauvegarde impossible: {exc}")
        return 0


def _restore(item: dict, open_calls: set[str]) -> BaseMessage | None:
    """Recree un message ; None s'il ne peut pas etre renvoye tel quel au modele.

    Un appel d'outil n'est garde que si chaque appel a son identifiant, et un
    resultat d'outil que s'il repond a un appel garde : l'API refuse un
    `ToolMessage` orphelin (anciens fichiers, sans identifiants).
    """
    message_type = MESSAGE_TYPES.get(str(item.get("type")))
    content = item.get("content")
    if message_type is None or not isinstance(content, str):
        return None
    if message_type is ToolMessage:
        call_id = item.get("tool_call_id")
        if not call_id or call_id not in open_calls:
            return None
        open_calls.discard(call_id)
        return ToolMessage(content=content, tool_call_id=call_id)
    calls = item.get("tool_calls")
    if message_type is AIMessage and calls:
        if not isinstance(calls, list) or not all(
            isinstance(call, dict) and call.get("id") for call in calls
        ):
            return None
        open_calls.update(str(call["id"]) for call in calls)
        return AIMessage(content=content, tool_calls=[
            {"name": call.get("name"), "args": call.get("args") or {},
             "id": str(call["id"])}
            for call in calls
        ])
    return message_type(content=content)


def load_history(path: Path | str) -> list[BaseMessage]:
    """Relit l'historique JSON. Retourne [] si absent ou illisible."""
    path = Path(path)
    try:
        if not path.exists():
            return []
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            return []
        messages: list[BaseMessage] = []
        open_calls: set[str] = set()
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                message = _restore(item, open_calls)
            except Exception:  # un message abime ne doit pas tout perdre
                message = None
            if message is not None:
                messages.append(message)
        if messages:
            log(f"[history] {len(messages)} messages recharges depuis {path.name}")
        return messages
    except Exception as exc:
        log(f"[history] chargement impossible: {exc}")
        return []


def transcript(messages: list[BaseMessage], limit: int = 20) -> str:
    """Rend l'historique sous forme de texte (pour le resume automatique)."""
    lines = []
    for message in messages[-limit:]:
        if isinstance(message, HumanMessage):
            speaker = "User"
        elif isinstance(message, AIMessage):
            speaker = "Jarvis"
        else:
            continue
        text = clean_text(message_text(message))
        if text:
            lines.append(f"{speaker}: {text}")
    return "\n".join(lines)


__all__ = [
    "SYSTEM_ID",
    "DEFAULT_KEEP",
    "MESSAGE_TYPES",
    "TurnResult",
    "build_system_prompt",
    "trim_history",
    "make_turn_messages",
    "build_graph",
    "stream_reply",
    "run_sync",
    "message_text",
    "serialise",
    "save_history",
    "load_history",
    "transcript",
]
