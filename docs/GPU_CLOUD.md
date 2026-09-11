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

## Kaggle automatique : vos identifiants, votre machine

Colab n'est jamais piloté à distance : le Studio prépare un notebook, et c'est vous qui l'ouvrez. Kaggle, lui, est piloté **par l'API** depuis le Sandbox (`run_kaggle` dans `sandbox-manager/app.py`), avec les identifiants saisis sur la page `/cles` du Sandbox. Ce chemin suppose deux choses :

- des identifiants **personnels**, ceux de la personne à qui appartient la machine ;
- un Studio qui tourne **sur cette machine**, pour cette personne seule.

Il ne tient plus dès que le Studio sert d'autres personnes : leurs calculs partiraient sur le compte Kaggle d'une seule. Le Sandbox coupe donc Kaggle automatique dès qu'il voit l'un des signes ci-dessous. Il refuse alors d'enregistrer des identifiants Kaggle et ne propose plus que le lien manuel <https://www.kaggle.com/code>.

| Signe | Ce qu'il indique |
|---|---|
| `STUDIO_HEBERGE=true` dans `.env` | déclaration explicite : instance hébergée |
| `WEBUI_AUTH=true` dans `.env` | comptes multiples : plusieurs personnes partagent le Studio |
| page appelée par un autre nom que `localhost` / `127.0.0.1` | port ouvert sur le réseau |
| en-tête `X-Forwarded-For` ou `Forwarded` | Studio placé derrière un proxy |

Ces signes sont des indices, pas une preuve. Un Studio exposé par un moyen qui n'en laisse aucun (tunnel qui réécrit l'en-tête `Host`, par exemple) doit être déclaré avec `STUDIO_HEBERGE=true`.

### Conditions d'utilisation de Kaggle — lues le 11/09/2026 (version du 22/06/2025)

- Les [conditions d'utilisation](https://www.kaggle.com/terms) réservent le service à un usage interne, personnel et non commercial, « not on behalf of or for the benefit of any third party ». Un compte ne se partage pas, et plusieurs personnes ne peuvent pas opérer sous un même identifiant. C'est exactement ce que ferait un Studio hébergé qui piloterait Kaggle avec les identifiants d'une seule personne : la garde ci-dessus applique ces conditions, ce n'est pas une précaution de style.
- La [politique d'usage](https://www.kaggle.com/aup) interdit d'abuser des ressources offertes, entre autres pour du « server farming » ou une activité sans rapport avec la science des données et l'apprentissage automatique. Conséquence : même sur votre machine, le mode `auto` du Sandbox peut envoyer sur Kaggle un code quelconque quand Modal et Local sont indisponibles. Réservez Kaggle aux calculs de données ou d'apprentissage. Une restriction dans le code reste à décider (voir `PLAN.md`).
- La documentation officielle du CLI ([kernels](https://github.com/Kaggle/kaggle-cli/blob/main/docs/kernels.md)) décrit `kernels push`, qui pousse le code puis exécute le noyau : le pilotage par programme est un usage prévu. Elle ne dit rien des quotas.

Ces pages ne s'affichent qu'avec JavaScript : elles ont été lues dans un navigateur, pas par un simple téléchargement.

