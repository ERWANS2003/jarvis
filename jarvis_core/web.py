"""Horizon 6 - interface web (navigateur), bibliotheque standard uniquement.

Alternative moderne a la fenetre Tkinter : Jarvis lance un petit serveur HTTP
local et ouvre la page dans le navigateur par defaut.

Principes de conception :

  * **Local seulement.** Le serveur n'ecoute que sur 127.0.0.1 ; l'en-tete
    ``Host`` est verifie (protection contre le *DNS rebinding*) et chaque appel
    de l'API exige un jeton aleatoire, injecte dans la page servie : un autre
    site ouvert dans le navigateur ne peut donc pas piloter Jarvis.
  * **Temps reel sans dependance.** La reponse du modele arrive phrase par
    phrase via *Server-Sent Events* (``/api/events``) ; les actions passent par
    de simples ``POST`` JSON.
  * **Meme cerveau que la fenetre.** Un tour est joue par la meme fonction que
    l'interface Tkinter (`gui._make_turn`) : prompt, outils, memoire, repli.
"""

from __future__ import annotations

import json
import queue
import secrets
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import graph as graphs
from .gui import _default_history, _make_turn
from .tts import SpeechPipe
from . import hearing as hearing_mod
from . import quiz as quiz_mod
from .text import is_exit_phrase, log

STATIC_DIR = Path(__file__).resolve().parent / "web"
DEFAULT_PORT = 8765
LOCAL_HOSTS = {"127.0.0.1", "localhost"}
PING_EVERY = 15.0  # secondes : garde la connexion SSE ouverte
FOLLOW_UP_SECONDS = 6.0  # ecoute apres une reponse, sans mot d'activation


class EventBus:
    """Diffuse les evenements du serveur a toutes les pages ouvertes."""

    def __init__(self):
        self._lock = threading.Lock()
        self._subscribers: list[queue.Queue] = []

    def subscribe(self) -> queue.Queue:
        inbox: queue.Queue = queue.Queue()
        with self._lock:
            self._subscribers.append(inbox)
        return inbox

    def unsubscribe(self, inbox: queue.Queue) -> None:
        with self._lock:
            if inbox in self._subscribers:
                self._subscribers.remove(inbox)

    def publish(self, kind: str, **data) -> None:
        event = {"type": kind, **data}
        with self._lock:
            subscribers = list(self._subscribers)
        for inbox in subscribers:
            inbox.put(event)


class JarvisWeb:
    """Etat de la session web : conversation, voix, micro et memoire."""

    def __init__(self, args, strings, listener, speech, chain, history,
                 memory=None, greet: bool = True):
        self.args = args
        self.s = strings
        self.listener = listener
        self.speech = speech
        self.chain = chain
        self.history = list(history)
        self.memory = memory
        self.turn = _make_turn(args, strings, chain, memory)
        self.turn.on_detail = self._detail   # « explique en detail » : version a l'ecran
        self.turn.speech = speech            # « parle plus lentement »
        transcriber = getattr(listener, "transcriber", None)
        if transcriber is not None:          # noms des proches, ville... des le debut
            transcriber.personal = hearing_mod.personal_vocabulary(memory)
        self.bus = EventBus()
        self.token = secrets.token_urlsafe(24)
        self.muted = False
        self.state = "ready"
        self.closed = threading.Event()
        self._busy = threading.Lock()
        # Ce que la page affiche : [{"kind": "user"|"jarvis"|"system", "text"}]
        self.transcript: list[dict] = self._transcript_from(self.history)
        if greet:
            self.transcript.append({"kind": "jarvis", "text": strings["greeting"]})
            self._speak_async(strings["greeting"])

    # -- etat --------------------------------------------------------------- #
    @staticmethod
    def _transcript_from(history) -> list[dict]:
        out = []
        for message in history:
            kind = getattr(message, "type", "")
            text = graphs.message_text(message).strip()
            if text and kind == "human":
                out.append({"kind": "user", "text": text})
            elif text and kind == "ai":
                out.append({"kind": "jarvis", "text": text})
        return out

    def info(self) -> dict:
        from . import __version__

        strings = {key: value for key, value in self.s.items()
                   if key.startswith(("gui_", "web_")) or key in (
                       "greeting", "llm_error", "stt_error", "empty_reply")}
        return {
            "version": __version__,
            "lang": self.args.lang,
            "model": self.chain.label(),
            "tools": len(getattr(self.chain, "tools", None) or []),
            "memory": self.memory is not None,
            "microphone": self.listener is not None,
            "muted": self.muted,
            "state": self.state,
            "busy": self._busy.locked(),
            "transcript": self.transcript,
            "strings": strings,
        }

    def _set_state(self, state: str) -> None:
        self.state = state
        self.bus.publish("state", state=state)

    def _status(self, text: str) -> None:
        """Message pendant un tour. « Un instant » (outil en cours) est seulement
        affiche : le dire bloquerait la reponse du modele pendant ~1 s."""
        if text and text == self.s.get("tool_running"):
            self.transcript.append({"kind": "system", "text": text})
            self.bus.publish("system", text=text)
            return
        self._system(text)

    def _system(self, text: str) -> None:
        """Message de service (erreur, « un instant »...) : affiche ET dit."""
        if text:
            self.transcript.append({"kind": "system", "text": text})
            self.bus.publish("system", text=text)
            if not self.muted:
                try:
                    self.speech.say(text)
                except Exception as exc:
                    log(f"[tts] {exc}")

    # -- voix --------------------------------------------------------------- #
    def _speak_async(self, text: str) -> None:
        if self.muted or not text:
            return

        def run() -> None:
            try:
                self.speech.begin()
                self.speech.say(text)
            except Exception as exc:
                log(f"[tts] {exc}")

        threading.Thread(target=run, daemon=True).start()

    def set_muted(self, muted: bool) -> None:
        self.muted = bool(muted)
        if self.muted:
            self.stop()

    def stop(self) -> None:
        try:
            self.speech.cancel()
        except Exception:
            pass

    # -- tours -------------------------------------------------------------- #
    def send(self, text: str) -> bool:
        """Lance un tour en arriere-plan. Faux si un tour est deja en cours."""
        text = " ".join((text or "").split())
        if not text or not self._busy.acquire(blocking=False):
            return False
        threading.Thread(target=self._run_turn, args=(text,), daemon=True).start()
        return True

    def listen(self, follow_up: bool = False) -> bool:
        """Ecoute le micro puis joue le tour entendu. Faux si indisponible.

        `follow_up` : relance automatique apres une reponse. L'ecoute est alors
        courte (FOLLOW_UP_SECONDS) et un silence termine la conversation sans
        rien dire, au lieu de « je n'ai rien entendu ».
        """
        if self.listener is None or not self._busy.acquire(blocking=False):
            return False
        threading.Thread(target=self._run_listen, args=(follow_up,),
                         daemon=True).start()
        return True

    def announce(self, text: str) -> None:
        """Jarvis prend la parole de lui-meme (briefing, rappel...)."""
        if text:
            self.transcript.append({"kind": "jarvis", "text": text})
            self._speak_async(text)

    def answer_audio(self, pcm: bytes, sample_rate: int = 16000) -> bool:
        """Repond a une question deja enregistree (« Jarvis, quelle heure... »)."""
        if self.listener is None or not self._busy.acquire(blocking=False):
            return False
        threading.Thread(target=self._run_audio, args=(pcm, sample_rate),
                         daemon=True).start()
        return True

    def _run_audio(self, pcm: bytes, sample_rate: int) -> None:
        self._set_state("thinking")
        heard, error = None, None
        try:
            import speech_recognition as sr

            audio = sr.AudioData(pcm, sample_rate, 2)
            heard, error = self.listener.transcriber.transcribe(audio)
            if heard and hasattr(self.listener, "continue_heard"):
                self._set_state("listening")
                heard = self.listener.continue_heard(heard)   # « Jarvis, ouvre le... » : la suite
                self._set_state("thinking")
        except Exception as exc:
            log(f"[web] transcription: {exc}")
            error = "unintelligible"
        self._remember_hearing()
        self._answer_heard(heard, error)

    def _run_listen(self, follow_up: bool = False) -> None:
        self._set_state("listening")
        heard, error = None, None
        try:
            if follow_up:
                try:
                    wait = (quiz_mod.FOLLOW_UP_SECONDS if quiz_mod.active_quiz(self.args)
                            else FOLLOW_UP_SECONDS)  # temps de reflechir pendant un quiz
                    heard, error = self.listener.listen(timeout=wait)
                except TypeError:  # ecouteur sans delai (doublure, ancien code)
                    heard, error = self.listener.listen()
            else:
                heard, error = self.listener.listen()
        except Exception as exc:
            log(f"[web] micro: {exc}")
            error = f"mic:{exc}"
        self._remember_hearing()
        self._answer_heard(heard, error, follow_up)

    def _remember_hearing(self) -> None:
        """Hypotheses et confiance de la derniere transcription, pour le tour suivant."""
        transcriber = getattr(self.listener, "transcriber", None)
        self._heard = getattr(transcriber, "last_heard", None)

    def _answer_heard(self, heard, error, follow_up: bool = False) -> None:
        """Joue le tour entendu, ou dit pourquoi rien n'a ete compris."""
        if heard:
            self._run_turn(heard, locked=True)
            return
        if follow_up and not (error and error.startswith(("network:", "mic:"))):
            # Fin naturelle de la conversation : on se tait.
            self._set_state("ready")
            self.bus.publish("finished", heard=False)
            self._busy.release()
            return
        # Toujours une reponse a voix haute, meme quand rien n'a ete compris.
        if error and error.startswith("network:"):
            message = self.s["stt_error"]
        elif error and error.startswith("mic:"):
            message = self.s["mic_error"]
        else:
            message = self.s["not_heard"]
        if not self.muted:
            self.speech.begin()
        self._system(message)
        self._set_state("ready")
        self.bus.publish("finished", heard=False)
        self._busy.release()

    def _run_turn(self, text: str, locked: bool = True) -> None:
        heard, self._heard = getattr(self, "_heard", None), None
        if heard is not None and text.strip() not in heard.text:
            heard = None                      # texte tape ou modifie : plus une dictee
        if hasattr(self.turn, "__dict__"):
            self.turn.heard = heard           # message dicte : comprendre l'intention
        try:
            self.transcript.append({"kind": "user", "text": text})
            self.bus.publish("user", text=text)
            self._set_state("thinking")
            reply: list[str] = []
            pipe = None if self.muted else SpeechPipe(self.speech)
            started = time.monotonic()

            def on_sentence(chunk: str) -> None:
                if not reply:
                    self._set_state("speaking")
                    # Mesure reelle a chaque echange (diagnostic de la vitesse).
                    log(f"[vitesse] premiere phrase en {time.monotonic() - started:.2f} s")
                reply.append(chunk)
                self.bus.publish("reply", text=chunk)
                if pipe is not None and not self.muted:
                    pipe.push(chunk)      # dite des que possible, la suivante preparee

            def on_tool(name: str) -> None:
                self.bus.publish("tool", name=name)

            if not self.muted:
                self.speech.begin()
            try:
                self.turn(text, self.history, on_sentence=on_sentence,
                          on_tool=on_tool, on_status=self._status)
            finally:
                if pipe is not None:
                    pipe.close()          # la reponse est entierement dite
            if reply:
                self.transcript.append({"kind": "jarvis", "text": " ".join(reply)})
                transcriber = getattr(self.listener, "transcriber", None)
                if transcriber is not None:      # la suite de la conversation oriente Whisper
                    transcriber.context = " ".join(reply)[-300:]
                    transcriber.personal = hearing_mod.personal_vocabulary(self.memory)
        except Exception as exc:  # un tour ne doit jamais tuer le serveur
            log(f"[web] {exc}")
            self._system(self.s["llm_error"])
        finally:
            self._set_state("ready")
            self.bus.publish("finished")
            if locked:
                self._busy.release()
        if is_exit_phrase(text, self.s["exit_phrases"]):
            self.quit(say_goodbye=True)

    def _detail(self, markdown: str) -> None:
        """Version complete d'une reponse detaillee (affichee, pas lue)."""
        self.transcript.append({"kind": "detail", "text": markdown})
        self.bus.publish("detail", text=markdown)

    def clear(self) -> bool:
        """Nouvelle conversation (refuse pendant un tour)."""
        if not self._busy.acquire(blocking=False):
            return False
        try:
            self.history.clear()
            self.transcript.clear()
            graphs.save_history([], self.args.history_path or _default_history())
        finally:
            self._busy.release()
        self.bus.publish("cleared")
        return True

    def quit(self, say_goodbye: bool = False) -> None:
        if say_goodbye and not self.muted:
            try:
                self.speech.begin()
                self.speech.say(self.s["goodbye"])
            except Exception:
                pass
        self.bus.publish("closed")
        self.closed.set()

    # -- memoire ------------------------------------------------------------ #
    def memories(self) -> list[dict]:
        if self.memory is None:
            return []
        return [m.as_dict() for m in self.memory.all(limit=200)]

    def forget(self, mem_id: int) -> bool:
        if self.memory is None:
            return False
        return self.memory.forget(int(mem_id))


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
def make_handler(app: JarvisWeb, port: int):
    allowed_hosts = {f"{host}:{port}" for host in LOCAL_HOSTS}

    class Handler(BaseHTTPRequestHandler):
        server_version = "Jarvis"
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args) -> None:  # pas de bruit dans la console
            pass

        # -- utilitaires ---------------------------------------------------- #
        def _host_ok(self) -> bool:
            return (self.headers.get("Host") or "").lower() in allowed_hosts

        def _token_ok(self) -> bool:
            sent = self.headers.get("X-Jarvis-Token") or ""
            return secrets.compare_digest(sent, app.token)

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, data) -> None:
            self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8")

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > 64_000:
                return {}
            try:
                data = json.loads(self.rfile.read(length).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return {}
            return data if isinstance(data, dict) else {}

        def _guard(self, api: bool) -> bool:
            if not self._host_ok():
                self._json(HTTPStatus.FORBIDDEN, {"error": "host"})
                return False
            if api and not self._token_ok():
                self._json(HTTPStatus.FORBIDDEN, {"error": "token"})
                return False
            return True

        # -- routes --------------------------------------------------------- #
        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                if not self._guard(api=False):
                    return
                page = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
                page = page.replace("__JARVIS_TOKEN__", app.token)
                page = page.replace("__JARVIS_LANG__", app.args.lang)
                self._send(HTTPStatus.OK, page.encode("utf-8"),
                           "text/html; charset=utf-8")
                return
            if path == "/api/events":
                # EventSource ne peut pas envoyer d'en-tete : jeton en parametre.
                query = self.path.split("?", 1)[1] if "?" in self.path else ""
                params = dict(item.split("=", 1) for item in query.split("&")
                              if "=" in item)
                if not self._host_ok() or not secrets.compare_digest(
                        params.get("token", ""), app.token):
                    self._json(HTTPStatus.FORBIDDEN, {"error": "token"})
                    return
                self._stream_events()
                return
            if not self._guard(api=True):
                return
            if path == "/api/info":
                self._json(HTTPStatus.OK, app.info())
            elif path == "/api/memory":
                self._json(HTTPStatus.OK, {"memories": app.memories()})
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def do_POST(self) -> None:
            if not self._guard(api=True):
                return
            path = self.path.split("?", 1)[0]
            body = self._body()
            if path == "/api/send":
                ok = app.send(str(body.get("text") or ""))
                self._json(HTTPStatus.OK if ok else HTTPStatus.CONFLICT, {"ok": ok})
            elif path == "/api/listen":
                ok = app.listen()
                self._json(HTTPStatus.OK if ok else HTTPStatus.CONFLICT, {"ok": ok})
            elif path == "/api/stop":
                app.stop()
                self._json(HTTPStatus.OK, {"ok": True})
            elif path == "/api/mute":
                app.set_muted(bool(body.get("muted")))
                self._json(HTTPStatus.OK, {"ok": True, "muted": app.muted})
            elif path == "/api/clear":
                ok = app.clear()
                self._json(HTTPStatus.OK if ok else HTTPStatus.CONFLICT, {"ok": ok})
            elif path == "/api/forget":
                try:
                    ok = app.forget(int(body.get("id")))
                except (TypeError, ValueError):
                    ok = False
                self._json(HTTPStatus.OK, {"ok": ok})
            elif path == "/api/quit":
                self._json(HTTPStatus.OK, {"ok": True})
                app.quit()
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def _stream_events(self) -> None:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            inbox = app.bus.subscribe()
            try:
                self.wfile.write(b": ok\n\n")
                self.wfile.flush()
                # On vide la file jusqu'a l'evenement « closed » : s'arreter des
                # que `app.closed` est leve pourrait le perdre en route.
                while True:
                    try:
                        event = inbox.get(timeout=PING_EVERY)
                    except queue.Empty:
                        if app.closed.is_set():
                            break
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                        continue
                    data = json.dumps(event, ensure_ascii=False)
                    self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    if event.get("type") == "closed":
                        break
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
            finally:
                app.bus.unsubscribe(inbox)
                self.close_connection = True

    return Handler


def start_server(app: JarvisWeb, port: int = DEFAULT_PORT):
    """Demarre le serveur ; essaie les ports suivants si `port` est pris."""
    last_error: OSError | None = None
    for candidate in range(port, port + 20):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", candidate),
                                         make_handler(app, candidate))
        except OSError as exc:
            last_error = exc
            continue
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server, f"http://127.0.0.1:{candidate}/"
    raise OSError(f"aucun port libre a partir de {port}") from last_error


def run(args, strings, listener, speech, chain, history, memory=None, greet=True,
        port: int | None = None, open_browser: bool = True) -> int:
    """Sert l'interface web jusqu'a « Quitter » ou Ctrl+C. Retourne 0."""
    app = JarvisWeb(args, strings, listener, speech, chain, history, memory, greet)
    server, url = start_server(app, port or DEFAULT_PORT)
    print(strings["web_open"].format(url=url), flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        while not app.closed.wait(0.5):
            pass
        time.sleep(0.3)  # laisse le temps au dernier evenement de partir
    finally:
        server.shutdown()
        server.server_close()
    return 0


__all__ = ["DEFAULT_PORT", "EventBus", "JarvisWeb", "make_handler",
           "start_server", "run"]
