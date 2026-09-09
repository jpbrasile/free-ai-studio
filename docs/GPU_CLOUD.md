# GPU, ComfyUI et génération image/vidéo

Cette partie est **optionnelle**.

L'installation minimale de Free AI Studio ne nécessite pas de GPU.

## ComfyUI

Site/documentation :

https://docs.comfy.org/

ComfyUI peut être exécuté :

- localement sur une machine avec GPU,
- dans un notebook cloud,
- sur un backend GPU distant.

URL par défaut :

```env
COMFYUI_BASE_URL=http://127.0.0.1:8188
```

## Pourquoi ComfyUI n'est pas lancé automatiquement

Les pilotes NVIDIA, CUDA, VRAM et modèles varient fortement selon la machine.

Pour un débutant, il est plus sûr de :

1. faire fonctionner Open WebUI,
2. détecter le GPU,
3. choisir ensuite le mode ComfyUI adapté.

## GPU cloud

Les offres gratuites et promotionnelles changent régulièrement. Toujours vérifier les conditions actuelles du fournisseur avant d'utiliser une carte bancaire.

Le mode par défaut de Free AI Studio reste :

```env
FREE_ONLY=true
ALLOW_PAID_MODELS=false
MAX_DAILY_COST=0
```

## Liens GPU gratuits sélectionnés

Les notebooks et workflows Image / Vidéo / TTS actuellement sélectionnés sont dans :

`notebooks/SOTA_LINKS.md`

Ils complètent le routage Sandbox Modal-first :
- Modal = backend automatique principal lorsqu’il est configuré ;
- Local = fallback isolé ;
- Kaggle = fallback automatisable **et** accès direct cliquable ;
- Colab = accès direct cliquable + handoff notebook ;
- le choix du modèle dépend de la mémoire GPU réellement disponible.

