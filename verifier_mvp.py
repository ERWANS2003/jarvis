"""Verification avant la presentation : tout est-il pret, sans appeler le modele ?

Usage :  .venv\\Scripts\\python.exe verifier_mvp.py
Code de sortie 1 si Jarvis ne pourrait pas repondre ; un simple avertissement laisse passer.
"""

from __future__ import annotations

import importlib.util
import os
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REQUIRED = {"langgraph": "orchestration", "langchain_openai": "modele",
            "speech_recognition": "ecoute", "pyaudio": "micro", "pyttsx3": "voix de secours",
            "PIL": "dessin de l'orbe", "numpy": "dessin de l'orbe", "yaml": "configuration"}
OPTIONAL = {"vosk": "mot d'activation « Jarvis »", "piper": "voix neuronale",
            "moderngl": "orbe 3D"}
KEYS = ("GROQ_API_KEY", "OPENROUTER_API_KEY", "OPENAI_API_KEY", "JARVIS_API_KEY")
HOSTS = ("api.groq.com", "openrouter.ai")


def has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def has_key(env) -> bool:
    """Une vraie cle est renseignee (sa valeur n'est jamais affichee)."""
    for name in KEYS:
        value = (env.get(name) or "").strip()
        if value and not value.startswith("your_") and value != "sk-no_key":
            return True
    return bool((env.get("JARVIS_LOCAL_MODEL") or "").strip())


def has_network(hosts=HOSTS, connect=socket.create_connection) -> bool:
    for host in hosts:
        try:
            connect((host, 443), timeout=3).close()
            return True
        except OSError:
            continue
    return False


def microphones() -> int:
    import pyaudio

    audio = pyaudio.PyAudio()
    try:
        return sum(1 for index in range(audio.get_device_count())
                   if audio.get_device_info_by_index(index).get("maxInputChannels", 0) > 0)
    finally:
        audio.terminate()


def checks(env=None, root: Path = ROOT):
    """Liste de (bloquant, reussi, libelle)."""
    env = os.environ if env is None else env
    found = [(True, sys.version_info >= (3, 10), f"Python {sys.version_info[0]}.{sys.version_info[1]}")]
    found += [(True, has_module(name), f"{name} : {role}") for name, role in REQUIRED.items()]
    found += [(False, has_module(name), f"{name} : {role}") for name, role in OPTIONAL.items()]
    found.append((True, has_key(env), "cle API dans .env (ou modele local)"))
    found.append((False, has_network(), "acces Internet vers le modele"))
    found.append((False, (root / "voices" / "vosk").is_dir(), "modele du mot d'activation (voices/vosk)"))
    found.append((False, any((root / "voices").glob("*.onnx")), "voix neuronale (voices/*.onnx)"))
    try:
        count = microphones()
    except Exception:
        count = 0
    found.append((False, count > 0, "micro detecte (sinon : clic droit sur l'orbe, Ecrire)"))
    return found


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    results = checks()
    print("\nVerification de Jarvis MVP\n")
    for blocking, passed, label in results:
        mark = "ok  " if passed else ("BLOQUANT" if blocking else "attention")
        print(f"  [{mark}] {label}")
    stop = any(blocking and not passed for blocking, passed, _ in results)
    print("\nA corriger avant de lancer Jarvis.\n" if stop else "\nPret.\n")
    return 1 if stop else 0


if __name__ == "__main__":
    sys.exit(main())
