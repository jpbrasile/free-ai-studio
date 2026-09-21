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

# ---------------------------------------------------------------------------
# LES ANCRES : les seuls clips REELLEMENT mesures sur cette carte.
# ---------------------------------------------------------------------------
# RTX 4090, Wan 2.2 TI2V-5B, 1280 x 704, 50 passes, 19/09/2026. On n'y touche
# pas a la main : `enregistrer_ancre()` y ajoute ce qu'un vrai clip a coute,
# et les lois ci-dessous se reajustent dessus.
#
# Jusqu'au 21/09 ces deux lignes etaient la SEULE reponse possible : une duree
# absente partait chez le loueur, motif << on ne lance pas sur un chiffre
# suppose >>. Deux consequences, relevees par le proprietaire :
#   - la page ne pouvait offrir que 3 s et 5 s, pour toujours ;
#   - et ces deux branches n'etaient atteignables par AUCUN chemin de
#     production, la page n'offrant que ces deux durees-la.
# Le chiffre ne sert qu'a une chose -- ai-je assez de memoire a cette seconde --
# et a cette question un majorant repond aussi bien qu'une mesure, et mieux
# qu'un refus.
ANCRES: dict[int, dict[str, float]] = {
    73: {"memoire_mo": 12841, "secondes": 412},    # clip_4090.mp4
    121: {"memoire_mo": 14902, "secondes": 598},   # clip_4090_5s.mp4
}

# Ce que ces deux lignes apprennent : 66 % d'images en plus coutent 45 % de
# temps en plus mais seulement 16 % de memoire en plus. Les deux croissent, et
# pas au meme rythme -- d'ou deux lois separees, et non un facteur unique.
#
# MARGE_LOI : deux points posent une droite, ils ne prouvent pas la forme de la
# courbe. L'attention sur l'axe temporel d'un modele de diffusion video peut
# etre superlineaire en nombre d'images. Cette marge couvre l'ecart entre une
# droite et une courbe un peu convexe, DANS le domaine des ancres.
MARGE_LOI = float(os.getenv("VIDEO_MARGE_LOI", "0.08"))

# MARGE_HORS_DOMAINE : au-dela de la plus grande ancre, on extrapole, et une
# extrapolation se paie. Par tranche de 24 images (une seconde) au-dela, on
# ajoute ceci. Loin des ancres, le majorant devient volontairement pessimiste :
# il envoie chez le loueur un clip que la carte aurait peut-etre tenu, ce qui
# coute de l'argent -- alors qu'un majorant trop bas coute au client dix
# minutes d'attente avant un depassement memoire. C'est le sens de l'asymetrie.
MARGE_HORS_DOMAINE = float(os.getenv("VIDEO_MARGE_HORS_DOMAINE", "0.04"))

# Au-dela, on refuse : l'extrapolation n'a plus de sens, et la marge aurait
# depasse le fait. Mesurer un clip long deplace cette borne d'elle-meme, par
# `enregistrer_ancre()`.
IMAGES_MAX_EXTRAPOLATION = int(os.getenv("VIDEO_SECONDES_EXTRAPOLATION", "4"))


def _loi(champ: str) -> tuple[float, float]:
    """La droite ajustee sur les ancres, RELEVEE pour passer au-dessus de chacune.

    Rend (origine, pente). Avec deux ancres c'est la droite qui les joint ;
    avec trois ou plus, la droite des moindres carres puis remontee du plus
    grand ecart, pour qu'aucune mesure ne se retrouve au-dessus de la loi.
    """
    points = sorted((n, float(v[champ])) for n, v in ANCRES.items())
    if len(points) == 1:
        (n0, v0), = points
        return v0, 0.0
    moy_n = sum(n for n, _ in points) / len(points)
    moy_v = sum(v for _, v in points) / len(points)
    haut = sum((n - moy_n) * (v - moy_v) for n, v in points)
    bas = sum((n - moy_n) ** 2 for n, _ in points)
    pente = haut / bas if bas else 0.0
    origine = moy_v - pente * moy_n
    releve = max(0.0, max(v - (origine + pente * n) for n, v in points))
    return origine + releve, pente


def _domaine() -> tuple[int, int]:
    """La plus petite et la plus grande ancre, en nombre d'images."""
    return min(ANCRES), max(ANCRES)


def besoin_mo(images: int) -> int:
    """La place a reserver pour ce clip, en Mo. Jamais None.

    DEUX NATURES DERRIERE UN SEUL NOMBRE, et `besoin_est_mesure()` dit laquelle :

      - sur un nombre d'images REELLEMENT MESURE, c'est la mesure, telle quelle.
      - ailleurs, c'est un MAJORANT : la droite ajustee sur les mesures, relevee
        d'une marge.

    Pourquoi la mesure n'est pas majoree (relecture adverse du 21/09, verifiee
    par le calcul) : `gpu_local.utilisable()` ajoute DEJA 1 024 Mo de marge. En
    empilant la mienne par-dessus un point mesure, je refusais a la maison, sur
    une carte de 16 Go, le clip de 5 s dont la mesure dit qu'il y tient --
    14 902 + 1 024 = 15 926, contre 16 094 + 1 024 = 17 118 avec la loi. Majorer
    une mesure n'est pas prudent : c'est jeter la mesure.
    """
    images = int(images)
    if images in ANCRES:
        return int(ANCRES[images]["memoire_mo"])

    # ENTRE DEUX MESURES : celle du palier au-dessus majore, exactement.
    # Ajouter des images ne peut pas faire BAISSER la memoire ; tout ce qui est
    # sous un palier mesure tient donc dans ce palier. Pas de droite a ajuster,
    # pas de marge a choisir, et aucune hypothese sur la forme de la courbe --
    # seulement qu'elle monte. C'est aussi ce qui rend cette fonction
    # croissante, sans quoi 4 secondes auraient reserve plus que 5.
    au_dessus = [n for n in ANCRES if n > images]
    if au_dessus:
        return int(ANCRES[min(au_dessus)]["memoire_mo"])

    # AU-DESSUS DE TOUT CE QUI A ETE MESURE : plus de palier, donc la droite
    # ajustee sur les mesures, relevee d'une marge qui grandit avec la
    # distance. C'est le seul endroit ou un chiffre est devine, et le seul ou
    # une marge se justifie.
    origine, pente = _loi("memoire_mo")
    n_max = max(ANCRES)
    marge = MARGE_LOI + MARGE_HORS_DOMAINE * ((images - n_max) / 24.0)
    return int((origine + pente * images) * (1.0 + marge) + 0.5)


def besoin_est_mesure(images: int) -> bool:
    """Vrai si ce nombre d'images a ete releve sur une vraie carte.

    La page n'a pas le droit de dire << il en faut X >> d'un majorant : ce
    serait annoncer un chiffre calcule comme un chiffre releve. Elle dit
    << il en faut au plus X >> quand c'est faux.
    """
    return int(images) in ANCRES


def secondes_estimees(images: int) -> int:
    """Le temps de calcul attendu sur la carte d'ici, MONTRE AVANT de valider.

    C'est une estimation, pas une mesure, et la page le dit avec ce mot. Elle
    est ancree sur des clips reels, et chaque clip fini la reajuste.
    """
    origine, pente = _loi("secondes")
    return int(origine + pente * int(images) + 0.5)


def extrapolation_trop_loin(images: int) -> bool:
    """Au-dela de ce point, la loi ne majore plus rien : elle devine."""
    _, n_max = _domaine()
    return int(images) > n_max + IMAGES_MAX_EXTRAPOLATION * 24


# NOTE : une fonction `enregistrer_ancre()` a ete ecrite ici puis RETIREE le
# meme jour, sur la relecture adverse. Elle n'etait appelee par personne -- le
# script de fabrication ne rapporte aucun pic memoire aujourd'hui -- et une
# table reecrite a l'execution derive de sa provenance : on ne saurait plus sur
# quelle carte, quelle definition ni quelle version de torch un chiffre a ete
# pris. Elle reviendra avec son fichier a provenance, pas avant. Voir le
# sous-plan SP-VIDEO-ETALONNAGE dans PLAN.md.


# Compatibilite : ce nom a ete publie dans README.md et dans les tests. Il rend
# les ancres, c'est-a-dire ce qui a ete mesure -- et non la loi.
BESOIN_MO_MESURE: dict[int, int] = {
    n: int(v["memoire_mo"]) for n, v in ANCRES.items()
}

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
    `ou`, `pourquoi`, `besoin_mo`, `carte`, `prix_estime_usd`, `sorties`,
    `secondes_estimees`, `besoin_est_mesure`."""
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
            # Le temps que ce clip prendra sur la carte d'ici, MONTRE AVANT que
            # le client valide (ordre du proprietaire, 21/09/2026). Tant que la
            # page n'offrait que 3 s et 5 s, l'ecart etait de trois minutes ;
            # des que le client choisit, il va de quatre a quinze. Personne ne
            # lance un quart d'heure de calcul sans le savoir.
            # `None` quand le clip ne part pas sur cette carte : le temps chez
            # le loueur n'est pas celui-ci, et une estimation prise pour l'autre
            # serait pire que pas d'estimation du tout.
            "secondes_estimees": (
                secondes_estimees(int(images)) if ou == MAISON and images else None),
            # La page n'a pas le droit d'annoncer un majorant comme un releve.
            # Vrai seulement pour les durees reellement mesurees sur une carte ;
            # partout ailleurs elle doit dire << au plus >>.
            "besoin_est_mesure": bool(images) and besoin_est_mesure(int(images)),
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
    # Un MAJORANT, pas une mesure -- et c'est assez, parce que ce chiffre ne
    # repond qu'a une question : reste-t-il assez de place a cette seconde.
    if extrapolation_trop_loin(int(images)):
        return reponse(MODAL, (
            "Un clip de %d images est trop loin de ce qui a ete mesure sur la carte "
            "d'ici pour qu'on sache l'y faire tenir. Il part chez %s."
            % (int(images), loueur)))
    besoin = besoin_mo(int(images))

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
