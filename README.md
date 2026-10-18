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
JARVIS_MODEL=nvidia/nemotron-3-super-120b-a12b:free
```

`.env` n'est jamais versionné. Tout ce qui n'est pas écrit dans `.env` prend sa
valeur par défaut, dans le fichier de configuration, ou sur la ligne de commande.

---

## Démarrage rapide

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
épuisé, réseau coupé), Jarvis bascule automatiquement vers le modèle local s'il
est configuré (voir [Mode local](#mode-local--hors-ligne)) ; `--no-fallback`
désactive cette bascule.

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
| `remember_fact` / `recall_memory` / `forget_memory` | Mémoire longue durée. |

Les outils réseau sont **sans clé**. `--no-tools` revient à un simple dialogue.
`--list_tools` affiche ce qui est chargé.

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
`JARVIS_LOCAL_BASE_URL`, `JARVIS_PLUGINS_DIR`, `JARVIS_GUI`.

---

## Interface graphique

L'interface est le **mode par défaut** : `.\run.bat` (ou `python jarvis.py`)
ouvre directement la fenêtre. Pour revenir à la console : `--no-gui`.

```powershell
.\run.bat                    # fenêtre graphique (défaut)
.\run.bat --no-gui           # console vocale
.\run.bat --text             # console, clavier seul
```

Une fenêtre Tkinter (bibliothèque standard, aucune dépendance) avec une pastille
d'état, le journal de conversation en bulles, un champ de saisie, un bouton
**Parler** (écoute) et un bouton **Stop** (interrompt la voix). Le menu
*Fichier* permet d'effacer, d'exporter la conversation en `.txt` ou de quitter ;
le menu *Aide* rappelle la version et le modèle utilisés. `Ctrl+L` efface la
conversation, `Échap` arrête la voix.

La fenêtre ne se fige jamais : l'écoute du micro et la réflexion du modèle
tournent dans un fil séparé, l'interface reste réactive.

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
