# Plan — Free AI Studio

Le seul fil de ce qui reste à faire, dans quel ordre, et de ce qui est gelé.
`AGENTS.md` dit **comment** travailler ; ce fichier dit **où on en est**.

Source : l'audit externe du 11/09/2026, copié tel quel dans
[`docs/audits/AUDIT-2026-09-11.md`](docs/audits/AUDIT-2026-09-11.md). Ce plan ne le
recopie pas : il dit ce qui en est fait, avec quelle preuve, ce que les sources
officielles ont contredit, et ce qui reste. Travail mené sur la branche
`audit-20260911`.

## Où en est le plan — 11/09/2026

| Tâche | État | Preuve | Ce qui manque |
|---|---|---|---|
| **P0-1** Quota Gemini, bascule annoncée | **fait ; en réel, seul le régime sans refus est vérifié** | essai du 11/09 : 65 messages à `gemini-3.5-flash-lite`, aucun refus de Google, aucun recours à OpenRouter (§ P0-1) ; bascule, pauses et refus vérifiés hors réseau par `tests/test_quotas.py`, 20 tests après `f9d5c91` | une **bascule réelle** (aucun refus en 65 messages) ; le rendu de l'avis dans Open WebUI ; les installations existantes gardent `gemini-3.8-flash` si leur `.env` le fixe |
| **P0-2** Modal : carte, crédit, plafond | **fait** | README, `.env.example`, page `/video`, `docs/MODAL_CATALOG.md`, `docs/SERVICES_DEBUTANT.md` ; nombre de clips recalculé avec la règle du code | le palier Modal ne peut pas être **détecté** (aucune API de crédit lue) : il est affiché comme une déclaration |
| **P0-3** « open source » / « gratuit » | **fait dans le dépôt** | README, section « Ce qui est ouvert, ce qui ne l'est pas » ; licence et territoire affichés à côté du choix sur `/video` ; règle de vocabulaire dans `AGENTS.md` | documents de présentation hors dépôt : non touchés |
| **P1-1** CI | **fait, critère vérifié en local** | une faute dans une copie de `video.py` fait échouer la CI (§ P1-1) | premier passage réel le 11/09 (run `34610911922`) : **échec** à « Docker Compose config », `.env` absent sur le runner. `main` échoue de la même façon depuis au moins le 09/09 (run `34394306955`) : le vrai `.env` masquait le défaut en local. Correction : la CI pose une copie de `.env.example`. **Vert sur GitHub** après correction : commit `41cdd9a`, run `34611618281`, toutes les étapes |
| **P1-2** Kaggle | **fait** | `tests/test_kaggle.py`, 8 tests ; conditions de Kaggle lues ; option (b) appliquée le 11/09 : en `auto`, Kaggle ne reçoit que les jobs `gpu=true` (étape 4) | aucun job réel envoyé à Kaggle depuis le changement |
| **P2** Périmètre | **commencé** | pastilles « expérimental » sur `/studio` (Voix, Vidéo, Étudier, Code, Sandbox) | parcours complet sur une machine vierge avec une vraie personne ; l'indicateur |
| **P2** Registre | **non commencé** | — | tout (étape 6) |
| Hors audit : **Free AI Max**, deuxième choix du chat | **fait et en service** (commit `9b5be4d`, reconstruit le 11/09) | décision de l'utilisateur le 11/09 ; `gemini-3.8-flash` en tête, puis la chaîne d'Auto ; quota et pause à part ; `tests/test_quotas.py` (4 tests de plus, 17 au total) ; essai réel dans le conteneur reconstruit le 11/09 : `/v1/models` propose les deux choix, une demande Max en flux servie par `gemini-3.8-flash` (1,4 s), une demande Auto par `gemini-3.5-flash-lite` (0,8 s) ; le sélecteur d'Open WebUI liste Free AI Auto et Free AI Max | bascule de Max vers Flash-Lite vérifiée seulement par les tests ; aucune demande envoyée depuis Open WebUI même ; « Arena Model », fourni par Open WebUI, est retiré du sélecteur depuis le 11/09 : variable `ENABLE_EVALUATION_ARENA_MODELS=false` pour une installation neuve, API d'administration une fois pour une installation existante (`tests/test_reglages_webui.py`, 3 tests) |
| Hors audit : **revue du 11/09**, cinq défauts de P0-1 | **corrigé** (commit `f9d5c91`) | l'avis vaut pour toute pause, y compris survenue pendant une demande Max ; 429 en français dès le premier refus avec une seule clé ; 5xx et coupures : pause courte et avis ; `ENABLE_GEMINI_MAX=false` respecté avec une clé saisie dans /cles ; messages « sans clé » et « fausse clé » en français ; 8 tests, qui échouent tous sur `80bcfee` | voir « Parcours débutant sur une machine vierge » |
| Hors audit : `/studio` sans JavaScript | **corrigé** | `scripts/verifier-js.py`, ajouté à la CI | vue dans Chrome (service d'essai, 0 erreur console) ; conteneurs reconstruits depuis `dcc742d` |

Le dernier point a été trouvé en vérifiant P0-1. Depuis le commit `ed3e71d`, un `\n` mal échappé dans la chaîne Python de la page `/studio` cassait **tout** son script dans le navigateur. Les effets : état des clés absent, bouton « Mettre à jour » inerte, et le bandeau des quotas n'aurait jamais paru. Ni `py_compile`, ni ruff, ni le test d'import ne pouvaient le voir ; `node --check` le voit.

## Règles qui tiennent pendant tout le plan

- **Gel des fonctions.** Aucune nouvelle fonction tant que P0-1 et P0-2 ne sont pas vérifiés **en réel**. Aujourd'hui, ils ne sont vérifiés que hors réseau. Seule exception, levée par l'utilisateur le 11/09/2026 : Free AI Max. Sur les fiches de Google, Flash-Lite est nettement en dessous de 3.8 Flash (Terminal-bench 2.1 : 54,0 % contre 89,4 %), et les deux quotas sont distincts. Deuxième exception, levée par l'utilisateur le 15/09/2026 (« fais tout ça ») : les dessins SVG montrés sous la réponse du chat et téléchargeables. Troisième exception, levée par l'utilisateur le 15/09/2026 (« laisse les deux options local amélioré et groq si dispo ») : la dictée, par Groq quand sa clé est branchée, sinon par un Whisper local plus gros et en français. Quatrième exception, levée par l'utilisateur le 15/09/2026 (« rajoute dans kaggle et/ou modal un text to sing […] accéssible depuis l'ui front end », puis « colab aussi ») : la chanson, par YuE2-3B. Cinquième exception, levée par l'utilisateur le 15/09/2026 (« le tts en français est effectivement avec l'accent anglais, faire mieux !! ») : la lecture à haute voix par une voix française, Piper, sur l'ordinateur.
- P0 avant P1, P1 avant P2.
- Source officielle d'abord. Si elle contredit l'audit, elle gagne, et l'écart s'écrit ci-dessous.
- Rien de payant en secours, jamais. `ALLOW_PAID_MODELS=false` ne s'assouplit pas.
- Un « fait » cite sa preuve ; sans preuve, c'est « non vérifié ».

## Écarts entre l'audit et les sources officielles (relevé du 11/09/2026)

| L'audit dit | La source dit | Conséquence |
|---|---|---|
| Gemini Flash : 20 demandes par jour ; Flash-Lite : 500 | La [page des limites](https://ai.google.dev/gemini-api/docs/rate-limits) ne publie **aucun chiffre**. Elle renvoie à AI Studio et précise que les limites valent par projet et par modèle, avec une remise à zéro à minuit, heure du Pacifique. Le « 500 par jour » est la ligne « ancrage Google Search » de la [page des prix](https://ai.google.dev/gemini-api/docs/pricing). | Le défaut passe quand même à `gemini-3.5-flash-lite` : c'est la variante d'usage courant, gratuite et stable ([modèles](https://ai.google.dev/gemini-api/docs/models)). Aucun chiffre n'est codé en dur : le Studio lit la limite que Google écrit dans son refus. |
| Modal : 5 $ par mois sans carte, 30 $ avec | 30 $ par mois de crédit sur l'offre Starter ([pricing](https://modal.com/pricing)). Un moyen de paiement est **exigé** ([billing](https://modal.com/docs/guide/billing)). Aucun palier sans carte n'apparaît. Au-delà du crédit, Modal facture jusqu'à la limite de dépense, qui vaut par défaut la limite d'usage moins le crédit ([budgets](https://modal.com/docs/guide/budgets)). | La « cinquantaine de clips sans carte » est sans objet. Le plafond vidéo reste à 20 $. Le vrai risque est la facture au-delà du crédit : partout où « 30 $ » apparaît, la carte et la limite de dépense sont dites. |
| Critère P0-2 : le budget vidéo ne dépasse pas le crédit d'un compte sans carte | Un compte sans carte ne peut pas utiliser Modal | Critère appliqué sous cette forme : aucune page n'annonce 30 $ sans la carte, et le plafond (20 $) reste sous le crédit (30 $). |
| Kaggle : conditions à vérifier | [Conditions](https://www.kaggle.com/terms) du 22/06/2025 : usage personnel, jamais pour des tiers, compte non partageable. [Politique d'usage](https://www.kaggle.com/aup) : pas d'activité étrangère à la science des données. [CLI](https://github.com/Kaggle/kaggle-cli/blob/main/docs/kernels.md) : `kernels push` est documenté. | La garde est confirmée par les conditions. La politique d'usage ouvre une question (étape 4). |
| Mode Découverte, Registry et scan Hugging Face ne se trouvent que dans `AGENTS.md` | Une recherche dans le dépôt, le 11/09, ne les trouve nulle part, pas même dans `AGENTS.md` | « Zéro ligne d'implémentation » tient. La mention dans `AGENTS.md` n'existe pas, ou plus. |

## Prochaines étapes, dans l'ordre

1. ~~**Vérifier P0-1 en réel.**~~ Fait le 11/09 : 65 messages sur 65 servis par Gemini (§ P0-1). Il reste à observer une **bascule réelle**. Elle viendra d'elle-même le jour où Google refusera ; ne pas brûler le quota d'OpenRouter pour la provoquer, cela n'apprend rien que les tests ne montrent déjà. Ce jour-là, relever la limite écrite par Google dans son refus et la reporter, datée, dans `docs/FREE_TIER_MANAGER.md`.
2. ~~**Reconstruire les conteneurs et regarder les pages**~~ **Fait le 11/09/2026.** Commit `dcc742d` sur `audit-20260911`, puis `docker compose up -d --build` : les 4 conteneurs sont en bonne santé. Contrôles sur les conteneurs reconstruits :
   - le routeur annonce la version `dcc742d` ;
   - le bloc `quotas` est présent dans `/diagnostic/etat` ;
   - Gemini (`gemini-3.5-flash-lite`), OpenRouter et Groq sont éligibles ;
   - la garde Kaggle dit permis depuis localhost et coupé par 192.168.1.20 ;
   - une demande de chat : HTTP 200, servie par Gemini, `x-free-ai-secours: non`.

   Les pages ont été vues dans Chrome sur le service d'essai hors conteneur, avec le même code. **Reste non vérifié** : une vraie bascule, et son avis tel qu'Open WebUI l'affiche.
3. ~~**Pousser la branche**~~ Poussée le 11/09, à la demande de l'utilisateur. Premier passage de GitHub Actions (run `34610911922`) : toutes les étapes passent sauf la dernière, « Docker Compose config », qui échoue. Le compose lit `.env` (`env_file`), qui n'est jamais dans le dépôt. `main` échoue de la même façon depuis au moins le 09/09 (run `34394306955`). Correction : la CI pose une copie de `.env.example`, sans secret, avant `docker compose config`. Rejouée en local sur une copie des seuls fichiers suivis, donc sans `.env` : code 1 avant, code 0 après. **Sur GitHub, après correction : vert**, commit `41cdd9a`, run `34611618281`, toutes les étapes en 23 s. Seul avertissement : Node.js 20 déprécié pour `checkout@v4`, `setup-node@v4` et `setup-python@v5`, que le runner force déjà en Node.js 24. `main` est resté rouge jusqu'au 13/09 : ce jour-là, à la demande de l'utilisateur, `main` a été avancé sur `6a934cc` (avance rapide, 8 commits, aucun conflit). Run `34750617340` : vert, toutes les étapes en 27 s.
   Après la reconstruction du Studio de l'utilisateur sur `41cdd9a` : l'auto-test rend le code 0 ; « Arena Model » est absent du chat, retiré par le chemin « installation existante » (témoin posé à 14:42:02) ; Free AI Auto et Free AI Max sont proposés ; gemini, gemini_max, openrouter et groq sont éligibles. Une question réelle par choix, en direct au routeur : Auto servi par gemini (HTTP 200, 1,0 s), Max par gemini_max (HTTP 200, 1,5 s), `x-free-ai-secours: non` pour les deux.
4. **Kaggle et la politique d'usage : décision humaine.** Même sur la machine de la personne, le mode `auto` peut envoyer sur Kaggle un code quelconque. Trois choix :
   - (a) laisser tel quel, avec l'avertissement de `docs/GPU_CLOUD.md` ;
   - (b) ne proposer Kaggle en `auto` qu'aux jobs `gpu=true` ;
   - (c) retirer Kaggle du mode `auto` et ne garder que le lien manuel.

   Recommandation : (b). Le coût est faible, et un job GPU relève presque toujours du calcul d'apprentissage. **Décision de l'utilisateur, 11/09/2026 : (b). Appliquée le même jour.**
   - `run_auto` n'envoie sur Kaggle que les jobs `gpu=true`. Un job CPU passe au notebook Colab, avec `cpu_job_not_sent` dans `fallback_attempts`.
   - `/providers` le dit : `kaggle.automatic_only_for = "gpu_jobs"`.
   - `backend_automatique` n'annonce plus Kaggle : `run_auto` essaie le worker local avant lui.
   - 3 tests dans `tests/test_kaggle.py`.
5. **P2 : verrouiller Chat, Recherche et Image** sur une machine vierge, avec une personne qui n'a jamais ouvert un terminal.
   - Écrire le protocole avant la séance : une liste fixe de tâches (installer, coller la clé, poser une question, chercher sur le Web, fabriquer une image, ouvrir le diagnostic), et pour chacune une case « menée à terme sans aide ». **Écrit : `docs/ESSAI_MACHINE_NEUVE.md`.** Il était prévu le 11/09 pour une machine virtuelle Hyper-V. Le 12/09, l'utilisateur a choisi un autre ordinateur physique : plus d'ISO, de points de contrôle ni de virtualisation imbriquée, et un vrai matériel. En contrepartie, l'ordinateur n'est pas neuf : son état de départ se note avant la séance, et il n'y a qu'un essai « neuf » par machine. C'est l'utilisateur qui le joue. **Joué en partie le 13/09**, voir le dernier point. Le 13/09, `main` a été avancé sur la branche **avant** l'essai, décision de l'utilisateur. La raison : le README fait cloner `main`, qui ne contenait alors rien de l'audit. L'essai suit donc le README à la lettre et porte sur `6a934cc` ou plus récent. S'il trouve un défaut, ce défaut est déjà sur `main`, et il se corrige après.
   - Indicateur : le pourcentage de tâches menées à terme, à la place de la taille du catalogue.
   - Aucune nouvelle fonction avant un premier chiffre.
   - **Essai du 13/09/2026, joué en partie.** HP 15-da0xxx sous Windows 10 Pro 22H2 (build 19045), 32 Go, un Docker Desktop de 2023 déjà installé, virtualisation éteinte dans le BIOS. Tâche 1 bloquée au geste 1 : virtualisation rallumée dans le BIOS, avec aide. Tâches 2 et 5 faussées : un `.env` recopié d'un autre ordinateur. Grille non remplie : **pas de chiffre**.
     - Défauts relevés, corrigés dans le même commit que cette note : `docker info` pris pour un moteur en marche (code 0 et sortie vide, client 23.0.5) ; version de Windows jamais vérifiée ; `/studio` ouvert avant le chat, et son état jamais relu ; conseil « magasin d'images » après un moteur arrêté ; copie du mot de passe du réglage Images jamais réparée (mesuré sur ce PC : clé gardée ≠ mot de passe interne) ; témoin des réglages posé malgré un échec.
     - Vu sur ce PC le même jour : port 3000 muet (`ERR_EMPTY_RESPONSE`) alors qu'Open WebUI était sain ; réparé par `docker compose restart open-webui`.
     - Sur l'autre ordinateur, « Image » rend du texte. Cause **non établie** : aucun appel d'image dans le journal du routeur.
     - Retour de l'utilisateur : un débutant ne doit ni ouvrir le panneau d'administration, ni penser à l'interrupteur « Image ».
   - **13-14/09, après l'essai.** Studio de ce PC reconstruit sur `6c3f7ef` : auto-test code 0. La réparation du mot de passe Images n'avait rien à réparer ici (clé déjà égale) : elle n'est vérifiée que par les tests. `main` avancé sur `6c3f7ef` à la demande de l'utilisateur, run `34782735000` vert.
   - **14/09 : bouton « Mettre à jour » inerte sur l'autre ordinateur.** Il y voyait bien `6c3f7ef`, mais le veilleur ne tournait pas, et le bouton ne faisait que renvoyer vers un double-clic. Décision de l'utilisateur : la mise à jour part du bouton, sans `.cmd`. Le veilleur tourne désormais sans fenêtre, pose un raccourci dans le dossier Démarrage de Windows, refuse de tourner en double, survit à une erreur passagère et se relance après une mise à jour qui le modifie. Défaut trouvé en passant : `demarrer.ps1` et `start.ps1` passaient son chemin sans guillemets ; depuis un dossier dont le chemin contient une espace, il ne démarrait jamais, et `demarrer.ps1` annonçait le contraire. La cause du 14/09 sur l'autre ordinateur reste **non établie** : redémarrage, fenêtre fermée ou espace dans le chemin.
     - Vérifié sur ce PC, dans une copie dont le chemin contient une espace, avec un faux `mettre-a-jour.ps1` et un faux dossier Démarrage : 7 contrôles sur 7. L'ancien appel, rejoué, ne démarre pas (code -196608). 40 tests, ruff, JavaScript des pages et imports sans erreur.
     - **Non vérifié** : un vrai redémarrage de Windows ; un antivirus devant un PowerShell sans fenêtre lancé à l'ouverture de session ; le parcours complet sur l'autre ordinateur.
     - Un Studio antérieur au 14/09 fait encore sa première mise à jour par `mettre-a-jour.cmd`, puis un `demarrer.cmd` lance le nouveau veilleur. Ensuite, le bouton suffit.
   - **15/09 : « fais moi un cube en svg » rendait une bulle vide.** Cause : l'interrupteur « Interpréteur de code » d'Open WebUI. Le modèle a écrit du Python mal fermé (`</code></thought>`), l'exécution a échoué, et la réponse est restée vide. Rejouée au routeur, la demande donne le dessin sans l'interpréteur ; avec son invite, la balise reste ouverte. Décision de l'utilisateur (« fais tout ça ») :
     - le routeur coupe l'interpréteur une fois (témoin `config/open-webui-interpreteur.json`) ; le bouton « Exécuter » d'un bloc de code reste ;
     - un refus de fournisseur écrit son motif dans le journal (300 caractères). La 400 de Gemini du 14/09 reste **inexpliquée** : son message était déjà perdu ;
     - chaque dessin SVG complet d'une réponse est rangé dans `config/dessins/` (200 au plus), montré sous la réponse, avec un lien qui enregistre le `.svg`.
     - Vérifié sur ce PC, routeur reconstruit. Interpréteur coupé au démarrage (`code_interpreter.enable = false`, `code_execution.enable = true`), puis laissé au redémarrage suivant. Au routeur, « fais moi un cube en svg » est servi par Gemini, le morceau du dessin arrive avant `[DONE]`, le fichier part en `image/svg+xml` avec `sandbox`, et en pièce jointe avec `?telecharger=1`. Dans Open WebUI, la même demande affiche la réponse, le lien « Télécharger » et le panneau d'aperçu.
     - Défaut trouvé en validant : un dessin en `width="100%"` se chargeait (150 × 150) mais s'affichait en 0 × 0 dans Open WebUI, dont le cadre prend la taille de son contenu. Le routeur lui donne désormais une taille en pixels tirée du `viewBox`. Dans la même page, un dessin en pixels s'affiche (111 × 111, largeur de la colonne). La conversion n'est vérifiée que par les tests : la réponse rejouée après la correction avait déjà sa taille en pixels.
     - 52 tests, ruff, imports, JavaScript des pages et compose sans erreur. La conversation « Cube en SVG » d'Open WebUI, sur ce PC, vient de cette vérification.
     - **Non vérifié** : le clic « Télécharger » dans un navigateur (seul l'en-tête de pièce jointe est contrôlé) ; le parcours sur l'autre ordinateur.
   - **15/09 : « speech to text très mauvais ».** Cause : Open WebUI dictait avec Whisper `base`, sans langue ; il devinait le français à 55 % et une dictée devenait « 3,4,5,5 ». Décision de l'utilisateur (« laisse les deux options local amélioré et groq si dispo », puis « un bouton de sélection : local pour confidentialité et fall back ») :
     - Open WebUI confie la dictée au routeur, une fois (témoin `config/open-webui-dictee.json`). Un autre moteur choisi ensuite dans l'administration reste en place.
     - Le routeur choisit à chaque dictée. En mode Groq : `whisper-large-v3` si la clé est branchée ; sinon, ou si Groq refuse, son propre Whisper `small`, en français, sur le processeur, sans message d'erreur.
     - La carte « Dictée » de `/studio` propose « Groq si possible » ou « Sur cet ordinateur » ; dans ce second cas, la voix ne quitte pas le PC. Le choix est rangé dans `config/dictee.json` et n'accepte que du JSON.
     - Mesure sur 4 cœurs, trois dictées de 4 à 7 s : `base` 0,5 s ; `small` 0,7 à 0,9 s et 0,95 Gio ; `large-v3-turbo` 2,6 à 3 s et 2,6 Gio. faster-whisper ajoute environ 440 Mo à l'image du routeur.
     - Vérifié sur ce PC, routeur et Open WebUI reconstruits. Au démarrage, `small` est téléchargé et Open WebUI est basculé vers le routeur. Les trois dictées du cache passent par Open WebUI :
       - mode Groq : HTTP 200, 0,4 à 0,7 s, « 3 x 5, 15 » ;
       - mode « sur cet ordinateur » : HTTP 200, 0,7 à 1,7 s, « Trois fois cinq, quinze. ».

       Le journal du routeur dit qui a transcrit chaque dictée. Un choix envoyé sans JSON est refusé (415). La page `/studio` servie contient les deux boutons. 71 tests, ruff, imports, JavaScript des pages et compose sans erreur.
     - **Non vérifié** : le repli quand Groq refuse, vérifié par les tests seulement ; le clic sur les boutons dans un navigateur ; une dictée au micro ; le parcours sur l'autre ordinateur.
   - **15/09 : la chanson** (« rajoute dans kaggle et/ou modal un text to sing », puis « colab aussi »). Modèle : YuE2-3B de m-a-p, celui du carnet Kaggle donné par l'utilisateur. Poids CC BY-NC 4.0, code Apache 2.0, anglais et chinois.
     - Page `/chanson` du Sandbox, carte « Chanson » sur `/studio`. Trois endroits : Modal (L4, pipeline officiel), Kaggle (T4, gratuit, coupé en contexte partagé) et Colab (le Studio fabrique le carnet, la personne le lance).
     - Un seul script distant. Il choisit le chemin d'après la carte : officiel quand elle calcule en bfloat16 (capacité ≥ 8.0), sinon les correctifs Turing du carnet d'AIQUEST Academy (Apache 2.0), repris et attribués.
     - Le script lit le modèle et la roue `yue2_infer` 0.1.5 à des révisions épinglées. Chaque fonction qu'il remplace a été relue dans la roue 0.1.5.
     - Compteur Modal à part, 5 $/mois : carte, processeur et mémoire, prix relevés le 15/09 sur modal.com/pricing. Refus avant de lancer si le pire cas (1 800 s de L4, 0,52 $) dépasse.
     - Compteur vidéo corrigé au passage : il ne comptait que la carte. Avec 1 cœur et 16 Gio, une seconde de L4 coûte 0,000271 $ et non 0,000222 $, soit 18 % oubliés. Il compte désormais le processeur et la mémoire, comme celui de la chanson ; les chiffres du README (clips, pire cas) sont refaits avec la règle de `budget_verifier`.
     - Quantification : non retenue. La seule que propose le dépôt officiel est fp8, pour les cartes de capacité ≥ 8.9, donc ni le T4 ni l'A10.
     - 81 tests, ruff, imports, JavaScript des pages et compose sans erreur. Ce qui est testé : les demandes bornées, le script et le carnet qui compilent, le refus du plafond, l'encaissement en cas d'échec, la garde Kaggle, `machine_shape` envoyé à Kaggle pour la seule chanson, et le jeton du fichier.
     - Vérifié en réel sur Kaggle le 15/09, services reconstruits, chanson lancée par l'utilisateur depuis la page `/chanson` :
       - `NvidiaTeslaT4` donne **2 × Tesla T4** ; chemin « correctifs Turing », float16 ;
       - une minute de chanson en 347 à 377 s de bout en bout (état relu toutes les 30 s), dont 327 s sur la machine : chargement 62 s, partition 77 s, jetons de son 73 s, flot 87 s, décodage 3,5 s ;
       - FLAC 16 bits, 48 kHz stéréo, 60,0 s, 4,9 Mo ; crête −0,5 dBFS, RMS −16,5 dBFS, aucune des 12 tranches de 5 s muette, aucun écrêtage, aucune valeur non finie ;
       - le lien du lecteur de la page sert le fichier (`audio/flac`), et le lien de téléchargement l'envoie en pièce jointe ;
       - la partition a atteint son plafond T4 de 1 200 jetons et le son la minute demandée : la chanson s'arrête là, sans fin composée.
     - Vérifié en réel sur Modal le 15/09, premier lancement (image à construire, 7 Go de modèle à télécharger), chanson lancée par l'utilisateur depuis la page, durée « 1 minute » :
       - 1 × NVIDIA L4, chemin officiel, bfloat16 ; 283,5 s de bout en bout, dont 135,5 s de script : chargement 66 s, partition 29 s (529 jetons), jetons de son 22 s (1 074), flot 6 s, décodage 8 s ;
       - FLAC 16 bits, 48 kHz stéréo, 42,96 s, 3,3 Mo ; crête −1,6 dBFS, RMS −19,3 dBFS, aucune des 9 tranches de 5 s muette (−26 à −17 dBFS, −32 sur la dernière), aucun écrêtage ;
       - 43 s et non 60 : la partition s'est terminée d'elle-même après une intro et un couplet (rien de coupé, `coupee` faux aux deux étapes) ;
       - compté par le Studio : 0,0818 $ (283,5 s au prix plein carte + processeur + mémoire, attente comprise) ; reste 4,92 $ sur 5 ;
       - le lien du lecteur sert le fichier (`audio/flac`), le lien de téléchargement l'envoie en pièce jointe.
     - **Non vérifié** : l'écoute (le niveau prouve qu'il y a du son, pas que la chanson est juste) ; la facture réelle de Modal (seul le compteur du Studio est relu) ; le temps d'un deuxième lancement Modal, image et modèle en cache ; Colab ; les durées de 2 et 3 minutes.
     - **Vérifié le 16/09 : une chanson de 2 minutes sur Modal.** Travail `4738a60c`, carte L4, réussi (`exit_code` 0, aucun dépassement) : **152,7 s** de bout en bout pour **120,0 s** de chant. Étapes : modèle prêt en **11 s** — le disque persistant avait bien gardé les 7 Go —, partition 38,8 s, jetons de son 60,3 s, flot acoustique 21,6 s, décodage 8,3 s, `secondes_calcul` 144,5. Trois artefacts : `chanson.flac` (11 980 487 octets), `partition.abc`, `resume.json`. Coût compté **0,044 $** ; compteur du mois à 0,1258 $ pour 2 chansons, reste 4,87 $ sur 5 $. Le rapport mesuré est d'environ **1,25 s de machine par seconde de chant**, pas 6,6 comme le laissait craindre l'extrapolation du 15/09 : ce premier essai-là payait le téléchargement du modèle.
       - **Pour 3 minutes** : `coupee.son` vaut `true`, les 3 000 jetons de son ont été atteints — la chanson s'arrête au plafond de durée, pas à sa fin naturelle. À ce rythme, 4 500 jetons (3 minutes) restent largement sous le plafond dur de 1 800 s.
       - **Toujours non vérifié** : l'écoute (le fichier a été lu trois fois depuis la page, le jugement reste celui de l'utilisateur) ; la facture réelle de Modal ; **la libération de la machine côté Modal** — le Studio demande l'arrêt dans un `finally`, mais ce code avale une erreur d'arrêt sans la journaliser, donc seul `modal.com/apps` fait foi ; Colab.
       - **Le stockage ne coûte rien aujourd'hui, et aucun compteur ne le surveille.** Page Storage de Modal le 16/09 : le volume `free-ai-studio-modeles` pèse **17,7 Gio** (19,2 Gio en tout avec `qwen38-codegen-lora-results`, 1,4 Gio, qui vient d'un autre projet et non du Studio). Ce volume est partagé par la vidéo et la chanson — `video.py` et `chanson.py` lisent le même nom — ce qui explique le modèle prêt en 11 s. Tarif relevé sur `modal.com/pricing` le 16/09 : **0,09 $ par Gio et par mois, 1 Tio par mois offert**, donc rien n'est facturé à cette taille. Mais les compteurs du Studio (vidéo, chanson) ne comptent **que** la carte, le processeur et la mémoire : si ces volumes franchissaient un jour le tébioctet offert, aucun garde-fou du Studio ne le verrait.
   - **15/09, « kaggle est ok , tu arrète le notebook ».** Chaque notebook Kaggle part désormais avec un délai que Kaggle applique lui-même : `kaggle kernels push -t`, « Limit the run time of a kernel to the given number of seconds » selon l'aide de la CLI 2.2.4. C'est 3 600 s par défaut, 5 400 s pour une chanson. Le Studio attend 15 minutes de plus, puis abandonne.
     - L'annulation directe n'est pas retenue. La CLI 2.2.4 n'a pas de commande pour ça. L'API (`cancel_kernel_session`, kagglesdk 0.1.37) demande un numéro de session qu'aucune réponse de l'envoi ni de l'état ne donne.
     - **Non vérifié** : l'arrêt réel par Kaggle à l'échéance ; si l'attente en file compte dans le délai.
     - **Vérifié le 16/09** : un travail lancé depuis la page Sandbox (`4734fa7a`, sans GPU) est allé au bout — noyau poussé, statut Kaggle `complete`, 34 s de bout en bout, deux artefacts récupérés (journal et `preuve.txt`), et le script y a constaté le réseau coupé (`reseau : bloque (TimeoutError)`). Cet essai ne met pas l'échéance à l'épreuve : 34 s pour un délai de 3 600 s.
     - **Vérifié le 16/09 : Kaggle arrête bien le notebook à l'échéance.** Délai abaissé à 60 s (`KAGGLE_JOB_TIMEOUT_SECONDS`, service recréé, valeur en vigueur contrôlée dans le conteneur avant le lancement), puis un travail sans carte graphique demandant 900 s d'attente (`time.sleep(900)`), lancé depuis `/essai` en choisissant **Kaggle** explicitement — « auto » ne va jamais à Kaggle pour un travail sans carte, il part sur Modal. Kaggle a coupé : travail `b01c67e1d2eb` en échec au bout de **95 s** de bout en bout (créé 1789545894,5 ; fini 1789545989,7), statut Kaggle `cancel_acknowledged`, message « Délai de 60 s dépassé ». Le `-t` de `kaggle kernels push` fait donc ce que l'aide de la CLI annonce.
       - **Toujours non vérifié : si l'attente en file compte dans le délai.** Le journal du carnet récupéré chez Kaggle est vide (`[]`, 2 octets) : le code d'essai n'imprimait rien avant de dormir, donc rien ne distingue « coupé pendant l'exécution » de « annulé avant d'avoir démarré ». Un second essai avec un `print(..., flush=True)` en première ligne trancherait.
   - **15/09 : la lecture à haute voix en français** (« le tts en français est effectivement avec l'accent anglais, faire mieux !! »).
     - Cause, relevée dans le code d'Open WebUI 0.11.3 : moteur vide, donc voix du navigateur. Open WebUI cherche une voix nommée comme son réglage (`alloy`, qu'aucun navigateur n'a) et ne donne jamais la langue du texte. Le navigateur lit alors avec sa voix par défaut, anglaise.
     - Correction : le routeur lit lui-même, route `/v1/audio/speech` au format OpenAI, avec Piper 1.8.0 (GPL-3.0-or-later) et la voix `fr_FR-siwis-medium` (base SIWIS, CC BY 4.0). La voix est lue à une révision fixe du dépôt `rhasspy/piper-voices`, avec son empreinte SHA-256 vérifiée. Open WebUI lui confie son 🔊 une fois, comme la dictée, avec un témoin `config/open-webui-voix.json` ; un autre moteur choisi dans l'administration reste.
     - Essai dans un conteneur `python:3.12-slim` jetable, 4 cœurs, sans carte graphique : empreinte conforme, chargement 1,7 s, 2,8 s de parole en 0,31 s et 7,2 s en 0,60 s, 313 Mo de mémoire. espeak-ng est dans la roue : aucun paquet système à ajouter.
     - **Vérifié le 16/09** sur la machine de l'utilisateur (« ça fonctionne ici ») : routeur reconstruit, les deux voix téléchargées (`Voix prete` × 2), et le 🔊 du chat appelé pour de vrai — six lectures de 14 à 93 caractères, aucune en échec, dont une phrase mixte lue `fr,en`. L'écoute, elle, reste le jugement de l'utilisateur.
   - **15/09 : la dictée reconnaît la langue** (« il fonctionne en français mais plus en anglais :! il traduit tu n'a pas un speech to text multilingue ? »).
     - Cause : Open WebUI envoie toujours `language=fr` (son `WHISPER_LANGUAGE`), et le routeur le suivait, ou prenait `fr` par défaut. Forcé en français, Whisper traduisait une dictée en anglais. Journal du routeur : les trois dictées de l'utilisateur sont passées par Groq, `whisper-large-v3`.
     - Correction : le routeur ignore la langue d'Open WebUI ; `DICTEE_LANGUE=auto` par défaut, ou un code pour l'imposer. Sur le Whisper de l'ordinateur, la langue reconnue doit être dans `DICTEE_LANGUES` (fr,en), sinon la plus probable de la liste est retenue.
     - **Non vérifié** : le routeur reconstruit, une dictée réelle en anglais et en français.
     - **Vérifié le 16/09** sur la machine de l'utilisateur : le routeur reconstruit porte le nouveau code, aucune langue n'est imposée, les dictées passent par Groq en 200. La lecture à haute voix, elle, n'a encore jamais été appelée (zéro `/v1/audio/speech` dans le journal).
   - **16/09 : un signe de vie daté du futur faisait croire le veilleur mort.** `veilleuse_vivante` exigeait un âge positif. Le veilleur écrit depuis Windows, le routeur lit l'heure de Docker : quelques secondes d'écart, surtout après une mise en veille, et le bouton « Mettre à jour » renvoyait vers `demarrer.cmd` pour rien. Désormais une avance de moins de deux minutes compte comme vivante. Trouvé par un échec de test isolé, reproduit en datant le fichier du futur (`tests/test_maj.py`).
   - **16/09 : une voix par langue pour la lecture à haute voix.** La voix française lisait l'anglais avec l'accent français. Le routeur coupe le texte en phrases, reconnaît le français ou l'anglais aux mots les plus courants et aux accents, recolle les phrases voisines de même langue, et lit chaque bloc avec sa voix ; les deux sonnent à 22 050 Hz mono, donc les morceaux se collent sans conversion. Voix anglaise `en_US-norman-medium` : enregistrements LibriVox, **domaine public**, entraînée de zéro — les autres voix anglaises de Piper sont soit dérivées de `lessac` (licence Blizzard 2013, restrictive), soit non commerciales (`hfc_female`, CC BY-NC-SA). 63,5 Mo de plus, téléchargés une fois, empreinte SHA-256 vérifiée. **Vérifié le 16/09 en réel** : voix anglaise téléchargée à 07 h 15 (63 531 379 octets), et le routeur a lu une réponse mixte en annonçant `Piper (fr,en)`. **Non vérifié** : l'écoute (est-ce que l'anglais sonne juste), et le découpage sur des réponses longues.
   - **16/09 : le diagnostic parle du choix fait dans le chat.** Les deux pages raisonnaient par service : dès qu'un service répondait, elles annonçaient que tout allait bien — même si le choix affiché dans le chat, lui, ne répondait plus. `/quotas/etat` rend désormais un bloc `choix` : pour Free AI Auto et pour Free AI Max, s'il reste un service libre, lequel répondrait, si c'est un secours, et l'heure de reprise sinon. `/diagnostic` et `/studio` nomment le choix bloqué et celui qu'il faut prendre ; l'ancien calcul par service reste en repli. **Vérifié le 16/09 en réel** : routeur reconstruit par l'utilisateur, `/quotas/etat` sert le bloc avec ses vraies clés — Free AI Auto prêt par Gemini (Google), Free AI Max prêt par Gemini Max (Google), aucun secours, aucune pause, aucune erreur au démarrage. **Non vérifié** : le rendu des deux pages dans le navigateur, et le verdict quand un choix est réellement à bout (seuls les tests le montrent).
6. **P2 : le registre**, après l'étape 5.
   1. `registry/apps.yaml`, une entrée par application : `id`, `fonction`, `modele`, `licence`, `territoire`, `vram_min_go`, `modes` (`api`, `local`, `modal`, `kaggle`, `colab`), `cout_estime`, `source`, `verifie_le`.
   2. `registry/apps.schema.json` (JSON Schema), validé en CI. Outil candidat : [`check-jsonschema`](https://pypi.org/project/check-jsonschema/) 0.38.0 (09/08/2026), qui existe en ligne de commande et en hook pre-commit. Sa page ne dit pas s'il lit le YAML : à vérifier avant de l'adopter. À défaut, vingt lignes de Python avec `jsonschema` et `pyyaml`.
   3. Faire lire le registre par `free-tier-manager` (`PROVIDERS`, `LIMITES_PUBLIEES`) et par `sandbox-manager` (`video.MODELES`). Aujourd'hui ces données sont en dur, et le tableau du README en est une troisième copie.
   4. Seulement ensuite, un job qui propose des candidats par PR, avec validation humaine.
7. **Dette relevée en passant, hors audit.** `@app.on_event("startup")` est déprécié par FastAPI (avertissements des tests). Passer à `lifespan` au prochain changement du démarrage.
8. **Reste de la revue du 11/09, non commencé.**
   - ~~`/studio` et `/diagnostic` raisonnent par service, pas par choix du chat~~ **Corrigé le 16/09/2026.** `etat_quotas` rend un bloc `choix` : pour Free AI Auto et pour Free AI Max, s'il reste un service libre, lequel répondrait, si c'est un secours, et l'heure de reprise sinon. `/diagnostic` affiche une ligne par choix et nomme, dans son verdict, le choix bloqué et celui à prendre en haut du chat ; `/studio` porte le même titre au-dessus des quotas. L'ancien calcul par service reste en repli si le bloc manque. Tests : `tests/test_quotas.py` (les deux choix libres ; Auto à bout et Max libre ; le secours dit par choix ; les deux à bout). **Non vérifié** : le rendu des deux pages dans un navigateur.
   - Le bouton « Mettre à jour » compare toujours à `main` : sur `audit-20260911`, il annonce une version plus récente alors que la branche est en avance. Sans effet tant que `main` et la branche coïncident : le 13/09, sur `6a934cc`, `/maj/etat` rend `a_jour: true`. Le défaut reste pour tout dossier cloné sur une autre branche.
   - ~~`/maj/lancer`, `/diagnostic/reparer` et `/cles/oublier` n'ont aucune garde d'origine~~ **Corrigé le 16/09/2026** (« quoi d'autres à améliorer tester ? »). Le Studio écoute sans mot de passe : n'importe quel site ouvert dans le même navigateur pouvait poster vers ces routes, sans lire la réponse, et effacer une clé ou lancer une mise à jour. `exiger_page_du_studio` refuse une demande dont `Sec-Fetch-Site` n'est pas `same-origin`/`none` ou dont `Origin` n'est pas l'adresse du service ; `exiger_json` exige `application/json`, qu'un formulaire d'un autre site ne peut pas envoyer sans permission. Posé sur `/cles/tester`, `/cles/oublier`, `/maj/lancer`, `/diagnostic/reparer` et `/dictee/choix` du routeur, et sur `/cles/tester`, `/cles/oublier` du Sandbox. Les routes coûteuses du Sandbox (`/jobs`, `/video/creer`, `/chanson/creer`) étaient déjà fermées par la clé interne. Tests : `tests/test_gardes.py` (10). **Non vérifié** : le comportement d'un vrai navigateur ; les en-têtes sont simulés dans les tests.
   - Petites dettes : une carte « gemini_max » sans titre sur /cles si `FREE_PROVIDER_ORDER` le contient ; `fournisseurs_branches` hors de l'ordre d'affichage.

## Détail par tâche

### P0-1 — Le chat ne se dégrade plus en silence

- **Code** (`free-tier-manager/app.py`) :
  - défaut `gemini-3.5-flash-lite` ; le modèle haut de gamme `gemini-3.8-flash` est le premier service de Free AI Max (`GEMINI_MAX_MODEL`) ;
  - `lire_quota()` lit un refus 429 de l'une ou l'autre forme (documentée ou réelle) ;
  - un quota du jour met Gemini en pause jusqu'à minuit, heure du Pacifique ; une limite par minute, de 5 s à 5 min ;
  - la première réponse du secours commence par une ligne d'avis ;
  - `GET /quotas/etat` ; bloc « quotas » dans `/diagnostic/etat` ; bandeau et liste sur `/studio` ;
  - un `429` explicite quand **tous** les services sont en pause, dès la demande qui met en pause le dernier (`f9d5c91`) ;
  - un 5xx ou une coupure : pause courte, avis « ne répond pas pour l'instant » (`f9d5c91`).
- **Docs** : `docs/FREE_TIER_MANAGER.md` (tableau des limites, avec date et sources), `README.md`, `.env.example`.
- **Vérifié hors réseau** : `tests/test_quotas.py`. Les fournisseurs y sont simulés, avec un refus au format réel et un au format documenté.
- **Vérifié en réel le 11/09/2026.** Le nouveau routeur a été lancé hors conteneur, sur un port d'essai. Conditions : la clé Gemini gratuite du `.env`, un dossier de configuration neuf, et `GEMINI_FREE_MODEL` retiré pour simuler une installation neuve. Déroulé :
  - 25 messages espacés de 4,5 s, puis 40 en rafale, à environ 0,8 s par message ;
  - **65 réponses sur 65 servies par `gemini-3.5-flash-lite`** : aucun refus, aucun recours à OpenRouter ;
  - `/quotas/etat` compte 65 réponses servies et aucune pause.

  Le critère d'acceptation (« plus de 20 échanges sans dégradation silencieuse ») est donc tenu sans bascule. Faute de refus, la bascule elle-même n'a pas pu être observée en réel.
- **Installations existantes.** Un `.env` créé avant le 11/09 peut contenir `GEMINI_FREE_MODEL=gemini-3.8-flash`, qui prime sur le défaut du code. C'est le cas sur la machine de l'essai. Pour passer à Flash-Lite, supprimer la ligne ou la remplacer par `gemini-3.5-flash-lite`. Le Studio ne réécrit jamais `.env`.
- **Pages rendues dans Chrome** (même service d'essai, après les 65 demandes). Sur `/studio`, le bloc « Services gratuits » affiche Gemini (`gemini-3.5-flash-lite`) « disponible, 65 réponse(s) servie(s) aujourd'hui » et OpenRouter à 0. Chaque ligne porte sa limite publiée, et les pastilles « expérimental » sont présentes. Sur `/diagnostic`, une ligne par service. Aucune erreur dans la console sur les deux pages. Groq n'apparaissait pas : `ENABLE_GROQ=false` dans le `.env`, donc le service n'était pas éligible. À la demande de l'utilisateur, `.env` a ensuite été remis sur le plan de `.env.example` et Groq activé, le 11/09. La clé Groq est acceptée (GET `/openai/v1/models`, HTTP 200), et `openai/gpt-oss-20b` figure dans la liste. Ce changement ne prend effet qu'à la recréation des conteneurs. Or `/diagnostic` le liste quand même parmi les services « branchés » ; ce décalage existait avant. Mesuré le 11/09, conteneurs reconstruits depuis `9b5be4d` : `/quotas/etat` donne Gemini, Gemini Max, OpenRouter et Groq éligibles.
- **Non vérifié** : la vraie limite du jour de Google, et le rendu de l'avis dans Open WebUI.

### P0-2 — Modal : la carte bancaire est dite partout

- **Fichiers** : `README.md`, `.env.example`, `sandbox-manager/video.py`, `docs/MODAL_CATALOG.md`, `docs/SERVICES_DEBUTANT.md`, et les cartes Vidéo et d'accueil de `/studio`.
- **Page `/video`** :
  - crédit « déclaré (`MODAL_CREDIT_MENSUEL_USD`), non vérifié chez Modal » ;
  - lien vers le réglage de la limite de dépense ;
  - option « Modal — machine louée (carte bancaire exigée) ».
- **Clips** : 0,096 $ au 09/09, mais c'était la carte seule ; avec le processeur et la mémoire (correction du 15/09), le même clip compte 0,117 $. 30 $ paieraient 256 clips. Le plafond de 20 $ en laisse passer **166**, parce que chaque clip doit encore tenir son pire cas (0,65 $). Ces nombres sont calculés en appliquant la règle de `budget_verifier`, pas estimés.

### P0-3 — Ce qui est ouvert, ce qui ne l'est pas

- Tableau du README : fonction, fournisseur, nature, licence. Licences relevées sur les fiches officielles : gpt-oss-20b et Wan 2.1 VACE sous Apache 2.0, Whisper sous MIT.
- `/video` affiche la licence et le territoire du modèle **à côté du choix de qualité**.
- « open source » est remplacé là où il voulait dire « gratuit » : `scripts/configure-beginner.*`, `docs/API_KEYS.md`, `AGENTS.md`. Il reste là où il est juste : Hugging Face dans `docs/SERVICES_DEBUTANT.md`, et une URL.

### P1-1 — La CI voit tout le Python, et le JavaScript des pages

La CI (`.github/workflows/validate.yml`) enchaîne :
1. la compilation de tous les `.py` suivis ;
2. `ruff check` (`ruff.toml` : règles E9 et F) ;
3. `scripts/verifier-imports.py` ;
4. `scripts/verifier-js.py` ;
5. `pytest tests` ;
6. puis, comme avant, Bash, les interdits du mode gratuit et Compose.

Preuve du critère : les fichiers du dépôt sont copiés (jamais `.env`), une faute est introduite dans la **copie** de `sandbox-manager/video.py`, puis les étapes Python sont rejouées.

| Cas | compilation | ruff | imports | tests | CI |
|---|---|---|---|---|---|
| nom mal écrit dans une fonction (`prix_secnde`) | passe | **échoue** (F821) | passe | passe | **échoue** |
| deux-points oublié | **échoue** | **échoue** | **échoue** | **échoue** | **échoue** |
| sans faute (témoin) | passe | passe | passe | passe | passe |

Le premier cas montre pourquoi la compilation ne suffisait pas : sans ruff, cette faute serait passée.

### P1-2 — Kaggle automatique : vos identifiants, votre machine

`contexte_partage()` dans `sandbox-manager/app.py` coupe Kaggle automatique dans quatre cas :
- `STUDIO_HEBERGE=true` ;
- `WEBUI_AUTH=true` ;
- la page est ouverte par une autre adresse que localhost ;
- la requête passe par un proxy.

Effets de la coupure :
- `POST /jobs` avec Kaggle, `/video/creer` vers Kaggle et `/cles/tester` pour Kaggle répondent 403, avec le lien manuel ;
- le mode `auto` saute Kaggle ;
- `/etat` et `/providers` donnent la raison.

Documenté dans `docs/GPU_CLOUD.md`, `docs/SANDBOX.md` et `AGENTS.md`. Vérifié par `tests/test_kaggle.py`.

**Vérifié en réel le 11/09/2026** : service lancé hors conteneur sur 127.0.0.1:8120, interrogé avec curl.
- `/etat` depuis localhost : `automatique_permis` vaut true, sans raison.
- Même requête avec l'en-tête `Host: 192.168.1.20:8120` : false, raison « page ouverte par l'adresse 192.168.1.20, pas par localhost ».
- Avec `X-Forwarded-For` : false, raison « requete relayee par un proxy ».
- Par 192.168.1.20 :
  - `POST /jobs` (kaggle), `POST /video/creer` (kaggle) et `POST /cles/tester` (kaggle) donnent tous **403**, avec le lien `https://www.kaggle.com/code` ;
  - `/cles/etat` porte `coupe` avec la même raison.

`/cles/tester` refuse avant tout appel réseau : aucune requête n'est partie vers Kaggle.

## Vérifications locales du 11/09/2026

Machine : ce PC sous Windows 11 Pro (10.0.26200), avec un venv Python **3.11.5** (la CI utilise 3.12), ruff 0.16.7, pytest 9.1.1 et Node 24.14.1.

```text
ruff check .                       All checks passed!
compilation de tous les .py        exit 0
python scripts/verifier-imports.py 3 services chargés
python scripts/verifier-js.py      9 scripts, 0 en échec (avant correction : /studio en échec)
python -m pytest -q tests          25 passed après f9d5c91 (13 à dcc742d)
docker compose --env-file .env.example config   exit 0 (sortie jetée : elle résout les variables)
```

**Essais réels, hors conteneur.** Les deux services ont été lancés depuis le dépôt sur 127.0.0.1:8110 et :8120. Les clés venaient de l'environnement ; aucun `keys.json` n'a été copié. Chaque service avait un dossier de configuration neuf, Open WebUI n'était pas joignable, et Modal comme Kaggle étaient coupés.
- **Fournisseurs** : 65 appels à Gemini, aucun à OpenRouter ni à Groq.
- **Pages rendues dans Chrome** : `/studio`, `/diagnostic`, `/video`, `/cles` et `/` du Sandbox. Aucune erreur dans la console, chaque page ayant été rechargée une fois le suivi de la console actif.
  - `/video` : option « Modal — machine louée (carte bancaire exigée) » ; ligne « licence Apache 2.0, aucune restriction de pays » ; crédit « déclaré (`MODAL_CREDIT_MENSUEL_USD`), non vérifié chez Modal ».
  - `/cles` : la carte Kaggle dit « Pilotage automatique réservé à votre machine ».
- **Non vérifié à l'écran** : la carte Kaggle grisée, et l'option Kaggle désactivée, quand le contexte est partagé. Le navigateur ne peut pas se présenter sous une autre adresse que localhost. Ce cas n'a été vérifié qu'au niveau de l'API (voir P1-2).

Les deux services d'essai ont été arrêtés après les mesures. Les conteneurs ont ensuite été reconstruits depuis `dcc742d`, à la demande de l'utilisateur (voir « Prochaines étapes », point 2). La branche `audit-20260911` a été poussée le 11/09, à la demande de l'utilisateur (étape 3).

## Parcours débutant sur une machine vierge (Linux simulé), 11/09/2026

Machine : un conteneur `docker:dind` privilégié sur ce PC (`fas-debutant-simule`), sans aucune image Docker ni `.env` au départ, le clone du dépôt monté dedans. Le script (hors dépôt) suit le README à la lettre, `./install.sh` puis `./start.sh`, sans aucune clé de fournisseur, et ne corrige rien.

| | `9b5be4d`, premier passage | `f9d5c91`, après corrections | `41cdd9a`, Arena et Kaggle, repris de zéro |
|---|---|---|---|
| `install.sh`, `start.sh`, attente des services sains | 108 s, 78 s, 32 s | 100 s, 68 s, 31 s | 100 s, 50 s, 31 s |
| durée totale | 219 s | 201 s | 182 s |
| auto-test | code 0 | code 0 | code 0 |
| conseil de l'auto-test, sans clé | « Ajoutez OPENROUTER_API_KEY dans .env » | « ouvrez http://127.0.0.1:8010/cles » | inchangé |
| une question dans le chat, sans clé | message anglais qui renvoie à `.env` | message français qui renvoie à la page Clés ; Open WebUI le relaie tel quel (HTTP 400) | même message, HTTP 503 au routeur, d'un bloc et en flux ; Open WebUI non rejoué |
| fausse clé Gemini sur /cles | « Refus du fournisseur (HTTP 400). Please pass a valid API key » | « Cle refusee. Verifiez que vous l'avez copiee en entier… », puis le motif de Google, annoncé comme anglais | inchangé |
| menu du chat | `free-ai-auto`, `arena-model` | inchangé ; Arena est l'étape suivante | `free-ai-auto` seul ; Open WebUI dit `ENABLE_EVALUATION_ARENA_MODELS: false` et le témoin `open-webui-arena.json` est posé |

Le troisième passage est parti d'une machine remise à zéro : aucune image Docker, ni `.env`, ni fichier dans `config/`. Il ne dit pas lequel des deux mécanismes a retiré Arena, la variable du compose au premier démarrage ou l'appel du routeur : le résultat est le même. Le chemin « installation existante » a été vu sur le Studio de l'utilisateur (étape 3).

Les durées dépendent du réseau : elles ne mesurent pas un débutant. Ce passage ne dit rien de Windows (`demarrer.cmd`, politique d'exécution, marque du Web), de Docker Desktop, d'une vraie clé ni d'une vraie personne : c'est l'objet de l'étape 5.
