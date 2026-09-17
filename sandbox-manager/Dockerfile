FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Tous les modules du service. La liste explicite a fait tomber le conteneur le
# 16/09/2026 : un module ajoute, oublie ici, et uvicorn refuse de demarrer sur un
# ModuleNotFoundError. Les tests tournent hors conteneur et ne peuvent pas le
# voir. Ce dossier ne contient que le service.
COPY *.py ./
# abcjs 6.7.0 (MIT), qui dessine les portees sur /chanson. La ligne ci-dessus ne
# prend que le Python : sans celle-ci, le fichier reste sur le disque de l'hote
# et la page sert un 404 en silence. Nom explicite plutot que *.js : si le
# fichier disparait, la construction echoue ICI, bruyamment, au lieu de livrer
# une page muette. Meme raison que le commentaire ci-dessus.
COPY abcjs-basic-min.js ./
RUN mkdir -p /workspace/jobs /workspace/artifacts
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
