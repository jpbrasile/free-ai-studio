# Services optionnels — explications pour débutant

Free AI Studio fonctionne d'abord avec les services essentiels. Les services ci-dessous sont **optionnels** : ils servent à ajouter des capacités précises.

## Essentiel

### Gemini
Apport concret :
- discuter avec une IA rapide ;
- analyser du texte et des images ;
- servir de secours gratuit si un autre fournisseur est limité.

### Groq
Apport concret :
- réponses très rapides ;
- transcription audio avec Whisper ;
- secours gratuit pour le chat.

### OpenRouter
Apport concret :
- accéder à plusieurs modèles gratuits derrière une seule clé ;
- augmenter le quota quotidien des modèles gratuits après achat de crédits ;
- utiliser ponctuellement le Boost si l'utilisateur le décide.

## Optionnel — utile selon vos besoins

### Hugging Face
**À quoi ça sert ?**
À accéder à de nombreux modèles open source hébergés en ligne.

Utile si vous voulez :
- tester des modèles supplémentaires ;
- utiliser certaines tâches spécialisées ;
- compléter les fournisseurs principaux.

Vous pouvez ignorer cette étape au début.

### Cloudflare Workers AI
**À quoi ça sert ?**
À exécuter certains modèles dans le cloud avec un quota gratuit.

Utile si vous voulez :
- ajouter un fournisseur de secours ;
- répartir les demandes quand les autres quotas sont atteints.

Vous pouvez ignorer cette étape au début.

### Modal
**À quoi ça sert ?**
À obtenir temporairement une machine puissante dans le cloud, parfois avec GPU.

Utile surtout pour :
- générer des images ;
- générer des vidéos ;
- lancer des modèles trop lourds pour votre ordinateur.

C'est particulièrement utile si votre ordinateur n'a pas de carte graphique puissante.

### Kaggle
**À quoi ça sert ?**
À utiliser gratuitement des notebooks avec GPU quand Google/Kaggle en met à disposition.

Utile surtout pour :
- tester ComfyUI ;
- générer ponctuellement des images ou vidéos ;
- exécuter des modèles lourds sans acheter de GPU.

Kaggle n'agit pas comme une API classique : il sert plutôt de machine de calcul temporaire.

### E2B
**À quoi ça sert ?**
À donner à l'IA un ordinateur temporaire et isolé pour exécuter du code sans toucher directement à votre ordinateur.

Exemple concret :
vous demandez à l'IA « teste ce script Python ».  
Avec E2B, le script peut être lancé dans un environnement séparé.

C'est plus sûr que d'exécuter du code inconnu directement sur votre PC.

### Daytona
**À quoi ça sert ?**
Même idée qu'E2B : fournir un environnement de travail séparé pour exécuter du code, installer des paquets et tester un projet.

Utile pour :
- tester du code ;
- ouvrir un projet ;
- lancer des commandes ;
- éviter de modifier directement votre ordinateur.

### fal.ai / Segmind / Fireworks
**À quoi ça sert ?**
À ajouter ponctuellement d'autres modèles cloud, selon leurs offres gratuites ou crédits promotionnels.

Ils ne sont pas nécessaires pour démarrer et peuvent être ignorés.

## Conseil pour débutant

Commencez uniquement avec :

```text
Gemini
Groq
OpenRouter
```

Puis ajoutez seulement ce dont vous avez besoin :

```text
Besoin d'image/vidéo lourde sans bon GPU → Modal ou Kaggle
Besoin d'exécuter du code sans risque sur votre PC → E2B ou Daytona
Besoin de fournisseurs de secours supplémentaires → Cloudflare / Hugging Face
```
