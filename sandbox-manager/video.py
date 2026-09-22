"""Fabrication de videos courtes, sur un GPU loue a la minute.

Pourquoi un fichier a part. La video est la seule fonction du Studio qui coute
vraiment de l'argent : une image se fabrique en deux secondes chez Google, une
video demande des minutes de carte graphique. Tout ce qui compte les secondes et
refuse de depasser est donc rassemble ici, lisible d'un coup d'oeil, plutot que
dispersé dans le gestionnaire de bacs a sable.

Un seul modele couvre les trois demandes du debutant, et c'est ce qui rend la
chose possible sans budget : Wan 2.1 VACE en 1,3 milliard de parametres (licence
Apache 2.0, environ 6 Go) sait a la fois partir d'une simple phrase, partir d'une
image, finir sur une autre image, et garder un personnage ressemblant a une image
de reference. Le meme code marche sur le grand modele 14B quand on a de quoi
payer : seul le nom du modele change.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import budget_modal
import format_fr
import ou_calculer

# Le compteur des depenses Modal est commun aux quatre usages -- la video, la
# chanson, le dialogue et le bac a sable lui-meme. Il tient le fichier, le
# verrou, la table des prix et le plafond ; ce module n'en garde que des
# renvois. CONFIG_DIR a disparu d'ici avec le fichier qu'il servait a nommer.
BUDGET_FICHIER = budget_modal.FICHIER

# TABLE UNIQUE depuis le 19/09/2026 : les prix Modal vivent dans
# budget_modal.py et ce module les LIT au lieu d'en garder une copie. Les noms
# sont conserves parce que les tests et les pages les citent ; ce ne sont plus
# que des renvois.
#
# Ce que la copie coutait, et qu'aucun test ne voyait : video.py portait les
# HUIT cartes, chanson.py et dialogue.py n'en portaient que QUATRE. Le test qui
# gardait ce flanc ne comparait que les cartes COMMUNES, donc il passait au
# vert -- pendant que prix_seconde() facturait une A100 au tarif L40S et une
# H100 a la MOITIE de son prix, parce qu'une carte inconnue retombe sur la plus
# chere CONNUE. Une table tronquee rend ce repli menteur.
PRIX_RELEVE_LE = budget_modal.PRIX_RELEVE_LE
PRIX_GPU_USD_S = budget_modal.PRIX_GPU_USD_S
PRIX_CPU_USD_S = budget_modal.PRIX_CPU_USD_S
PRIX_MEMOIRE_USD_S = budget_modal.PRIX_MEMOIRE_USD_S

# Ce que les DEMANDES peuvent atteindre : le plafond unique moins la part
# reservee au bac a sable. VIDEO_BUDGET_USD_PAR_MOIS n'est plus lu -- trois
# plafonds qui s'ignorent etaient precisement le defaut a reparer, et leur
# somme valait deja le credit entier. Voir budget_modal.py.
BUDGET_MENSUEL_USD = budget_modal.plafond_de("video")
CREDIT_OFFERT_USD = budget_modal.CREDIT_OFFERT_USD

# Duree maximale d'un clip, garde-fou dur : au-dela, la Sandbox est arretee et le
# compteur encaisse ce qui a ete consomme. 40 min couvre le premier lancement,
# telechargement du modele compris.
DUREE_MAX_S = int(os.getenv("VIDEO_TIMEOUT_SECONDS", "2400"))

VOLUME_MODELES = os.getenv("VIDEO_MODAL_VOLUME", "free-ai-studio-modeles")
CACHE_MODAL = "/modeles/hf"
# Ou le bac a sable de la maison garde les 34 Go de poids. Le worker construit
# un environnement nu pour le script : sans ce chemin ecrit DANS la demande, le
# modele se retelechargerait a chaque clip, dans un dossier de travail efface
# ensuite. Le meme chemin est monte cote compose (docker-compose.gpu.yml).
CACHE_MAISON = os.getenv("VIDEO_CACHE_MAISON", "/cache/huggingface")

# Sous quel systeme le Studio a ete lance. Ce service tourne dans un conteneur
# Linux quelle que soit la machine : il ne PEUT pas le deviner. C'est le
# lanceur qui le dit -- `scripts/demarrer.ps1` pose "windows", `start.sh` pose
# "linux" -- et la seule chose qui en depend est le nom du script a taper pour
# descendre les 34 Go. Nommer un script PowerShell a quelqu'un sous Linux, ou
# l'inverse, transforme un message utile en cul-de-sac.
STUDIO_LANCEUR = (os.getenv("STUDIO_LANCEUR") or "").strip().lower()
_TELECHARGEMENT_PS1 = "powershell -ExecutionPolicy Bypass -File scripts\\telecharger-modele-video.ps1"
_TELECHARGEMENT_SH = "./scripts/telecharger-modele-video.sh"


def commande_telechargement() -> str:
    """La commande qui descend les 34 Go, ecrite pour CETTE machine.

    Lanceur inconnu -- un `docker compose up` tape a la main, par exemple : on
    nomme les deux plutot que d'en inventer un. Se tromper coute a la personne
    le temps de comprendre pourquoi la commande n'existe pas ; donner les deux
    ne coute qu'une ligne."""
    if STUDIO_LANCEUR == "windows":
        return _TELECHARGEMENT_PS1
    if STUDIO_LANCEUR == "linux":
        return _TELECHARGEMENT_SH
    return "%s   (Linux, macOS)\n    %s   (Windows)" % (_TELECHARGEMENT_SH, _TELECHARGEMENT_PS1)


MODELES = {
    "rapide": {
        "titre": "Rapide (defaut)",
        # La cadence du modele, ecrite dans SA fiche et non dans un `.get(..., 16)`
        # enfoui : c'est une propriete du modele, elle se lit la ou on le decrit.
        "images_par_seconde": 16,
        "hf": "Wan-AI/Wan2.1-VACE-1.3B-diffusers",
        "parametres": "1,3 milliard",
        # 19 Go de fichiers dans le depot (le lecteur de texte pese plus lourd
        # que le modele d'images lui-meme). Telecharges une fois, gardes sur le
        # disque Modal, qui est offert jusqu'a 1 Tio.
        "poids_go": 19,
        "licence": "Apache 2.0",
        "territoire": "aucune restriction de pays",
        "gpu": os.getenv("VIDEO_GPU_RAPIDE", "L4"),
        "largeur": 832,
        "hauteur": 480,
        "flow_shift": 3.0,
        "etapes": 30,
        # DECLAREE, NON MESUREE. C'est ce que le depot servait avant le 21/09,
        # ou la table du loueur s'arretait a 5 s (81 images a 16 img/s). Le
        # 21/09 au matin je l'ai etendue a 9 s en la faisant deriver des ancres
        # de la carte D'ICI -- autre modele, autre machine, aucun rapport. Elle
        # revient a ce qui est sourceable, et sa vraie valeur est un chantier.
        "secondes_max": int(os.getenv("VIDEO_SECONDES_MAX_RAPIDE", "5")),
        "note": "Tient sur une petite carte : marche aussi sur Kaggle et Colab gratuits.",
    },
    "soigne": {
        "titre": "Soigne (plus lent, plus cher)",
        # La cadence du modele, ecrite dans SA fiche et non dans un `.get(..., 16)`
        # enfoui : c'est une propriete du modele, elle se lit la ou on le decrit.
        "images_par_seconde": 16,
        "hf": "Wan-AI/Wan2.1-VACE-14B-diffusers",
        "parametres": "14 milliards",
        "poids_go": 75,
        "licence": "Apache 2.0",
        "territoire": "aucune restriction de pays",
        "gpu": os.getenv("VIDEO_GPU_SOIGNE", "A100"),
        "largeur": 1280,
        "hauteur": 720,
        "flow_shift": 5.0,
        "etapes": 30,
        # Meme provenance que ci-dessus : declaree, non mesuree.
        "secondes_max": int(os.getenv("VIDEO_SECONDES_MAX_SOIGNE", "5")),
        # << environ six fois le prix >> a ete retire le 21/09/2026 : ce
        # nombre n'avait de source nulle part dans le depot, et ce modele
        # n'a jamais ete lance une seule fois. `prix_estime("soigne", ...)`
        # rend None, ce qui est la bonne reponse ; la note ne dit pas plus.
        "note": "Meilleure image. Ce modele n'a jamais ete lance : sa carte coute 1,98 fois celle de Rapide a la seconde, mais son temps de calcul n'a jamais ete mesure, donc le prix d'un clip est inconnu.",
    },
    # Le modele de la MAISON. Il ne se choisit pas dans la liste des qualites :
    # il est choisi par `ou_calculer.decider()` quand le clip peut etre fabrique
    # sur la carte d'ici. Premier clip mesure le 19/09/2026 a 18:43 : 412 s de
    # calcul, 12 841 Mo de pic, 0 $, contre 422 s et 0,117 $ pour le meme clip
    # de 3 s loue chez Modal -- mais en 720p au lieu de 480p.
    #
    # Il n'a PAS de VACE, et c'est la contrainte qui gouverne tout le routage :
    # la Wan 2.2 n'en publie aucun, et le seul qui existe (chez une autre
    # equipe) pese 81,24 Go en deux experts de 34,68 Go, donc ne tient pas dans
    # 24 Go. Une image de fin ou de reference ne peut donc pas etre fabriquee
    # ici -- elle part chez Modal, et la page le dit.
    "maison": {
        "titre": "A la maison (gratuit)",
        "hf": "Wan-AI/Wan2.2-TI2V-5B-Diffusers",
        "famille": "ti2v",
        "parametres": "5 milliards",
        "poids_go": 34,
        "licence": "Apache 2.0",
        "territoire": "aucune restriction de pays",
        "gpu": "maison",
        "largeur": 1280,
        "hauteur": 704,
        "flow_shift": None,
        "etapes": 50,
        "images_par_seconde": 24,
        "note": "Fabrique sur la carte de cet ordinateur. Ne coute rien, "
                "ne sait pas faire l'image de fin ni l'image de reference.",
    },
}

# Jusqu'au 21/09/2026 ces deux tables etaient ecrites a la main, avec deux
# lignes chacune, et une duree absente partait chez le loueur. Releve du
# proprietaire : << deux durees, 3 s et 5 s : ce n'est pas normal, le client
# doit pouvoir choisir dans la limite des capacites du llm et de la vram
# possible >>. Elles se calculent maintenant.
#
# LA CADENCE ET LA FORME DES IMAGES. Le modele n'accepte qu'un nombre d'images
# de la forme 4k+1. A 24 im/s comme a 16, `fps * secondes + 1` l'est toujours,
# les deux cadences etant des multiples de 4 : la contrainte est donc satisfaite
# par construction, et non par une table choisie a la main.
#
# LA BORNE HAUTE vient de la loi memoire (`ou_calculer`), qui refuse
# d'extrapoler trop loin de ce qui a ete reellement mesure. Elle se deplace
# d'elle-meme : un clip plus long mesure une fois, et la borne suit.
def fps_de(qualite: str) -> int:
    """La cadence de ce modele, lue dans sa fiche -- jamais recopiee ici."""
    return int(MODELES[qualite]["images_par_seconde"])


# Le modele n'accepte qu'un nombre d'images de la forme k * p + 1, ou p est la
# compression TEMPORELLE de son autoencodeur. Ce n'est pas un reglage : c'est
# une propriete du modele, ecrite dans `vae/config.json` sous le nom
# `scale_factor_temporal`. Elle etait recopiee en commentaire dans deux
# fichiers ; le jour ou le modele change, une recopie ment en silence.
# Repli : la valeur lue sur Wan 2.2 TI2V-5B le 21/09/2026, utilisee seulement
# tant que les poids ne sont pas descendus.
PAS_TEMPOREL_REPLI = 4


def pas_temporel() -> int:
    """La granularite imposee par l'autoencodeur du modele de la maison.

    Lue dans la fiche du modele quand les poids sont la ; a defaut, le repli
    ci-dessus. Jamais une constante seule.
    """
    racine = Path(os.getenv("POIDS_VIDEO_DIR", "/cache/huggingface"))
    for config in racine.glob("hub/models--Wan-AI--Wan2.2-TI2V-5B-Diffusers/"
                              "snapshots/*/vae/config.json"):
        try:
            valeur = json.loads(config.read_text(encoding="utf-8")).get(
                "scale_factor_temporal")
        except (OSError, ValueError):
            continue
        if isinstance(valeur, int) and valeur > 0:
            return valeur
    return PAS_TEMPOREL_REPLI


def images_pour(secondes: int, fps: int) -> int:
    """Combien d'images pour cette duree, a cette cadence.

    Arrondi a la granularite du modele : le compte doit etre k * p + 1. Avec
    p = 4 et une cadence multiple de 4, `fps * secondes + 1` l'est deja ; ce
    calcul tient quand meme si l'un des deux change.
    """
    pas = pas_temporel()
    brut = fps * int(secondes)
    return (brut // pas) * pas + 1


def secondes_max_maison() -> int:
    """La plus longue duree que la loi memoire accepte encore de majorer.

    C'est un plafond de CONNAISSANCE, pas de capacite : au-dela, on ne sait plus
    majorer la place memoire a partir des ancres. Il ne dit rien de la carte du
    client -- c'est `durees_offertes()` qui confronte chaque duree a SA carte.
    """
    plafond = max(ou_calculer.ANCRES) + 24 * ou_calculer.IMAGES_MAX_EXTRAPOLATION
    return max(1, (plafond - 1) // fps_de("maison"))


def secondes_max_loueur() -> int:
    """La plus longue duree que les modeles LOUES declarent savoir faire.

    Elle n'a rien a voir avec la carte d'ici, et le 21/09 au matin elle en
    dependait : j'avais construit la table du loueur sur `secondes_max_maison()`,
    donc sur mes deux ancres. Un portable sans carte se voyait alors offrir neuf
    durees << fabriquees chez le loueur >> sans que rien n'etablisse que le
    modele loue sache faire 9 s -- et un depassement memoire chez le loueur se
    paie.
    """
    return max(int(MODELES[q].get("secondes_max", 0))
               for q in MODELES if q != "maison")


def table_maison() -> dict:
    """Les durees offertes pour la carte d'ici, calculees et non recopiees."""
    fps = fps_de("maison")
    return {str(s): {"images": images_pour(s, fps), "secondes": s}
            for s in range(1, secondes_max_maison() + 1)}


# `None` veut dire << aucune carte >>, et il faut donc un autre mot pour dire
# << je n'ai pas regarde, sonde toi-meme >>. Les deux tenaient dans `None`
# jusqu'au 21/09/2026, et cela coutait deux choses : la page annoncait
# << trop long pour votre carte >> a qui n'a pas de carte, et elle sondait
# DEUX fois par ouverture -- `options_duree_html()` d'abord, puis cette
# fonction quand la premiere sonde n'avait rien vu.
SONDE_MOI_MEME = object()


def durees_offertes(totale_mo: int | None = SONDE_MOI_MEME) -> list[dict]:
    """Ce que la page met dans son menu, avec le temps attendu pour chacune.

    Le temps est montre AVANT que le client valide (ordre du 21/09) : entre la
    plus courte et la plus longue il y a un facteur quatre, et personne ne lance
    un quart d'heure de calcul sans le savoir.

    `totale_mo` borne la liste a ce que la carte peut PHYSIQUEMENT tenir. C'est
    bien le total et non le libre : le total est une propriete de la machine, le
    libre change a chaque seconde et sera regarde au lancement. Sans carte vue,
    la liste entiere est rendue -- c'est le loueur qui fabriquera, et sa memoire
    n'est pas celle d'ici.
    """
    if totale_mo is SONDE_MOI_MEME:
        etat = ou_calculer.gpu_local.releve()
        totale_mo = etat["totale_mo"] if etat.get("vue") else None

    fps = fps_de("maison")
    plafond_loueur = secondes_max_loueur()
    offres = []
    for secondes in range(1, max(secondes_max_maison(), plafond_loueur) + 1):
        cle = str(secondes)
        entree = {"images": images_pour(secondes, fps), "secondes": secondes}
        besoin = ou_calculer.besoin_mo(entree["images"])
        # `tient_ici` ne retire rien tout seul : le loueur sait fabriquer la
        # plupart de ces clips, et un menu vide serait un cul-de-sac. Il dit
        # seulement, duree par duree, si CETTE carte-ci peut la porter.
        tient_ici = (totale_mo is not None
                     and besoin + ou_calculer.gpu_local.MARGE_MO <= totale_mo)
        # Mais une duree que PERSONNE ne sait faire n'a rien a faire dans le
        # menu. Avant cette ligne, un portable sans carte se voyait offrir 9 s
        # << chez le loueur >> alors que le plafond declare du loueur est 5.
        if not tient_ici and secondes > plafond_loueur:
            continue
        offres.append({
            "duree": cle,
            "secondes": entree["secondes"],
            "images": entree["images"],
            # Le temps est celui de la carte d'ici. `None` quand ce clip n'y
            # tient pas : le temps chez le loueur n'est pas le meme, et une
            # estimation prise pour l'autre serait pire que pas d'estimation.
            "secondes_estimees": (ou_calculer.secondes_estimees(entree["images"])
                                  if tient_ici else None),
            "besoin_mo": besoin,
            "tient_ici": tient_ici,
            # Le temps et le prix CHEZ LE LOUEUR, pour le modele qu'il
            # rencontrerait. `None` tant que moins de deux durees de ce modele
            # ont ete chronometrees -- on ne trace pas une droite sur un point.
            "secondes_loueur": secondes_loueur(QUALITE_LOUEE_PAR_DEFAUT, cle),
            "temps_loueur_mesure": temps_loueur_est_mesure(
                QUALITE_LOUEE_PAR_DEFAUT, cle),
            "prix_loueur_usd": prix_estime(QUALITE_LOUEE_PAR_DEFAUT, cle),
        })
    return offres


def durees_mesurees() -> list[str]:
    """Les durees dont la PLACE sur la carte a ete relevee sur un vrai clip.

    La page nommait ici toutes les durees de son menu. Tant que le menu tenait
    exactement les deux durees chronometrees, la phrase disait vrai par
    coincidence ; le 21/09 le menu s'est ouvert a neuf durees et la phrase a
    continue de les dire << mesurees >>. Elle se calcule desormais sur les
    ancres, donc elle suit la mesure au lieu de la doubler.
    """
    return [cle for cle, entree in table_maison().items()
            if ou_calculer.besoin_est_mesure(entree["images"])]


def durees_chronometrees() -> list[str]:
    """Les durees dont le TEMPS a ete mesure, aux vraies passes de production.

    Pourquoi ce n'est PAS la meme liste que `durees_mesurees()` depuis la
    campagne du 21/09 : la place et le temps n'ont pas ete pris dans les memes
    conditions. La place a ete relevee a 2 passes, et le temoin a montre
    qu'elle n'en depend pas (12 841 Mo a 50 passes, 12 828 a 2). Le temps, lui,
    en depend de plein fouet -- 412 s contre 170 s pour le meme clip de 3 s --
    et il n'a ete chronometre a 50 passes que pour deux durees.

    Confondre les deux ferait dire a la page << chronometree >> d'une duree
    dont le temps affiche est extrapole. C'est le defaut repare le matin meme,
    un cran plus loin : une phrase vraie tant que les deux listes coincidaient,
    et fausse le jour ou l'une des deux s'allonge.
    """
    return [cle for cle, entree in table_maison().items()
            if ou_calculer.temps_est_mesure(entree["images"])]


DUREES_MAISON = table_maison()

# Par defaut on garde 5 s : c'est ce que la page proposait, et l'un des deux
# clips reellement mesures.
DUREE_PAR_DEFAUT = "5"


def _en_minutes(secondes: int) -> str:
    """<< environ 13 min >>, ou << environ 4 min >>. Jamais de fausse precision.

    Un temps estime annonce a la seconde se lirait comme une mesure. Il est
    arrondi a la minute, et le mot << environ >> reste."""
    minutes = max(1, int(round(secondes / 60.0)))
    return "environ %d min" % minutes


def _en_dollars(usd: float) -> str:
    """<< 0,06 $ >>. La virgule est le separateur decimal en francais.

    Ecrit le 21/09/2026 apres avoir imprime le menu d'une machine sans carte :
    ma propre ligne annoncait << environ 0.06 $ >>. Le 22/09 la meme reparation
    etait due a 42 autres endroits : le formateur est parti dans `format_fr`, et
    ce nom-ci reste la porte d'entree des appels deja ecrits.
    """
    return format_fr.en_dollars(usd)


def _pourquoi_pas_ici(totale_mo: int | None, aucune_ne_tient: bool) -> str:
    """Pourquoi ce clip ne se fabrique pas sur la carte du client.

    TROIS RAISONS, ET CE NE SONT PAS LES MEMES MOTS. Une seule phrase servait
    pour les trois jusqu'au 21/09/2026, et elle disait faux dans deux cas sur
    trois.

    - Pas de carte : rien n'est << trop long >>, il n'y a pas de carte. Tout
      part chez le loueur, quelle que soit la duree.
    - Carte vue, mais aucune duree n'y tient : c'est le MODELE qui ne rentre
      pas, pas la duree. Une seconde de video fait dix-sept images ; si
      dix-sept images debordent, treize n'y changeraient rien. La phrase
      << trop long >> envoie le debutant essayer plus court en boucle.
    - Carte vue, les durees courtes tiennent : la duree EST en cause, et le
      menu montre justement lesquelles passent.
    """
    if totale_mo is None:
        return "vous n'avez pas de carte ici"
    if aucune_ne_tient:
        return "votre carte est trop petite pour ce mod\u00e8le"
    return "trop long pour votre carte"


def options_duree_html() -> str:
    """Le menu de la page, avec le temps attendu DANS chaque option.

    Le client lit ce que son choix coutera en minutes au moment ou il choisit,
    et non apres avoir appuye sur le bouton (ordre du 21/09/2026).
    """
    # Une seule sonde, et son verdict sert DEUX fois : pour savoir ce qui tient
    # ici, et pour choisir entre << vous n'avez pas de carte >> et << votre
    # carte est trop petite pour ce clip-la >>. Ce ne sont pas la meme phrase
    # et ce n'est pas le meme probleme.
    etat = ou_calculer.gpu_local.releve()
    totale_mo = etat["totale_mo"] if etat.get("vue") else None
    offres = durees_offertes(totale_mo)
    ici = [o for o in offres if o["tient_ici"]]
    defaut = DUREE_PAR_DEFAUT
    if ici and not any(o["duree"] == defaut for o in ici):
        # La carte ne tient pas la duree par defaut : on choisit la plus longue
        # qu'elle porte, plutot que d'ouvrir sur une option payante.
        defaut = ici[-1]["duree"]

    morceaux = []
    for offre in offres:
        if offre["tient_ici"]:
            dit = "%s sur votre carte" % _en_minutes(offre["secondes_estimees"])
        elif offre["secondes_loueur"] is not None:
            # Le clip ne tient pas ici : il sera loue, et le client lit ce que
            # cela lui prendra ET ce que cela lui coutera avant de choisir.
            # Jusqu'au 21/09 cette branche ne disait ni l'un ni l'autre.
            dit = "%s \u2014 %s chez le loueur" % (
                _pourquoi_pas_ici(totale_mo, not ici),
                _en_minutes(offre["secondes_loueur"]))
            if offre["prix_loueur_usd"] is not None:
                dit += ", environ %s" % _en_dollars(offre["prix_loueur_usd"])
        else:
            dit = ("%s, fabriqu\u00e9 chez le loueur"
                   % _pourquoi_pas_ici(totale_mo, not ici))
        morceaux.append(
            '<option value="%s"%s>%d %s \u2014 %s</option>'
            % (offre["duree"],
               " selected" if offre["duree"] == defaut else "",
               offre["secondes"],
               "seconde" if offre["secondes"] == 1 else "secondes",
               dit))
    return "".join(morceaux)


def loueur_sait_faire(duree: str) -> bool:
    """Le modele LOUE sait-il fabriquer un clip de cette duree ?

    Separe de la maison depuis le 21/09 : le plafond du loueur derivait des
    ancres de la carte d'ici, ce qui n'avait aucun sens -- autre modele, autre
    machine. Quand la reponse est non, un clip de cette duree ne doit jamais
    etre propose a la location : il y serait rabattu sur une duree plus courte.
    """
    return str(duree) in DUREES


def images_maison(duree: str):
    """Combien d'images pour cette duree sur le modele de la maison, ou None.

    `None` n'est pas un echec : il veut dire << cette duree n'a pas encore ete
    mesuree ici >>, et le routage part chez Modal en le disant."""
    entree = DUREES_MAISON.get(str(duree))
    return entree["images"] if entree else None

# 16 images par seconde, meme contrainte 4k+1, meme formule -- mais PAS les
# memes durees, et c'est le correctif du 21/09 apres-midi. Ce commentaire disait
# que l'egalite des deux tables etait << une necessite, pas une symetrie de
# confort >>, parce que `preparer()` rabattait sinon la duree sur 5 s en silence.
# La necessite venait de la substitution : on a retire la substitution. Le
# plafond du loueur est desormais celui du loueur, declare dans sa fiche.
#
# Le plafond du loueur est CELUI DU LOUEUR. Il derivait de `secondes_max_maison()`
# -- donc des ancres de la carte d'ici -- le 21/09 au matin ; corrige le meme jour.
DUREES = {str(s): {"images": images_pour(s, fps_de("rapide")), "secondes": s}
          for s in range(1, secondes_max_loueur() + 1)}

NEGATIF = (
    "couleurs criardes, surexpose, statique, details flous, sous-titres, style, "
    "oeuvre, peinture, image fixe, gris terne, pire qualite, basse qualite, "
    "compression JPEG, laid, incomplet, doigts en trop, mains mal dessinees, "
    "visages mal dessinés, deforme, membres difformes, doigts fusionnes, "
    "arriere-plan encombre, trois jambes, marche a reculons"
)


# --- Compteur de depense ------------------------------------------------------
#
# UN SEUL compteur depuis le 19/09/2026 : budget_modal.py, partage avec les
# deux autres fonctions ET avec le bac a sable lui-meme, qui envoyait du code
# sur Modal sans etre compte par personne. Ce qui suit ne compte plus rien :
# ce sont des renvois, gardes pour que app.py, les tests et les pages n'aient
# pas a savoir ou vit le compteur. Le motif est en tete de budget_modal.py.


def budget_lire() -> dict:
    """L'etat du mois, TOUS usages confondus, vu du plafond de celui-ci."""
    etat = budget_modal.vue("video")
    etat["clips"] = etat["appels"]["video"]
    return etat


def budget_ecrire(secondes: float, usd: float, clips: int) -> None:
    """Pose l'etat de cet usage. Outil de TEST : le service passe par
    budget_consommer(), qui ajoute au lieu de poser."""
    budget_modal.poser("video", secondes, usd, clips)


def prix_seconde(gpu: str) -> float:
    return budget_modal.prix_seconde(gpu, int(os.getenv("VIDEO_MEMORY_MB", "16384")))


# Temps de calcul MESURE sur une machine louee, par qualite et par duree. Sert
# a chiffrer ce qu'une location couterait AVANT de la lancer : quand la carte
# d'ici est prise, le client choisit entre attendre et payer, et il ne peut pas
# choisir sans le prix.
#
# ENGENDRE DEPUIS LES FICHES DE TRAVAIL -- jamais retape. Chaque ligne porte
# l'identifiant du travail qui l'a produite, avec sa date, sa carte, sa
# definition et ses trois temps. Une mesure recopiee a la main est une mesure
# qui derive : le 21/09/2026 trois tests recopiaient 12,5 Go et defendaient
# l'erreur qu'ils devaient attraper.
#
# CE QUI EST ECRIT : `resume.secondes_calcul`, le script entier dans le bac a
# sable. Le mur vu du gestionnaire, 2 a 3 % plus grand parce qu'il comprend
# l'allumage de la machine louee, est en commentaire : c'est lui que le
# compteur de depense encaisse, et le confondre avec l'autre compterait deux
# fois. Deux releves sur la meme duree : on garde LE PLUS GRAND -- un temps
# montre avant de depenser se majore.
#
# LE PRIX N'EST PAS ECRIT ICI. `prix_estime()` le calcule au tarif du jour, et
# c'est ce qui a evite que la correction des tarifs du 20/09 le laisse en
# arriere -- le registre, lui, en avait recopie un, 25 % trop bas.
#
# CE QUE LA TABLE NE DIT PAS ENCORE : le modele soigne n'a qu'UNE duree, donc
# aucune pente -- `secondes_loueur` rend None pour toutes les autres. Et sa
# seule mesure comprend le PREMIER telechargement de ses 75 Go, qui ne se
# reproduira pas : elle majore donc largement un clip suivant. Les deux
# manques sont chiffres dans SP-VIDEO-TEMPS-LOUEUR.
SECONDES_MESUREES = {
    # 21/09/2026 `0d1afe0e` NVIDIA L4 832x480 bfloat16 17 images
    #   modele 17 s + calcul 117 s = 150.8 s dans le bac ; 162.8 s vus du gestionnaire.
    ("rapide", "1"): 151,
    # 20/09/2026 `52a7cf3e` NVIDIA L4 832x480 bfloat16 49 images
    #   modele 16 s + calcul 361 s = 393.9 s dans le bac ; 405.5 s vus du gestionnaire.
    # 09/09/2026 `b16ee2c1` NVIDIA L4 832x480 bfloat16 49 images   <-- gardee
    #   modele 24 s + calcul 380 s = 422.4 s dans le bac ; 433.1 s vus du gestionnaire.
    ("rapide", "3"): 422,
    # 21/09/2026 `54182907` NVIDIA L4 832x480 bfloat16 81 images
    #   modele 18 s + calcul 712 s = 750.7 s dans le bac ; 761.8 s vus du gestionnaire.
    ("rapide", "5"): 751,
    # 21/09/2026 `dce69faa` NVIDIA A100-SXM4-40GB 1280x720 bfloat16 17 images
    #   modele 382 s + calcul 353 s = 765.4 s dans le bac ; 785.1 s vus du gestionnaire.
    #   PREMIER lancement de ce modele : les 75 Go de poids sont descendus ici.
    #   Ce que cela coute vraiment est desormais mesure, voir la table suivante.
    ("soigne", "1"): 765,
}

# LE MEME CLIP, RELANCE. Un modele qui tourne pour la premiere fois descend ses
# poids chez le loueur ; les fois suivantes, il les retrouve sur le disque. Les
# deux temps n'ont rien a voir, et le client merite les deux plutot qu'une
# moyenne qui ne decrit aucun de ses clips.
#
# Cette table ne sert PAS a chiffrer un budget : c'est `SECONDES_MESUREES` qui
# le fait, et elle garde le premier lancement, parce qu'un client qui decouvre
# ce modele le paiera. Celle-ci sert a DIRE, dans le registre et le README, ce
# que coute un clip ordinaire une fois la decouverte passee.
SECONDES_MESUREES_REPRISE = {
    # 21/09/2026 `9517593d` NVIDIA A100-SXM4-40GB 17 images, meme phrase que
    # `dce69faa`, meme carte, quelques heures plus tard.
    #   modele 120 s + calcul 345 s = 479.4 s dans le bac.
    #   Le temps vu du gestionnaire n'a PAS ete releve pour ce clip : le
    #   suiveur sondait une adresse abregee, donc inexistante, pendant que le
    #   clip finissait. La mesure qui compte ici est celle du bac, qui est
    #   aussi ce que `SECONDES_MESUREES` porte pour tous les autres.
    #
    # CE QUE LA PAIRE ETABLIT : 382 s de charge deviennent 120 s, donc
    # 262 s ne se reproduisent pas -- et non 382, qui etait la lecture facile.
    # Le calcul seul, lui, ne bouge pas : 353 s puis 345 s, 2,3 % d'ecart.
    ("soigne", "1"): 479,
}


def secondes_reprise(qualite: str, duree: str):
    """Le temps du MEME clip relance, poids deja sur le disque du loueur.

    `None` tant qu'aucune relance n'a ete chronometree : on ne devine pas une
    reprise a partir d'un premier lancement, la part qui disparait n'etant
    connue que si on l'a mesuree deux fois.
    """
    valeur = SECONDES_MESUREES_REPRISE.get((str(qualite), str(duree)))
    return None if valeur is None else float(valeur)


def prix_reprise(qualite: str, duree: str):
    """Ce que coute le meme clip relance, ou None si ce n'est pas mesure."""
    if qualite not in MODELES:
        return None
    secondes = secondes_reprise(qualite, duree)
    if secondes is None:
        return None
    return round(prix_seconde(MODELES[qualite]["gpu"]) * secondes, 4)


# Quel modele le clip rencontrerait s'il partait chez le loueur. C'est le defaut
# de `preparer()`, et il est nomme ici plutot que recopie : le menu des durees
# montre le temps de CE modele-la.
QUALITE_LOUEE_PAR_DEFAUT = "rapide"


def _points_loueur(qualite: str) -> list[tuple[int, float]]:
    """Les clips de CE modele chronometres chez le loueur, en (images, secondes).

    Le nombre d'images est recalcule depuis la duree et la cadence du modele :
    c'est lui qui gouverne le temps, pas la duree affichee. Deux modeles de
    cadences differentes ne seraient pas sur la meme droite.
    """
    fps = fps_de(qualite)
    return sorted((images_pour(int(duree), fps), float(secondes))
                  for (q, duree), secondes in SECONDES_MESUREES.items()
                  if q == str(qualite))


def secondes_loueur(qualite: str, duree: str):
    """Le temps de calcul attendu chez le loueur, ou None si on n'en sait rien.

    Trois reponses, et la page doit pouvoir les distinguer :
      - cette duree a ete chronometree : la mesure, telle quelle ;
      - au moins deux durees l'ont ete : la droite de ces mesures, relevee pour
        ne jamais promettre moins qu'un clip deja paye ;
      - moins de deux : None, et la page s'en tient au plafond du pire cas.

    CE QUE CETTE FONCTION REPARE. Jusqu'au 21/09/2026 la table etait lue comme
    un simple dictionnaire : une seule duree y figurait, donc le client qui
    demandait 1 s ou 5 s ne voyait ni temps ni prix avant de payer. La cause
    n'etait pas le code mais la mesure -- trois clips avaient ete fabriques chez
    le loueur et LES TROIS faisaient 49 images. Une droite a deux inconnues ;
    trois mesures au meme point n'en determinent qu'une.

    Une duree que le modele loue ne declare pas savoir faire rend None, et non
    une extrapolation : `DUREES` s'arrete a ce que sa fiche annonce.
    """
    if qualite not in MODELES or str(duree) not in DUREES:
        return None
    cle = (str(qualite), str(duree))
    if cle in SECONDES_MESUREES:
        return float(SECONDES_MESUREES[cle])
    points = _points_loueur(qualite)
    if len(points) < 2:
        return None
    images = images_pour(int(duree), fps_de(qualite))
    if images > points[-1][0]:
        # AU-DELA DE LA PLUS LONGUE MESURE, LA DROITE MENT DU MAUVAIS COTE.
        # Trois clips loues le 21/09 ont montre que le prix d'une image MONTE
        # avec la longueur du clip : 8,22 s par image de 17 a 49 images, puis
        # 10,97 s de 49 a 81. La courbe est convexe -- forme attendue d'une
        # attention qui compare chaque image a toutes les autres.
        #
        # ENTRE deux mesures, la droite relevee majore encore : une courbe
        # convexe passe SOUS la corde qui joint deux de ses points, et la
        # droite passe au-dessus de cette corde (300,8 s contre 286,6 a
        # 33 images ; 600,7 contre 586,5 a 65). AU-DELA, la courbe monte plus
        # vite qu'elle : la droite promettrait moins cher que la realite.
        #
        # C'est l'erreur commise a la main le jour meme : une fourchette posee
        # avant la mesure plafonnait a 698 s pour le clip de 5 s, qui en a pris
        # 750,7. Le garde est ecrit avant d'en avoir besoin -- aucune duree
        # offerte ne depasse la derniere mesure aujourd'hui -- parce que le jour
        # ou `secondes_max` bougera d'une seconde, rien ne sonnerait.
        return None
    origine, pente = ou_calculer.droite_relevee(points)
    return round(origine + pente * images, 1)


def temps_loueur_est_mesure(qualite: str, duree: str) -> bool:
    """Vrai si ce temps-la a ete chronometre sur un vrai clip loue.

    Meme separation que `ou_calculer.temps_est_mesure()` pour la carte d'ici :
    la page n'a pas le droit de presenter une droite comme un releve.
    """
    return (str(qualite), str(duree)) in SECONDES_MESUREES


def prix_estime(qualite: str, duree: str):
    """Ce que cette location couterait, en dollars, ou None si on n'en sait rien.

    Le temps vient de `secondes_loueur()` -- mesure ou droite des mesures --, le
    tarif du jour de `prix_seconde()`. C'est cette seconde moitie qui a evite
    que la correction des tarifs du 20/09 laisse ce prix en arriere, quand le
    registre, lui, en gardait une copie de 25 % trop basse.
    """
    if qualite not in MODELES:
        return None
    secondes = secondes_loueur(qualite, duree)
    if secondes is None:
        return None
    return round(prix_seconde(MODELES[qualite]["gpu"]) * secondes, 4)


def budget_verifier(gpu: str, duree_max_s: int) -> dict:
    """Refuse AVANT de lancer si le pire cas entame ce qui reste a cet usage."""
    etat = budget_modal.verifier(
        "video", gpu, duree_max_s, int(os.getenv("VIDEO_MEMORY_MB", "16384")),
        quoi="Ce clip", suite="")
    etat["cout_max_du_clip_usd"] = etat["cout_max_usd"]
    etat["clips"] = etat["appels"]["video"]
    return etat


def budget_consommer(gpu: str, secondes: float) -> dict:
    """Encaisse le temps reellement passe, meme si le clip a echoue."""
    etat = budget_modal.consommer("video", gpu, secondes, int(os.getenv("VIDEO_MEMORY_MB", "16384")))
    etat["clips"] = etat["appels"]["video"]
    return etat


# LA MEME exception pour les trois, et c'etait un piege arme : un
# `except video.BudgetDepasse` attrapait jusqu'ici une classe differente de
# celle que chanson.py levait.
BudgetDepasse = budget_modal.BudgetDepasse


# --- Le script envoye sur la machine distante ---------------------------------

# Ce texte part tel quel sur le GPU. Il est autonome : il installe ce qui manque,
# telecharge le modele dans le cache s'il n'y est pas, fabrique la video, et
# depose le fichier dans le repertoire de sortie que le bac a sable ramene.
_SCRIPT = r'''# -*- coding: utf-8 -*-
"""Fabrique une video courte. Genere par Free AI Studio."""
import base64, importlib.util, io, json, os, subprocess, sys, time

DEBUT = time.time()
D = json.loads(base64.b64decode("__DEMANDE__").decode("utf-8"))
SORTIE = os.environ.get("FREE_AI_OUTPUT_DIR", "/tmp/free_ai_output")
os.makedirs(SORTIE, exist_ok=True)
if D.get("cache"):
    os.makedirs(D["cache"], exist_ok=True)
    os.environ["HF_HOME"] = D["cache"]
    # Le bac a sable de la maison n'a PAS internet (reseau `internal: true`,
    # comme celui sur processeur). Si les poids ne sont pas deja dans le cache,
    # il ne pourra pas aller les chercher -- et le message brut serait une pile
    # d'erreurs de resolution de nom, ou personne ne lit << il manque le
    # modele >>. On regarde donc AVANT, et on dit quoi faire.
    if os.environ.get("HF_HUB_OFFLINE") == "1":
        dossier = os.path.join(D["cache"], "hub", "models--" + D["modele"].replace("/", "--"))
        if not os.path.isdir(dossier):
            print("ECHEC : les poids du modele %s ne sont pas sur cet ordinateur.\n"
                  "Ce bac a sable n'a pas internet, par construction : il ne peut pas les\n"
                  "telecharger lui-meme. Lancez UNE FOIS, dans le dossier du Studio :\n"
                  "    %s\n"
                  "C'est environ 34 Go, une seule fois, et le clip repartira ensuite tout seul."
                  % (D["modele"], D.get("aide_poids", "scripts/telecharger-modele-video")),
                  file=sys.stderr)
            sys.exit(5)
os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "0")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
# La memoire de la carte se morcelle au fil du calcul : il reste de la place au
# total, mais plus un seul bloc assez grand d'un seul tenant. Ce reglage laisse
# le systeme agrandir les blocs deja poses au lieu d'en reserver de nouveaux.
# Il doit etre pose AVANT le premier import de torch, sinon il est ignore en
# silence -- c'est pourquoi il est ici et pas plus bas.
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")


def assurer(paquets):
    """Installe ce qui manque. Sur Modal l'image les contient deja : cout nul."""
    manquants = [pip for pip, mod in paquets if importlib.util.find_spec(mod) is None]
    if manquants:
        print("Installation de : " + ", ".join(manquants), flush=True)
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", *manquants])


assurer([
    ("torch", "torch"),
    ("torchvision", "torchvision"),
    ("diffusers>=0.35.0", "diffusers"),
    ("transformers", "transformers"),
    ("accelerate", "accelerate"),
    ("sentencepiece", "sentencepiece"),
    ("protobuf", "google.protobuf"),
    ("ftfy", "ftfy"),
    ("imageio", "imageio"),
    ("imageio-ffmpeg", "imageio_ffmpeg"),
    ("pillow", "PIL"),
])

import PIL.Image
import torch
from diffusers import AutoencoderKLWan, WanPipeline, WanVACEPipeline
from diffusers.schedulers.scheduling_unipc_multistep import UniPCMultistepScheduler
from diffusers.utils import export_to_video

if not torch.cuda.is_available():
    print("ECHEC : aucune carte graphique sur cette machine.", file=sys.stderr)
    sys.exit(2)

nom_gpu = torch.cuda.get_device_name(0)
vram_go = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
print("Carte : %s, %.1f Go" % (nom_gpu, vram_go), flush=True)

# Un T4 est de generation Turing : il sait faire du float16, pas du bfloat16.
# Lui imposer bfloat16 le fait retomber sur une emulation lente, en silence.
supporte_bf16 = torch.cuda.is_bf16_supported()
dtype = torch.bfloat16 if supporte_bf16 else torch.float16
print("Precision : %s" % ("bfloat16" if supporte_bf16 else "float16"), flush=True)

L, H = int(D["largeur"]), int(D["hauteur"])
IMAGES = int(D["images"])
# Deux familles de modeles passent par ce script, et une seule sait faire les
# images de fin et de reference :
#   "vace" -> Wan 2.1 VACE, loue chez Modal ou Kaggle, 16 images/s
#   "ti2v" -> Wan 2.2 TI2V-5B, la carte de la maison, 24 images/s, PAS de VACE
FAMILLE = D.get("famille", "vace")
FPS = int(D.get("images_par_seconde", 16))


def charger(cle):
    brut = D.get(cle)
    if not brut:
        return None
    img = PIL.Image.open(io.BytesIO(base64.b64decode(brut))).convert("RGB")
    return img.resize((L, H))


depart = charger("image_depart")
fin = charger("image_fin")
reference = charger("image_reference")

print("Chargement du modele %s ..." % D["modele"], flush=True)
t0 = time.time()
vae = AutoencoderKLWan.from_pretrained(D["modele"], subfolder="vae", torch_dtype=torch.float32)
if FAMILLE == "ti2v":
    # Le modele de la maison. Sa configuration porte son propre ordonnanceur et
    # son propre `expand_timesteps` : on ne lui impose PAS de flow_shift, qui
    # est un reglage de la 2.1.
    pipe = WanPipeline.from_pretrained(D["modele"], vae=vae, torch_dtype=dtype)
else:
    pipe = WanVACEPipeline.from_pretrained(D["modele"], vae=vae, torch_dtype=dtype)
    pipe.scheduler = UniPCMultistepScheduler.from_config(
        pipe.scheduler.config, flow_shift=float(D["flow_shift"])
    )

# MESURE DU 09/09 : tout mettre sur la carte a sature 22 Go et le clip est mort
# en pleine compression d'images. Le coupable n'est pas le modele d'images (1,3
# milliard de parametres) mais le LECTEUR DE TEXTE qui l'accompagne, bien plus
# gros, et qui n'a rien a faire sur la carte pendant le calcul des images.
# enable_model_cpu_offload() ne garde sur la carte que la piece qui travaille a
# cet instant. On ne s'en passe qu'avec beaucoup de memoire.
if vram_go < 60:
    pipe.enable_model_cpu_offload()
    print("Pieces chargees une par une sur la carte (memoire limitee).", flush=True)
else:
    pipe.to("cuda")

# Deuxieme economie, sur le meme echec : la compression des images se faisait
# d'un bloc. En tuiles, le pic de memoire descend fortement pour un cout de
# temps faible.
for piece in ("vae",):
    objet = getattr(pipe, piece, None)
    for methode in ("enable_tiling", "enable_slicing"):
        fonction = getattr(objet, methode, None)
        if callable(fonction):
            try:
                fonction()
            except (RuntimeError, ValueError, TypeError) as exc:
                print("%s.%s indisponible : %s" % (piece, methode, exc), flush=True)

print("Modele pret en %.0f s" % (time.time() - t0), flush=True)

kwargs = dict(
    prompt=D["description"],
    negative_prompt=D["negatif"],
    height=H,
    width=L,
    num_frames=IMAGES,
    num_inference_steps=int(D["etapes"]),
    guidance_scale=5.0,
)

# Image de depart et/ou de fin : on fabrique une piste ou seules ces deux images
# sont connues, le reste est gris et masque. C'est la facon dont VACE recoit une
# contrainte de premiere et de derniere image.
if FAMILLE == "ti2v" and (depart is not None or fin is not None or reference is not None):
    # Ce cas ne doit jamais arriver : `ou_calculer.decider()` envoie ces clips
    # chez Modal, et `preparer(maison=True)` refuse deja. Le troisieme garde est
    # ici parce que les deux premiers sont dans un autre fichier, et que la
    # panne qu'on evite est SILENCIEUSE : `diffusers` accepte `last_image` sur
    # ce modele et ne s'en sert pas (mesure du 19/09), et `WanPipeline` n'a
    # meme pas d'argument `image` -- une image de depart posee ici partirait a
    # la poubelle sans un mot. Mieux vaut un arret net qu'un clip qui a l'air
    # bon et ignore la consigne.
    print("ECHEC : le modele de la maison, tel qu'il est lance ici, ne pose ni "
          "l'image de depart ni l'image de fin ni l'image de reference. "
          "Ce clip devait partir chez Modal.",
          file=sys.stderr)
    sys.exit(4)

if FAMILLE != "ti2v" and (depart is not None or fin is not None):
    gris = PIL.Image.new("RGB", (L, H), (128, 128, 128))
    noir = PIL.Image.new("L", (L, H), 0)
    blanc = PIL.Image.new("L", (L, H), 255)
    pistes, masque = [], []
    for i in range(IMAGES):
        premiere = i == 0 and depart is not None
        derniere = i == IMAGES - 1 and fin is not None
        if premiere:
            pistes.append(depart); masque.append(noir)
        elif derniere:
            pistes.append(fin); masque.append(noir)
        else:
            pistes.append(gris); masque.append(blanc)
    kwargs["video"] = pistes
    kwargs["mask"] = masque

resultat = None
erreurs = []
# L'image de reference se passe en liste. Selon la version de diffusers, c'est
# une liste d'images ou une liste par element du lot : on essaie les deux plutot
# que d'epingler une version qui vieillira.
essais = [None]
if reference is not None and FAMILLE != "ti2v":
    essais = [[reference], [[reference]]]

for tentative in essais:
    args = dict(kwargs)
    if tentative is not None:
        args["reference_images"] = tentative
    try:
        print("Calcul en cours (%d images, %d etapes) ..." % (IMAGES, args["num_inference_steps"]), flush=True)
        t1 = time.time()
        resultat = pipe(**args).frames[0]
        print("Calcul fait en %.0f s" % (time.time() - t1), flush=True)
        break
    except (TypeError, ValueError) as exc:
        erreurs.append("%s: %s" % (type(exc).__name__, exc))
        continue

if resultat is None:
    print("ECHEC du calcul : " + " | ".join(erreurs), file=sys.stderr)
    sys.exit(3)

chemin = os.path.join(SORTIE, "video.mp4")
export_to_video(resultat, chemin, fps=FPS)

# Un MP4 range son sommaire (duree, taille, position des images) a la FIN du
# fichier. Un navigateur doit alors telecharger tout le fichier avant d'afficher
# la premiere image. Le deplacer au debut ne recompresse rien -- on recopie les
# memes donnees dans un autre ordre -- et la lecture demarre tout de suite.
# Si quoi que ce soit echoue ici, on garde le fichier d'origine : il est bon,
# seulement moins commode.
try:
    import imageio_ffmpeg
    provisoire = chemin + ".rapide.mp4"
    subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error",
         "-i", chemin, "-c", "copy", "-movflags", "+faststart", provisoire],
        check=True, timeout=120,
    )
    if os.path.getsize(provisoire) > 0:
        os.replace(provisoire, chemin)
        print("Index deplace en tete : la lecture demarre sans tout telecharger.", flush=True)
except Exception as exc:  # noqa: BLE001 - une commodite, jamais une condition
    print("Index laisse en fin de fichier (%s). Le clip reste lisible." % exc, flush=True)

taille = os.path.getsize(chemin)
resume = {
    "fichier": "video.mp4",
    "octets": taille,
    "images": IMAGES,
    "images_par_seconde": FPS,
    "secondes_video": round(IMAGES / float(FPS), 1),
    "largeur": L,
    "hauteur": H,
    "modele": D["modele"],
    "famille": FAMILLE,
    "carte": nom_gpu,
    "precision": "bfloat16" if supporte_bf16 else "float16",
    "secondes_calcul": round(time.time() - DEBUT, 1),
}
with open(os.path.join(SORTIE, "resume.json"), "w", encoding="utf-8") as f:
    json.dump(resume, f, ensure_ascii=False, indent=2)
print(json.dumps(resume, ensure_ascii=False), flush=True)
'''


def construire_script(demande: dict) -> str:
    """Fabrique le script autonome a envoyer sur le GPU.

    La demande voyage encodee DANS le script : un seul fichier part, quel que
    soit le fournisseur (Modal ecrit un fichier, Kaggle pousse un carnet, Colab
    fabrique un notebook). Une seule facon de faire, donc une seule a reparer.
    """
    charge = base64.b64encode(
        json.dumps(demande, ensure_ascii=False).encode("utf-8")
    ).decode("ascii")
    return _SCRIPT.replace("__DEMANDE__", charge)


def preparer(payload: dict, pour_modal: bool = True, maison: bool = False) -> dict:
    """Traduit ce que la page a envoye en une demande complete et bornee.

    `maison` n'est pas un choix du client : c'est le verdict de
    `ou_calculer.decider()`. La qualite demandee ne survit pas a ce verdict --
    le modele de la maison a sa propre definition et sa propre cadence -- et
    c'est voulu : le client choisit OU, pas quel modele."""
    qualite = payload.get("qualite") or "rapide"
    if qualite not in MODELES or qualite == "maison":
        qualite = "rapide"
    if maison:
        qualite = "maison"
    modele = MODELES[qualite]
    table_durees = DUREES_MAISON if maison else DUREES

    duree = str(payload.get("duree") or DUREE_PAR_DEFAUT)
    if duree not in table_durees:
        if maison:
            raise ValueError(
                "Un clip de %s s est trop long pour ce que l'on sait majorer sur la "
                "carte d'ici. Il ne peut pas y etre fabrique." % duree
            )
        if duree not in DUREES_MAISON:
            raise ValueError(
                "Aucun des deux modeles ne sait faire un clip de %s s : le modele "
                "loue s'arrete a %d s, et la carte d'ici a %d s."
                % (duree, secondes_max_loueur(), secondes_max_maison())
            )
        # ICI VIVAIT `duree = "5"`. Le client demandait 7 s, recevait 5 s, et
        # aucune ligne ne le disait -- la substitution corrompait meme le
        # routage, qui decidait sur la memoire d'un clip de 5 s. Cette duree
        # n'est connue que de la maison : on prepare donc le plan de la maison,
        # pour que le routage tranche sur la VRAIE duree. `decider()` sait
        # qu'elle ne peut pas partir chez le loueur (`loueur_peut`).
        return preparer(payload, pour_modal=False, maison=True)

    description = str(payload.get("description") or "").strip()
    if not description:
        raise ValueError("Il faut decrire la scene en quelques mots.")
    if len(description) > 2000:
        description = description[:2000]

    demande = {
        "modele": modele["hf"],
        "famille": modele.get("famille", "vace"),
        "description": description,
        "negatif": NEGATIF,
        "largeur": modele["largeur"],
        "hauteur": modele["hauteur"],
        "flow_shift": modele["flow_shift"],
        "etapes": modele["etapes"],
        "images": table_durees[duree]["images"],
        "images_par_seconde": modele.get("images_par_seconde", 16),
        "cache": CACHE_MAISON if maison else (CACHE_MODAL if pour_modal else ""),
        # Le script part sur une machine qui ne sait rien du systeme d'ou vient
        # la demande : la commande a taper voyage donc AVEC lui.
        "aide_poids": commande_telechargement(),
    }
    for cle_page, cle_demande in (
        ("image_depart", "image_depart"),
        ("image_fin", "image_fin"),
        ("image_reference", "image_reference"),
    ):
        brut = payload.get(cle_page)
        if brut:
            demande[cle_demande] = _nettoyer_image(brut, cle_page)

    # Le modele de la maison n'a pas de VACE : il ne SAIT PAS poser une image de
    # fin ni une image de reference. `diffusers` ne s'en plaindrait pas -- il
    # accepte l'argument et l'ignore en silence (mesure du 19/09 sur la 5B, ou
    # `last_image` est accepte puis jamais utilise). Un clip qui ignore la
    # consigne sans rien dire est pire qu'un clip paye : on refuse ici, fort.
    # L'image de DEPART est refusee pour une autre raison : le modele sait la
    # poser, mais par `WanImageToVideoPipeline`, pas par `WanPipeline` que ce
    # script emploie -- laquelle n'accepte meme pas l'argument. Non mesure ici,
    # donc non offert : le silence serait le meme.
    if maison:
        ignorees = [n for n in ("image_depart", "image_fin", "image_reference") if demande.get(n)]
        if ignorees:
            raise ValueError(
                "Le modele de la maison ne sait pas poser %s. Ce clip doit partir "
                "chez Modal." % " ni ".join(n.replace("_", " de ") for n in ignorees)
            )

    return {
        "qualite": qualite,
        "duree": duree,
        "gpu": modele["gpu"],
        "demande": demande,
        "resume_public": {
            # La phrase tapee par le client. Elle manquait jusqu'au 19/09/2026,
            # et son absence se mesure : des deux clips fabriques ce soir-la,
            # l'un pese 1 901 468 octets et l'autre 390 313 -- personne ne peut
            # plus dire sur quel texte, ni refaire le meme clip, ni comparer
            # deux modeles << sur le meme texte >> comme le plan le demande.
            # Elle ne quitte pas cet ordinateur : elle est ecrite dans la fiche
            # du travail, a cote du reste.
            "description": description,
            "modele": modele["hf"],
            "titre_modele": modele["titre"],
            "licence": modele["licence"],
            "carte": modele["gpu"],
            "definition": f"{modele['largeur']}x{modele['hauteur']}",
            "secondes_video": table_durees[duree]["secondes"],
            "images_par_seconde": demande["images_par_seconde"],
            "maison": maison,
            "image_depart": bool(demande.get("image_depart")),
            "image_fin": bool(demande.get("image_fin")),
            "image_reference": bool(demande.get("image_reference")),
        },
    }


MAX_IMAGE_OCTETS = int(os.getenv("VIDEO_MAX_IMAGE_BYTES", str(900 * 1024)))


def _nettoyer_image(brut: str, nom: str) -> str:
    """Accepte une image de la page, en base64 nue ou en data URI."""
    valeur = str(brut)
    if valeur.startswith("data:"):
        _, _, valeur = valeur.partition(",")
    valeur = "".join(valeur.split())
    try:
        octets = base64.b64decode(valeur, validate=True)
    except Exception as exc:  # noqa: BLE001 - message destine au debutant
        raise ValueError(f"L'image « {nom} » n'a pas pu etre lue.") from exc
    if len(octets) > MAX_IMAGE_OCTETS:
        raise ValueError(
            f"L'image « {nom} » est trop lourde ({len(octets) // 1024} Ko). "
            f"La page les reduit normalement toute seule ; reessayez avec une "
            f"image plus petite que {MAX_IMAGE_OCTETS // 1024} Ko."
        )
    if not octets:
        raise ValueError(f"L'image « {nom} » est vide.")
    return base64.b64encode(octets).decode("ascii")


# --- La page ------------------------------------------------------------------

PAGE_HTML = r"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Vidéo — Free AI Studio</title>
<style>
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;max-width:900px;
 margin:34px auto;padding:0 18px;line-height:1.55}
h1{font-size:1.5rem;margin-bottom:4px}
.sous{opacity:.8;margin-top:0}
.banniere{padding:14px 16px;border-radius:14px;margin:16px 0;border:1px solid #bbb;background:#eef4fb}
.ligne{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:14px 0}
select,button,input{font:inherit;padding:9px 12px;border-radius:10px;border:1px solid #666;background:#fff}
button.primaire{background:#222;color:#fff;border-color:#222;cursor:pointer}
button[disabled]{opacity:.5;cursor:default}
a.bouton{display:inline-block;font:inherit;padding:10px 16px;border-radius:10px;
 border:1px solid #222;background:#222;color:#fff;text-decoration:none;cursor:pointer}
a.bouton.discret{background:#fff;color:#222;border-color:#666}
a.bouton:hover{opacity:.86}
textarea{font:inherit;width:100%;box-sizing:border-box;height:110px;padding:12px;
 border-radius:12px;border:1px solid #999}
.images{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:14px}
.case{border:1px solid #bbb;border-radius:14px;padding:14px}
.case h3{margin:0 0 4px;font-size:1rem}
.case p{margin:0 0 10px;font-size:.85rem;opacity:.8}
.case img{max-width:100%;border-radius:9px;margin-top:9px;display:block}
pre{background:#f6f6f6;border:1px solid #ddd;border-radius:12px;padding:12px;
 overflow-x:auto;white-space:pre-wrap;word-break:break-word;font-size:.82rem}
video{width:100%;border-radius:12px;margin-top:12px;background:#000}
.ok{color:#1d6b32}.ko{color:#9b2116}
.avert{font-size:.86rem;opacity:.75}
.jauge{height:9px;border-radius:999px;background:#e6e6e6;overflow:hidden;margin:6px 0 2px}
.jauge span{display:block;height:100%;background:#5b8c5a}
/* La boite qui s'ouvre quand la carte de la maison est prise. Jaune et non
   rouge : rien n'est en panne, on attend une reponse. */
.attente{padding:14px 16px;border-radius:14px;margin:16px 0;border:1px solid #d6b45a;background:#fdf6e3}
.attente h3{margin:0 0 6px;font-size:1rem}
.attente .chiffres{font-size:.88rem;opacity:.85;margin:6px 0 12px}
.pied{margin-top:26px;padding-top:16px;border-top:1px solid #ddd;font-size:.9rem;opacity:.8}
</style></head><body>
<h1>🎬 Fabriquer une vidéo</h1>
<p class="sous">Décrivez une scène. Vous pouvez aussi donner l’image de départ,
celle d’arrivée, et une image de référence pour garder le même personnage.</p>

<div id="banniere" class="banniere">Vérification en cours…</div>

<textarea id="description" placeholder="Un phare breton sous la pluie, la mer se soulève, la lumière tourne."></textarea>

<div class="ligne">
  <label>Durée
    <select id="duree">__OPTIONS_DUREE__</select>
  </label>
  <!-- « si on loue » ici aussi, et pour la même raison que le menu voisin :
       quand le clip est fabriqué sur la carte de cet ordinateur, ce menu ne
       gouverne rien. Le modèle de la maison n'est pas dans cette liste -- il
       ne se choisit pas, il se déduit du réglage du dessous -- et la page l'a
       donc tu jusqu'au 19/09/2026 au soir, alors qu'il est celui qui fabrique
       le clip sur le réglage PAR DÉFAUT. Le propriétaire l'a vu : « pas de
       Wan 2.2 sur le lien /video ». La ligne de licence en dessous nomme
       maintenant les deux, et dit lequel part vraiment. -->
  <label>Qualité si on loue
    <select id="qualite"><option value="rapide" selected>Rapide — Wan 2.1, 1,3 B</option><option value="soigne">Soignée — Wan 2.1, 14 B (plus chère)</option></select>
  </label>
  <!-- Ce menu ne dit plus OÙ le clip se fabrique : depuis le 19/09/2026 c'est
       la ligne « Carte de cet ordinateur », juste en dessous, qui le décide.
       Celui-ci dit quelle machine on loue QUAND on loue. Garder le mot « Où »
       aurait laissé deux réglages se disputer la même question. -->
  <label>Si on loue
    <select id="ou"><option value="modal" selected>Modal — machine louée (carte bancaire exigée)</option><option value="kaggle">Kaggle — gratuit, plus lent</option></select>
  </label>
  <button id="lancer" class="primaire">Fabriquer</button>
</div>
<p id="licence" class="avert"></p>

<!-- N'apparait QUE si cet ordinateur a une carte branchee au Studio. Celui qui
     n'en a pas ne doit pas voir un reglage qui ne le concerne pas. -->
<div id="ouCalculer" class="ligne" hidden>
  <label>Carte de cet ordinateur
    <select id="reglage">
      <option value="maison-si-libre">À la maison si la carte est libre (défaut)</option>
      <option value="toujours-modal">Toujours sur une machine louée</option>
      <option value="toujours-maison">Toujours à la maison, quitte à attendre</option>
    </select>
  </label>
  <span class="avert" id="reglageNote"></span>
</div>

<div id="carteprise" class="attente" hidden></div>

<div class="images">
  <div class="case"><h3>Image de départ</h3>
    <p>Facultatif. La vidéo commencera exactement sur cette image.</p>
    <input type="file" accept="image/*" data-cle="image_depart"><div></div></div>
  <div class="case"><h3>Image de fin</h3>
    <p>Facultatif. La vidéo se terminera exactement sur celle-ci.</p>
    <input type="file" accept="image/*" data-cle="image_fin"><div></div></div>
  <div class="case"><h3>Image de référence</h3>
    <p>Facultatif. Le personnage ou l’objet montré ici sera gardé ressemblant.</p>
    <input type="file" accept="image/*" data-cle="image_reference"><div></div></div>
</div>

<div id="etat" class="ligne"></div>
<details id="detailJournal" hidden><summary>Voir le détail technique</summary>
<pre id="journal"></pre></details>
<div id="resultat"></div>

<div class="pied" id="pied"></div>

<script>
const CLE = "__CLE__";
const ENTETES = {"Authorization":"Bearer "+CLE, "Content-Type":"application/json"};
const IMAGES = {};
let minuteur = null;
let MODELES = null;
let CARTE_POSSIBLE = false;   // cet ordinateur a-t-il une carte branchée au Studio

// Du texte libre qui repasse dans du HTML redevient du code si on le laisse
// faire. Une seule ligne, et elle sert partout où l'on affiche ce que le
// client a tapé.
function enTexte(s){
  const d = document.createElement("div");
  d.textContent = String(s == null ? "" : s);
  return d.innerHTML;
}

// La licence s'affiche LA OU l'on choisit, pas dans une note en bas de page.
//
// Et depuis le 19/09/2026 elle nomme les DEUX modèles quand il y a une carte
// ici : celui qu'on loue, et celui de la maison. Le menu « Qualité si on loue »
// ne nomme que la Wan 2.1 ; or sur le réglage par défaut, carte libre, c'est la
// Wan 2.2 qui fabrique le clip -- 1280x704 à 24 images/s au lieu de 832x480 à
// 16. La page affichait donc, sur son chemin le plus fréquent, le nom d'un
// modèle qui ne tournait pas. Aucun chiffre n'est écrit ici à la main : tout
// vient du dictionnaire servi par /video/budget.
function majLicence(){
  const cible = document.getElementById("licence");
  if(!MODELES){ cible.textContent = ""; return; }
  const m = MODELES[document.getElementById("qualite").value];
  const lignes = [];
  if(m){
    lignes.push("Si on loue : <b>" + m.hf + "</b> — licence " + m.licence + ", "
                + m.territoire + ".");
  }
  const maison = MODELES["maison"];
  const reglage = (document.getElementById("reglage") || {}).value;
  if(CARTE_POSSIBLE && maison && reglage !== "toujours-modal"){
    lignes.push("À la maison : <b>" + maison.hf + "</b> — licence " + maison.licence
                + ", " + maison.largeur + "×" + maison.hauteur + " à "
                + maison.images_par_seconde + " images/s, gratuit. "
                + maison.note);
  }
  cible.innerHTML = lignes.join("<br>");
}
document.getElementById("qualite").addEventListener("change", majLicence);

// Les images sont réduites ICI, dans le navigateur : le modèle travaille de
// toute façon en 480p, et une photo de téléphone de 4 Mo n'apporterait rien
// qu'un envoi lent et un refus pour cause de taille.
function reduire(fichier, cote){
  return new Promise((ok, ko) => {
    const lecteur = new FileReader();
    lecteur.onerror = () => ko(new Error("lecture impossible"));
    lecteur.onload = () => {
      const img = new Image();
      img.onerror = () => ko(new Error("image illisible"));
      img.onload = () => {
        const r = Math.min(1, cote / Math.max(img.width, img.height));
        const c = document.createElement("canvas");
        c.width = Math.round(img.width * r); c.height = Math.round(img.height * r);
        c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
        ok(c.toDataURL("image/jpeg", 0.85));
      };
      img.src = lecteur.result;
    };
    lecteur.readAsDataURL(fichier);
  });
}

document.querySelectorAll('input[type=file]').forEach(entree => {
  entree.addEventListener("change", async () => {
    const cle = entree.dataset.cle;
    const apercu = entree.nextElementSibling;
    if(!entree.files || !entree.files[0]){ delete IMAGES[cle]; apercu.innerHTML=""; return; }
    try {
      const uri = await reduire(entree.files[0], 1024);
      IMAGES[cle] = uri;
      apercu.innerHTML = '<img src="' + uri + '" alt="">';
    } catch(e){
      delete IMAGES[cle];
      apercu.innerHTML = '<span class="ko">Image illisible.</span>';
    }
  });
});

function budgetTexte(b){
  const part = Math.min(100, 100 * b.usd / b.plafond_usd);
  // Le nombre affiché vient de Modal dès que leur relevé est là et qu'il est le
  // plus grand des deux. Le dire, parce que « estimation » et « relevé » ne se
  // discutent pas de la même façon.
  const reel = (b.usd_reel !== null && b.usd_reel !== undefined
                && b.usd_reel >= b.usd_estime);
  return "Dépensé sur Modal ce mois-ci " + (reel ? "selon Modal" : "selon le Studio")
    + ", tous usages confondus : <b>"
    + fr(b.usd, 2) + " $</b> sur les " + fr(b.plafond_usd, 2)
    + " $ ouverts aux demandes. " + b.clips + " clip(s) sur cette page."
    + '<div class="jauge"><span style="width:' + fr(part, 1) + '%"></span></div>'
    + '<span class="avert">'
    + (reel
       // Les 8 % décrivent la MÉTHODE de comptage, pas le total affiché : ce total court
       // sur tout le mois et peut contenir des travaux comptés AVANT la correction des
       // tarifs du 20/09/2026, à des prix trop bas. Mesuré ce jour-là sur cette page :
       // 1,39 $ estimé contre 3,80 $ facturés, soit 37 % — annoncer 8 % sur CE nombre
       // serait faux de loin.
       ? 'Chiffre <b>relevé chez Modal</b> le ' + dateFr(b.usd_reel_le) + ' : leur compte, pas '
         + 'le nôtre. Notre estimation locale, d’après les prix relevés le '
         + dateFr(b.prix_releve_le) + ', dit ' + fr(b.usd_estime, 2) + ' $. La méthode '
         + 'sous-compte d’environ 8 %, le temps de processeur réellement utilisé dépassant '
         + 'le cœur réservé — et ce total peut contenir des travaux comptés avant le '
         + dateFr(b.prix_releve_le) + ', à des tarifs plus bas. '
       : 'Estimation locale d’après les prix relevés le ' + dateFr(b.prix_releve_le)
         + ', pas une facture : Modal n’a pas répondu. La méthode <b>sous-compte d’environ '
         + '8 %</b> (le processeur réellement utilisé dépasse le cœur réservé, et cela ne se '
         + 'sait qu’après), et ce total peut contenir des travaux comptés avant cette date, '
         + 'à des tarifs plus bas. ')
    + 'Ce compteur est <b>unique</b> depuis le 19/09/2026 : il compte '
    + 'ensemble les clips, les chansons, les dialogues et le code envoyé au Sandbox, sur un '
    + 'budget de ' + fr(b.plafond_total_usd, 2) + ' $, dont '
    + fr(b.reserve_autonome_usd, 2) + ' $ sont réservés au Sandbox et ne peuvent pas '
    + 'être entamés ici. '
    + 'Le Studio ne lit pas votre compte Modal : le crédit de '
    + fr(b.credit_offert_usd, 0) + ' $ par mois est celui que vous avez déclaré '
    + '(MODAL_CREDIT_MENSUEL_USD), non vérifié chez Modal. Modal exige une carte bancaire et facture '
    + 'au-delà du crédit, jusqu’à votre limite de dépense : '
    + '<a href="https://modal.com/settings/usage" target="_blank" rel="noopener">réglez-la au plus bas chez Modal</a>.</span>';
}

function rafraichirBudget(){
  return fetch("/video/budget", {headers:{"Authorization":"Bearer "+CLE}})
    .then(r => r.json())
    .then(d => {
      document.getElementById("banniere").innerHTML = budgetTexte(d.budget);
      MODELES = d.modeles;
      majLicence();
      if(d.kaggle_permis === false){
        const k = document.querySelector('#ou option[value="kaggle"]');
        k.disabled = true;
        k.textContent = "Kaggle — coupé ici : Studio partagé";
      }
      const p = document.getElementById("pied");
      // Deux modèles, pas un : celui qu'on loue et celui d'ici. Le pied ne
      // citait que le premier -- voir le commentaire de majLicence().
      p.innerHTML = "Modèles : <b>" + d.modeles.rapide.hf + "</b> (" + d.modeles.rapide.licence
        + ", " + d.modeles.rapide.poids_go + " Go) quand on loue"
        + (CARTE_POSSIBLE && d.modeles.maison
            ? (", <b>" + d.modeles.maison.hf + "</b> (" + d.modeles.maison.licence + ", "
               + d.modeles.maison.poids_go + " Go) sur la carte de cet ordinateur")
            : "")
        + ". Rien ne part chez un fournisseur d’IA : "
        + "le calcul tourne sur une machine que vous louez à la minute. "
        // Une phrase se coupe sur un point, jamais au milieu : coupee en
        // deux morceaux, elle s’affiche bien mais ne se cherche plus,
        // ni par un test ni par qui relit. Vu le 21/09/2026.
        + "Le modèle n’est téléchargé qu’une fois, mais il est rechargé à chaque clip, "
        + "ce qui prend une ou deux minutes avant que le calcul commence."
        + '<br><a href="/">Retour au Sandbox</a> &nbsp; <a href="/cles">Brancher Modal ou Kaggle</a>';
      return d;
    })
    .catch(() => {
      document.getElementById("banniere").textContent =
        "État non vérifiable : le service Sandbox ne répond pas.";
    });
}

function condenser(t){
  // Les barres d'avancement ecrivent une ligne par pourcentage : le
  // telechargement du modele en produit plusieurs centaines, toutes pareilles,
  // et le debutant se retrouve devant un mur de chiffres ou il ne trouve plus
  // le message qui compte. On ne garde que la ligne d'arrivee de chaque barre,
  // et on dit combien de lignes ont ete mises de cote -- masquer sans le dire
  // serait mentir sur ce qui s'est passe.
  const gardees = []; let cachees = 0;
  for(const ligne of (t || "").split("\n")){
    if(/\d+%\|/.test(ligne) && !/100%\|/.test(ligne)){ cachees++; continue; }
    gardees.push(ligne);
  }
  if(cachees) gardees.push("… " + cachees + " lignes d’avancement masquées.");
  return gardees.join("\n");
}

function afficherJournal(t){
  document.getElementById("detailJournal").hidden = !t;
  document.getElementById("journal").textContent = condenser(t);
}

function nomDeFichier(){
  // Dix clips fabriques, et le dossier Telechargements contient video.mp4,
  // video(1).mp4, video(2).mp4 : plus personne ne sait lequel est lequel. Le nom
  // porte donc la date, l'heure, et le debut de la phrase demandee.
  const d = new Date();
  const jour = d.getFullYear() + "-"
    + String(d.getMonth()+1).padStart(2,"0") + "-"
    + String(d.getDate()).padStart(2,"0");
  const heure = String(d.getHours()).padStart(2,"0") + "h" + String(d.getMinutes()).padStart(2,"0");
  const mots = (document.getElementById("description").value || "")
    .normalize("NFD").replace(/[^\x00-\x7F]/g, "")
    .toLowerCase().replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+/, "").slice(0, 40).replace(/-+$/, "");
  return jour + "-" + heure + "-" + (mots || "video") + ".mp4";
}

function suivre(id){
  const etat = document.getElementById("etat");
  minuteur = setInterval(() => {
    fetch("/video/jobs/" + id, {headers:{"Authorization":"Bearer "+CLE}})
      .then(r => r.json())
      .then(j => {
        if(j.status === "running" || j.status === "queued"){
          const t = Math.round((Date.now()/1000) - (j.created_at || Date.now()/1000));
          etat.innerHTML = "⏳ En cours depuis " + t + " s. Le tout premier clip est le plus "
            + "long : le modèle se télécharge (une seule fois).";
          return;
        }
        clearInterval(minuteur); minuteur = null;
        document.getElementById("lancer").disabled = false;
        afficherJournal([j.stdout, j.stderr].filter(Boolean).join("\n"));
        rafraichirBudget();
        if(j.video_url){
          // Deux mots suffisent : fait ici, ou loué. Et le prix s'il y en a un.
          const maison = j.ou_calculer && j.ou_calculer.ou === "maison";
          const ouFait = maison
            ? "fait à la maison, 0 $"
            : ("loué" + (j.ou_calculer && j.ou_calculer.prix_estime_usd != null
                         ? (" — environ " + fr(j.ou_calculer.prix_estime_usd, 3) + " $") : ""));
          etat.innerHTML = '<span class="ok">✔ Vidéo prête</span> — ' + ouFait + (j.resume ?
            (", " + j.resume.secondes_calcul + " s de calcul, " + Math.round(j.resume.octets/1024) + " Ko") : "");
          const nom = nomDeFichier();
          const lienTelecharger = j.video_url + "&telecharger=1&nom=" + encodeURIComponent(nom);
          document.getElementById("resultat").innerHTML =
            '<video controls autoplay loop src="' + j.video_url + '"></video>'
            + '<div class="ligne">'
            + '<a class="bouton" href="' + lienTelecharger + '" download="' + nom + '">'
            + '⬇️ Télécharger la vidéo</a>'
            + '<a class="bouton discret" href="' + j.video_url + '" target="_blank" '
            + 'rel="noopener">Ouvrir dans un onglet</a>'
            + '<span class="avert">Le fichier s’appellera <code>' + nom + '</code> et ira '
            + 'dans votre dossier Téléchargements.</span>'
            + '</div>'
            // Le texte qui a fait ce clip, sous le clip. Sans lui, deux clips
            // côte à côte ne se distinguent plus dès le lendemain. Échappé :
            // c'est du texte libre, et il ne doit jamais redevenir du code en
            // revenant du serveur.
            + ((j.video && j.video.description)
                ? ('<p class="avert">Texte : « ' + enTexte(j.video.description) + ' »</p>')
                : "");
        } else {
          etat.innerHTML = '<span class="ko">✖ Échec</span> — ' + (j.message || "voir le journal ci-dessous.");
        }
      })
      .catch(() => {});
  }, 4000);
}

// --- Où le clip se fabrique --------------------------------------------------
//
// Le service tranche ce qui est factuel — ce que la carte d'ici sait faire, la
// place qu'il faut, ce qui reste de libre — et REND LA QUESTION dès qu'il ne
// reste qu'un arbitrage de goût : attendre ne coûte rien, louer coûte de
// l'argent, et personne d'autre que le client ne sait s'il est pressé.
// Un 409 n'est donc pas une panne : c'est une question.

let ATTENTE_DEPUIS = null;      // l'heure où le client a dit « j'attends »
let ATTENTE_MINUTEUR = null;

function reglageActuel(){
  const s = document.getElementById("reglage");
  return s ? s.value : null;
}

function chargerReglage(){
  return fetch("/video/ou-calculer", {headers:{"Authorization":"Bearer "+CLE}})
    .then(r => r.json())
    .then(d => {
      if(!d.carte_possible) return d;   // pas de carte ici : rien à régler
      CARTE_POSSIBLE = true;
      document.getElementById("ouCalculer").hidden = false;
      document.getElementById("reglage").value = d.reglage;
      majLicence();   // la ligne de licence doit nommer le modèle de la maison
      // Ce qui est MESURE, jamais ce qui est offert : les nommer toutes
      // << mesurees >> etait un nombre fabrique, vu en ouvrant la page.
      // Et DEUX listes, pas une : la place a ete relevee sur un vrai clip pour
      // toutes les durees de la campagne du 21/09 ; le TEMPS n'a ete
      // chronometre aux vraies passes que pour deux d'entre elles, et il
      // depend des passes la ou la place n'en depend pas. Une seule liste
      // ferait dire << chronometree >> d'un temps extrapole.
      // Une enumeration francaise prend des virgules et un seul << et >>.
      // `join(" et ")` disait vrai tant que la liste tenait deux elements ; la
      // campagne du 21/09 l'a portee a sept, et la page affichait
      // << 1 et 2 et 3 et 4 et 6 et 7 et 8 secondes >> -- vu en ouvrant la page,
      // invisible aux tests, qui ne lisent pas une phrase.
      const enumere = (l) => l.length < 2 ? (l[0] || "")
        : l.slice(0, -1).join(", ") + " et " + l[l.length - 1];
      const place = enumere(d.durees_mesurees || []);
      const chrono = enumere(d.durees_chronometrees || []);
      document.getElementById("reglageNote").textContent =
        "Fabriquer ici ne coûte rien. La carte est partagée : le Studio ne prend "
        + "jamais la place d'un calcul en cours."
        + (place
           ? (" Place relevée sur cette carte pour : " + place + " secondes.")
           : "")
        + (chrono
           ? (" Le temps affiché est une estimation, sauf pour " + chrono
              + " secondes, qui ont été chronométrées.")
           : "");
      return d;
    })
    .catch(() => null);
}

const selReglage = document.getElementById("reglage");
if(selReglage){
  selReglage.addEventListener("change", () => {
    majLicence();   // « toujours sur une machine louée » retire la ligne maison
    fetch("/video/ou-calculer", {method:"POST", headers:ENTETES,
                                 body:JSON.stringify({reglage: selReglage.value})})
      .catch(() => {});
  });
}

function fermerAttente(){
  if(ATTENTE_MINUTEUR){ clearTimeout(ATTENTE_MINUTEUR); ATTENTE_MINUTEUR = null; }
  ATTENTE_DEPUIS = null;
  document.getElementById("carteprise").hidden = true;
  document.getElementById("carteprise").innerHTML = "";
}

function prix(d){
  return d.prix_estime_usd == null ? "" : (" — environ " + fr(d.prix_estime_usd, 3) + " $");
}

// La carte est prise. On montre CE QUI BLOQUE avec ses nombres, puis on attend
// une réponse. Jamais « indisponible » tout seul : un refus sans chiffre envoie
// chercher une panne qui n'existe pas.
function demanderAuClient(d){
  const boite = document.getElementById("carteprise");
  const c = d.carte || {};
  const chiffres = (c.libre_mo != null && c.totale_mo != null)
    ? (c.nom + " : " + fr((c.libre_mo/1024), 1) + " Go libres sur "
       + fr((c.totale_mo/1024), 1)
       + (d.besoin_est_mesure ? ", il en faut " : ", il en faut au plus ")
       + fr((d.besoin_mo/1024), 1) + ".")
    : (d.pourquoi || "");
  boite.hidden = false;

  // `titre` n'arrive que quand ce n'est PAS la carte qui bloque -- aujourd'hui
  // le modèle qui se télécharge. Sans lui, la boîte dirait « la carte est
  // prise » pendant que le Studio descend 34 Go, ce qui est faux et inquiète.
  if(d.ou === "attente"){
    const depuis = ATTENTE_DEPUIS ? Math.round((Date.now() - ATTENTE_DEPUIS)/1000) : 0;
    boite.innerHTML = "<h3>⏸ " + (d.titre ? d.titre : "J’attends la carte") + "</h3>"
      + '<div class="chiffres">' + chiffres + " Nouvel essai toutes les 30 secondes ; "
      + "j’attends depuis " + depuis + " s."
      + (d.titre ? "" : " On n’arrête jamais le calcul qui tient la carte.") + "</div>"
      + '<div class="ligne">'
      + '<button class="primaire" id="btLouer">Louer chez ' + (document.getElementById("ou").value === "kaggle" ? "Kaggle" : "Modal") + prix(d) + '</button>'
      + '<button id="btAnnuler">Annuler</button></div>';
    document.getElementById("btLouer").onclick = () => { fermerAttente(); envoyer({ou_calculer:"toujours-modal"}); };
    document.getElementById("btAnnuler").onclick = () => {
      fermerAttente();
      document.getElementById("lancer").disabled = false;
      document.getElementById("etat").textContent = "Abandonné. Rien n’a été fabriqué, rien n’a été facturé.";
    };
    if(!ATTENTE_DEPUIS) ATTENTE_DEPUIS = Date.now();
    ATTENTE_MINUTEUR = setTimeout(() => envoyer({attendre:true}), 30000);
    return;
  }

  // « on-demande » : trois sorties, et le prix AVANT, pas après.
  boite.innerHTML = "<h3>" + (d.titre ? d.titre : "La carte de cet ordinateur est prise") + "</h3>"
    + '<div class="chiffres">' + chiffres + " Attendre ne coûte rien ; louer, si.</div>"
    + '<div class="ligne">'
    + '<button class="primaire" id="btAttendre">J’attends</button>'
    + '<button id="btLouer">Louer chez ' + (document.getElementById("ou").value === "kaggle" ? "Kaggle" : "Modal") + prix(d) + '</button>'
    + '<button id="btAnnuler">Annuler</button></div>';
  document.getElementById("btAttendre").onclick = () => { ATTENTE_DEPUIS = Date.now(); envoyer({attendre:true}); };
  document.getElementById("btLouer").onclick = () => { fermerAttente(); envoyer({ou_calculer:"toujours-modal"}); };
  document.getElementById("btAnnuler").onclick = () => {
    fermerAttente();
    document.getElementById("lancer").disabled = false;
    document.getElementById("etat").textContent = "Abandonné. Rien n’a été fabriqué, rien n’a été facturé.";
  };
}

function envoyer(extra){
  const bouton = document.getElementById("lancer");
  const etat = document.getElementById("etat");
  const corps = Object.assign({
    description: document.getElementById("description").value,
    duree: document.getElementById("duree").value,
    qualite: document.getElementById("qualite").value,
    ou: document.getElementById("ou").value,
    ou_calculer: reglageActuel(),
  }, IMAGES, extra || {});
  bouton.disabled = true;
  if(!extra || !extra.attendre){
    etat.textContent = "Envoi…";
    document.getElementById("resultat").innerHTML = "";
    afficherJournal("");
  }
  fetch("/video/creer", {method:"POST", headers:ENTETES, body:JSON.stringify(corps)})
    .then(async r => {
      const d = await r.json().catch(() => ({}));
      // 409 : rien n'est cassé, la carte est prise et c'est au client de dire.
      if(r.status === 409 && d.detail && d.detail.ou){ demanderAuClient(d.detail); return null; }
      if(!r.ok){ throw new Error(typeof d.detail === "string" ? d.detail : ("HTTP " + r.status)); }
      return d;
    })
    .then(d => {
      if(!d) return;
      fermerAttente();
      const ouFait = (d.ou_calculer && d.ou_calculer.ou === "maison")
        ? "⏳ Lancé sur la carte de cet ordinateur — gratuit."
        : "⏳ Lancé sur une machine louée.";
      etat.textContent = ouFait;
      suivre(d.id);
    })
    .catch(e => {
      fermerAttente();
      bouton.disabled = false;
      etat.innerHTML = '<span class="ko">✖ ' + e.message + '</span>';
    });
}

document.getElementById("lancer").addEventListener("click", () => { ATTENTE_DEPUIS = null; envoyer(null); });

// Dans cet ordre, et pas l'inverse : le pied de page et la ligne de licence
// nomment le modèle de la maison, ce qu'ils ne peuvent faire que si l'on sait
// déjà si cet ordinateur a une carte. chargerReglage() répond à cette
// question ; rafraichirBudget() écrit les deux lignes.
chargerReglage().then(rafraichirBudget);
</script>
</body></html>"""
