# Création des clés API

Commencez par **Gemini + Groq + OpenRouter**. Les autres services sont optionnels.

| Service | Utilité | Variable | Lien officiel |
|---|---|---|---|
| Google Gemini | Chat, vision, outils | `GEMINI_API_KEY` | https://aistudio.google.com/apikey |
| Groq | LLM rapide, transcription | `GROQ_API_KEY` | https://console.groq.com/keys |
| OpenRouter | Catalogue de modèles et fallback | `OPENROUTER_API_KEY` | https://openrouter.ai/settings/keys |
| Hugging Face | Modèles / inference | `HF_TOKEN` | https://huggingface.co/settings/tokens |
| Cloudflare Workers AI | Inference | `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN` | https://developers.cloudflare.com/workers-ai/get-started/rest-api/ |
| Modal | Calcul cloud / GPU optionnel | `MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET` | https://modal.com/docs/guide |

## Google Gemini

1. Ouvrir https://aistudio.google.com/apikey
2. Se connecter à son compte Google.
3. Créer/copier une clé.
4. La mettre directement dans `.env` :

```env
GEMINI_API_KEY=votre_cle
```

## Groq

1. Ouvrir https://console.groq.com/keys
2. Créer une API key.
3. La mettre dans `.env`.

## OpenRouter

1. Ouvrir https://openrouter.ai/settings/keys
2. Créer une clé.
3. La mettre dans `.env`.

Gardez le mode gratuit activé et choisissez uniquement des modèles gratuits tant que `ALLOW_PAID_MODELS=false`.

## Important

Les quotas, modèles gratuits et conditions des fournisseurs peuvent changer.

Free AI Studio doit considérer une clé comme **un accès technique**, pas comme une garantie que toutes les requêtes sont gratuites.

Ne mettez jamais vos clés dans :

- un dépôt GitHub public,
- une capture d'écran,
- un message de forum,
- un prompt envoyé à un assistant en ligne.


## Management Key OpenRouter — optionnelle

La clé OpenRouter normale suffit pour utiliser les modèles.

Une **Management Key OpenRouter** est uniquement utile si vous voulez que Free AI Studio lise automatiquement le total de crédits acheté et indique le niveau de quota gratuit.

La documentation officielle de l'API Credits précise qu'une Management Key est requise.

N'ajoutez cette clé que si vous souhaitez cette détection automatique. Le projet fonctionne sans elle.


## Services optionnels expliqués simplement

Les clés optionnelles ne sont pas demandées parce qu'elles sont « techniques ». Elles ajoutent des capacités concrètes :

- **Hugging Face** : plus de modèles open source.
- **Cloudflare Workers AI** : fournisseur de secours avec quota gratuit.
- **Modal** : machine cloud puissante, parfois avec GPU, utile pour image/vidéo.
- **Kaggle** : GPU gratuit via notebooks pour les tâches lourdes.
- **E2B** : ordinateur temporaire isolé pour tester du code sans toucher directement au PC.
- **Daytona** : environnement séparé pour tester du code ou un projet.
- **fal.ai / Segmind / Fireworks** : fournisseurs supplémentaires selon crédits/offres disponibles.

Le guide complet pour débutant est dans `docs/SERVICES_DEBUTANT.md`.
