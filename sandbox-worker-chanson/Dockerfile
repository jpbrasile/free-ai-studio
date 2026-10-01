# Le bac a sable de la CHANSON sur la carte de cet ordinateur (01/10/2026).
#
# Demande du proprietaire : un film « Leila et un martien » fait en local de bout
# en bout, musique comprise, et « Installer YuE2 en local ». Le bac a sable video
# de la carte (`sandbox-worker-gpu`) porte torch 2.6 pour Wan ; YuE2 n'y est pas,
# et sa roue exige torch 2.10. On ne touche pas a la machine video qui marche :
# une image a part, meme code de worker (`sandbox-worker/app.py`, copie), meme
# compte, meme reseau clos, poids en lecture seule dans le cache partage.
#
# torch 2.7.1 : celui sous lequel le pic de YuE2 a ete mesure sur la 4090
# (23/09, chanson_maison.BESOIN_MO). La roue s'installe SANS ses dependances,
# comme sur Kaggle et Colab (chanson.py) : le reste est epingle aux versions
# qu'elle declare.
#
# Construit depuis la RACINE du depot (docker-compose.gpu.yml).
FROM pytorch/pytorch:2.7.1-cuda12.6-cudnn9-runtime

WORKDIR /app

COPY sandbox-worker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && pip install --no-cache-dir \
      "transformers==4.57.6" "huggingface-hub==0.36.2" "safetensors==0.7.0" \
      "tiktoken==0.12.0" "soundfile==0.13.1" "accelerate==1.13.0" \
 && pip install --no-cache-dir --no-deps \
      "https://huggingface.co/m-a-p/YuE2-3B/resolve/29b3558dd46954a0cd9021dc76d5c91864a0f1c7/yue2_infer-0.1.5-py3-none-any.whl" \
 && python -c "import importlib.util as u; assert u.find_spec('yue2'), 'yue2 absent'"

COPY sandbox-worker/app.py .

RUN useradd -r -u 10001 -m sandbox \
 && mkdir -p /workspace/jobs /cache/huggingface \
 && chown -R sandbox:sandbox /workspace /cache

USER sandbox
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
