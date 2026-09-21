"""La carte de la maison : y en a-t-il une, et reste-t-il de la place MAINTENANT.

Chantier ouvert le 19/09/2026 sur demande de l'utilisateur. Jusqu'a ce jour,
trois fichiers du depot annoncaient << GPU local d'abord >> et AUCUN code ne
l'implementait : `docker-compose.yml` ne nommait la carte nulle part, le backend
appele `local` est le bac a sable SUR PROCESSEUR, et la video part sur Modal par
defaut. Resultat mesure le 19/09 : la 4090 libre a 24 138 Mo sur 24 564, et
1,2781 $ de calcul loues chez Modal dans le mois.

Ce module ne fait qu'une chose, et c'est la seule qui soit difficile : **repondre
a << peut-on lancer CE travail sur la carte, la, tout de suite >>**.

Quatre faits mesures qui dictent sa forme :

1. **Docker passe deja la carte sur cette machine** (19/09) : `docker run --gpus
   all python:3.12-slim nvidia-smi` rend la 4090 et sa memoire libre. Aucune
   image CUDA n'est necessaire pour la SONDE -- le runtime injecte `nvidia-smi`.
   La surcouche `docker-compose.gpu.yml` suffit donc a rendre ce module utile.
2. **<< Une carte existe >> ne repond pas a la question.** Elle est partagee :
   un serveur LLM y tenait 15,5 Go le 04/09, et un autre travail peut la
   prendre entre deux lancements. La mesure se fait AU LANCEMENT, jamais au
   demarrage du service, et elle se refait au lancement suivant.
3. **Elle peut se remplir entre la mesure et le lancement**, donc on garde une
   marge (`MARGE_MO`) et on traite le manque de memoire comme un repli vers
   Modal, jamais comme une panne du Studio.
4. **On n'arrete jamais un processus qui tient la carte.** Occupee = on va
   ailleurs. C'est la regle du proprietaire sur son materiel partage, et elle
   vaut ici sans discussion.

Aucune exception ne sort d'ici : pas de carte, `nvidia-smi` absent, sortie
illisible ou trop lente donnent tous le meme resultat honnete -- << aucune carte
vue >> -- et le routage part sur Modal comme avant.
"""
from __future__ import annotations

import os
import shutil
import subprocess

# Ce que la sonde s'autorise a attendre. nvidia-smi repond en moins d'une
# seconde sur une machine saine ; au-dela, quelque chose ne va pas et le travail
# n'a pas a attendre pour le savoir.
DELAI_S = int(os.getenv("GPU_LOCAL_DELAI_S", "10"))

# La memoire libre mesuree n'est pas celle qu'on aura : un autre travail peut
# commencer dans la seconde. La marge n'est pas une precaution de style, c'est
# la difference entre un repli propre et un travail mort a mi-chemin.
MARGE_MO = int(os.getenv("GPU_LOCAL_MARGE_MO", "1024"))

# Mis a false par l'utilisateur qui veut tout envoyer chez Modal sans toucher au
# reste. Un interrupteur explicite vaut mieux qu'un fichier a deplacer.
ACTIF = os.getenv("GPU_LOCAL_ACTIF", "true").strip().lower() != "false"

_REQUETE = ("--query-gpu=name,memory.total,memory.free", "--format=csv,noheader,nounits")


def releve(delai_s: int | None = None) -> dict:
    """L'etat de la carte, tel qu'il est a cette seconde.

    Rend toujours un dictionnaire, jamais une exception : `vue` dit si une carte
    a ete mesuree, `motif` dit pourquoi quand elle ne l'a pas ete."""
    if not ACTIF:
        return _rien("GPU_LOCAL_ACTIF=false : le GPU local est eteint par reglage")

    chemin = shutil.which("nvidia-smi")
    if not chemin:
        return _rien(
            "nvidia-smi absent du conteneur : la carte n'y est pas passee "
            "(surcouche docker-compose.gpu.yml non appliquee, ou machine sans carte)"
        )

    try:
        sortie = subprocess.run(
            [chemin, *_REQUETE],
            capture_output=True,
            text=True,
            timeout=delai_s if delai_s is not None else DELAI_S,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return _rien("nvidia-smi n'a pas repondu : %s" % type(exc).__name__)

    if sortie.returncode != 0:
        detail = (sortie.stderr or "").strip().splitlines()
        return _rien("nvidia-smi a refuse (code %d) : %s"
                     % (sortie.returncode, detail[0][:200] if detail else "sans message"))

    premiere = next((l for l in (sortie.stdout or "").splitlines() if l.strip()), "")
    morceaux = [m.strip() for m in premiere.split(",")]
    if len(morceaux) < 3:
        return _rien("sortie de nvidia-smi illisible : %r" % premiere[:120])
    try:
        totale = int(float(morceaux[1]))
        libre = int(float(morceaux[2]))
    except ValueError:
        return _rien("memoire illisible dans %r" % premiere[:120])

    return {
        "vue": True,
        "nom": morceaux[0],
        "totale_mo": totale,
        "libre_mo": libre,
        "marge_mo": MARGE_MO,
        "motif": "",
    }


# Ce qu'on tolere de voir pris sur la carte tout en la disant LIBRE. Ce n'est
# pas une prediction du besoin d'un code -- il n'y en a aucune de possible pour
# un code jamais vu -- c'est le seuil qui separe << le bureau affiche des
# fenetres >> de << un vrai calcul tient la carte >>. Mesure du 21/09/2026 sur
# cette machine, bureau Windows allume et rien d'autre : 426 Mo pris sur
# 24 564. Un vrai locataire se compte en gigaoctets : llama-server en tient
# 15 500, un clip de la page Video 12 841.
OCCUPATION_TOLEREE_MO = int(os.getenv("GPU_LOCAL_OCCUPATION_TOLEREE_MO", "2048"))


def libre_pour_un_code_inconnu(delai_s: int | None = None) -> tuple[bool, str, dict]:
    """La carte est-elle libre pour un code dont on ignore l'appetit ?

    `utilisable()` compare a un besoin MESURE ; ici il n'y en a pas, et il ne
    peut pas y en avoir. On regarde donc l'autre bout : est-ce que quelqu'un
    d'autre s'en sert ? La phrase rendue dit la carte et les chiffres, parce
    qu'un << non >> sans chiffre envoie chercher une panne qui n'existe pas.
    Elle ne dit PAS ce qu'on va faire ensuite : c'est a l'appelant.
    """
    etat = releve(delai_s)
    if not etat["vue"]:
        return False, etat["motif"], etat

    pris = max(0, etat["totale_mo"] - etat["libre_mo"])
    if pris > OCCUPATION_TOLEREE_MO:
        return False, (
            "%s : %d Mo deja pris sur %d. Un autre calcul tient la carte, et on "
            "ne l'arrete jamais." % (etat["nom"], pris, etat["totale_mo"])
        ), etat

    return True, (
        "%s : %d Mo libres sur %d, personne d'autre ne la tient."
        % (etat["nom"], etat["libre_mo"], etat["totale_mo"])
    ), etat


def utilisable(besoin_mo: int, delai_s: int | None = None) -> tuple[bool, str, dict]:
    """Peut-on lancer ICI un travail qui demande `besoin_mo` de memoire ?

    Rend (oui/non, phrase lisible, releve). La phrase est faite pour etre
    montree telle quelle : elle dit la carte, ce qui reste et ce qu'il fallait,
    parce qu'un << non >> sans chiffre envoie chercher une panne qui n'existe
    pas."""
    etat = releve(delai_s)
    if not etat["vue"]:
        return False, etat["motif"], etat

    besoin_total = max(0, int(besoin_mo)) + MARGE_MO
    if etat["libre_mo"] < besoin_total:
        return False, (
            "%s : %d Mo libres, il en faut %d (%d demandes + %d de marge). "
            "La carte est partagee : on va chez Modal, on n'arrete personne."
            % (etat["nom"], etat["libre_mo"], besoin_total, int(besoin_mo), MARGE_MO)
        ), etat

    return True, (
        "%s : %d Mo libres pour %d demandes (marge %d)."
        % (etat["nom"], etat["libre_mo"], int(besoin_mo), MARGE_MO)
    ), etat


def _rien(motif: str) -> dict:
    return {"vue": False, "nom": None, "totale_mo": None, "libre_mo": None,
            "marge_mo": MARGE_MO, "motif": motif}
