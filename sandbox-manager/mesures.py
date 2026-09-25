"""La base de mesures : une ligne par usage, sur CE poste d'abord.

docs/PLAN-PLATEFORME.md, « Une base de mesures, anonyme, locale d'abord », et
la decision du 25/09/2026 sur le contenu des clients : date, fonction,
endroit, duree, refus -- AUCUNE phrase ecrite par une personne. La forme est
fermee : un champ inconnu ou un texte libre est refuse ici, pas a la relecture.

Un fichier par mois (AAAA-MM.jsonl), rien n'est efface. Rien ne part vers
l'administrateur : la remontee viendra avec son interrupteur, eteint par
defaut, et son ecran d'accord.
"""
from __future__ import annotations

import datetime as dt
import json
import threading
from pathlib import Path

# Les seuls champs, et pour les textes les seules valeurs admises.
NOMBRES = {"duree_s", "cout_usd", "pages_web", "citations"}
BOOLEENS = {"ok", "web"}
TEXTES = {
    "endroit": {"notebooklm", "local", "modal", "kaggle", "colab"},
    "motif": {"", "session", "quota", "plein", "echec"},
}
FONCTIONS = {"notebooklm.question"}

_verrou = threading.Lock()


def ecrire(dossier: Path, fonction: str, **champs) -> dict:
    """Ajoute une ligne au fichier du mois. `ValueError` si la ligne sort de
    la forme fermee : c'est une faute de programmation, a voir en test."""
    if fonction not in FONCTIONS:
        raise ValueError("fonction inconnue : %s" % fonction)
    ligne = {"date": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
             "fonction": fonction}
    for cle, valeur in champs.items():
        if cle in NOMBRES and isinstance(valeur, (int, float)) and not isinstance(valeur, bool):
            ligne[cle] = round(float(valeur), 3) if isinstance(valeur, float) else valeur
        elif cle in BOOLEENS and isinstance(valeur, bool):
            ligne[cle] = valeur
        elif cle in TEXTES and valeur in TEXTES[cle]:
            ligne[cle] = valeur
        else:
            raise ValueError("champ refuse par la base de mesures : %s" % cle)
    dossier.mkdir(parents=True, exist_ok=True)
    fichier = dossier / (ligne["date"][:7] + ".jsonl")
    with _verrou, fichier.open("a", encoding="utf-8") as f:
        f.write(json.dumps(ligne, ensure_ascii=False) + "\n")
    return ligne
