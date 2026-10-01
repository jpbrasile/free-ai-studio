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
