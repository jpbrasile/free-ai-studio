"""Ou fabriquer ce clip : a la maison, ou sur une carte louee.

Phase 3 du chantier ouvert le 19/09/2026. Les phases 1 et 2 ont repondu a
<< peut-on >> (`gpu_local.py`, la sonde) et a << avec quoi >> (Wan 2.2 TI2V-5B,
premier clip fabrique le 19/09 a 18:43 : 412 s, 12 841 Mo de pic, 0 $).
Celle-ci repond a << ou >>, et elle ne repond pas toute seule.

**L'ordre du proprietaire, le 19/09 au soir, apres avoir vu ce qui s'etait
passe** : << il faut que le client ait le choix du gpu local et du bypass si
occupee >>. Ce qui venait de se passer : un clip pret a partir a attendu de
18:20:54 a 18:35:52 qu'un calcul voisin rende la carte -- **quinze minutes
d'attente pour une fabrication de quelques minutes**. La regle que j'avais
ecrite la veille, << occupee => on va chez Modal >>, aurait depense de l'argent
sans demander, la ou un quart d'heure de patience ne coutait rien.

**Aucune regle ecrite d'avance ne sait si le client est presse.** D'ou la forme
de ce module : il ne tranche que ce qui est factuel, et il RENVOIE LA QUESTION
des qu'il ne reste qu'un arbitrage de gout.

Quatre faits mesures qui dictent sa forme :

1. **Le modele de la maison ne sait pas tout faire.** Les trois commandes de la
   page /video -- image de depart, image de FIN, image de REFERENCE -- sont des
   fonctions de VACE, et la Wan 2.2 n'a pas de VACE (releve du 19/09 :
   l'organisation Wan-AI ne publie aucun `Wan2.2-VACE`, et le seul qui existe,
   chez une autre equipe, pese 81,24 Go en deux experts de 34,68 Go, donc ne
   tient pas dans 24 Go). Une image de fin ou de reference part donc chez Modal
   MEME SI la carte est libre. Router sur la seule memoire libre produirait un
   clip qui ignore la consigne -- un faux vert, pas une panne.
2. **Le besoin memoire se mesure, il ne se devine pas.** 12 841 Mo au pic pour
   73 images en 1280 x 704 et 50 passes. Une duree dont le besoin n'a PAS ete
   mesure ne part pas a la maison : elle va chez Modal avec son motif ecrit.
   C'est volontairement genant -- la gene est ce qui fait mesurer.
3. **La carte est partagee et peut se prendre entre deux secondes.** La sonde
   mesure au lancement, jamais au demarrage du service.
4. **On n'arrete jamais le travail qui tient la carte.** Occupee, on demande ou
   on attend ; on ne prend jamais sa place.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import gpu_local

# Les trois reglages du client. Le premier est le defaut quand une carte existe.
MAISON_SI_LIBRE = "maison-si-libre"
TOUJOURS_MODAL = "toujours-modal"
TOUJOURS_MAISON = "toujours-maison"
REGLAGES = (MAISON_SI_LIBRE, TOUJOURS_MODAL, TOUJOURS_MAISON)
REGLAGE_DEFAUT = MAISON_SI_LIBRE

# Ce que la decision peut valoir.
MAISON = "maison"          # on fabrique ici, gratuitement
MODAL = "modal"            # on loue, et le prix est dit avant
ON_DEMANDE = "on-demande"  # la carte est prise et le client n'a pas dit quoi faire
ATTENTE = "attente"        # le client a dit << j'attends >>, ou l'a regle une fois

# Besoin memoire MESURE sur cette machine, par nombre d'images, pour la
# definition et le nombre de passes du modele de la maison. Rien n'est
# extrapole : une cle absente vaut << non mesure >>, pas << sans doute a peu
# pres >>. Mesure du 19/09/2026, RTX 4090, Wan 2.2 TI2V-5B, 1280 x 704,
# 50 passes.
BESOIN_MO_MESURE: dict[int, int] = {
    73: 12841,    # 3,04 s a 24 im/s -- clip_4090.mp4, 412 s de calcul
    121: 14902,   # 5,04 s a 24 im/s -- clip_4090_5s.mp4, 598 s de calcul
}
# Ce que ces deux lignes apprennent, et qui interdit d'extrapoler la troisieme :
# 66 % d'images en plus coutent 45 % de temps en plus (412 -> 598 s) mais
# seulement 16 % de memoire en plus (12 841 -> 14 902 Mo). Ni l'un ni l'autre
# n'est proportionnel, et dans deux sens differents. Une duree absente de cette
# table est donc vraiment inconnue, pas << a peu pres devinable >>.

CONFIG_DIR = Path(os.getenv("FREE_AI_CONFIG_DIR", "/config"))
FICHIER = CONFIG_DIR / "ou-calculer.json"


def reglage_lu() -> str:
    """Le reglage choisi par le client, ou le defaut s'il n'a jamais choisi."""
    try:
        brut = json.loads(FICHIER.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return REGLAGE_DEFAUT
    valeur = str(brut.get("reglage") or "").strip()
    return valeur if valeur in REGLAGES else REGLAGE_DEFAUT


def reglage_ecrit(valeur: str) -> str:
    """Pose le reglage. Rend celui qui a ete ecrit, jamais une exception."""
    if valeur not in REGLAGES:
        raise ValueError(
            "Reglage inconnu : %r. Les trois possibles sont %s."
            % (valeur, ", ".join(REGLAGES))
        )
    FICHIER.parent.mkdir(parents=True, exist_ok=True)
    tmp = FICHIER.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"reglage": valeur}, ensure_ascii=False), encoding="utf-8")
    tmp.replace(FICHIER)
    return valeur


def commandes_que_la_maison_ignore(resume: dict) -> list[str]:
    """Ce que le client a demande et que le modele de la maison ne sait pas faire.

    Rend des mots lisibles, pas des noms de champs : ils vont a l'ecran.

    L'image de DEPART est dans la liste, et ce n'est pas la meme raison que les
    deux autres. Le modele de la maison sait la poser -- mais par une AUTRE
    classe, `WanImageToVideoPipeline` ; `WanPipeline`, celle que le script
    emploie, n'accepte meme pas l'argument (verifie dans diffusers 0.40.0 le
    19/09). Tant que cette autre classe n'a pas ete essayee ici, un clip avec
    image de depart part chez Modal. La sortir de cette liste sans l'avoir
    mesuree rendrait un clip qui ignore l'image, en silence."""
    manquantes = []
    if resume.get("image_depart"):
        manquantes.append("l'image de depart")
    if resume.get("image_fin"):
        manquantes.append("l'image de fin")
    if resume.get("image_reference"):
        manquantes.append("l'image de reference")
    return manquantes


def decider(resume: dict, images: int | None, prix_estime_usd: float | None = None,
            reglage: str | None = None, sonde=None, loueur: str = "Modal") -> dict:
    """Ou fabriquer ce clip, et pourquoi -- en une reponse montrable telle quelle.

    `resume` est le `resume_public` de `video.preparer()`. `images` est le
    nombre d'images demande, ou None quand la duree n'est pas dans la table de
    la maison. `sonde` sert aux tests : par defaut la vraie carte. `loueur` est
    le nom de la machine louee, tel que le client l'a choisi sur la page --
    Modal ou Kaggle -- pour que la phrase rendue dise ou le clip part vraiment.

    Rend toujours les memes cles, pour que la page n'ait jamais a deviner :
    `ou`, `pourquoi`, `besoin_mo`, `carte`, `prix_estime_usd`, `sorties`."""
    reglage = reglage if reglage in REGLAGES else (reglage or reglage_lu())
    if reglage not in REGLAGES:
        reglage = REGLAGE_DEFAUT
    sonde = sonde or gpu_local.utilisable

    def reponse(ou, pourquoi, carte=None, besoin=None, sorties=()):
        return {
            "ou": ou,
            "reglage": reglage,
            "pourquoi": pourquoi,
            "besoin_mo": besoin,
            "carte": carte or {"vue": False, "motif": "carte non sondee"},
            "prix_estime_usd": None if ou == MAISON else prix_estime_usd,
            "sorties": list(sorties),
        }

    # 1. Ce que la maison ne sait pas faire passe avant tout le reste, y compris
    #    avant << toujours a la maison >> : sinon on rendrait un clip qui ignore
    #    la consigne, ce qui est pire qu'un clip paye.
    ignorees = commandes_que_la_maison_ignore(resume)
    if ignorees:
        quoi = " et ".join(ignorees)
        if reglage == TOUJOURS_MAISON:
            return reponse(MODAL, (
                "Vous avez regle << toujours a la maison >>, mais %s demande un modele "
                "que la carte d'ici ne peut pas faire tourner. Ce clip part chez %s, "
                "ou il est refuse si vous preferez : il ne peut pas etre fabrique ici."
                % (quoi, loueur)), sorties=(MODAL, "annuler"))
        return reponse(MODAL, (
            "%s se fabrique avec un modele que la carte d'ici ne peut pas porter. "
            "Ce clip part chez %s." % (quoi.capitalize(), loueur)))

    # 2. Le contournement permanent. Rien a sonder : c'est le comportement
    #    d'avant ce chantier, et il reste disponible en un reglage.
    if reglage == TOUJOURS_MODAL:
        return reponse(MODAL, "Vous avez regle << toujours sur une machine louee >> (%s)." % loueur)

    # 3. Un besoin non mesure ne se devine pas.
    if images is None:
        return reponse(MODAL, (
            "Cette duree n'a pas encore ete mesuree sur la carte d'ici. Tant qu'elle "
            "ne l'est pas, ce clip part chez %s : on ne lance pas un travail sur un "
            "chiffre suppose." % loueur))
    besoin = BESOIN_MO_MESURE.get(int(images))
    if besoin is None:
        return reponse(MODAL, (
            "La place que prend un clip de %d images sur la carte n'a pas encore ete "
            "mesuree ici. Tant qu'elle ne l'est pas, ce clip part chez %s : on ne "
            "lance pas un travail sur un chiffre suppose." % (int(images), loueur)))

    # 4. L'etat de la carte, a cette seconde.
    libre, phrase, carte = sonde(besoin)
    if libre:
        return reponse(MAISON, "Fabrique ici, gratuitement. " + phrase,
                       carte=carte, besoin=besoin)

    if not carte.get("vue"):
        return reponse(MODAL, "Aucune carte utilisable ici : " + phrase,
                       carte=carte, besoin=besoin)

    # La carte existe et elle est prise. C'est ICI que le client decide.
    if reglage == TOUJOURS_MAISON:
        return reponse(ATTENTE, (
            "La carte est prise et vous avez regle << toujours a la maison >> : "
            "on attend qu'elle se libere, on n'arrete jamais le travail qui la tient. "
            + phrase), carte=carte, besoin=besoin)

    return reponse(ON_DEMANDE, (
        "La carte est prise par un autre calcul. " + phrase +
        " A vous de dire : attendre ne coute rien, louer chez " + loueur + " coute "
        + (("environ %.3f $" % prix_estime_usd) if prix_estime_usd is not None
           else "ce que la page affiche") + "."),
        carte=carte, besoin=besoin, sorties=(ATTENTE, MODAL, "annuler"))
