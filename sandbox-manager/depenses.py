"""Ce que Modal facture vraiment, a cote de ce que le Studio estime.

Les compteurs de la video et de la chanson sont des estimations locales : un
temps mesure multiplie par un prix recopie a la main. Ils servent a REFUSER
avant de lancer, donc ils doivent marcher hors ligne, sans jeton et sans
reseau. Ce module ne les remplace pas et ne les corrige pas : il va chercher,
quand c'est possible, le chiffre que Modal lui-meme annonce, pour que l'ecart
se voie au lieu de se supposer.

Le secret ne passe pas par ici. `modal billing summary` exige un jeton, mais ce
module ne le lit jamais : il lance la CLI comme sous-processus, qui herite de
l'environnement du processus -- ou apply_stored_secrets() a deja pose
MODAL_TOKEN_ID et MODAL_TOKEN_SECRET. Rien n'est recopie, rien n'est journalise.

Trois prudences, parce qu'une page ne doit jamais dependre d'un service
distant : un delai court, un cache, et aucune exception qui remonte. Quand
Modal ne repond pas, l'etat dit pourquoi, en francais, et la page continue
d'afficher l'estimation locale.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from typing import Optional

# Assez court pour qu'une page ne pende pas, assez long pour un aller-retour
# reseau depuis un conteneur.
DELAI_S = float(os.getenv("MODAL_BILLING_TIMEOUT_SECONDS", "25"))

# Un chiffre de facturation ne bouge pas a la seconde, et chaque appel cree un
# processus : dix minutes de cache. Un echec se garde moins longtemps, pour
# qu'une panne passagere ne fige pas l'affichage pendant dix minutes.
CACHE_S = float(os.getenv("MODAL_BILLING_CACHE_SECONDS", "600"))
CACHE_ECHEC_S = 60.0

# La sortie brute est rendue pour que l'on voie la forme exacte du JSON sans
# avoir a deviner. Bornee : elle finit dans une page web.
MAX_BRUT = 4000

_VERROU = threading.Lock()
_CACHE: dict = {}

# Noms de champs, normalises (minuscules, sans separateur). Ils ne sont pas
# documentes dans l'aide de la CLI : ceux-ci ont ete RELEVES le 16/09/2026 sur
# une vraie reponse de l'espace de travail, pas devines. La premiere version de
# ce fichier les devinait, et se trompait sur cinq des six.
#
# Reponse du 16/09/2026, telle quelle :
#   metered_cost 1.08346824, billed_cost 0E-8
#   adjustments           : credits -0.70000000, free_storage -0.38346824
#   metered_cost_breakdown: deployed_apps 0.70356317, volumes 0.38346824
#
# Modal previent que son modele de facturation evolue. Si un nom change, la
# liste des montants se vide et la sortie brute reste affichee : on ne devine
# pas, on montre.
_CHAMPS = {
    "facture": ("billedcost",),
    "mesure": ("meteredcost",),
    "calcul": ("deployedapps",),
    "stockage": ("volumes",),
    "credits": ("credits",),
    "stockage_offert": ("freestorage",),
}


def _normaliser(cle: str) -> str:
    return "".join(c for c in cle.lower() if c.isalnum())


def _nombre(valeur) -> Optional[float]:
    """Un montant peut arriver en nombre ou en texte (« $0.73 »). Rien d'autre
    n'est converti : mieux vaut ne pas savoir que se tromper de facteur."""
    if isinstance(valeur, bool):
        return None
    if isinstance(valeur, (int, float)):
        return float(valeur)
    if isinstance(valeur, str):
        propre = valeur.strip().replace("$", "").replace(",", "").replace(" ", "")
        try:
            return float(propre)
        except ValueError:
            return None
    return None


def _reconnaitre(objet, profondeur: int = 0) -> dict:
    """Cherche les montants connus dans le JSON rendu par Modal, a plat puis
    dans les sous-objets. Ce qui n'est pas reconnu n'est pas invente : il reste
    dans la sortie brute, visible."""
    trouves: dict = {}
    if not isinstance(objet, dict) or profondeur > 2:
        return trouves
    for cle, valeur in objet.items():
        norme = _normaliser(cle)
        for nom, candidats in _CHAMPS.items():
            if nom in trouves:
                continue
            if norme in candidats:
                montant = _nombre(valeur)
                if montant is not None:
                    trouves[nom] = montant
    for valeur in objet.values():
        if isinstance(valeur, dict):
            for nom, montant in _reconnaitre(valeur, profondeur + 1).items():
                trouves.setdefault(nom, montant)
    return trouves


def _sans_jeton() -> bool:
    return not (os.getenv("MODAL_TOKEN_ID", "").strip()
                and os.getenv("MODAL_TOKEN_SECRET", "").strip())


def _interroger(cycle: str) -> dict:
    """Un aller-retour vers Modal. Ne leve jamais : rend toujours un etat."""
    base = {
        "disponible": False,
        "cycle": cycle,
        "montants": {},
        "brut": None,
        "raison": None,
        "releve_le": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    if _sans_jeton():
        base["raison"] = ("Aucun jeton Modal enregistré : le Studio ne peut pas demander "
                          "la facture. Collez vos jetons sur la page Clés.")
        return base
    try:
        fin = subprocess.run(
            ["modal", "billing", "summary", "--for", cycle, "--json"],
            capture_output=True, text=True, timeout=DELAI_S, check=False,
        )
    except FileNotFoundError:
        base["raison"] = "La commande « modal » n'est pas installée dans ce conteneur."
        return base
    except subprocess.TimeoutExpired:
        base["raison"] = f"Modal n'a pas répondu en {DELAI_S:.0f} s."
        return base
    except OSError as err:
        base["raison"] = f"La commande « modal » n'a pas pu être lancée ({err.__class__.__name__})."
        return base

    if fin.returncode != 0:
        detail = (fin.stderr or fin.stdout or "").strip()
        base["brut"] = detail[:MAX_BRUT] or None
        base["raison"] = f"« modal billing summary » a échoué (code {fin.returncode})."
        return base

    sortie = (fin.stdout or "").strip()
    base["brut"] = sortie[:MAX_BRUT] or None
    try:
        charge = json.loads(sortie)
    except ValueError:
        base["raison"] = "Modal a répondu, mais pas en JSON lisible. La sortie brute est ci-dessous."
        return base

    base["montants"] = _reconnaitre(charge)
    base["disponible"] = True
    if not base["montants"]:
        base["raison"] = ("Modal a répondu, mais le Studio n'a reconnu aucun montant dans sa "
                          "réponse. La sortie brute est ci-dessous, telle quelle.")
    return base


def etat(cycle: str = "this month", forcer: bool = False) -> dict:
    """Etat de facturation, en cache. Jamais d'exception vers l'appelant."""
    maintenant = time.time()
    with _VERROU:
        garde = _CACHE.get(cycle)
        if garde and not forcer:
            age = maintenant - garde["horodatage"]
            duree = CACHE_S if garde["etat"].get("disponible") else CACHE_ECHEC_S
            if age < duree:
                rendu = dict(garde["etat"])
                rendu["age_s"] = round(age, 1)
                rendu["depuis_cache"] = True
                return rendu
    resultat = _interroger(cycle)
    with _VERROU:
        _CACHE[cycle] = {"horodatage": time.time(), "etat": resultat}
    rendu = dict(resultat)
    rendu["age_s"] = 0.0
    rendu["depuis_cache"] = False
    return rendu
