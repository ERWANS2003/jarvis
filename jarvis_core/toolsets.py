"""Les bons outils pour la bonne question : moins de texte envoye, reponse plus rapide.

Les 26 a 34 outils de Jarvis representent ~2 100 jetons de descriptions a
chaque appel au modele. Mesure sur Groq (30/10/2026) : 0,90 s avec tous les
outils, 0,71 s avec les 6 utiles, soit ~0,4 s gagnees sur une reponse qui
appelle un outil (deux appels au modele), et un quota qui dure plus longtemps.

Les outils de base sont toujours fournis (heure, calcul, meteo, recherche web,
memoire) ; les autres groupes s'ajoutent quand la question en parle. Un outil
inconnu (plugin) est toujours fourni, par prudence.
"""

from __future__ import annotations

import re

from .intents import normalize

CORE = {"get_current_datetime", "calculate", "get_weather", "web_search", "search_wikipedia",
        "remember_fact", "recall_memory", "forget_memory"}

GROUPS = {
    "temps": ({"set_timer", "list_timers", "cancel_timer", "set_reminder", "list_reminders",
               "cancel_reminder"},
              r"minut|chrono|timer|rappel|alarm|reveil|remind|compte a rebours|dans \d+ (?:min|h|sec)"),
    "pc": ({"control_volume", "control_media", "lock_screen", "take_screenshot",
            "get_system_info", "get_disk_usage"},
           r"volume|\bson\b|muet|sourdine|pause|suivant|precedent|verrouill|capture|batterie|"
           r"disque|memoire vive|\bram\b|processeur|\bcpu\b|ordinateur|\bpc\b|systeme|"
           r"screenshot|lock|battery|disk"),
    "web": ({"open_application_tool", "open_website", "search_on_site", "play_music"},
            r"ouvr|lanc|demarr|site|youtube|spotify|netflix|google|joue|ecoute|musique|chanson|"
            r"playlist|application|appli|open|launch|play|music|song"),
    "texte": ({"read_clipboard", "type_text", "copy_to_clipboard", "find_files", "open_file",
               "explain_error", "look_at_screen"},
              r"fichier|dossier|document|pdf|photo|image|copi|coll|presse|selection|ecri|redig|"
              r"\blis\b|lire|tradui|resum|erreur|bug|plant|crash|ecran|regarde|vois|cette page|"
              r"\bca\b|ceci|file|folder|clipboard|write|translate|summar|error|screen"),
    "infos": ({"get_news"}, r"\binfo|actu|nouvelles|journal|news|headline|a la une"),
    "quiz": ({"start_quiz", "record_quiz_answer", "stop_quiz"},
             r"quiz|interroge|revis|question(?:s)? sur|teste-moi|quiz me"),
}
_COMPILED = {name: (tools, re.compile(pattern)) for name, (tools, pattern) in GROUPS.items()}
KNOWN = set(CORE).union(*(tools for tools, _ in GROUPS.values()))


def select(tools: list, text: str, quiz_active: bool = False) -> list:
    """Sous-ensemble d'outils utile pour `text` (ordre d'origine conserve)."""
    low = normalize(text)
    wanted = set(CORE)
    for name, (group, pattern) in _COMPILED.items():
        if pattern.search(low) or (name == "quiz" and quiz_active):
            wanted |= group
    return [tool for tool in tools if tool.name in wanted or tool.name not in KNOWN]


__all__ = ["select", "CORE", "GROUPS"]
