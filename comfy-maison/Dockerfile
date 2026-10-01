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
FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends git ffmpeg \
 && rm -rf /var/lib/apt/lists/*

ARG COMFY_VERSION=v0.37.0
RUN git clone --depth 1 --branch ${COMFY_VERSION} https://github.com/Comfy-Org/ComfyUI /comfy \
 && pip install --no-cache-dir -r /comfy/requirements.txt psutil

WORKDIR /comfy
