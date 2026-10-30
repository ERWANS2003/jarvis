"""Un Jarvis plus intelligent : expert a la demande, details, memoire qui apprend.

  * **modele expert** : maths, code, logique, analyse... partent vers un modele
    gratuit qui raisonne (Nemotron Ultra 550B : 16 h 17 juste en 20 s la ou le
    modele rapide rendait une reponse vide). Le reste garde le modele rapide.
  * **reponses adaptees** : « explique en detail » -> Jarvis dit un resume de
    deux phrases et affiche la version complete (titres, listes) a l'ecran.
  * **memoire qui apprend seule** : apres un echange ou l'utilisateur parle de
    lui, un petit appel en arriere-plan extrait les faits durables (gouts,
    projets, proches, habitudes) et les range dans la memoire.
"""

from __future__ import annotations

import json
import re
import threading

from .intents import normalize
from .text import log

# --------------------------------------------------------------------------- #
# Modele expert
# --------------------------------------------------------------------------- #
_EXPERT = re.compile(
    r"\b(?:resous|resoudre|equation|integrale|derivee|probabilit\w*|"
    r"statistique\w*|demontre|demonstration|prouve|theoreme|enigme|devinette|logique|"
    r"raisonne\w*|reflechis|prends ton temps|mode expert|analyse|analyser|compare[rz]?|"
    r"avantages et (?:les )?inconvenients|strategie|optimise\w*|algorithme|complexite|"
    r"code|coder|programme|programmer|fonction|python|javascript|typescript|java|sql|regex|"
    r"html|css|api|script|debug\w*|compile\w*|rattrape|km/h|vitesse moyenne|"
    r"solve|prove|equation|probability|algorithm|step by step|think carefully|"
    r"pros and cons|explain why|reason)\b")
_ARITH = re.compile(r"\d+(?:[.,]\d+)?\s*(?:[x*/^+-]|fois|divise|plus|moins|%)\s*\d")


def needs_expert(text: str) -> bool:
    """Vrai pour une question qui demande du raisonnement (maths, code, analyse)."""
    low = normalize(text)
    if not low:
        return False
    words = len(low.split())
    if _EXPERT.search(low):
        return True
    numbers = len(re.findall(r"\d+", low))
    # Un simple calcul (« 15 % de 18 500 ») va a la calculatrice du modele rapide ;
    # l'expert sert aux problemes a plusieurs donnees ou longuement enonces.
    return (numbers >= 4 and words >= 12) or (bool(_ARITH.search(low)) and words >= 16) \
        or words >= 35


# --------------------------------------------------------------------------- #
# Reponses detaillees
# --------------------------------------------------------------------------- #
DETAIL_MARK = "---DETAIL---"
_DETAIL = re.compile(
    r"\b(?:en detail|en details|detaille\w*|de facon (?:complete|detaillee)|developpe|"
    r"explique(?:-moi)? (?:tout|precisement|completement)|fais(?:-moi)? (?:une liste|un tableau|"
    r"un plan|un resume complet|une fiche)|liste(?:-moi)? |donne(?:-moi)? (?:la liste|les etapes)|"
    r"etape par etape|tutoriel|recette|in detail|detailed|step by step|make a list|full summary)")


def needs_detail(text: str) -> bool:
    return bool(_DETAIL.search(normalize(text) + " "))


DETAIL_RULES = {
    "fr": ("L'utilisateur veut une réponse détaillée. Écris d'abord un résumé oral de deux "
           "phrases (lu à voix haute), puis une ligne contenant exactement " + DETAIL_MARK +
           ", puis la version complète en Markdown (titres ##, listes, étapes numérotées, "
           "**gras**), sans limite de longueur. Cette version s'affiche à l'écran."),
    "en": ("The user wants a detailed answer. First write a two-sentence spoken summary, then "
           "a line containing exactly " + DETAIL_MARK + ", then the full version in Markdown "
           "(## headings, lists, numbered steps, **bold**), any length. It is shown on screen."),
}
EXPERT_HINT = {"fr": "Laissez-moi réfléchir un instant.", "en": "Let me think for a moment."}


class DetailSplitter:
    """Laisse passer le resume oral, retient la partie detaillee (apres la marque)."""

    def __init__(self, speak):
        self.speak = speak
        self.detail: list[str] = []
        self.in_detail = False
        self._pending = ""

    def __call__(self, chunk: str) -> None:
        if self.in_detail:
            self.detail.append(chunk)
            return
        text = self._pending + chunk
        self._pending = ""
        if DETAIL_MARK in text:
            before, after = text.split(DETAIL_MARK, 1)
            if before.strip():
                self.speak(before.strip())
            self.in_detail = True
            if after.strip():
                self.detail.append(after)
            return
        # La marque peut arriver coupee entre deux morceaux (« ---DE » + « TAIL--- »).
        cut = text.rfind("---")
        if cut != -1 and DETAIL_MARK.startswith(text[cut:].strip()):
            self._pending = text[cut:]
            text = text[:cut]
        if text.strip():
            self.speak(text.strip())

    def finish(self) -> str:
        if self._pending and not self.in_detail:
            self.speak(self._pending)
            self._pending = ""
        return "\n".join(part.rstrip() for part in self.detail).strip()


# --------------------------------------------------------------------------- #
# Memoire qui apprend seule
# --------------------------------------------------------------------------- #
_ABOUT_ME = re.compile(r"\b(?:je|j'|j |moi|mon|ma|mes|nous|notre|nos|i|i'm|my|me|we|our)\b")
LEARN_PROMPT = {
    "fr": ("Voici un échange entre l'utilisateur et son assistant.\n"
           "Extrais UNIQUEMENT les faits DURABLES sur l'utilisateur : goûts, préférences, "
           "projets, travail ou études, proches (nom et lien), habitudes, contraintes de "
           "santé ou d'emploi du temps, objectifs. Ignore ce qui est passager (une envie "
           "du moment, la météo, une question ponctuelle) et ce que l'assistant dit.\n"
           "Réponds UNIQUEMENT par un tableau JSON de phrases courtes à la troisième "
           "personne (« Il travaille comme infirmier. »), ou [] s'il n'y a rien.\n\n"
           "Utilisateur : {user}\nAssistant : {reply}"),
    "en": ("Here is an exchange between the user and their assistant.\n"
           "Extract ONLY DURABLE facts about the user: tastes, preferences, projects, job "
           "or studies, close people (name and relation), habits, health or schedule "
           "constraints, goals. Ignore anything temporary and what the assistant says.\n"
           "Answer ONLY with a JSON array of short third-person sentences, or [] if none.\n\n"
           "User: {user}\nAssistant: {reply}"),
}
MAX_FACTS = 4


def worth_learning(text: str) -> bool:
    """Le message parle-t-il de l'utilisateur lui-meme (et pas d'une simple commande) ?"""
    low = normalize(text)
    return len(low.split()) >= 4 and bool(_ABOUT_ME.search(low))


def parse_facts(raw: str) -> list[str]:
    """Tableau JSON (meme entoure de texte ou de ```) -> liste de phrases propres."""
    match = re.search(r"\[.*\]", raw or "", re.S)
    if not match:
        return []
    try:
        items = json.loads(match.group(0))
    except Exception:
        return []
    facts = []
    for item in items if isinstance(items, list) else []:
        if isinstance(item, str):
            fact = " ".join(item.split()).strip(" -•")
            if 8 <= len(fact) <= 160:
                facts.append(fact)
    return facts[:MAX_FACTS]


def learn(memory, ask, user_text: str, reply: str, lang: str = "fr") -> list[str]:
    """Extrait et enregistre les faits durables d'un echange. Renvoie les faits appris."""
    from .memory import FACT

    if memory is None or ask is None or not worth_learning(user_text):
        return []
    prompt = LEARN_PROMPT["fr" if lang == "fr" else "en"].format(
        user=user_text.strip()[:800], reply=(reply or "").strip()[:500])
    try:
        facts = parse_facts(ask(prompt))
    except Exception as exc:
        log(f"[memoire] apprentissage impossible : {exc}")
        return []
    for fact in facts:
        try:
            memory.remember(fact, kind=FACT, source="learned")
            log(f"[memoire] appris : {fact}")
        except Exception:
            pass
    return facts


def learn_async(memory, ask, user_text: str, reply: str, lang: str = "fr") -> None:
    if memory is None or ask is None or not worth_learning(user_text):
        return
    threading.Thread(target=learn, args=(memory, ask, user_text, reply, lang),
                     name="jarvis-apprend", daemon=True).start()


__all__ = ["needs_expert", "needs_detail", "DetailSplitter", "DETAIL_MARK", "DETAIL_RULES",
           "EXPERT_HINT", "learn", "learn_async", "parse_facts", "worth_learning"]
