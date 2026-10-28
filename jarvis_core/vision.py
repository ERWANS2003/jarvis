"""Horizon 3 - vision : « Jarvis, qu'est-ce qu'il y a sur mon ecran ? ».

Sur demande explicite seulement, Jarvis capture l'ecran, le reduit (JPEG,
1600 px de cote au plus) et le confie a un modele qui comprend les images
(par defaut `nvidia/nemotron-3.5-super-vl:free`, gratuit sur OpenRouter). La
description revient au modele de conversation, qui repond a voix haute.

Confidentialite : l'image part chez le fournisseur du modele. L'outil ne doit
donc servir que lorsque l'utilisateur demande clairement de regarder son ecran
(c'est ecrit dans sa description), et `--no-vision` le retire entierement.
"""

from __future__ import annotations

import base64
import io

from .providers import ProviderSpec, build_llm, is_openrouter
from .text import log

VISION_MODEL_DEFAULT = "nvidia/nemotron-3.5-super-vl:free"
MAX_SIDE = 1600

PROMPTS = {
    "fr": ("Voici une capture de l'ecran de l'utilisateur. Reponds en francais, "
           "precisement et en peu de mots, a sa demande : {question}"),
    "en": ("Here is a screenshot of the user's screen. Answer precisely and "
           "briefly, in English, the request: {question}"),
}
DEFAULT_QUESTION = {"fr": "Decris ce qui est affiche.", "en": "Describe what is shown."}


def capture_screen():
    """Capture de tout le bureau (tous les ecrans) en image Pillow."""
    from PIL import ImageGrab

    return ImageGrab.grab(all_screens=True)


def to_jpeg(image, max_side: int = MAX_SIDE, quality: int = 80) -> bytes:
    """Reduit l'image (cote max `max_side`) et l'encode en JPEG."""
    from PIL import Image

    image = image.convert("RGB")
    scale = max_side / max(image.size)
    if scale < 1:
        image = image.resize((round(image.width * scale), round(image.height * scale)),
                             Image.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality, optimize=True)
    return buffer.getvalue()


def image_message(jpeg: bytes, text: str):
    from langchain_core.messages import HumanMessage

    data = base64.b64encode(jpeg).decode("ascii")
    return HumanMessage(content=[
        {"type": "text", "text": text},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{data}"}},
    ])


class Vision:
    """Pose une question sur l'ecran a un modele qui voit les images."""

    def __init__(self, spec: ProviderSpec, lang: str = "fr", llm=None, capture=None):
        self.spec = spec
        self.lang = lang if lang in PROMPTS else "en"
        self._llm = llm
        self._capture = capture or capture_screen

    def llm(self):
        if self._llm is None:
            self._llm = build_llm(self.spec, max_tokens=500, timeout=90.0)
        return self._llm

    def ask_image(self, image, question: str = "") -> str:
        question = (question or "").strip() or DEFAULT_QUESTION[self.lang]
        prompt = PROMPTS[self.lang].format(question=question)
        reply = self.llm().invoke([image_message(to_jpeg(image), prompt)])
        content = getattr(reply, "content", "")
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content
                              if isinstance(part, dict))
        return str(content or "").strip()

    def __call__(self, question: str = "") -> str:
        """Capture l'ecran puis repond a `question`."""
        return self.ask_image(self._capture(), question)


def make_vision(primary: ProviderSpec, model: str | None = None,
                lang: str = "fr") -> Vision | None:
    """Vision avec la meme cle et la meme URL que le modele principal.

    Sur OpenRouter, le modele gratuit `VISION_MODEL_DEFAULT` est utilise par
    defaut ; ailleurs, il faut nommer un modele explicitement (`--vision_model`).
    """
    try:
        import PIL  # noqa: F401
    except Exception:
        log("[vision] Pillow absent : outil desactive")
        return None
    name = model or (VISION_MODEL_DEFAULT if is_openrouter(primary.base_url) else None)
    if not name:
        return None
    spec = ProviderSpec(name=primary.name, model=name, base_url=primary.base_url,
                        api_key=primary.api_key, temperature=0.2)
    return Vision(spec, lang)


__all__ = ["Vision", "make_vision", "capture_screen", "to_jpeg", "image_message",
           "VISION_MODEL_DEFAULT"]
