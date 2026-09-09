# Expérience débutant — Free AI Studio

## Principe

Le débutant choisit **une intention**, jamais un fournisseur.

Interface cible :

```text
FREE AI STUDIO

💬 Chat      🎨 Image      🎬 Vidéo
🎤 Voix     📚 Étudier    💻 Code

🟢 Gratuit par défaut
```

Les noms OpenRouter, Groq, Gemini, ComfyUI, Modal, Docker et les endpoints restent dans les paramètres, diagnostics et documentation technique.

## Page d'accueil unifiée

Après démarrage :

```text
http://127.0.0.1:8010/studio
```

Elle sert de portail simple vers les fonctions principales.

Open WebUI reste l'interface de conversation principale :

```text
http://localhost:3000
```

## Règles UX

1. Afficher l'intention avant la technologie.
2. Ne jamais demander au débutant de choisir un fournisseur pour une tâche normale.
3. Afficher `Gratuit` comme état par défaut.
4. Masquer les détails techniques sauf dans les diagnostics/paramètres.
5. En cas d'échec, essayer automatiquement un fallback gratuit avant d'afficher une erreur.
6. Ne proposer un Boost que lorsque le gain attendu est moyen ou élevé.
7. Toujours expliquer le bénéfice concret du Boost.
8. Toujours afficher son plafond de coût avant activation.
9. Retour automatique au gratuit.
10. NotebookLM reste un complément externe clairement identifié.

## Exemple Boost

```text
Cette tâche est difficile.

🟢 Continuer gratuitement
   Résultat correct attendu

⚡ Utiliser Boost
   Gain attendu : ÉLEVÉ
   Raison : gros projet de code
   Coût maximum : 0,25 $
   Budget Boost restant : 4,50 $
```

L'utilisateur peut toujours choisir le gratuit.

## Objectif à terme

La page `/studio` est la couche d'accueil V1. L'étape suivante consiste à transformer cette logique en navigation native/personnalisée dans l'interface finale, sans casser la compatibilité Open WebUI.
