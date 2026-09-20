"""Les 34 Go du modele video, telecharges PAR LE STUDIO quand on en a besoin.

REGLE POSEE PAR LE PROPRIETAIRE LE 20/09/2026 :
<< si on supprime, l'usage de la ressource demandee demarre par son
telechargement >>. Ce module est ce qui la rend vraie pour la seule ressource
qui ne la respectait pas.

Avant lui, demander un clip << a la maison >> sans les poids donnait une porte
fermee : le clip partait chez le loueur et la page disait << lancez ce script
dans un terminal >>. Un debutant qui vide la place se retrouvait a payer sans
comprendre, et le produit promet l'inverse. Maintenant la demande DEMARRE le
telechargement, et la page propose les trois memes sorties que pour une carte
prise : j'attends, je loue tout de suite, j'annule.

POURQUOI C'EST LE DECIDEUR QUI TELECHARGE, et pas le bac a sable.
Le bac a sable qui fabrique les clips est sur un reseau SANS internet
(`internal: true`), parce que du code quelconque y tourne -- c'est ce qui rend
le produit sur. Le decideur, lui, est sur le reseau normal et n'execute jamais
de code du client. C'est donc lui qui va chercher les poids, dans le MEME
dossier que le bac a sable lira ensuite (le cache Hugging Face du compte, monte
des deux cotes par `docker-compose.gpu.yml`).

Ce module ne fait rien tant qu'on ne l'appelle pas, et il n'a pas d'etat sur le
disque : l'etat, c'est le dossier des poids lui-meme.
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path

DEPOT = os.getenv("VIDEO_MODELE_MAISON", "Wan-AI/Wan2.2-TI2V-5B-Diffusers")

# Le cache monte dans CE conteneur. Vide = pas de surcouche GPU : il n'y a pas
# de carte, donc rien a telecharger, et ce module reste muet.
DOSSIER = (os.getenv("POIDS_VIDEO_DIR") or "").strip()

# MESURE du 20/09/2026, telechargement complet depuis un dossier vide :
# 34 203 034 754 octets, 1 310,9 s, 24,9 Mio/s. Sert a dire un pourcentage et
# un temps restant qui veulent dire quelque chose. Si le modele change, ce
# nombre change : il est ici et nulle part ailleurs.
TOTAL_OCTETS = int(os.getenv("VIDEO_POIDS_OCTETS", "34203034754"))

_MODELE = "models--" + DEPOT.replace("/", "--")

_verrou = threading.Lock()
_etat: dict = {"en_cours": False, "fini": False, "erreur": None, "debut": None}


def cache_hub() -> Path | None:
    """Le sous-dossier `hub/` du cache monte -- l'endroit unique.

    Le cache Hugging Face a DEUX etages : le dossier lui-meme, et son
    sous-dossier `hub/` ou vont les modeles. Le bac a sable, lui, lit
    `/cache/huggingface/hub/models--Wan-AI--...` (`SANDBOX_POIDS_REQUIS`).
    Cette fonction sert aux DEUX usages -- mesurer, et dire a Hugging Face ou
    ecrire -- pour qu'ils ne PUISSENT pas diverger. C'est exactement ce qui
    avait ete rate : voir le commentaire de `_travail()`."""
    return Path(DOSSIER) / "hub" if DOSSIER else None


def chemin() -> Path | None:
    """Le dossier des poids, ou None quand ce conteneur ne voit pas de cache."""
    c = cache_hub()
    return c / _MODELE if c else None


# Un telechargement de 34 Go qui s'arrete laisse un dossier a moitie plein.
# << Le dossier existe >> ne veut donc pas dire << les poids sont la >> : c'est
# le defaut qu'un test a trouve le 20/09, et il existait deja dans le bac a
# sable, ou un essai interrompu faisait croire le Studio pret. Deux marques :
# aucun fichier `.incomplete` (huggingface_hub les nomme ainsi pendant qu'il
# ecrit), et au moins 98 % des octets mesures le 20/09.
SEUIL_COMPLET = 0.98


def present(octets: int | None = None) -> bool:
    c = chemin()
    if not (c and c.is_dir()):
        return False
    try:
        if next(c.rglob("*.incomplete"), None) is not None:
            return False
    except OSError:
        return False
    o = octets_sur_disque() if octets is None else octets
    return o >= SEUIL_COMPLET * TOTAL_OCTETS


def octets_sur_disque() -> int:
    """Ce qui est deja descendu. Mesure, jamais un compteur qu'on tient soi-meme :
    un compteur ment des qu'un telechargement a ete interrompu et repris."""
    c = chemin()
    if not c or not c.is_dir():
        return 0
    total = 0
    for f in c.rglob("*"):
        try:
            if f.is_file():
                total += f.stat().st_size
        except OSError:                       # fichier en cours d'ecriture, efface entre-temps
            continue
    return total


def _travail() -> None:
    from huggingface_hub import snapshot_download
    try:
        # Les deux memes reglages que le script du 19/09 : deux ouvriers (huit
        # s'etaient bloques) et la couche de transfert << Xet >> desactivee
        # (treize minutes sans un octet ecrit, mesure du 19/09).
        os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
        # `cache_dir` EST le correctif du 20/09, trouve en jouant le chemin en
        # vrai depuis un dossier vide. Sans lui, Hugging Face ecrit dans SON
        # dossier par defaut (`/root/.cache/huggingface` dans le conteneur,
        # efface au redemarrage) et pas dans le cache monte : la page annonce
        # << se telecharge : 0 % faits >> pendant que rien n'arrive la ou le
        # Studio regarde -- mesure, 0 octet apres 30 s -- et les 34 Go seraient
        # perdus au premier `docker compose up`. Une phrase rassurante posee
        # sur rien, c'est precisement ce qu'on refuse.
        snapshot_download(DEPOT, max_workers=2, cache_dir=str(cache_hub()))
        with _verrou:
            _etat.update(en_cours=False, fini=True, erreur=None)
    except Exception as exc:                  # noqa: BLE001 -- le motif est rendu tel quel
        with _verrou:
            _etat.update(en_cours=False, fini=False,
                         erreur="%s: %s" % (type(exc).__name__, str(exc)[:300]))


def demarrer() -> dict:
    """Lance le telechargement s'il n'est pas deja parti. Idempotent.

    Appele a chaque demande de clip : c'est voulu. Deux clics coup sur coup ne
    doivent pas faire deux telechargements, et un echec ne doit pas bloquer
    definitivement -- on repart au prochain essai."""
    if not DOSSIER or present():
        return etat()
    with _verrou:
        if not _etat["en_cours"]:
            _etat.update(en_cours=True, fini=False, erreur=None, debut=time.time())
            threading.Thread(target=_travail, name="poids-video", daemon=True).start()
    return etat()


def etat() -> dict:
    """Ce qu'on peut dire a la page, avec ses nombres."""
    with _verrou:
        e = dict(_etat)
    octets = octets_sur_disque()
    complet = present(octets)
    pourcent = min(99.0, 100.0 * octets / TOTAL_OCTETS) if TOTAL_OCTETS else 0.0
    if complet:
        pourcent = 100.0
    reste_s = None
    if e["en_cours"] and octets > 0 and e["debut"]:
        ecoule = time.time() - e["debut"]
        debit = octets / ecoule if ecoule > 0 else 0
        if debit > 0:
            reste_s = max(0, int((TOTAL_OCTETS - octets) / debit))
    return {
        "possible": bool(DOSSIER),
        "present": complet,
        "en_cours": e["en_cours"],
        "erreur": e["erreur"],
        "octets": octets,
        "total_octets": TOTAL_OCTETS,
        "pourcent": round(pourcent, 1),
        "reste_s": reste_s,
        "depot": DEPOT,
    }


def phrase(e: dict | None = None) -> str:
    """L'etat en une phrase montrable telle quelle, avec ses chiffres."""
    e = e or etat()
    if e["present"]:
        return "Le modele video est sur cet ordinateur."
    if not e["possible"]:
        return ("Ce Studio n'a pas de carte branchee : le modele video ne sert a rien ici, "
                "et il n'est pas telecharge.")
    if e["erreur"]:
        return ("Le telechargement du modele video s'est arrete : %s. Il repart au "
                "prochain essai, et il reprend ou il s'etait arrete." % e["erreur"])
    if e["en_cours"]:
        restant = ""
        if e["reste_s"]:
            restant = " Encore environ %d minutes." % max(1, round(e["reste_s"] / 60))
        return ("Le modele video (34 Go) se telecharge maintenant : %.0f %% faits.%s "
                "Une seule fois -- les clips suivants repartent du disque."
                % (e["pourcent"], restant))
    return ("Le modele video (34 Go) n'est pas encore sur cet ordinateur. "
            "Il se telecharge des que vous demandez un clip a la maison.")
