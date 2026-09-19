# Le bac a sable de la MAISON : le meme worker, sur la carte graphique.
#
# Phase 3 du chantier ouvert le 19/09/2026. Le code execute est exactement celui
# du bac a sable sur processeur -- `sandbox-worker/app.py`, copie ici et non
# reecrite : un seul fichier a reparer, comme le reste du depot. Seule l'image
# change, parce que torch et CUDA ne tiennent pas dans un `python:3.12-slim`.
#
# Le contexte de construction est la RACINE du depot (voir
# docker-compose.gpu.yml), pour pouvoir copier le worker sans le dupliquer.
#
# Pourquoi cette image de base precisement : elle a ete mesuree le 19/09 --
# torch 2.6.0+cu124 y voit la RTX 4090 depuis WSL2 sans rien installer, et le
# premier clip du Studio en est sorti (412 s, 12 841 Mo de pic, 0 $).
#
# Pourquoi le Python de la machine ne sert pas : son `tokenizers` (0.15.2) et
# son `numpy` sont en conflit avec `transformers`, qui en exige >= 0.22. On ne
# repare pas l'installation d'un tiers pour faire tourner un service : on isole.
FROM pytorch/pytorch:2.6.0-cuda12.4-cudnn9-runtime

WORKDIR /app

COPY sandbox-worker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && pip install --no-cache-dir \
      "diffusers>=0.35.1" \
      "transformers>=4.51.0" \
      accelerate \
      sentencepiece \
      protobuf \
      ftfy \
      imageio \
      imageio-ffmpeg \
      pillow

COPY sandbox-worker/app.py .

# Le meme compte non privilegie que le bac a sable sur processeur, et le meme
# uid : les deux ecrivent dans le MEME volume /workspace, que le gestionnaire
# relit pour ramasser le clip.
RUN useradd -r -u 10001 -m sandbox \
 && mkdir -p /workspace/jobs /cache/huggingface \
 && chown -R sandbox:sandbox /workspace /cache

USER sandbox
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
