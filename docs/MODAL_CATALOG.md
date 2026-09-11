# Catalogue Modal — Free AI Studio

> Vérifié : septembre 2026. Modal est un service de calcul facturé à l'usage avec, sur le plan Starter, un crédit de calcul gratuit mensuel. Free AI Studio ne doit jamais considérer ce crédit comme illimité.

## Rôle de Modal

Modal est le backend GPU distant automatique de Free AI Studio.

Parcours :

```text
GPU local suffisant
→ utiliser le GPU local

sinon
→ Modal si configuré et si l'usage reste couvert par le crédit gratuit

sinon
→ proposer Colab / Kaggle en secours manuel
```

Le débutant ne doit pas avoir à comprendre les GPU, endpoints, volumes ou conteneurs.

## Profils internes

Free AI Studio ne doit pas afficher une liste interminable de modèles.

```text
IMAGE_FAST
IMAGE_HIGH
IMAGE_EDIT

VIDEO_FAST
VIDEO_HIGH
IMAGE_TO_VIDEO
VIDEO_AUDIO

TTS_FAST
TTS_HIGH
VOICE_CLONE

STT_FAST
STT_HIGH

VISION
LLM_LARGE
```

L'assistant de codage peut remplacer les modèles associés à ces profils après vérification actuelle.

## Catalogue de départ

### IMAGE_EDIT

**Flux Kontext**
- Catégorie : édition d'image.
- Intérêt : exemple officiel Modal orienté édition avec modèle de diffusion.
- Point de départ : catalogue officiel Modal Image & Video.

### IMAGE_HIGH

**FLUX / diffusion optimisée**
- Modal fournit des exemples officiels pour servir FLUX et d'autres modèles de diffusion.
- À choisir lorsque la qualité importe plus que le temps de démarrage.

### IMAGE_FAST

**Stable Diffusion 3.5 Large Turbo**
- Exemple officiel Modal disponible en CLI, API et Web UI.
- Bon profil de référence pour valider rapidement la chaîne Image.

### VIDEO_HIGH

**Wan**
- Modal référence officiellement des workflows Wan, notamment un exemple Wan2.1 spécialisé.
- L'assistant peut déployer une version Wan plus récente uniquement après avoir vérifié licence, VRAM et compatibilité actuelle.

### IMAGE_TO_VIDEO

**Animation d'image**
- Modal propose officiellement un exemple « Bring images to life » dans son catalogue Image & Video.
- Utiliser ce type de workflow lorsque l'utilisateur fournit une image source.

### VIDEO_FAST

**Mochi**
- Modal référence un exemple officiel « Generate videos with Mochi ».
- À conserver comme fallback démonstratif si un modèle Wan/LTX plus récent n'est pas praticable.

### VIDEO_AUDIO

**LTX / modèle vidéo+audio compatible**
- Profil prévu pour un moteur produisant vidéo + audio synchronisés.
- Ne pas figer un modèle Modal non vérifié : l'assistant doit vérifier le meilleur candidat actuel au moment du déploiement.

### TTS_HIGH / VOICE_CLONE

**Chatterbox Turbo**
- Modal fournit un exemple officiel d'API TTS.
- Prend en charge la voix expressive et le clonage vocal à partir d'un court échantillon.

### TTS_FAST

**Qwen3-TTS ou moteur léger actuel**
- Utiliser seulement après vérification de la documentation et de la compatibilité Modal.
- Si un exemple officiel plus simple/rapide existe au moment de l'installation, l'assistant peut le privilégier.

### STT_HIGH

**Parakeet**
- Modal fournit un exemple officiel de transcription streaming avec Parakeet.
- Bon candidat pour la transcription temps réel.

### STT_FAST

**Whisper**
- Modal fournit un exemple officiel de déploiement Whisper.
- Bon choix de compatibilité générale.

### VISION

**Qwen 3.6 VLM via SGLang**
- Exemple officiel Modal actuel.
- Sert un modèle vision-langage derrière un serveur HTTP.

### LLM_LARGE

**Modal Endpoint / SGLang / vLLM**
- Modal Endpoints accepte des modèles open-weight et des poids personnalisés.
- Exemple CLI actuel :
  `modal endpoint create --model Qwen/Qwen3.6-27B-FP8`
- À utiliser uniquement si le crédit gratuit disponible suffit au test visé.

## Liens officiels à vérifier par l'assistant

- Documentation Modal : https://modal.com/docs
- Tarifs : https://modal.com/pricing
- Image & Video : https://modal.com/solutions/image-and-video
- Stable Diffusion 3.5 Large Turbo : https://modal.com/docs/examples/a1111_webui
- Chatterbox TTS : https://modal.com/docs/examples/chatterbox_tts
- Parakeet STT : https://modal.com/docs/examples/streaming_parakeet
- Whisper : https://modal.com/blog/how-to-deploy-whisper
- Qwen Vision-Language : https://modal.com/docs/examples/sglang_vlm
- Modal Endpoints : https://modal.com/docs/cli/latest/endpoint
- Serveurs HTTP : https://modal.com/docs/sdk/py/latest/web_server

## Règles financières

Vérifié le 11/09/2026 sur les pages officielles de Modal :

- **Tarifs** (<https://modal.com/pricing>) : plan Starter à « $0 + compute / month », avec **« $30 / month free credits »**. Les GPU sont facturés à la seconde.
- **Carte bancaire obligatoire** (<https://modal.com/docs/guide/billing>) : « you must have a payment method on file in order to use Modal ». Modal ne s'utilise pas sans moyen de paiement enregistré.
- **Au-delà du crédit, Modal facture** (<https://modal.com/docs/guide/budgets>) : « If you do not set a custom spend limit, Modal uses the cycle's usage limit minus credits. For example, if your usage limit is $100 and you have $30 in credits, the default spend limit is $70. » Autrement dit, sans réglage, **jusqu'à 70 $ peuvent être prélevés** dans cet exemple. Quand la limite est atteinte, « Modal stops workloads that would incur additional out-of-pocket charges ».
- La limite se règle sur la page **Usage & Billing** (<https://modal.com/settings/usage>). La documentation ne dit pas si 0 $ est accepté : la régler au plus bas que la page permet, et vérifier.
- Le Studio **ne lit pas** le crédit restant ni la facture chez Modal. Le plafond vidéo (`VIDEO_BUDGET_USD_PAR_MOIS`) est une estimation locale, et le crédit affiché (`MODAL_CREDIT_MENSUEL_USD`) est une **déclaration** de l'utilisateur.

Donc :

```text
ALLOW_PAID_GPU=false
MAX_DAILY_COST=0
```

signifie :

- utiliser Modal seulement si l'utilisateur a choisi/configuré Modal ;
- ne jamais ajouter de carte ou activer une facturation ;
- ne jamais promettre que Modal est « gratuit illimité » ;
- ne jamais continuer automatiquement après épuisement du crédit gratuit ;
- si le statut du crédit ne peut pas être vérifié de manière fiable, demander à l'utilisateur de vérifier son tableau de bord Modal avant un déploiement potentiellement coûteux ;
- préférer Colab/Kaggle lorsque la gratuité Modal n'est plus certaine.

## Mise à jour du catalogue

Quand l'utilisateur demande :
> « Mets les meilleurs modèles actuels »

l'assistant doit :

1. consulter les sources officielles du modèle et de Modal ;
2. vérifier licence et restrictions d'usage ;
3. estimer le GPU/VRAM requis ;
4. vérifier si Modal dispose du GPU adapté ;
5. privilégier une variante réaliste pour le crédit gratuit restant ;
6. tester le déploiement ;
7. mettre à jour ce fichier avec la date de vérification ;
8. conserver un fallback connu et fonctionnel.

## Principe

**Modal = automatique et puissant.**
**Colab/Kaggle = secours gratuit ponctuel.**

Le meilleur modèle n'est utile que s'il peut réellement être exécuté dans les limites financières choisies par l'utilisateur.
