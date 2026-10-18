"""Textes et parametres par langue.

Les chaines sont en UTF-8 ; la console Windows recente les affiche
correctement (cf. `errors="replace"` applique dans jarvis.py).
"""

from __future__ import annotations

STRINGS: dict[str, dict] = {
    "en": {
        "greeting": "Hello, I am Jarvis. How can I help you today?",
        "yes": "Yes, I am listening.",
        "didnt_understand": "I'm sorry, I didn't understand that.",
        "stt_error": "I cannot reach the speech service. Check your internet connection.",
        "mic_error": "I cannot use the microphone.",
        "llm_error": "Sorry, I could not reach the language model. Please try again.",
        "goodbye": "Goodbye.",
        "listening": "Listening...",
        "system": (
            "You're an assistant who's good at {ability}. "
            "Respond in {words} words or fewer. Reply in English."
        ),
        "exit_phrases": [
            "thank you for your help",
            "stop jarvis",
            "goodbye jarvis",
            "that is all",
        ],
        "google_lang": "en-US",
        "whisper_lang": "en",
        "voice_hints": ["en-us", "en_us", "english", "david", "zira"],
        # --- Horizon 2 : memoire ---
        "remembered": "Okay, I will remember that.",
        "forgotten": "Forgotten.",
        "nothing_to_forget": "I could not find anything to forget.",
        "memory_empty": "I do not know anything about that yet.",
        "profile_header": "What you know about the user:",
        "memory_header": "Relevant memories:",
        "episodes_header": "Summaries of past conversations:",
        "summary_prompt": (
            "Summarise the conversation below in three sentences at most. "
            "Keep durable facts about the user, decisions and preferences. "
            "Answer with the summary only, in English."
        ),
        # --- Horizon 3 : outils ---
        "tool_error": "The tool failed.",
        "timer_done": "Your timer is done: {label}",
        "no_timers": "No timer is running.",
        "cancelled_timers": "{count} timer(s) cancelled.",
        "app_denied": "I am not allowed to open that application.",
        "tool_guidance": (
            "You have tools: current date and time, calculations, weather, "
            "web search, Wikipedia, timers and opening an application. Use them "
            "instead of guessing."
        ),
        "memory_guidance": (
            "Use 'remember_fact' whenever the user shares something durable "
            "about themselves. Use 'recall_memory' when they refer to something "
            "from the past."
        ),
        "tool_running": "One moment.",
        "timer_state_running": "running",
        "timer_state_done": "done",
        # --- Horizon 4 : fournisseurs ---
        "fallback_used": "Switching to the local model.",
        "local_down": "The local model is not available.",
        "whisper_loading": "Loading the local speech model...",
        # --- Horizon 5 : voix ---
        "vad_calibrated": "Voice detection calibrated.",
        # --- Horizon 6 : interface graphique ---
        "gui_you": "You",
        "gui_jarvis": "Jarvis",
        "gui_placeholder": "Type a message, then press Enter...",
        "gui_send": "Send",
        "gui_listen": "Speak",
        "gui_stop": "Stop",
        "gui_clear": "Clear",
        "gui_mute": "Mute",
        "gui_state_ready": "Ready",
        "gui_state_thinking": "Jarvis is thinking...",
        "gui_state_speaking": "Jarvis is speaking...",
        "gui_state_listening": "Listening...",
        "gui_tool": "tool: {name}",
        "gui_no_mic": "Microphone unavailable: you can still type.",
        "gui_menu_file": "File",
        "gui_menu_help": "Help",
        "gui_menu_quit": "Quit",
        "gui_menu_clear": "Clear conversation",
        "gui_menu_export": "Export conversation...",
        "gui_export_title": "Save conversation",
        "gui_export_ok": "Conversation exported.",
        "gui_export_empty": "Nothing to export yet.",
        "gui_about": "About Jarvis",
        "gui_about_body": (
            "Jarvis {version}\n\nModel : {model}\nLanguage : {lang}\n"
            "Tools : {tools}\nMemory : {memory}\n\n"
            "Type a message, or click \u201cSpeak\u201d to talk."
        ),
        "gui_resumed": "(conversation resumed)",
        "gui_you_label": "You",
        "gui_on": "enabled",
        "gui_off": "disabled",
        "gui_none": "none",
        "gui_ft_text": "Text file",
        "gui_ft_all": "All files",
    },
    "fr": {
        "greeting": "Bonjour, je suis Jarvis. Comment puis-je vous aider ?",
        "yes": "Oui, je t'écoute.",
        "didnt_understand": "Désolé, je n'ai pas compris.",
        "stt_error": "Je ne peux pas joindre le service de reconnaissance. Vérifie ta connexion.",
        "mic_error": "Je ne peux pas utiliser le microphone.",
        "llm_error": "Désolé, je n'arrive pas à contacter le modèle. Réessaie.",
        "goodbye": "Au revoir.",
        "listening": "À l'écoute...",
        "system": (
            "Tu es un assistant qui excelle en {ability}. "
            "Réponds en {words} mots maximum. Réponds en français."
        ),
        "exit_phrases": [
            "merci pour ton aide",
            "stop jarvis",
            "au revoir jarvis",
            "c'est tout",
        ],
        "google_lang": "fr-FR",
        "whisper_lang": "fr",
        "voice_hints": ["fr-fr", "fr_fr", "french", "hortense"],
        # --- Horizon 2 : memoire ---
        "remembered": "D'accord, je m'en souviendrai.",
        "forgotten": "C'est oublié.",
        "nothing_to_forget": "Je n'ai rien trouvé à oublier.",
        "memory_empty": "Je ne sais encore rien là-dessus.",
        "profile_header": "Ce que tu sais sur l'utilisateur :",
        "memory_header": "Souvenirs pertinents :",
        "episodes_header": "Résumés de conversations passées :",
        "summary_prompt": (
            "Résume la conversation ci-dessous en trois phrases maximum. "
            "Garde les faits durables sur l'utilisateur, les décisions et les "
            "préférences. Réponds uniquement par le résumé, en français."
        ),
        # --- Horizon 3 : outils ---
        "tool_error": "L'outil a échoué.",
        "timer_done": "Ton minuteur est terminé : {label}",
        "no_timers": "Aucun minuteur en cours.",
        "cancelled_timers": "{count} minuteur(s) annulé(s).",
        "app_denied": "Je n'ai pas le droit d'ouvrir cette application.",
        "tool_guidance": (
            "Tu disposes d'outils : date et heure, calculs, meteo, recherche "
            "web, Wikipedia, minuteurs et ouverture d'application. Utilise-les "
            "au lieu de deviner."
        ),
        "memory_guidance": (
            "Utilise 'remember_fact' des que l'utilisateur confie un fait "
            "durable sur lui. Utilise 'recall_memory' quand il fait reference "
            "a quelque chose de passé."
        ),
        "tool_running": "Un instant.",
        "timer_state_running": "en cours",
        "timer_state_done": "terminé",
        # --- Horizon 4 : fournisseurs ---
        "fallback_used": "Je bascule sur le modèle local.",
        "local_down": "Le modèle local n'est pas disponible.",
        "whisper_loading": "Chargement du modèle vocal local...",
        # --- Horizon 5 : voix ---
        "vad_calibrated": "Détection de voix calibrée.",
        # --- Horizon 6 : interface graphique ---
        "gui_you": "Vous",
        "gui_jarvis": "Jarvis",
        "gui_placeholder": "Écris ton message, puis Entrée...",
        "gui_send": "Envoyer",
        "gui_listen": "Parler",
        "gui_stop": "Stop",
        "gui_clear": "Effacer",
        "gui_mute": "Muet",
        "gui_state_ready": "Prêt",
        "gui_state_thinking": "Jarvis réfléchit...",
        "gui_state_speaking": "Jarvis parle...",
        "gui_state_listening": "À l'écoute...",
        "gui_tool": "outil : {name}",
        "gui_no_mic": "Micro indisponible : la saisie clavier reste active.",
        "gui_menu_file": "Fichier",
        "gui_menu_help": "Aide",
        "gui_menu_quit": "Quitter",
        "gui_menu_clear": "Effacer la conversation",
        "gui_menu_export": "Exporter la conversation...",
        "gui_export_title": "Enregistrer la conversation",
        "gui_export_ok": "Conversation exportée.",
        "gui_export_empty": "Rien à exporter pour l'instant.",
        "gui_about": "À propos de Jarvis",
        "gui_about_body": (
            "Jarvis {version}\n\nModèle : {model}\nLangue : {lang}\n"
            "Outils : {tools}\nMémoire : {memory}\n\n"
            "Écris un message, ou clique sur « Parler » pour parler."
        ),
        "gui_resumed": "(conversation reprise)",
        "gui_you_label": "Vous",
        "gui_on": "activée",
        "gui_off": "désactivée",
        "gui_none": "aucun",
        "gui_ft_text": "Fichier texte",
        "gui_ft_all": "Tous les fichiers",
    },
}

__all__ = ["STRINGS"]
