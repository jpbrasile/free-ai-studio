# Dépannage

## Docker n'est pas trouvé

Vérifier :

```bash
docker --version
docker compose version
```

Sous Windows/macOS, ouvrir Docker Desktop et attendre qu'il soit démarré.

## Le port 3000 est déjà utilisé

Modifier dans `docker-compose.yml` :

```yaml
ports:
  - "3001:8080"
```

Puis ouvrir http://localhost:3001.

## Open WebUI ne démarre pas

```bash
docker compose ps
docker compose logs --tail=200
```

## Réinitialiser uniquement le conteneur

```bash
docker compose down
docker compose pull
docker compose up -d
```

Les données restent dans le volume Docker.

## Supprimer toutes les données

Attention : ceci supprime l'historique Open WebUI.

```bash
docker compose down -v
```

## Vérifier la configuration

Linux/macOS :

```bash
./scripts/diagnose.sh
./scripts/check-providers.sh
```
