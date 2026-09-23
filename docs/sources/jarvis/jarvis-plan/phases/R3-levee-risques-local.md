> Fichier de phase du projet JARVIS. Lire d'abord `PLAN.md` (règles, principes) et `CLAUDE.md`. Références techniques : `docs/reference.md`.

# Phase R3 — Levée de risques du mode confidentiel (avant la Phase 13)

**But** : vérifier sur **votre machine** qu'une version 100 % locale est utilisable avant de la construire. Mêmes règles que R1/R2 : **boîte de temps de 4 soirées**, scripts jetables dans `spikes/r3/`, résultats dans `RISKS.md`, `PLAN.md` et `phases/13-mode-confidentiel.md` mis à jour avant la Phase 13.

**Prérequis** : noter dans `RISKS.md` la machine de test (GPU et mémoire vidéo, ou Mac et mémoire unifiée, RAM, OS). Tous les chiffres n'ont de sens que pour cette machine.

| # | Hypothèse testée | Test | Passe si | Plan B si échec |
|---|---|---|---|---|
| S12 | La chaîne locale est assez rapide en français | Kyutai STT 1B (`stt-1b-en_fr`) → LLM local (serveur compatible OpenAI : llama.cpp, Ollama ou vLLM) → Qwen3-TTS en flux ; 20 tours en français ; mesurer fin de parole → premier son | p50 < 1 200 ms, p95 < 2 000 ms ; compréhension et voix françaises jugées correctes | LLM plus petit (Gemma 4 12B) ; TTS plus léger (Qwen3-TTS 0.6B) ; démarrer la voix dès la première phrase générée ; en dernier recours, mode « appuyer pour parler » |
| S13 | L'interruption (barge-in) fonctionne en local | Parler pendant que JARVIS répond, 10 fois | Arrêt de la voix < 300 ms, génération annulée, pas d'auto-interruption avec l'annulation d'écho du navigateur | Seuil de détection relevé pendant la parole de JARVIS ; appuyer pour interrompre |
| S14 | Le LLM local choisit bien les outils | Les mêmes 10 phrases que S4, avec les ~20 outils voix | ≥ 8/10 bons choix, arguments valides | Sortie contrainte par grammaire JSON (llama.cpp / vLLM) ; moins d'outils exposés ; méta-outil par domaine |
| S15 | Un « NotebookLM open source » couvre l'essentiel, hors ligne | Tester **Open Notebook** (`lfnovo/open-notebook`, MIT) puis **SurfSense** avec le même protocole : API REST pour lister, interroger avec citations, ajouter une source (PDF, URL, texte), notes, podcast ; modèles locaux uniquement ; documents français ; 10 questions de référence | Au moins l'un des deux réussit toutes les opérations hors ligne et répond correctement avec citations à ≥ 8/10 questions ; retenir le meilleur | Mini-RAG maison (SQLite + embeddings locaux) pour les questions ; podcasts via `podcastfy` + Qwen3-TTS ; fonctions non couvertes masquées en mode confidentiel |
| S16 | Un solveur local écrit des leçons de tableau valides | Les 10 problèmes de S7 avec le meilleur LLM local | ≥ 6/10 leçons validées (après au plus 2 corrections) | Tableau limité à l'algèbre et aux fonctions en mode confidentiel ; bibliothèque de leçons vérifiées ; mode hybride (solveur cloud sur accord explicite, énoncé seul) |
| S17 | L'étanchéité réseau est vérifiable | Scénario complet en mode confidentiel avec surveillance des connexions (test Python qui intercepte les sockets + outil système type `ss`/`lsof`/`nettop`) | **Zéro** connexion hors de `127.0.0.1` | Aucun : critère obligatoire. Corriger jusqu'à ce qu'il passe. |
| S18 | Vision locale du tableau (optionnel) | Gemma 4 multimodal lit 10 images du tableau (figures, écriture au stylet) | Description correcte ≥ 7/10 | En mode confidentiel, Gemini « voit » seulement l'état textuel du tableau ; l'écriture au stylet n'est pas commentée |

**Décision de fin de R3** :
- **Tout passe** → Phase 13 telle quelle.
- **Plans B appliqués** → réduire le périmètre du mode confidentiel dans `phases/13-mode-confidentiel.md` (fonctions masquées, tableau limité, appuyer pour parler…), et l'afficher clairement dans l'UI.
- **S12 ou S15 en échec sans plan B satisfaisant sur cette machine** → le mode confidentiel est reporté (matériel insuffisant) ; noter la configuration minimale estimée dans `RISKS.md`.

**Terminé quand** : `RISKS.md` rempli pour S12 à S18, modèles locaux choisis et notés, décision prise, fichiers de plan mis à jour.
