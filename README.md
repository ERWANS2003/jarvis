# JARVIS — assistant vocal conversationnel

Assistant vocal en Python : il écoute (micro), comprend (grand modèle de
langage), agit (outils, mémoire) et répond à voix haute. Le projet utilise
`langchain` / `langgraph` pour l'orchestration, `pyttsx3` pour la synthèse
vocale locale et `speech_recognition` pour la reconnaissance.

Inspiré de Jarvis (Iron Man). Fonctionne sous Windows, macOS et Linux ; les
scripts d'installation et de démarrage automatique fournis visent Windows.

---

## Sommaire

- [Fonctionnalités](#fonctionnalités)
- [Prérequis](#prérequis)
- [Installation](#installation)
- [Démarrage rapide](#démarrage-rapide)
- [Fournisseurs de modèle](#fournisseurs-de-modèle)
- [Mémoire longue durée](#mémoire-longue-durée)
- [Outils](#outils)
- [Mode local / hors-ligne](#mode-local--hors-ligne)
- [Voix temps réel](#voix-temps-réel)
- [Configuration par fichier](#configuration-par-fichier)
- [Interface graphique](#interface-graphique)
- [Plugins](#plugins)
- [Démarrage automatique](#démarrage-automatique)
- [Créer un exécutable](#créer-un-exécutable)
- [Toutes les options](#toutes-les-options)
- [Tests](#tests)
- [Crédits](#crédits)
- [Licence](#licence)

---

## Fonctionnalités

Le projet est organisé en six paliers (« horizons ») :

| Horizon | Contenu |
| --- | --- |
| 1. Dialogue vocal | Écoute, transcription, réponse parlée, mot d'activation, interruption (barge-in), historique de conversation. |
| 2. Mémoire longue durée | Base SQLite : faits, profil utilisateur, résumés d'épisodes, recherche dans le passé. |
| 3. Outils & actions | Météo, minuteurs, recherche web, Wikipédia, date/heure, calculs, ouverture d'applications : Jarvis agit au lieu de deviner. |
| 4. Mode local | Reconnaissance hors-ligne (faster-whisper), modèle local (Ollama), bascule automatique cloud → local. |
| 5. Voix temps réel | Fin de phrase par détection de voix (VAD), latence réduite, interruption instantanée. |
| 6. Application | Fichier de configuration, interface graphique, démarrage automatique, installation en une commande, exécutable autonome, plugins. |

Tout est facultatif et tolérant aux pannes : si une brique manque, Jarvis le
signale et continue de fonctionner avec ce qui est disponible.

---

## Prérequis

- **Python 3.10 ou plus récent** (testé avec 3.13).
- Un **micro** pour le mode vocal (facultatif : `--text` fonctionne sans).
- Une **clé API** d'un fournisseur compatible OpenAI (OpenRouter, OpenAI,
  Groq…) — ou un modèle local via Ollama (voir [Mode local](#mode-local--hors-ligne)).
- **Internet** pour la reconnaissance Google et les outils réseau. Le mode
  hors-ligne complet est possible (voir plus bas).

---

## Installation

### En une commande (Windows, recommandé)

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

Le script crée l'environnement virtuel `.venv`, installe les dépendances, crée
`.env` à partir de `.env.example` et vérifie que l'assistant démarre.

Pour ajouter en plus les briques hors-ligne (Whisper, WebRTC VAD, icône de
notification) :

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1 -Optional
```

### Manuellement

```bash
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt     # Windows
# .venv/bin/python -m pip install -r requirements.txt           # macOS / Linux
```

### Clé API

1. Copie `.env.example` en `.env`.
2. Renseigne une clé :

```env
OPENROUTER_API_KEY=sk-or-v1-...
JARVIS_BASE_URL=https://openrouter.ai/api/v1
JARVIS_MODEL=nvidia/nemotron-3.5-super-vl:free
```

`.env` n'est jamais versionné. Tout ce qui n'est pas écrit dans `.env` prend sa
valeur par défaut, dans le fichier de configuration, ou sur la ligne de commande.

Le modèle ci-dessus est **gratuit** : c'est le plus rapide des modèles gratuits
testés (≈ 6 s pour une réponse, 2,5 s pour un appel d'outil), avec un bon
français, et il comprend aussi les images. Si OpenRouter le sature ou le
retire, Jarvis bascule tout seul sur d'autres modèles gratuits (même clé, même
URL) : `nvidia/nemotron-3-ultra-550b-a55b:free` (550B, plus lent),
`nvidia/nemotron-3.5-lightning:free`, `google/gemma-4-31b-it:free`. Le catalogue
gratuit change souvent ; pour choisir la liste toi-même :

```env
JARVIS_FALLBACK_MODELS=nvidia/nemotron-3-ultra-550b-a55b:free,google/gemma-4-31b-it:free
```

---

## Démarrage rapide

**Le plus simple : double-clic sur `Lancer_Jarvis.bat`.** Ce lanceur Windows
prépare tout et ouvre la fenêtre en français :

1. choisit `.venv` s'il existe, sinon le Python de `PATH` (3.10 ou plus) ;
2. vérifie que tkinter est bien installé ;
3. crée `.env` depuis `.env.example` et l'ouvre dans le Bloc-notes s'il manque —
   il suffit d'y coller la clé OpenRouter puis de relancer ;
4. démarre Jarvis avec `--lang fr`, enfin lance la commande passée en argument.

```powershell
.\run.bat                    # ouvre la fenêtre graphique (défaut)
.\run.bat --lang fr          # en français
.\run.bat --no-gui           # console avec micro
.\run.bat --text             # au clavier, sans micro ni voix
.\run.bat --help             # toutes les options
```

Équivalent sans le lanceur :

```bash
python jarvis.py            # après avoir activé l'environnement virtuel
python jarvis.py --lang fr --vad --no-gui
```

Au démarrage, Jarvis ouvre sa fenêtre et se présente. Deux façons de lui parler :

- au **clavier** : tape la question puis **Entrée** (ou le bouton *Envoyer*) ;
- à la **voix** : clique sur **Parler** et pose ta question ; le bouton *Stop*
  coupe la réponse en cours.

En mode console (`--no-gui`), parle après le mot d'activation
(**« Jarvis »** par défaut) : *« Jarvis, quelle heure est-il ? »*. Dis
**« au revoir »** ou **« stop Jarvis »** pour terminer.

Pour reprendre la conversation précédente sans salutation : `--resume`.

---

## Fournisseurs de modèle

Jarvis parle à n'importe quelle API compatible OpenAI (`--base_url` +
`--model` + une clé) :

| Fournisseur | `--base_url` | Clé lue dans |
| --- | --- | --- |
| OpenRouter | `https://openrouter.ai/api/v1` | `OPENROUTER_API_KEY` |
| OpenAI | *défaut* | `OPENAI_API_KEY` |
| Groq | `https://api.groq.com/openai/v1` | `GROQ_API_KEY` |
| Ollama (local) | `http://localhost:11434/v1` | *aucune* (`local`) |

La clé est cherchée dans `--api_key`, puis `JARVIS_API_KEY`, puis la variable
correspondant au fournisseur. Si le fournisseur principal échoue (quota
épuisé, réseau coupé), Jarvis bascule automatiquement : d'abord vers le modèle
local s'il est configuré (voir [Mode local](#mode-local--hors-ligne)), puis vers
d'autres modèles **gratuits** du même OpenRouter ; `--no-fallback` désactive
cette bascule.

**Groq, ~1 s par réponse (gratuit).** Crée une clé sur
<https://console.groq.com/keys> et ajoute `GROQ_API_KEY=gsk_...` dans `.env` :
Groq passe alors en tête (`llama-3.3-70b-versatile`, modifiable avec
`JARVIS_GROQ_MODEL`) et OpenRouter devient le repli. `JARVIS_GROQ=0` le coupe.

---

## Mémoire longue durée

Jarvis se souvient d'une session à l'autre dans une base SQLite
(`.jarvis_memory.db`) :

- **Faits explicites** — « souviens-toi que je préfère le thé » est enregistré.
- **Profil** — nom, ville, métier, préférences détectés automatiquement.
- **Épisodes** — la conversation est résumée et archivée pour être rappelée.
- **Recherche** — « de quoi avons-nous parlé hier ? » interroge le passé.

Options : `--no-memory` (désactive), `--memory_path CHEMIN` (autre fichier).

---

## Outils

Quand le modèle le juge utile, il appelle un outil au lieu d'inventer :

| Outil | Rôle |
| --- | --- |
| `get_current_datetime` | Date et heure locales. |
| `calculate` | Calcul arithmétique (évaluation sûre, sans `eval`). |
| `get_weather` | Météo actuelle d'une ville (Open-Meteo). |
| `search_wikipedia` | Résumé factuel (API Wikipédia). |
| `web_search` | Recherche web récente. |
| `set_timer` / `list_timers` / `cancel_timer` | Minuteurs et rappels, annoncés à voix haute. |
| `open_application_tool` | Ouvre une application autorisée (liste blanche). |
| `control_volume` | Volume : monter, baisser, couper, régler à un pourcentage. |
| `control_media` | Musique / vidéo en cours : lecture-pause, suivant, précédent, stop. |
| `take_screenshot` | Capture d'écran PNG dans `Images\Jarvis`. |
| `lock_screen` | Verrouille l'écran (sur demande explicite). |
| `read_clipboard` / `copy_to_clipboard` | Lit ce que tu as copié (« résume / traduis ça ») ou y place un texte. |
| `find_files` / `open_file` | Cherche par nom dans Bureau, Documents, Téléchargements, Images… (OneDrive compris) et ouvre avec l'application habituelle ; programmes et scripts refusés. |
| `open_website` / `search_on_site` | Ouvre un site (« ouvre YouTube », « lemonde.fr ») ou cherche directement dessus (« cherche des tutos Python sur YouTube ») ; adresses `http(s)` uniquement. |
| `look_at_screen` | Regarde l'écran **sur demande explicite** (« lis-moi cette erreur ») : une capture réduite part au modèle de vision (`nemotron-3.5-super-vl`, gratuit). `--no-vision` retire l'outil. |
| `set_reminder` / `list_reminders` / `cancel_reminder` | Rappels à une date précise (« demain à 9 h »), conservés après redémarrage ; un rappel manqué est annoncé au lancement suivant. |
| `play_music` | « Joue Daft Punk » : lance directement la première vidéo YouTube (ou une recherche Spotify). |
| `get_news` | Titres du jour (Le Monde, Google Actualités), en général ou sur un sujet. |
| `type_text` | Écrit un texte rédigé par Jarvis dans ta fenêtre active (« rédige un mail poli pour décaler le RDV »). |
| `explain_error` | « C'est quoi cette erreur ? » : lit le texte sélectionné (ou l'écran) et explique la cause et la correction. |
| `start_quiz` / `record_quiz_answer` / `stop_quiz` | Mode révision : quiz oral, une question à la fois, avec le score. |
| `remember_fact` / `recall_memory` / `forget_memory` | Mémoire longue durée. |

Les outils réseau sont **sans clé**. `--no-tools` revient à un simple dialogue.
`--list_tools` affiche ce qui est chargé.

---

## Rapidité

- **Commandes instantanées**, sans appel au modèle (moins d'une seconde) : l'heure,
  la date, la météo d'une ville, « ouvre YouTube / Spotify », « cherche X sur
  YouTube », « pause », « suivant », « monte le son », « mets le volume à 30 % ».
- **Minuteurs et rappels instantanés** : « minuteur de 5 minutes », « rappelle-moi
  dans une demi-heure d'éteindre le four », « rappelle-moi demain à 9 h d'appeler
  Paul ». Les rappels sont annoncés à la seconde près (vérification toutes les 5 s).
- Le mode console profite aussi des commandes instantanées et de l'aiguillage.
- **Outils à la demande** : une simple conversation part au modèle sans la
  description des outils (≈ 2 s de moins).
- **Délai maximal** de 30 s par essai : un modèle gratuit figé est abandonné au
  profit du suivant.
- Fin de phrase détectée après 0,65 s de silence ; « Un instant » n'est plus
  dit à voix haute pendant un outil (il retardait la réponse).
- Reconnaissance : si Google renvoie une réponse vide, nouvel essai puis
  transcription **hors ligne** avec Vosk.

## Assistant au quotidien

- **Musique par nom** : « joue Stromae », « mets la chanson Bohème », « écoute du jazz sur Spotify ».
- **Actualités** : « quelles sont les infos ? », « les actus sur le football » ; le
  titre du jour est aussi dans le briefing du matin.
- **Lire et écrire** : sélectionne un texte puis « lis ça » ; « écris : j'arrive
  dans dix minutes » le tape dans ta fenêtre ; « rédige… » fait écrire Jarvis.
- **Révision** : « interroge-moi sur la Révolution française » : quiz oral noté ;
  Jarvis t'écoute 15 s après chaque question, le temps de réfléchir.
- **Notifications Windows** : rappels, minuteurs et alertes s'affichent aussi à l'écran.
- **Jarvis proactif** : il prévient seul d'une batterie faible, de la pluie dans
  l'heure (ville du profil) et d'une pause à faire après 2 h d'activité. La nuit,
  notification seulement. `--no-proactive` le coupe.
- **Journal** (clic droit sur l'orbe) : conversations avec recherche, rappels à
  venir (annulables), souvenirs (effaçables).

---

## Mode local / hors-ligne

### Reconnaissance hors-ligne

Installe les briques optionnelles puis choisis le moteur :

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1 -Optional
.\run.bat --stt whisper --whisper_model small
```

- `--stt auto` (défaut) : Google si Internet, sinon Whisper local.
- `--stt whisper` / `--stt local` : reconnaissance locale uniquement.
- `--whisper_model` : `tiny`, `base`, `small`, `medium`, `large`.

### Modèle hors-ligne

Avec [Ollama](https://ollama.com) installé et un modèle téléchargé
(`ollama pull llama3.2`) :

```powershell
.\run.bat --local_model llama3.2
```

`local_model` devient le repli automatique. Pour **tout** faire en local :

```powershell
.\run.bat --model llama3.2 --base_url http://localhost:11434/v1
```

---

## Voix temps réel

- `--vad` : détecte la fin de la phrase par la voix (et non par un délai fixe) ;
  plus naturel et plus rapide.
- **Barge-in** (actif par défaut) : tu peux couper la parole à Jarvis en
  parlant. `--no-bargein` l'interdit.
- `--phrase_limit` : délai maximal d'écoute par phrase.
- `--max_speak` : garde-fou qui coupe une synthèse vocale trop longue.

---

## Configuration par fichier

Toutes les options peuvent vivre dans `jarvis.yaml` (ou `.json` / `.toml`),
cherché automatiquement dans le dossier courant puis dans celui du projet, ou
imposé par `--config`.

```yaml
voice:
  lang: fr
  wake: true
  wake_words: [jarvis, hey jarvis]
  bargein: true
  volume: 1.0
  stt: auto
provider:
  temperature: 0.4
memory:
  memory: true
tools:
  tools: true
  plugins: true
```

Ordre de priorité : **ligne de commande > variables `JARVIS_*` > fichier de
configuration > valeurs par défaut**. Un modèle est fourni dans
`jarvis.example.yaml`. `--show_config` affiche la configuration réellement
appliquée.

Variables d'environnement reconnues : `JARVIS_LANG`, `JARVIS_MODEL`,
`JARVIS_BASE_URL`, `JARVIS_API_KEY`, `JARVIS_VOICE`, `JARVIS_VOLUME`,
`JARVIS_RATE`, `JARVIS_ABILITY`, `JARVIS_STT`, `JARVIS_WHISPER_MODEL`,
`JARVIS_MEMORY_PATH`, `JARVIS_HISTORY_PATH`, `JARVIS_LOCAL_MODEL`,
`JARVIS_LOCAL_BASE_URL`, `JARVIS_FALLBACK_MODELS`, `JARVIS_PLUGINS_DIR`,
`JARVIS_GUI`.

---

## Interface graphique

L'interface est le **mode par défaut** : `.\run.bat` (ou `python jarvis.py`)
ouvre directement la fenêtre. Pour revenir à la console : `--no-gui`.

```powershell
.\run.bat                    # fenêtre graphique (défaut)
.\run.bat --no-gui           # console vocale
.\run.bat --text             # console, clavier seul
```

Une fenêtre Tkinter (bibliothèque standard, aucune dépendance) organisée en cinq
bandes :

- un **en-tête** avec l'avatar de Jarvis, le modèle utilisé et une pastille
  d'état animée (« En attente », « Jarvis réfléchit… ») ;
- le **journal de conversation** en bulles, chacune horodatée, avec export en
  `.txt` ;
- trois **puces de suggestion** qui pré-remplissent une question type ;
- le **champ de saisie** avec un bouton *Envoyer* (actif dès qu'il y a du texte),
  un bouton *Parler* (écoute) et un bouton *Stop* (rouge pendant la réponse) ;
- une **barre d'état** rappelant le modèle, la langue, les outils et la mémoire.

Raccourcis : `Ctrl+L` efface la conversation, `Ctrl+E` l'exporte, `Ctrl+M` coupe
ou rétablit la voix, `Échap` interrompt la réflexion ou la voix. Remonter dans
l'historique met l'auto-défilement en pause (bouton **↓** pour le réactiver).
Si le modèle est injoignable (connexion coupée), Jarvis l'annonce dans la
conversation au lieu de rester bloqué.

La fenêtre ne se fige jamais : l'écoute du micro et la réflexion du modèle
tournent dans un fil séparé, l'interface reste réactive.

### Orbe flottante (recommandé)

```powershell
.\Jarvis_Orbe.bat           # double-clic : l'orbe apparaît sur le bureau
```

Une sphère toujours au premier plan, sans fenêtre ni console :

- **« Jarvis »**, tout court : l'orbe se met à écouter. Dit d'une traite,
  « Jarvis, quelle heure est-il ? » est traité directement. La détection tourne
  **entièrement sur l'ordinateur** (petit modèle Vosk dans `voices/vosk/`) :
  rien n'est envoyé tant que le mot n'est pas prononcé. Autre mot :
  `--wake ordinateur` ; `--no-wake-word` la désactive. Sans Vosk, l'orbe
  retombe sur openWakeWord (« Hey Jarvis »).
- **Briefing au lancement** : salutation selon l'heure, ton prénom et la météo
  de ta ville s'il les connaît (« je m'appelle… », « j'habite à… »), la date
  et les rappels du jour.
- **Conversation continue** : après une réponse vocale, l'orbe réécoute
  6 secondes ; enchaîne sans redire « Jarvis ». Un silence clôt l'échange
  (`--no-follow-up` pour désactiver).
- **Personnalité** : ton de majordome courtois et précis, une pointe
  d'humour pince-sans-rire ; il t'appelle par ton prénom.
- Avec la voix Piper, l'égaliseur et le cœur de l'orbe **suivent le volume
  réel de la voix**.
- **Ctrl+Espace**, depuis n'importe quelle application : parler (ou couper la
  voix pendant une réponse). Autre raccourci : `--hotkey ctrl+alt+j`.
- **Double-clic** : historique des derniers échanges.
- **Clic droit** : un panneau graphique aux couleurs du thème — mini-orbe et
  état, tuiles **Parler / Écrire / Stop / Muet**, Historique, Journal,
  interrupteurs « Écouter Jarvis » et « Conversation continue », **grille des
  28 thèmes** (survol = nom, clic = appliqué), Masquer, Quitter. **Réglages** :
  voix (essai immédiat), intro de démarrage (aperçu au clic), qualité,
  masquage auto. Tous ces choix sont retenus.
- **Intro au démarrage**, discrète, autour de l'orbe (~2,6 s) : Anneaux HUD,
  Onde, Constellation, Radar, Éclosion, Terminal, Minimal, ou Aucune ; puis
  « Tous les systèmes sont opérationnels » et le briefing.
- **Clic** : parler ; **glisser** : déplacer (position retenue).
- Sphère de verre animée (nuages de couleur, reflet, halo qui respire) dont
  la couleur suit l'état : bleu prêt, vert écoute, orange réflexion, cyan
  parole. Une bulle affiche la question et la réponse. Rendu lisse avec
  Pillow (transparence réelle sous Windows), dessin simple sinon.
- **Thème** `--orb_theme opale` (défaut, forme nacrée qui ondule) ; `jarvis` : HUD holographique — cœur lumineux,
  anneaux qui tournent, ondes à l'écoute, égaliseur quand Jarvis parle,
  panneaux bleu nuit aux coins biseautés. Formes organiques qui ondulent
  (style goutte de verre mat) : `aurore` (pastel cyan-lavande), `opale` (nacrée),
  `nebuleuse` (profonde, halo lumineux). `siri` : sphère de verre. Plus 22
  ambiances : chaudes (Soleil couchant, Lave, Or royal, Ambre, Corail, Rubis),
  fraîches (Océan, Abysse, Glacier, Menthe, Émeraude, Forêt, Minuit), néon et
  cosmos (Galaxie, Synthwave, Cyberpunk, Matrix, Toxique, Prisme) et pastels
  (Lavande, Sakura, Barbe à papa). Changement à chaud depuis le clic droit.
- **Qualité ultra** (défaut) : les thèmes organiques sont rendus en **vraie 3D sur
  la carte graphique** (OpenGL via `moderngl`) : sphère liquide éclairée,
  reflets, irisation nacrée, halo, particules, anticrénelage 4x, 40 images/s.
  Sans carte graphique compatible, repli automatique sur le rendu processeur.
  **Réglages → Qualité** pour choisir. Thème **Plasma** : sphère liquide aux
  bandes irisées qui défilent.
- **Masquage automatique** : après 1 min sans activité, l'orbe disparaît en
  fondu ; « Jarvis », Ctrl+Espace ou l'icône la font revenir (**Réglages →
  Masquage auto** : jamais, 30 s, 1 min, 5 min ; `--auto_hide SECONDES`).
- **Une orbe vivante** (thèmes organiques) : elle lévite, ses couleurs coulent,
  un reflet glisse à sa surface ; elle sursaute quand tu dis « Jarvis » ou
  cliques, grossit au survol de la souris, respire de temps en temps au repos,
  suit le volume de **ta** voix pendant l'écoute et de la sienne quand elle
  parle ; les couleurs passent d'un état à l'autre en douceur.

**Voix naturelle (Piper).** Avec `install.ps1 -Optional`, la voix neuronale
française `fr_FR-siwis-medium` est téléchargée dans `voices/` et utilisée
automatiquement, hors-ligne. Sinon Jarvis prend la voix Windows. Choix forcé :
`--tts piper|sapi|pyttsx3`, autre voix : `--piper_voice NOM`
(catalogue : <https://huggingface.co/rhasspy/piper-voices>).

**Au démarrage de Windows :**
`powershell -ExecutionPolicy Bypass -File .\autostart.ps1` installe l'orbe
dans le dossier Démarrage (`-Remove` pour la retirer).

### Interface dans le navigateur

```powershell
.\Jarvis_Navigateur.bat      # double-clic : interface web en français
.\run.bat --web              # même chose depuis la console
.\run.bat --web --port 9000  # autre port (défaut 8765)
```

Jarvis lance un petit serveur local (bibliothèque standard, aucune dépendance
en plus) et ouvre la page dans le navigateur par défaut :

- réponses affichées **en direct**, phrase par phrase, avec gras, `code` et liens ;
- **orbe animée** dont la couleur suit l'état (prêt, réflexion, parole, écoute) ;
- panneau **Mémoire** : les souvenirs de Jarvis, avec un bouton *Oublier* ;
- *Nouvelle conversation*, export `.txt`, copie d'une réponse, coupure de la
  voix, thème clair / sombre mémorisé, mise en page adaptée au téléphone ;
- mêmes raccourcis que la fenêtre (`Entrée`, `Échap`, `Ctrl+L`, `Ctrl+E`, `Ctrl+M`).

Le serveur n'écoute que sur `127.0.0.1`, vérifie l'en-tête `Host` et exige un
jeton aléatoire propre à chaque lancement : un autre site ouvert dans le
navigateur ne peut pas piloter Jarvis. Le bouton **Quitter Jarvis** arrête le
serveur. Pour en faire le mode par défaut : `web: true` dans la section
`interface` de `jarvis.yaml`, ou `JARVIS_WEB=1` dans `.env`.

Si Tkinter est absent, Jarvis repasse automatiquement en mode console. Certaines
distributions Python (par ex. Laragon) rangent Tcl/Tk dans `<python>\tcl\` au
lieu de `<python>\lib\tcl8.6` : Jarvis le détecte et pointe `TCL_LIBRARY` /
`TK_LIBRARY` au bon endroit, sans rien installer.

---

## Plugins

Dépose un fichier `.py` dans `plugins/`. Il peut exposer :

- `build_tools(ctx) -> list[BaseTool]`, ou
- `register(ctx) -> list[BaseTool]`, ou
- `TOOLS = [...]`.

`ctx` donne accès à la langue, aux chaînes traduites, à la mémoire et à la
synthèse vocale. Un plugin qui échoue est signalé mais **ne bloque jamais**
Jarvis. Exemple fourni : `plugins/system_info.py`. Options : `--plugins_dir`,
`--no-plugins`.

---

## Démarrage automatique

```powershell
powershell -ExecutionPolicy Bypass -File .\autostart.ps1            # mode texte
powershell -ExecutionPolicy Bypass -File .\autostart.ps1 -Gui       # fenêtre
powershell -ExecutionPolicy Bypass -File .\autostart.ps1 -Remove    # retirer
```

Un raccourci est placé dans le dossier « Démarrage » de la session.

---

## Créer un exécutable

```powershell
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1 -OneFile
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1 -Windowed
```

Produit `dist\Jarvis\` (ou un seul `.exe` avec `-OneFile`) via PyInstaller.
L'exécutable ouvre la fenêtre graphique par défaut ; `-Windowed` masque la
console, utile si tu ne veux que la fenêtre. Place un fichier `.env` à côté de
l'exécutable : la clé API n'est jamais embarquée dans le binaire.

> La fabrication d'un exécutable tiers est **optionnelle**. Les bibliothèques
> LangChain/LangGraph étant volumineuses, le résultat pèse plusieurs centaines
> de Mo et le démarrage peut être lent ; pour un usage personnel, `run.bat` est
> plus simple.

---

## Toutes les options

| Option | Effet |
| --- | --- |
| `--lang {en,fr}` | Langue (prompt, voix, reconnaissance). |
| `--voice ID` | Voix TTS (voir `--list_voices`). |
| `--rate N` / `--volume 0..1` | Vitesse et volume de la voix. |
| `--max_speak S` | Coupe la synthèse au-delà de S secondes (0 = off). |
| `--wake MOTS` / `--no-wake` | Mots d'activation (séparés par des virgules). |
| `--no-bargein` | Interdit de couper la parole à Jarvis. |
| `--vad` | Fin de phrase par détection de voix. |
| `--ptt` | Appuyer sur Entrée avant chaque question. |
| `--resume` | Reprend l'historique au lieu de saluer. |
| `--text` | Mode clavier (ni micro ni synthèse). |
| `--max_words N` | Longueur maximale des réponses. |
| `--ability TEXTE` | Rôle donné à Jarvis (ex. « un professeur de maths »). |
| `--retries N` | Tentatives sur le modèle. |
| `--phrase_limit S` | Délai maximal d'écoute par phrase. |
| `--api_key`, `--model`, `--base_url`, `--temperature` | Fournisseur et modèle. |
| `--local_model`, `--local_base_url` | Repli hors-ligne (Ollama). |
| `--no-fallback` | Désactive la bascule automatique vers le local. |
| `--no-memory`, `--memory_path` | Mémoire longue durée. |
| `--no-tools` | Désactive les outils. |
| `--plugins`, `--no-plugins`, `--plugins_dir` | Plugins. |
| `--history_path` | Fichier d'historique JSON. |
| `--gui` / `--no-gui` | Fenêtre graphique (défaut) ou console. |
| `--web`, `--port N` | Interface dans le navigateur (port local, défaut 8765). |
| `--orb` | Orbe flottante sur le bureau. |
| `--no-wake-word` | Orbe : désactive l'écoute locale de « Jarvis ». |
| `--hotkey COMBO` | Raccourci global pour parler (défaut `ctrl+space`, `""` = aucun). |
| `--tts {auto,piper,sapi,pyttsx3}`, `--piper_voice NOM` | Moteur et voix de synthèse. |
| `--config CHEMIN` | Fichier de configuration. |
| `--stt {auto,google,whisper,local}`, `--whisper_model` | Reconnaissance. |
| `--list_voices`, `--test_voice` | Voix disponibles / essai. |
| `--list_tools`, `--show_config`, `--version` | Informations puis quitter. |

`--help` résume tout.

---

## Tests

Suite de tests sans dépendance externe (pas de `pytest` requis) :

```powershell
.venv\Scripts\python.exe tests\run_tests.py
```

---

## Crédits

Projet basé sur les travaux de @ShaunLinTW
(<https://github.com/ShaunLinTW/Voice_Assistant_Jarvis_Based_on_ChatGPT_API>),
à l'origine du dépôt `meirm/jarvis`.

## Contribution

Les contributions sont bienvenues : ouvre une *issue* ou une *pull request*.

## Licence

MIT — voir le fichier `LICENSE`.
