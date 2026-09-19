# -*- coding: utf-8 -*-
"""Un seul budget Modal, partage entre le mode autonome et les demandes humaines.

DECISION DE L'UTILISATEUR DU 19/09/2026 (docs/PLAN-PLATEFORME.md, paragraphe 8,
decision 2). Ce qu'elle repare, mesure a l'appui :

Il y avait TROIS compteurs -- 5 $ pour la chanson, 20 $ pour la video, 5 $ pour
le dialogue -- dont la somme egalait EXACTEMENT le credit declare de 30 $
(docker-compose.yml, .env.example), et dont aucun ne voyait les deux autres. Ils
pouvaient donc atteindre leur plafond le meme mois, et le depot l'avait ecrit
dans son propre compose sans le corriger.

Et il y avait un QUATRIEME depensier que personne ne comptait : run_auto() envoie
du code sur Modal des que des jetons sont configures (app.py, fallback_order avec
"modal" en premier), sans passer par aucun budget_verifier. Le mode autonome
depensait donc a cote de tous les compteurs. C'est lui que la decision nomme
quand elle dit << partage entre le mode autonome et les demandes humaines >>.

UN compteur, UN fichier, UN plafond, QUATRE usages. On ne peut plus depasser en
additionnant des plafonds qui s'ignorent : c'est referme par construction, pas
par vigilance.

LA PART RESERVEE. A l'interieur du plafond unique, une part est reservee au mode
autonome : les demandes humaines sont refusees avant de l'entamer. La forme est
reprise telle quelle de la reserve protegee du Boost (free-tier-manager :
`if balance - cap_usd < BOOST_RESERVE_USD: refuse`), qui REFUSE AVANT DE
DEPENSER et non apres. Motif : sans elle, une soiree de clips video mange tout
le credit du mois et la validation automatique n'a plus rien pour tourner --
c'est-a-dire que le mode autonome devient le seul a jeuner, alors qu'il est la
raison d'etre du plafond.

CE QUE CE MODULE NE FAIT PAS. Il ne lit pas le compte Modal : personne ici ne
connait la facture. Il ESTIME a partir des prix publics releves a la main, pour
pouvoir REFUSER avant de lancer. Le compte qui fait foi reste celui de Modal, et
la seule limite qui arrete vraiment la facture est celle reglee chez eux. Les
pages le disent, et doivent continuer de le dire.
"""

import json
import os
import threading
import time
from pathlib import Path
from typing import Dict, Optional

CONFIG_DIR = Path(os.getenv("FREE_AI_CONFIG_DIR", "/config"))
FICHIER = CONFIG_DIR / "modal-budget.json"
_VERROU = threading.RLock()

# Les quatre depensiers. "autonome" est run_auto() : le code qu'un agent ou une
# page envoie au bac a sable et que le routage met sur Modal en premier.
USAGES = ("video", "chanson", "dialogue", "autonome")
USAGES_HUMAINS = ("video", "chanson", "dialogue")

# Prix Modal a la seconde, releves a la main sur https://modal.com/pricing.
# Ils servent a COMPTER, pas a facturer. Un prix qui change chez Modal sans
# changer ici rend l'estimation fausse : c'est pourquoi les pages affichent la
# date du releve.
#
# TABLE UNIQUE depuis le 19/09/2026. Il y en avait trois : video.py portait les
# HUIT cartes, chanson.py et dialogue.py n'en portaient que QUATRE. Les quatre
# communes s'accordaient -- un test le gardait -- mais la troncature avait une
# consequence que personne n'avait vue : prix_seconde() facture une carte
# inconnue au prix de la plus chere CONNUE. Une chanson sur A100 etait donc
# estimee au tarif L40S (0,000542 contre 0,000583), et sur H100 a la moitie du
# vrai prix (0,000542 contre 0,001097). Se tromper vers le bas est exactement ce
# qu'un compteur de refus ne doit jamais faire.
PRIX_RELEVE_LE = "2026-09-17"
PRIX_GPU_USD_S: Dict[str, float] = {
    "T4": 0.000164,
    "L4": 0.000222,
    # Modal publie cette carte sous le nom << A10 >> (verifie le 17/09/2026) ;
    # << A10G >> est l'ancien nom, garde pour les configurations ecrites avant.
    "A10": 0.000306,
    "A10G": 0.000306,
    "L40S": 0.000542,
    "A100": 0.000583,
    "A100-80GB": 0.000694,
    "H100": 0.001097,
}
PRIX_CPU_USD_S = 0.0000131       # par coeur physique et par seconde
PRIX_MEMOIRE_USD_S = 0.00000222  # par Gio et par seconde

# Le plafond unique. Par defaut : le credit declare lui-meme. Ce n'est pas une
# generosite, c'est la seule valeur qui ne soit pas inventee -- l'ancien 5+20+5
# valait deja 30, a ceci pres qu'il ne comptait pas le mode autonome.
CREDIT_OFFERT_USD = float(os.getenv("MODAL_CREDIT_MENSUEL_USD", "30"))
PLAFOND_USD = float(os.getenv("MODAL_BUDGET_USD_PAR_MOIS", str(CREDIT_OFFERT_USD)))

# Part du plafond reservee au mode autonome, que les demandes humaines ne
# peuvent pas entamer. 50 % par decision du 19/09/2026, ajustable.
PART_RESERVEE_AUTONOME = float(os.getenv("MODAL_PART_RESERVEE_AUTONOME", "0.5"))
RESERVE_AUTONOME_USD = PLAFOND_USD * PART_RESERVEE_AUTONOME

# Les trois compteurs d'avant, repris une seule fois pour ne pas perdre le mois
# en cours. Un compteur qui oublie est un compteur qui ment.
#
# Calcules a partir de FICHIER.parent et non de CONFIG_DIR : les tests deplacent
# FICHIER vers un repertoire jetable, et une constante figee a l'import les
# ferait lire le vrai /config du poste.
_NOMS_ANCIENS = {
    "video": "video-budget.json",
    "chanson": "chanson-budget.json",
    "dialogue": "dialogue-budget.json",
}
_CLE_D_APPELS = {"video": "clips", "chanson": "chansons", "dialogue": "dialogues"}


def _anciens() -> Dict[str, Path]:
    return {u: FICHIER.parent / nom for u, nom in _NOMS_ANCIENS.items()}


class BudgetDepasse(RuntimeError):
    """Le plafond du mois serait franchi : rien n'est lance."""


def _mois_courant() -> str:
    return time.strftime("%Y-%m")


def _vide() -> dict:
    return {
        "mois": _mois_courant(),
        "secondes": 0.0,
        "usd": 0.0,
        "usd_par_usage": {u: 0.0 for u in USAGES},
        "appels": {u: 0 for u in USAGES},
        "repris_des_anciens": [],
    }


def _reprendre_les_anciens() -> dict:
    """Additionne ce que les trois compteurs d'avant ont deja compte CE MOIS-CI.

    Ne tourne qu'une fois : le resultat est ecrit dans le nouveau fichier, et les
    anciens sont laisses en place -- on n'efface rien, et ils servent de preuve
    si le report est conteste. Un mois plus ancien est ignore : il est clos.
    """
    etat = _vide()
    for usage, chemin in _anciens().items():
        try:
            brut = json.loads(chemin.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        if brut.get("mois") != etat["mois"]:
            continue
        try:
            usd = float(brut.get("usd", 0))
            secondes = float(brut.get("secondes", 0))
            appels = int(brut.get(_CLE_D_APPELS[usage], 0))
        except (ValueError, TypeError):
            continue
        if usd <= 0 and secondes <= 0 and appels <= 0:
            continue
        etat["usd"] += usd
        etat["secondes"] += secondes
        etat["usd_par_usage"][usage] += usd
        etat["appels"][usage] += appels
        etat["repris_des_anciens"].append(chemin.name)
    return etat


def _relire() -> dict:
    """L'etat brut du mois en cours, sans les champs calcules."""
    etat = _vide()
    try:
        brut = json.loads(FICHIER.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return _reprendre_les_anciens()
    if brut.get("mois") != etat["mois"]:
        return etat
    try:
        etat["secondes"] = float(brut.get("secondes", 0))
        etat["usd"] = float(brut.get("usd", 0))
    except (ValueError, TypeError):
        return etat
    for u in USAGES:
        try:
            etat["usd_par_usage"][u] = float((brut.get("usd_par_usage") or {}).get(u, 0))
            etat["appels"][u] = int((brut.get("appels") or {}).get(u, 0))
        except (ValueError, TypeError):
            pass
    etat["repris_des_anciens"] = list(brut.get("repris_des_anciens") or [])
    return etat


def _ecrire(etat: dict) -> None:
    FICHIER.parent.mkdir(parents=True, exist_ok=True)
    tmp = FICHIER.with_suffix(".tmp")
    tmp.write_text(json.dumps({
        "mois": etat["mois"],
        "secondes": round(etat["secondes"], 1),
        "usd": round(etat["usd"], 4),
        "usd_par_usage": {u: round(etat["usd_par_usage"][u], 4) for u in USAGES},
        "appels": dict(etat["appels"]),
        "repris_des_anciens": etat["repris_des_anciens"],
        "note": "Compteur UNIQUE des depenses Modal, tous usages confondus : la "
                "video, la chanson, le dialogue et le mode autonome du bac a "
                "sable. Estimation locale, pas une facture : le compte qui fait "
                "foi est celui de Modal. Supprimez ce fichier pour repartir de "
                "zero.",
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(FICHIER)


def lire() -> dict:
    """L'etat du mois, champs calcules compris. Un mois neuf repart de zero."""
    with _VERROU:
        etat = _relire()
        if etat["repris_des_anciens"] and not FICHIER.exists():
            # Le report ne vaut que s'il est ecrit : sinon il se referait a
            # chaque lecture et doublerait des la premiere depense.
            _ecrire(etat)
    etat["plafond_usd"] = PLAFOND_USD
    etat["credit_offert_usd"] = CREDIT_OFFERT_USD
    etat["prix_releve_le"] = PRIX_RELEVE_LE
    etat["reste_usd"] = max(0.0, PLAFOND_USD - etat["usd"])
    etat["reserve_autonome_usd"] = RESERVE_AUTONOME_USD
    etat["part_reservee_autonome"] = PART_RESERVEE_AUTONOME
    # Ce qu'une demande HUMAINE peut encore depenser sans entamer la reserve.
    etat["reste_humain_usd"] = max(0.0, etat["reste_usd"] - RESERVE_AUTONOME_USD)
    return etat


def vue(usage: str) -> dict:
    """L'etat du mois VU PAR cet usage-la.

    Meme compteur pour tous, mais pas le meme plafond : une demande humaine
    s'arrete avant la reserve du mode autonome. Les pages affichent donc
    `plafond_usd` (ce qu'ELLES peuvent atteindre) et `plafond_total_usd` (le
    budget entier) -- deux nombres differents qui disent chacun la verite, et
    qu'il serait faux de confondre.
    """
    if usage not in USAGES:
        raise ValueError("usage inconnu : %r (attendus : %s)" % (usage, ", ".join(USAGES)))
    etat = lire()
    etat["plafond_total_usd"] = PLAFOND_USD
    etat["plafond_usd"] = plafond_de(usage)
    etat["reste_usd"] = max(0.0, etat["plafond_usd"] - etat["usd"])
    etat["usage"] = usage
    return etat


def prix_seconde(gpu: Optional[str], memoire_mb: int,
                 coeurs: Optional[float] = None) -> float:
    """Carte + processeur + memoire demandee, par seconde.

    Deux cas a ne pas confondre, et c'est le mode autonome qui les a rendus
    visibles -- lui seul lance des travaux SANS carte :

    - AUCUNE carte demandee (None ou chaine vide) : Modal n'en facture aucune,
      la part carte vaut zero. La compter au prix du H100 refuserait tous les
      travaux processeur, qui sont les moins chers du service.
    - une carte INCONNUE : comptee au prix de la plus chere connue. Se tromper
      vers le haut est le bon sens du refus -- on prefere refuser un calcul de
      trop que d'en laisser passer un qui creuse la facture.
    """
    nom = str(gpu).strip().upper() if gpu else ""
    carte = PRIX_GPU_USD_S.get(nom, max(PRIX_GPU_USD_S.values())) if nom else 0.0
    if coeurs is None:
        coeurs = float(os.getenv("MODAL_CPU", "1.0"))
    return carte + PRIX_CPU_USD_S * coeurs + PRIX_MEMOIRE_USD_S * (memoire_mb / 1024)


def plafond_de(usage: str) -> float:
    """Ce que cet usage-la peut atteindre. Le mode autonome va jusqu'au bout."""
    if usage == "autonome":
        return PLAFOND_USD
    return max(0.0, PLAFOND_USD - RESERVE_AUTONOME_USD)


def verifier(usage: str, gpu: Optional[str], duree_max_s: int, memoire_mb: int,
             quoi: str = "Ce calcul", suite: str = "") -> dict:
    """Refuse AVANT de lancer si le PIRE CAS depasse ce que cet usage peut prendre.

    Le pire cas, c'est le calcul qui va jusqu'au bout de son delai sans rien
    rendre. C'est le seul chiffre honnete : au moment de lancer, personne ne sait
    combien de temps prendra le calcul.
    """
    etat = vue(usage)
    pire = prix_seconde(gpu, memoire_mb) * duree_max_s
    plafond = etat["plafond_usd"]
    if etat["usd"] + pire > plafond:
        if usage == "autonome":
            detail = (
                f"Plafond Modal du mois atteint. Déjà dépensé : "
                f"{etat['usd']:.2f} $ sur {PLAFOND_USD:.2f} $."
            )
        else:
            detail = (
                f"Budget Modal du mois atteint pour les demandes. Déjà dépensé, "
                f"tous usages confondus : {etat['usd']:.2f} $ sur "
                f"{PLAFOND_USD:.2f} $, dont {RESERVE_AUTONOME_USD:.2f} $ sont "
                f"réservés au mode autonome et ne peuvent pas être entamés ici."
            )
        # `suite` porte la sortie de secours propre a l'usage -- pour la chanson,
        # << Kaggle reste possible, gratuitement. >>. Un refus qui ne dit pas ce
        # qui reste ouvert se lit comme une panne.
        raise BudgetDepasse(
            f"{detail} {quoi} peut coûter jusqu'à {pire:.2f} $, donc il n'est pas "
            f"lancé. {suite + ' ' if suite else ''}Le compteur repart tout seul le "
            f"1er du mois prochain."
        )
    etat["cout_max_usd"] = round(pire, 3)
    return etat


def poser(usage: str, secondes: float, usd: float, appels: int) -> None:
    """Pose l'etat de CET usage, en recalculant le total. Outil de TEST.

    Le service ne s'en sert jamais : il passe par consommer(), qui ajoute. Il
    existe parce que les tests ont besoin d'amener le compteur au bord du
    plafond sans lancer un calcul reel, et qu'ecrire le fichier a la main dans
    chaque test reconstituerait le format a cote du module qui le definit.
    """
    if usage not in USAGES:
        raise ValueError("usage inconnu : %r" % (usage,))
    with _VERROU:
        etat = _relire()
        etat["usd"] = max(0.0, etat["usd"] - etat["usd_par_usage"].get(usage, 0.0)) + float(usd)
        etat["usd_par_usage"][usage] = float(usd)
        etat["secondes"] = float(secondes)
        etat["appels"][usage] = int(appels)
        _ecrire(etat)


def consommer(usage: str, gpu: Optional[str], secondes: float, memoire_mb: int) -> dict:
    """Encaisse le temps reellement passe, MEME si le calcul a echoue.

    Un calcul qui plante a la derniere minute a quand meme loue la carte pendant
    ce temps-la. Ne compter que les reussites donnerait un compteur menteur.
    """
    if usage not in USAGES:
        raise ValueError("usage inconnu : %r" % (usage,))
    secondes = max(0.0, float(secondes))
    with _VERROU:
        etat = _relire()
        depense = prix_seconde(gpu, memoire_mb) * secondes
        etat["secondes"] += secondes
        etat["usd"] += depense
        etat["usd_par_usage"][usage] += depense
        etat["appels"][usage] += 1
        _ecrire(etat)
    return vue(usage)
