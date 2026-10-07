# La machine de calcul de la MAISON pour H3, l'agrandissement et les visages :
# la même que celle louée chez Modal, sur la 4090 de ce PC.
#
# Demande du propriétaire, 01/10/2026 : « mettre dans le studio un mode local non
# urgent pour lancer H3 et le upscale ou enhanced portrait ». Chez Modal, l'image est
# `debian_slim(python_version="3.12")` + git + ffmpeg + ComfyUI cloné à la version
# épinglée (sandbox-manager/app.py et video_h3.COMMANDES) ; elle est recopiée ici
# telle quelle, pour que les scripts envoyés (video_h3._SCRIPT, agrandir, visages)
# tournent sans changement. Les poids sont montés en lecture seule sur /poids,
# le même chemin que le disque Modal.
#
# Construit depuis la RACINE du dépôt (il copie sandbox-worker/) :
#   docker build -f comfy-maison/Dockerfile -t free-ai-studio-comfy-maison .
FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends git ffmpeg \
 && rm -rf /var/lib/apt/lists/*

ARG COMFY_VERSION=v0.37.0
RUN git clone --depth 1 --branch ${COMFY_VERSION} https://github.com/Comfy-Org/ComfyUI /comfy \
 && pip install --no-cache-dir -r /comfy/requirements.txt psutil

# Triton compile ses noyaux au premier appel et cherche un compilateur C : sans lui, le
# premier plan H3 sur la 4090 est mort à l'encodage VAE (« Failed to find C compiler »,
# torch._native bmm_outer_product, 01/10/2026). Couche à part : le cache des précédentes reste.
RUN apt-get update \
 && apt-get install -y --no-install-recommends gcc libc6-dev \
 && rm -rf /var/lib/apt/lists/*

# L'agrandissement d'ici : FlashVSR v1.1 (OpenImagingLab, Apache-2.0) remplace SeedVR2 sur la
# carte de ce PC (demande du propriétaire, 03/10/2026 : SeedVR2 vieillissait les visages).
# Version « Tiny » avec flashvsr-sm89-ops (aireet, Apache-2.0) : Triton à la place de
# block_sparse_attn (rien à compiler), FP8 et rendu en tuiles pour tenir en 24 Go. Mesuré le
# 03/10 sur la 4090 : 120 images 960x548 -> 3840x2176 en 160,8 s, pic 14,7 Go. Les deux dépôts
# épinglés ; ni l'un ni l'autre n'est installé par pip (le script les met dans son chemin).
# Les poids (3 fichiers) sont lus sur /poids/flashvsr/FlashVSR-v1.1, en lecture seule.
ARG FLASHVSR_COMMIT=cf910c61a60733e610e9c6e8b607f80c3a6c202b
ARG SM89_COMMIT=59c74311b715b0f038854365b799707636236e73
RUN git clone https://github.com/OpenImagingLab/FlashVSR /opt/flashvsr \
 && git -C /opt/flashvsr checkout ${FLASHVSR_COMMIT} \
 && git clone https://github.com/aireet/flashvsr-sm89-ops /opt/flashvsr-sm89 \
 && git -C /opt/flashvsr-sm89 checkout ${SM89_COMMIT} \
 && rm -rf /opt/flashvsr/.git /opt/flashvsr-sm89/.git /opt/flashvsr-sm89/assets \
 && ln -s /poids/flashvsr/FlashVSR-v1.1 /opt/flashvsr/examples/WanVSR/FlashVSR-v1.1 \
 && pip install --no-cache-dir --no-deps imageio==2.37.0 imageio-ffmpeg==0.6.0 \
    opencv-python-headless==4.11.0.86 ftfy==6.3.1 peft==0.16.0 wcwidth==0.9.1

# La fluidification à 60 images/s (sandbox-manager/fluide.py, PLAN 21.6 étape 5) : GIMM-VFI, nœud de
# kijai épinglé, appelé directement par le script (pas de graphe). Licence S-Lab 1.0, NON COMMERCIALE.
# Dépendances aux versions mesurées le 06/10 sur la 4090 (cupy pour CUDA 13, avec son kit de
# compilation). Les poids (2 fichiers) sont lus sur /poids/gimm-vfi, en lecture seule.
ARG GIMM_COMMIT=4c9a3123762af85e7c796e41737da0b70c75d72d
RUN git clone https://github.com/kijai/ComfyUI-GIMM-VFI /comfy/custom_nodes/gimm_vfi \
 && git -C /comfy/custom_nodes/gimm_vfi checkout ${GIMM_COMMIT} \
 && rm -rf /comfy/custom_nodes/gimm_vfi/.git \
 && mkdir -p /comfy/models/interpolation \
 && ln -s /poids/gimm-vfi /comfy/models/interpolation/gimm-vfi \
 && pip install --no-cache-dir "cupy-cuda13x[ctk]==14.2.0" timm==1.0.30 omegaconf==2.3.1 yacs==0.1.8 easydict==1.13

# Les clips d'un tour 360° enchaînés par le latent (sandbox-manager/tour360_chaine.py, PLAN 21.6) : nœud
# ComfyUI-H3-Motion-Context (NikoDemon80, GPL-3.0), au commit relu le 27/09 (video_h3.MC_COMMIT), le même que
# chez Modal ; appelé par le graphe, jamais importé par le Studio. Monté à la main pour le tour v3 du 06/10.
ARG MC_COMMIT=5335715abe54c1a9bfbe3494da29aae3e8635ce3
RUN git clone https://github.com/NikoDemon80/ComfyUI-H3-Motion-Context /comfy/custom_nodes/h3_motion_context \
 && git -C /comfy/custom_nodes/h3_motion_context checkout ${MC_COMMIT} \
 && rm -rf /comfy/custom_nodes/h3_motion_context/.git

# La mesure de la pièce d'un tour 360° (sandbox-manager/tour360_pano.py, mode « mesure », PLAN 21.6 étape 1) :
# MoGe-3 (Microsoft, MIT), au commit de tour360.MOGE_DEPOT, déjà lancé sur cette image le 05/10
# (scripts/decor360/moge_plaque.py, ~20 s, 2,5 Go de carte). Le bac à sable n'a pas Internet : les poids
# (Ruicheng/moge-3-vitl, révision 184008f) sont lus sur /poids/moge-3-vitl/model.pt, en lecture seule.
ARG MOGE_COMMIT=74fbce054ebed49800de42d0ad0e83495065719a
RUN pip install --no-cache-dir "git+https://github.com/microsoft/MoGe.git@${MOGE_COMMIT}"

# Le petit serveur des bacs à sable (sandbox-worker/app.py, sans changement) : le Studio
# lui envoie le script d'un plan comme au bac à sable de la carte, sans aucun crochet de
# la machine hôte (« le client débutant n'aura aucun hook installé », 01/10). Construit
# depuis la racine du dépôt : docker-compose.gpu.yml, service sandbox-worker-comfy.
COPY sandbox-worker/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY sandbox-worker/app.py /app/app.py

# Compte sans privilège, comme les autres bacs à sable ; ComfyUI écrit dans /comfy
# (input, user, temp) pendant un plan.
RUN useradd -r -u 10001 -m sandbox \
 && mkdir -p /workspace/jobs \
 && chown -R sandbox:sandbox /comfy /workspace

USER sandbox
WORKDIR /comfy
EXPOSE 8000
CMD ["uvicorn", "--app-dir", "/app", "app:app", "--host", "0.0.0.0", "--port", "8000"]
