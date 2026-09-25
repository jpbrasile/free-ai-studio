FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Le refus au demarrage. Fichier separe et non fondu dans app.py : le bac a
# sable en a besoin aussi, et tests/test_garde_exposition.py echoue si les
# deux exemplaires divergent d'un octet.
COPY garde_exposition.py .
# Le coffre des secrets. Meme raison que ci-dessus : le bac a sable en a besoin
# aussi, et tests/test_coffre.py echoue si les deux exemplaires divergent.
COPY coffre.py .
# Le bouton << Studio >> des pages. Meme raison : deux exemplaires identiques,
# verifies par tests/test_accueil.py.
COPY accueil.py .
COPY app.py .
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
