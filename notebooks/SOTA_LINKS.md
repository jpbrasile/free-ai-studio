# GPU gratuit — liens Image / Vidéo / Voix

> Vérifié : septembre 2026. Les notebooks communautaires peuvent évoluer. Free AI Studio les présente comme des solutions ponctuelles, jamais comme des backends garantis 24/7.

## Choix recommandé pour un débutant

### 🎨 Image

**Qwen Image — génération / édition**
- Colab, collection ComfyUI prête à l'emploi : https://github.com/Collab-AI-Gen/Google-Colab_Notebooks/tree/main/Qwen_Image
- Workflow officiel ComfyUI Qwen Image 2512 : https://docs.comfy.org/tutorials/image/qwen/qwen-image-2512
- Projet officiel Qwen Image : https://github.com/QwenLM/Qwen-Image

Pourquoi : Qwen-Image-2512 dispose d'un workflow ComfyUI natif, d'une version FP8 et d'une accélération Lightning 4 étapes. Qwen a aussi annoncé Qwen-Image-2.0 en 2026. Pour les GPU gratuits, Free AI Studio privilégie pour l'instant le workflow réellement documenté/exécutable plutôt que de promettre Qwen-Image-2.0 sans notebook gratuit vérifié.

### 🎬 Vidéo — option légère/pratique

**Wan 2.2 TI2V 5B**
- Colab Wan 2.2 : https://github.com/epg900/wan2.2
- Workflow officiel ComfyUI Wan 2.2 : https://docs.comfy.org/tutorials/video/wan/wan2_2

Pourquoi : le workflow officiel ComfyUI indique que la variante Wan2.2 TI2V 5B peut fonctionner avec l'offloading natif sur environ 8 Go de VRAM. C'est donc un meilleur candidat de secours gratuit que les variantes 14B beaucoup plus lourdes.

### 🎬 Vidéo — qualité / fonctions avancées

**Wan 2.2 Animate**
- Kaggle T4, notebook ComfyUI : https://github.com/kelvinweijun/wan-2.2-animate-comfyui-kaggle
- Documentation ComfyUI : https://docs.comfy.org/tutorials/video/wan/wan2-2-animate

Le dépôt Kaggle est préparé pour 2 × T4 16 Go. Ce choix dépend donc du GPU réellement attribué par Kaggle.

### 🎬 Vidéo + audio synchronisé

**LTX-2**
- Colab, collection : https://github.com/Collab-AI-Gen/Google-Colab_Notebooks/tree/main/LTX
- Modèles ComfyUI + raccourcis notebook Colab/Kaggle : https://huggingface.co/Comfy-Org/ltx-2
- Présentation ComfyUI : https://blog.comfy.org/p/ltx-2-open-source-audio-video-ai

Pourquoi : LTX-2 génère vidéo et audio synchronisés et bénéficie d'une intégration native ComfyUI. Les poids complets restent lourds : il faut vérifier la mémoire réellement disponible avant de lancer.

### 🎤 Voix

**Qwen3-TTS**
- Notebook : https://github.com/openvinotoolkit/openvino_notebooks/blob/latest/notebooks/qwen3-tts/qwen3-tts.ipynb

Ce notebook OpenVINO sert de référence exécutable. Free AI Studio ne prétend pas qu'un GPU Colab/Kaggle est nécessaire pour chaque configuration TTS.

## Règle de sélection

```text
IMAGE
→ Qwen Image workflow compatible GPU disponible

VIDEO
→ Wan 2.2 5B si ressources limitées
→ Wan 2.2 Animate si Kaggle fournit les GPU nécessaires
→ LTX-2 pour vidéo + audio synchronisé si mémoire suffisante

TTS
→ Qwen3-TTS
```

## Important

« SOTA » ne veut pas dire « exécutable gratuitement sur n'importe quel GPU ».

Free AI Studio distingue donc :
- **meilleur modèle actuel identifié** ;
- **meilleur modèle réellement praticable sur le GPU gratuit obtenu**.

L'assistant de codage doit vérifier la documentation officielle et la mémoire GPU avant de conseiller ou remplacer un profil.
