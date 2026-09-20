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

DE COMBIEN IL SE TROMPE, MESURE LE 20/09/2026. L'ecart n'etait jusqu'ici qu'une
precaution de redaction ; il a ete mesure, et il va dans le mauvais sens.

  ce fichier, mois 2026-09 ........  1,3878 $
  Modal, meme periode ............  3,7971 $   (`modal billing report`, somme
                                               des 6 jours factures)
  tableau de bord, meme periode ..  3,80 $     (<< $3.80 in credits >>)
  credit restant annonce .........  26,20 $    (et non 28,61 $)

La comparaison est exacte, et elle l'est pour une raison : le premier usage de
Modal par le Studio est le 09/09/2026 a 11 h (heure de Paris), et rien d'autre
n'avait tourne depuis le 1er septembre -- les 6 jours factures du mois portent
tous le nom `free-ai-studio-sandbox`. Les deux compteurs couvrent donc la MEME
fenetre et le MEME travail. Ce n'est pas un decalage de perimetre.

D'OU VIENT L'ECART -- et ce n'est ni un retard d'affichage, ni le stockage.
Question du proprietaire le meme jour : << c'est une mauvaise lecture de notre
part ou un temps de latence a afficher une consommation ? >>. Les deux branches
ont ete verifiees, et c'est la premiere.

  Pas la latence. Modal l'ecrit dans son API (`modal/_billing.py`) : les
  donnees arrivent << within minutes, although there may be collection
  delays >>. Des minutes, pas des jours -- et surtout un retard ferait afficher
  MOINS que la realite, alors que c'est NOTRE chiffre qui est le plus petit.

  Pas le stockage. C'etait ma premiere explication, et elle etait FAUSSE : je
  l'avais tiree d'un releve du 16/09 sans regarder ce que ce mois-la contenait.
  Le tableau de bord donne la decomposition -- << Deployed Apps: $3.80 >>,
  stockage zero, et la ligne << Network Egress >> non facturee (1,05 Gio sur
  1 Tio inclus).

  C'est le PRIX A LA SECONDE, et l'ecart est localise. Modal, septembre :

    GPU ....... 1,97 $   52 %
    memoire ... 1,37 $   36 %
    processeur  0,46 $   12 %

  Notre modele, pour un clip video sur L4 : 82 % de carte, 13 % de memoire,
  5 % de processeur. Nous traitons comme marginal ce que Modal facture presque
  a moitie. Deux causes nommees : `coeurs` vaut 1,0 par defaut (`MODAL_CPU`)
  alors que la facture correspond a plusieurs coeurs, et la memoire est comptee
  sur ce que le code DEMANDE (`VIDEO_MEMORY_MB`, `CHANSON_MEMORY_MB`) et non
  sur ce que Modal reserve.

CE QU'IL NE FAUT PAS EN FAIRE : multiplier l'estimation par 2,74. Ce rapport est
UNE mesure, sur UN mois, sur UN melange de travaux ; ce n'est pas un coefficient.
Le corriger en le multipliant serait remplacer un nombre faux par un nombre
invente. La consequence, elle, est un fait et doit etre dite : au rythme mesure,
le plafond de 30 $ ne se declenche qu'aux alentours de 82 $ reellement factures,
donc APRES le credit. La reparation est de lire le vrai chiffre -- depenses.py
le sait deja faire -- et elle est ouverte en sous-plan GPU-7 dans PLAN.md, parce
qu'elle touche le garde appele dans 5 fichiers et 67 endroits.

UNE PRECAUTION SUR LE 2,74 LUI-MEME. Il porte sur TOUT septembre, alors que ce
compteur-ci n'existe que depuis le 19/09 : avant cette date, le quatrieme
depensier (run_auto) n'etait compte NULLE PART, ce qui est precisement le defaut
repare ce jour-la. Le rapport melange donc deux compteurs. Sur la seule fenetre
ou celui d'aujourd'hui etait aux commandes -- du 19/09 a maintenant -- Modal ne
porte qu'une depense, 0,1579 $ dans l'heure de 06 h le 20/09, en face de 0,1097 $
comptes ici a 06 h 08 : un rapport de 1,44 sur UN evenement. Le sens est le meme,
l'ampleur non. Les deux chiffres sont ecrits parce qu'ils disent deux choses
differentes, et qu'en garder un seul serait choisir celui qui arrange.
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


def premier_du_mois_suivant(mois: str) -> str:
    """La date ou NOTRE compteur repart de zero, en AAAA-MM-JJ.

    Ce n'est pas une politique de Modal : c'est la consequence de la cle
    `%Y-%m`, un mois neuf ne relisant pas l'ancien. Elle est rendue ICI pour
    que les pages et `scripts/ressources.{sh,ps1}` annoncent la MEME date et
    non chacune la sienne -- deux dates differentes sur le meme compteur, c'est
    un client qui attend une remise a zero deja faite, ou qui lance un calcul
    qui sera refuse.

    CE N'EST PAS, EN SOI, LA DATE DES 30 $ DE MODAL -- et les deux coincident
    quand meme ici, ce qui a ete MESURE le 20/09/2026, pas suppose.

    Les pages publiques ne donnent pas le jour : modal.com/pricing dit
    << $30 / month free compute >>, docs/guide/billing dit << All Workspaces
    are billed monthly >>, aucune ne nomme une date. Un << 1er du mois >> avait
    ete affiche ici sur la foi d'un resume de moteur de recherche ; il a ete
    retire faute de source. La source existe, mais ailleurs : le tableau de
    bord de l'espace de travail. Releve le 20/09/2026 sur `jp-brasile`, page
    << Usage & billing >> : plan Starter, << $30.00 included compute credits
    per month >>, et << Billing Cycle: Sep 1 - Oct 1, 2026 >>. Le cycle est
    donc le mois civil, et notre remise a zero tombe le meme jour.

    Ce qui reste vrai malgre la coincidence : le champ mesure NOTRE compteur,
    d'ou son nom `compteur_remis_a_zero_le` et non `renouvele_le`. Le cycle
    s'affiche par espace de travail et un autre client peut avoir le sien
    ailleurs dans le mois -- la date qui fait foi pour SON credit est celle que
    SON tableau de bord affiche, jamais celle que ce fichier calcule.
    """
    annee, mois_n = int(mois[:4]), int(mois[5:7])
    mois_n += 1
    if mois_n > 12:
        mois_n, annee = 1, annee + 1
    return "%04d-%02d-01" % (annee, mois_n)


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
                "foi est celui de Modal. ET IL COMPTE MOINS QUE LA VRAIE "
                "FACTURE : mesure le 20/09/2026 sur la meme periode, ce fichier "
                "disait 1,39 $ quand Modal en facturait 3,80 $. Le chiffre a "
                "regarder est celui de votre tableau de bord Modal, page "
                "<< Usage & billing >>. Supprimez ce fichier pour repartir de "
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
    etat["compteur_remis_a_zero_le"] = premier_du_mois_suivant(etat["mois"])
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
