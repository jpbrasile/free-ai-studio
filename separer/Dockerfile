FROM python:3.11-slim
# git : DeepFilterNet le cherche au chargement du modele (essai du 05/10/2026 :
# << fatal: not a git repository >> sans consequence, mais un echec sans lui).
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
# torch en roue CPU : le remix tourne sur le processeur, la carte reste a la file.
# Versions de l'essai du 05/10/2026 (conteneur jetable, film << Leila >> 1-8).
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu \
       torch==2.14.1 torchaudio==2.11.0 \
    && pip install --no-cache-dir DeepFilterNet==0.5.6 DeepFilterLib==0.5.6 soundfile==0.14.0
# DeepFilterNet 0.5.6 importe torchaudio.backend, retire des torchaudio recents ;
# il ne s'en sert que pour une annotation de type.
RUN sed -i 's/^from torchaudio.backend.common import AudioMetaData/AudioMetaData = object/' \
    /usr/local/lib/python3.11/site-packages/df/io.py
# Le modele DeepFilterNet3, telecharge une fois ici : le conteneur tourne en
# lecture seule, sans rien chercher sur le reseau au premier remix.
ENV HOME=/app
RUN python -c "from df.enhance import init_df; init_df()"
COPY remix.py app.py ./
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
