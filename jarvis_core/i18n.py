"""Textes et parametres par langue.

Les chaines sont en UTF-8 ; la console Windows recente les affiche
correctement (cf. `errors="replace"` applique dans jarvis.py).
"""

from __future__ import annotations

STRINGS: dict[str, dict] = {
    "en": {
        "greeting": "Hello, I am Jarvis. How may I help you today?",
        "yes": "Yes, I am listening.",
        "didnt_understand": "I'm sorry, I didn't understand that.",
        "stt_error": "I cannot reach the speech service. Check your internet connection.",
        "mic_error": "I cannot use the microphone.",
        "llm_error": "Sorry, I could not reach the language model. Please try again.",
        "empty_reply": "I did not manage to answer that one. Could you rephrase?",
        "goodbye": "Goodbye.",
        "listening": "Listening...",
        "system": (
            "You are J.A.R.V.I.S., the user's personal assistant, highly skilled "
            "in {ability}. Your manner is that of a brilliant British butler: "
            "courteous, composed, precise, with a touch of dry wit, never "
            "servile. Address the user by their first name when you know it "
            "(see their profile), without overdoing it. Reply in English in "
            "{words} words or fewer. Your answer is read aloud: natural "
            "sentences, no lists, no markdown, no emoji. When you perform an "
            "action, confirm it briefly."
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
            "web search, Wikipedia, timers, reminders at a given date, opening "
            "an application, the computer volume, music playback, screenshots, "
            "locking the screen, opening websites or searching on them, the "
            "clipboard (what the user copied) and "
            "finding or opening the user's files, and looking at the screen "
            "(only when asked). Use them instead of guessing."
        ),
        "memory_guidance": (
            "Use 'remember_fact' whenever the user shares something durable "
            "about themselves. Use 'recall_memory' when they refer to something "
            "from the past."
        ),
        "verify_guidance": (
            "Reliability: use 'calculate' for every calculation, even a simple one. For "
            "a precise or recent fact (figures, dates, names, prices, results, who holds "
            "a position), use 'web_search' and briefly name the source ('according to "
            "the BBC...'). Check your result before answering a problem. If you are not "
            "sure, say so plainly instead of inventing. Do not comment on these checks "
            "(no 'I checked' or 'I calculated')."
        ),
        "honesty_guidance": (
            "If you are not sure of a precise or recent fact, say so plainly instead of "
            "inventing; never make up figures, dates or names."
        ),
        "tool_running": "One moment.",
        "timer_state_running": "running",
        "timer_state_done": "done",
        # --- outils : controle du PC et rappels ---
        "pc_unsupported": "That only works on Windows.",
        "pc_done": "Done.",
        "volume_set": "Volume set to {percent}%.",
        "screen_locked": "Screen locked.",
        "screenshot_saved": "Screenshot saved in {path}.",
        "reminder_set": "Reminder {id} set for {when}.",
        "reminder_bad_date": "I could not read that date.",
        "no_reminders": "No reminder planned.",
        "cancelled_reminders": "{count} reminder(s) cancelled.",
        "reminder_due": "Reminder: {text}",
        "reminder_late": "Missed reminder: {text}",
        "clipboard_empty": "The clipboard is empty: copy a text first.",
        "clipboard_copied": "It is in the clipboard, you can paste it.",
        "files_none": "I did not find any matching file in your folders.",
        "file_opened": "Opening {name}.",
        "file_denied": "I am not allowed to open that file.",
        "site_opened": "Opening {site}.",
        "timer_started": "Timer set for {duration}.",
        "music_playing": "Playing {query}.",
        "typed_done": "Done, it is written.",
        "nothing_selected": "Select or copy a text first, then ask me again.",
        "timer_label": "{duration} timer done.",
        "reminder_noted": "Noted, I will remind you {when}.",
        "site_searched": "Here are the results for {query} on {site}.",
        "site_unknown": "I do not know that site; give me its address.",
        "vision_error": "I could not see the screen.",
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
        "gui_tagline": "Your personal assistant",
        "gui_export_short": "Export",
        "gui_suggest_title": "Try:",
        "gui_suggest_1": "What time is it?",
        "gui_suggest_2": "Tell me a joke",
        "gui_suggest_3": "Open Spotify",
        "gui_model": "Model",
        "gui_lang": "Language",
        "gui_tools_word": "Tools",
        "gui_memory_word": "Memory",
        "gui_hints": "Enter: send \u00b7 Esc: stop \u00b7 Ctrl+L: clear \u00b7 Ctrl+E: export",
        # --- Horizon 6 : interface web (navigateur) ---
        "web_open": "Jarvis interface: {url}",
        "web_new_chat": "New conversation",
        "web_memory": "Memory",
        "web_memory_empty": "Jarvis does not remember anything yet.",
        "web_forget": "Forget",
        "web_copy": "Copy",
        "web_copied": "Copied",
        "web_theme": "Theme",
        "web_offline": "Connection to Jarvis lost. Retrying...",
        "web_busy": "Jarvis is already answering.",
        "web_quit": "Quit Jarvis",
        "web_closed": "Jarvis is closed. You can close this tab.",
        "web_kind_profile": "Profile",
        "web_kind_fact": "Fact",
        "web_kind_episode": "Summary",
        # --- Horizon 6 : orbe flottante ---
        "orb_speak": "Speak",
        "orb_type": "Type a message...",
        "orb_stop": "Stop talking",
        "orb_mute": "Mute voice",
        "orb_quit": "Quit Jarvis",
        "orb_listening": "Listening...",
        "orb_hint": "Jarvis orb: click to talk, drag to move, right-click for the menu.",
        "orb_wake_menu": "Listen for \u00ab {word} \u00bb",
        "orb_say_hey": "Say \u00ab {word} \u00bb",
        "orb_press_key": "press {key}",
        "orb_or": " or ",
        "orb_history": "History",
        "orb_journal": "Journal…",
        "orb_history_empty": "No exchange yet.",
        "orb_settings": "Settings",
        "orb_voice": "Voice",
        "orb_voice_windows": "Windows voice",
        "orb_theme": "Theme",
        "orb_theme_jarvis": "Jarvis (holographic HUD)",
        "orb_theme_siri": "Siri (glass sphere)",
        "orb_theme_aurore": "Aurora (soft pastel)",
        "orb_theme_opale": "Opal (pearly)",
        "orb_theme_nebuleuse": "Nebula (deep, glowing)",
        "orb_theme_plasma": "Plasma (iridescent liquid)",
        "orb_follow_up": "Continuous conversation",
        "orb_hide": "Hide the orb",
        "orb_show": "Show Jarvis",
        "orb_voice_sample": "Here is my new voice. Does it suit you?",
        "orb_auto_hide": "Auto-hide",
        "orb_quality": "Quality",
        "orb_quality_ultra": "Ultra (graphics card, 3D)",
        "orb_quality_standard": "Standard (processor)",
        "orb_never": "Never",
        "orb_seconds": "After {n} s",
        "orb_minutes": "After {n} min",
        "not_heard": "I did not hear anything. Click and try again.",
    },
    "fr": {
        "greeting": "Bonjour, je suis Jarvis. Comment puis-je vous aider ?",
        "yes": "Oui, je t'écoute.",
        "didnt_understand": "Désolé, je n'ai pas compris.",
        "stt_error": "Je ne peux pas joindre le service de reconnaissance. Vérifie ta connexion.",
        "mic_error": "Je ne peux pas utiliser le microphone.",
        "llm_error": "Désolé, je n'arrive pas à contacter le modèle. Réessaie.",
        "empty_reply": "Je n'ai pas réussi à répondre à ça. Peux-tu reformuler ?",
        "goodbye": "Au revoir.",
        "listening": "À l'écoute...",
        "system": (
            "Tu es J.A.R.V.I.S., l'assistant personnel de l'utilisateur, qui "
            "excelle en {ability}. Ton style : celui d'un majordome britannique "
            "brillant, courtois, posé et précis, avec une pointe d'humour "
            "pince-sans-rire, jamais servile. Tu vouvoies l'utilisateur et "
            "l'appelles par son prénom quand tu le connais (voir son profil), "
            "sans en abuser. Réponds en français, en {words} mots maximum. Ta "
            "réponse est lue à voix haute : phrases naturelles, sans listes, "
            "sans mise en forme ni émojis. Quand tu fais une action, "
            "confirme-la brièvement."
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
            "web, Wikipedia, minuteurs, rappels a une date precise, ouverture "
            "d'application, volume de l'ordinateur, lecture de la musique, "
            "captures d'ecran, verrouillage de l'ecran, ouverture de sites web ou "
            "recherche dessus, presse-papiers (ce que "
            "l'utilisateur a copie), recherche ou ouverture de ses fichiers, et "
            "regard sur l'ecran (seulement si on te le demande). Utilise-les au "
            "lieu de deviner."
        ),
        "memory_guidance": (
            "Utilise 'remember_fact' des que l'utilisateur confie un fait "
            "durable sur lui. Utilise 'recall_memory' quand il fait reference "
            "a quelque chose de passé."
        ),
        "verify_guidance": (
            "Fiabilité : utilise 'calculate' pour tout calcul, même simple. Pour un fait "
            "précis ou récent (chiffres, dates, noms, prix, résultats, qui occupe un "
            "poste), utilise 'web_search' et cite brièvement la source (« d'après Le "
            "Monde… »). Vérifie ton résultat avant de répondre à un problème. Si tu "
            "n'es pas certain, dis-le franchement plutôt que d'inventer. Ne commente pas "
            "ces vérifications (pas de « j'ai vérifié » ni « j'ai calculé »)."
        ),
        "honesty_guidance": (
            "Si tu n'es pas certain d'un fait précis ou récent, dis-le franchement "
            "plutôt que d'inventer ; n'invente jamais de chiffres, de dates ni de noms."
        ),
        "tool_running": "Un instant.",
        "timer_state_running": "en cours",
        "timer_state_done": "terminé",
        # --- outils : controle du PC et rappels ---
        "pc_unsupported": "Cela ne fonctionne que sous Windows.",
        "pc_done": "C'est fait.",
        "volume_set": "Volume réglé à {percent} %.",
        "screen_locked": "Écran verrouillé.",
        "screenshot_saved": "Capture enregistrée dans {path}.",
        "reminder_set": "Rappel {id} enregistré pour le {when}.",
        "reminder_bad_date": "Je n'arrive pas à lire cette date.",
        "no_reminders": "Aucun rappel prévu.",
        "cancelled_reminders": "{count} rappel(s) annulé(s).",
        "reminder_due": "Rappel : {text}",
        "reminder_late": "Rappel en retard : {text}",
        "clipboard_empty": "Le presse-papiers est vide : copie d'abord un texte.",
        "clipboard_copied": "C'est dans le presse-papiers, tu peux le coller.",
        "files_none": "Je n'ai trouvé aucun fichier correspondant dans tes dossiers.",
        "file_opened": "J'ouvre {name}.",
        "file_denied": "Je n'ai pas le droit d'ouvrir ce fichier.",
        "site_opened": "J'ouvre {site}.",
        "timer_started": "C'est parti pour {duration}.",
        "music_playing": "Je lance {query}.",
        "typed_done": "C'est écrit.",
        "nothing_selected": "Sélectionne ou copie d'abord un texte, puis redemande-moi.",
        "timer_label": "Minuteur de {duration} terminé.",
        "reminder_noted": "C'est noté, je te le rappelle {when}.",
        "site_searched": "Voici les résultats pour {query} sur {site}.",
        "site_unknown": "Je ne connais pas ce site ; donnez-moi son adresse.",
        "vision_error": "Je n'arrive pas à voir l'écran.",
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
        "gui_tagline": "Ton assistant personnel",
        "gui_export_short": "Exporter",
        "gui_suggest_title": "Essaie :",
        "gui_suggest_1": "Quelle heure est-il ?",
        "gui_suggest_2": "Raconte-moi une blague",
        "gui_suggest_3": "Ouvre Spotify",
        "gui_model": "Modèle",
        "gui_lang": "Langue",
        "gui_tools_word": "Outils",
        "gui_memory_word": "Mémoire",
        "gui_hints": "Entrée : envoyer \u00b7 Échap : stop \u00b7 Ctrl+L : effacer \u00b7 Ctrl+E : exporter",
        # --- Horizon 6 : interface web (navigateur) ---
        "web_open": "Interface de Jarvis : {url}",
        "web_new_chat": "Nouvelle conversation",
        "web_memory": "Mémoire",
        "web_memory_empty": "Jarvis ne se souvient encore de rien.",
        "web_forget": "Oublier",
        "web_copy": "Copier",
        "web_copied": "Copié",
        "web_theme": "Thème",
        "web_offline": "Connexion à Jarvis perdue. Nouvelle tentative...",
        "web_busy": "Jarvis est déjà en train de répondre.",
        "web_quit": "Quitter Jarvis",
        "web_closed": "Jarvis est fermé. Tu peux fermer cet onglet.",
        "web_kind_profile": "Profil",
        "web_kind_fact": "Fait",
        "web_kind_episode": "Résumé",
        # --- Horizon 6 : orbe flottante ---
        "orb_speak": "Parler",
        "orb_type": "Écrire un message...",
        "orb_stop": "Arrêter la voix",
        "orb_mute": "Couper la voix",
        "orb_quit": "Quitter Jarvis",
        "orb_listening": "Je t'écoute...",
        "orb_hint": "Orbe Jarvis : clic pour parler, glisser pour déplacer, clic droit pour le menu.",
        "orb_wake_menu": "\u00c9couter \u00ab {word} \u00bb",
        "orb_say_hey": "Dis \u00ab {word} \u00bb",
        "orb_press_key": "appuie sur {key}",
        "orb_or": " ou ",
        "orb_history": "Historique",
        "orb_journal": "Journal…",
        "orb_history_empty": "Aucun échange pour l'instant.",
        "orb_settings": "Réglages",
        "orb_voice": "Voix",
        "orb_voice_windows": "Voix Windows",
        "orb_theme": "Thème",
        "orb_theme_jarvis": "Jarvis (HUD holographique)",
        "orb_theme_siri": "Siri (sphère de verre)",
        "orb_theme_aurore": "Aurore (pastel doux)",
        "orb_theme_opale": "Opale (nacrée)",
        "orb_theme_nebuleuse": "Nébuleuse (profonde, lumineuse)",
        "orb_theme_plasma": "Plasma (liquide irisé)",
        "orb_follow_up": "Conversation continue",
        "orb_hide": "Masquer l'orbe",
        "orb_show": "Afficher Jarvis",
        "orb_voice_sample": "Voici ma nouvelle voix. Vous convient-elle ?",
        "orb_auto_hide": "Masquage auto",
        "orb_quality": "Qualité",
        "orb_quality_ultra": "Ultra (carte graphique, 3D)",
        "orb_quality_standard": "Standard (processeur)",
        "orb_never": "Jamais",
        "orb_seconds": "Après {n} s",
        "orb_minutes": "Après {n} min",
        "not_heard": "Je n'ai rien entendu. Clique et réessaie.",
    },
}

__all__ = ["STRINGS"]
