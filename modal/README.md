# Modal — backend automatique principal

Modal est le premier moteur d'exécution distant du Sandbox Manager **lorsqu'il est explicitement configuré**.

Activation dans `.env` :

```dotenv
MODAL_ENABLED=true
MODAL_TOKEN_ID=...
MODAL_TOKEN_SECRET=...
```

Le manager utilise `modal.Sandbox` directement. Aucun déploiement manuel d'une Function n'est nécessaire pour les jobs Python génériques : un Sandbox temporaire est créé, le code est copié, exécuté, ses artefacts sont récupérés, puis le Sandbox est terminé.

Le routage recommandé est :

```text
Modal → Local → Kaggle → Colab handoff
```

Kaggle et Colab gardent parallèlement leurs **accès directs utilisateur** dans l'interface Sandbox.

## Coût et sécurité

Modal possède sa propre politique de crédits et de facturation. Le Studio ne peut pas certifier qu'un compte est encore couvert par du crédit gratuit ; c'est pourquoi `MODAL_ENABLED=false` reste la valeur d'installation. Fournir les tokens ne suffit pas : l'utilisateur doit aussi activer Modal.

Le réseau du Sandbox Modal est bloqué sauf si le job demande `internet=true`. Aucun secret fournisseur IA n'est injecté dans le code exécuté.

Voir `../docs/SANDBOX.md` et `../docs/MODAL_CATALOG.md`.
