# Permissions de l'assistant de codage

Free AI Studio n'essaie jamais d'activer ou de contourner des permissions sans l'accord de l'utilisateur.

Pour une expérience complète, l'assistant de codage devrait idéalement avoir accès à :

- **Fichiers du projet** : lire et modifier le dépôt.
- **Terminal** : lancer Docker, scripts et tests.
- **Web** : consulter les documentations officielles et vérifier les APIs actuelles.

## Ce que l'assistant doit vérifier

Au début d'une session d'installation ou de développement, il doit déterminer quelles capacités sont réellement disponibles.

Exemple de message attendu :

```text
Capacités détectées

✓ Accès aux fichiers
✓ Terminal
ℹ Accès Web : à vérifier / autoriser

Je peux installer le projet maintenant.
Pour ajouter de nouveaux fournisseurs automatiquement, l'accès Web est recommandé.
```

## Si l'accès Web n'est pas disponible

L'assistant doit :

1. le signaler clairement ;
2. ne pas inventer de documentation ou d'endpoint ;
3. demander à l'utilisateur d'autoriser l'accès Web dans l'extension si cette option existe ;
4. continuer uniquement avec les informations déjà présentes dans le projet.

## Sécurité

Même avec accès Web et terminal, l'assistant ne doit jamais :

- activer un abonnement payant ;
- ajouter un moyen de paiement ;
- désactiver le mode gratuit sans demande explicite ;
- publier le fichier `.env` ;
- afficher les clés API ;
- contourner les confirmations ou permissions de VS Code.

Les autorisations exactes dépendent de l'assistant utilisé (Gemini Code Assist, Continue, Cline, Copilot ou autre) et de sa configuration.
