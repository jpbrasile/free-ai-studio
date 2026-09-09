# Boost ponctuel — guide débutant

Le mode normal reste **100 % gratuit**.

Le Boost est une option ponctuelle pour les tâches où un modèle premium peut réellement apporter quelque chose.

## Ce que le débutant doit comprendre

| Tâche | Gain attendu du Boost |
|---|---|
| Question courante | Faible |
| Traduction / petit résumé | Faible |
| Raisonnement difficile | Élevé |
| Gros projet de code | Élevé |
| Très long document | Moyen à élevé |
| Analyse complexe multi-étapes | Élevé |
| Plusieurs éléments visuels / contexte riche | Moyen à élevé |

Le système évalue la complexité **localement**, sans faire un appel IA supplémentaire.

Il renvoie :

- `gain_expected` : faible / moyen / élevé ;
- les raisons ;
- un plafond de coût suggéré.

## Budget recommandé

Configuration par défaut :

```env
OPENROUTER_PROTECTED_RESERVE_USD=10
OPENROUTER_BOOST_TOTAL_BUDGET_USD=5
OPENROUTER_BOOST_DEFAULT_CAP_USD=0.50
OPENROUTER_BOOST_MAX_SINGLE_USD=1.00
OPENROUTER_BOOST_SESSION_MINUTES=60
```

Avec 15 $ de crédits OpenRouter, Free AI Studio peut donc protéger logiquement 10 $ et n'autoriser que 5 $ de Boost au total.

Important : OpenRouter gère un solde unique. La séparation 10 $ / 5 $ est imposée par Free AI Studio, pas par OpenRouter.

## Activation sécurisée

Le Boost exige `OPENROUTER_MANAGEMENT_KEY`.

Avant activation, Free AI Studio vérifie le solde. L'activation est refusée si le plafond demandé pourrait faire passer le solde sous la réserve protégée.

Le Boost :

1. est désactivé par défaut ;
2. doit être activé explicitement ;
3. possède un plafond par session ;
4. possède un budget global ;
5. expire automatiquement ;
6. retourne ensuite au mode gratuit.

## Pourquoi le streaming est désactivé pendant le Boost

Pendant une requête payante, Free AI Studio demande à OpenRouter les données `usage` afin d'enregistrer le coût réellement retourné.

Pour simplifier et fiabiliser le contrôle du budget, les réponses Boost ne sont pas streamées dans cette V1.

## Tableau local

Ouvrir :

```text
http://127.0.0.1:8010/boost
```

Ce tableau explique à quoi sert le Boost et rappelle les limites financières.

## Limite de sécurité importante

Le contrôle local réduit fortement le risque de dépense accidentelle, mais un client ne peut pas garantir à lui seul qu'un fournisseur externe n'aura jamais un changement de facturation ou de comptabilisation.

Le budget OpenRouter natif / les contrôles de dépenses du compte doivent également être utilisés lorsque disponibles.
