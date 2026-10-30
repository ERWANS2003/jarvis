# Jarvis — version MVP

Un assistant vocal qui écoute, comprend, agit et répond à voix haute, en moins de quelques
secondes, et qui s'améliore à partir des réactions de son utilisateur.

## Lancer

Double-clic sur `Jarvis_MVP.bat`. Il installe ce qui manque au premier lancement (Python 3.11
recommandé), crée `.env` si besoin, vérifie tout (`verifier_mvp.py`), puis fait apparaître l'orbe.

Il faut une clé dans `.env` : `GROQ_API_KEY` (gratuite, la plus rapide, <https://console.groq.com/keys>)
ou `OPENROUTER_API_KEY`. `.env` n'est jamais versionné.

## Périmètre

| Dans le MVP | Présent dans le code, désactivé ici |
| --- | --- |
| Écoute : mot d'activation « Jarvis » local, reconnaissance vocale, interruption | Ranger le bureau |
| Réponse parlée phrase par phrase | Fermer ou réduire toutes les fenêtres |
| Commandes instantanées sans modèle : heure, calcul, unités, minuteurs, listes | Accès depuis le téléphone |
| Agent avec outils : météo, recherche web, Wikipédia, rappels, sites, musique | Alertes spontanées (batterie, pluie) |
| Mémoire longue durée (SQLite) | Vision de l'écran |
| Bascule automatique entre modèles | Plugins |
| Orbe animée, avec ses états | |
| Auto-amélioration : mesures, leçons, bilan | |

La démonstration utilise sa propre mémoire (`.jarvis_mvp_memory.db`) : aucun souvenir personnel
n'apparaît devant la salle.

## Scénario de démonstration (5 minutes)

| Dire | Ce que ça montre |
| --- | --- |
| « Jarvis » | Détection locale : rien ne part sur Internet avant le mot |
| « Quelle heure est-il ? » | Commande instantanée, sans modèle |
| « Combien font 18 500 fois 3,5 ? » | Calcul exact, sans modèle |
| « Quel temps fait-il à Paris ? » | Donnée réelle, en direct |
| « Souviens-toi que je préfère le thé » puis « Que sais-tu de moi ? » | Mémoire longue durée |
| « Explique-moi comment marche une pompe à chaleur » | Modèle de langage, voix en continu |
| Parler pendant sa réponse | Interruption |
| « C'est trop long » | Réaction enregistrée |
| « À l'avenir, réponds sans préambule » puis « Qu'as-tu appris ? » | Leçon dictée, appliquée aux tours suivants |
| « Fais ton bilan » | Chiffres de l'auto-amélioration |
| « Range mon bureau » | Garde-fou de la version de présentation |

## Plan de secours

- **Micro capricieux** : clic sur l'orbe pour parler sans le mot d'activation, ou clic droit, *Écrire*.
- **Devises** : à éviter en démonstration, elles dépendent d'un service externe qui peut refuser la connexion.
- **Pas d'Internet** : les commandes instantanées marchent encore ; le reste passe par `JARVIS_LOCAL_MODEL` si Ollama est installé.
- **Quota épuisé** : Jarvis bascule seul sur un autre modèle.
- **Tout en panne** : la vidéo de secours de la démonstration, à enregistrer avant le jour J.

## Vérifier

```powershell
.venv\Scripts\python.exe verifier_mvp.py
.venv\Scripts\python.exe tests\run_tests.py
```
