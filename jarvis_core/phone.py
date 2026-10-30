"""Parler a Jarvis depuis le telephone, sur le Wi-Fi de la maison (`--phone`).

Desactive par defaut. Une fois active :

  * le serveur n'accepte que les adresses du reseau prive (jamais Internet) ;
  * chaque demande doit porter une cle secrete de 32 caracteres, conservee dans
    ``.jarvis_phone.json`` et transmise par le QR code de la page d'appairage ;
  * la cle est dans le « # » de l'adresse : le navigateur ne l'envoie pas dans l'URL ;
  * « /pair », qui montre le QR code, ne repond qu'au PC lui-meme.

Limite : la liaison est en HTTP. Sur un Wi-Fi partage, quelqu'un qui ecoute le
reseau pourrait lire les echanges et la cle : a reserver a un reseau de confiance.
Pour la meme raison le micro du navigateur est bloque : on dicte avec le micro
du clavier du telephone.
"""

from __future__ import annotations

import copy
import hmac
import ipaddress
import json
import secrets
import socket
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .text import log

DEFAULT_PORT = 8766
ROOT = Path(__file__).resolve().parent.parent
KEY_FILE = ROOT / ".jarvis_phone.json"
HISTORY_FILE = ROOT / ".jarvis_history_phone.json"
MAX_BODY = 8000
MAX_HISTORY = 40


def load_key(path: Path = KEY_FILE) -> str:
    try:
        key = json.loads(path.read_text(encoding="utf-8")).get("key", "")
        if len(key) >= 24:
            return key
    except (OSError, ValueError, AttributeError):
        pass
    key = secrets.token_urlsafe(24)
    path.write_text(json.dumps({"key": key}), encoding="utf-8")
    return key


def local_address() -> str:
    """Adresse du PC sur le reseau local (aucun paquet n'est envoye)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        try:
            probe.connect(("192.168.0.1", 9))
            return probe.getsockname()[0]
        except OSError:
            return socket.gethostbyname(socket.gethostname())


def is_local_client(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback


def qr_svg(url: str) -> str:
    """QR code en SVG ; vide si le paquet `segno` manque (le lien reste affiche)."""
    try:
        import segno

        return segno.make(url, error="m").svg_inline(scale=8, border=3, dark="#000", light="#fff")
    except Exception:
        return ""


PAGE = """<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Jarvis</title>
<style>:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;height:100dvh;display:flex;flex-direction:column;
background:#0b0f17;color:#e8edf5;font:16px/1.45 system-ui,sans-serif}#log{flex:1;overflow:auto;padding:16px}
.m{max-width:85%;margin:0 0 10px;padding:10px 13px;border-radius:14px;white-space:pre-wrap;overflow-wrap:anywhere}
.u{margin-left:auto;background:#1f6feb}.j{background:#1a2230}.e{background:#4a1d1d}
form{display:flex;gap:8px;padding:10px 12px;background:#111723;padding-bottom:max(10px,env(safe-area-inset-bottom))}
input{flex:1;min-width:0;font:inherit;color:inherit;background:#0b0f17;border:1px solid #2c3647;border-radius:12px;padding:12px}
button{font:inherit;color:#fff;background:#1f6feb;border:0;border-radius:12px;padding:0 18px}</style></head><body>
<div id="log"></div><form id="f"><input id="t" autocomplete="off" placeholder="Écris ou dicte avec le micro du clavier"><button>Envoyer</button></form>
<script>
const log=document.getElementById("log"),box=document.getElementById("t");
let key=location.hash.startsWith("#k=")?location.hash.slice(3):"";
try{if(key)localStorage.setItem("k",key);else key=localStorage.getItem("k")||""}catch(e){}
history.replaceState(null,"",location.pathname);
function add(text,cls){const d=document.createElement("div");d.className="m "+cls;d.textContent=text;log.append(d);log.scrollTop=log.scrollHeight;return d}
if(!key)add("Clé manquante : scanne le QR code affiché par le PC.","e");
document.getElementById("f").onsubmit=async e=>{e.preventDefault();const text=box.value.trim();if(!text)return;box.value="";add(text,"u");
const wait=add("…","j");try{const r=await fetch("/api/ask",{method:"POST",headers:{"Content-Type":"application/json","X-Jarvis-Key":key},body:JSON.stringify({text})});
const data=await r.json();if(!r.ok)throw new Error(r.status===403?"Clé refusée : scanne à nouveau le QR code.":data.error||"Erreur");wait.textContent=data.reply||"(pas de réponse)"}
catch(err){wait.className="m e";wait.textContent=err.message}log.scrollTop=log.scrollHeight};
</script></body></html>"""

PAIR_PAGE = """<!doctype html><html lang="fr"><meta charset="utf-8"><title>Jarvis sur le téléphone</title>
<body style="font:16px system-ui;text-align:center;padding:32px;background:#fff;color:#111"><h2 style="font-weight:500">Scanne avec ton téléphone</h2>
{qr}<p>Le téléphone doit être sur le même Wi-Fi.</p><p style="overflow-wrap:anywhere;color:#555">{url}</p>
<p style="color:#a00">Ce code donne accès à Jarvis : ne le partage pas.</p></body></html>"""


class PhoneBridge:
    """Une conversation a part : elle ne parle pas sur le PC et n'ecrase pas l'historique."""

    def __init__(self, args, strings, chain, memory=None, turn=None):
        if turn is None:
            from .gui import _make_turn

            phone_args = copy.copy(args)
            phone_args.history_path = HISTORY_FILE
            turn = _make_turn(phone_args, strings, chain, memory)
        self.turn = turn
        self.history: list = []
        self._lock = threading.Lock()

    def ask(self, text: str) -> str:
        with self._lock:
            parts: list[str] = []
            self.turn(text, self.history, parts.append, lambda _name: None, parts.append)
            del self.history[:-MAX_HISTORY]
            return " ".join(part for part in parts if part)


def make_handler(ask, key: str, port: int):
    class Handler(BaseHTTPRequestHandler):
        server_version = "Jarvis"
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args) -> None:
            pass

        def _send(self, status, body: bytes, kind: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status, data) -> None:
            self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8")

        def _html(self, page: str) -> None:
            self._send(HTTPStatus.OK, page.encode("utf-8"), "text/html; charset=utf-8")

        def _allowed(self) -> bool:
            if is_local_client(self.client_address[0]):
                return True
            self._json(HTTPStatus.FORBIDDEN, {"error": "reseau"})
            return False

        def do_GET(self) -> None:
            if not self._allowed():
                return
            path = self.path.split("?", 1)[0]
            if path == "/":
                self._html(PAGE)
            elif path == "/pair" and self.client_address[0] == "127.0.0.1" and \
                    (self.headers.get("Host") or "").lower() in (f"127.0.0.1:{port}", f"localhost:{port}"):
                url = f"http://{local_address()}:{port}/#k={key}"
                self._html(PAIR_PAGE.format(qr=qr_svg(url), url=url))
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": "introuvable"})

        def do_POST(self) -> None:
            if not self._allowed():
                return
            if self.path != "/api/ask":
                self._json(HTTPStatus.NOT_FOUND, {"error": "introuvable"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            if not 0 < length <= MAX_BODY:
                self.close_connection = True
                self._json(HTTPStatus.BAD_REQUEST, {"error": "demande invalide"})
                return
            body = self.rfile.read(length)
            if not hmac.compare_digest(self.headers.get("X-Jarvis-Key") or "", key):
                self._json(HTTPStatus.FORBIDDEN, {"error": "cle"})
                return
            try:
                text = str(json.loads(body.decode("utf-8")).get("text") or "").strip()
            except (ValueError, UnicodeDecodeError, AttributeError):
                text = ""
            if not text:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "message vide"})
                return
            try:
                self._json(HTTPStatus.OK, {"reply": ask(text)})
            except Exception as exc:
                log(f"[telephone] {exc}")
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "Jarvis a eu un problème."})

    return Handler


def start(ask, port: int = DEFAULT_PORT, key: str | None = None, host: str = "0.0.0.0"):
    """Demarre le serveur ; renvoie (serveur, port reel)."""
    key = key or load_key()
    last: OSError | None = None
    for candidate in range(port, port + 10):
        try:
            server = ThreadingHTTPServer((host, candidate), make_handler(ask, key, candidate))
        except OSError as exc:
            last = exc
            continue
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, name="jarvis-telephone", daemon=True).start()
        return server, candidate
    raise OSError(f"aucun port libre a partir de {port}") from last


_ENABLE = None          # fabrique le pont (branchee au lancement de Jarvis)
_RUNNING: dict = {}


def configure(make_bridge, port: int = DEFAULT_PORT) -> None:
    global _ENABLE
    _ENABLE = (make_bridge, port)


def ensure_started() -> int | None:
    """Demarre le serveur une seule fois ; renvoie son port, None si impossible."""
    if "port" in _RUNNING:
        return _RUNNING["port"]
    if _ENABLE is None:
        return None
    make_bridge, port = _ENABLE
    try:
        server, actual = start(make_bridge().ask, port)
    except Exception as exc:
        log(f"[telephone] {exc}")
        return None
    _RUNNING.update(server=server, port=actual)
    log(f"[telephone] acces actif sur http://{local_address()}:{actual}/")
    return actual


def open_pairing() -> bool:
    """Demarre si besoin et affiche le QR code dans le navigateur du PC."""
    import webbrowser

    port = ensure_started()
    if port is None:
        return False
    webbrowser.open(f"http://127.0.0.1:{port}/pair")
    return True


__all__ = ["PhoneBridge", "start", "configure", "ensure_started", "open_pairing", "load_key", "local_address", "is_local_client", "make_handler"]
