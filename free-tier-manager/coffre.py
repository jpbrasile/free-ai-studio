# -*- coding: utf-8 -*-
"""Le coffre : les magasins de secrets gardent les NOMS en clair, les VALEURS non.

CE QUE CE MODULE FERME, ET IL A MORDU POUR DE VRAI. Le 22/09/2026, un filtre de
lecture cherchant << modal >> dans la configuration a fait sortir
`MODAL_TOKEN_ID` et `MODAL_TOKEN_SECRET` dans un transcript ; les deux jetons ont
du etre revoques et regeneres. Ce n'etait pas une inattention isolee : tant que
les valeurs sont en clair, TOUTE lecture large les emporte -- un grep, un
journal, une sauvegarde, une capture d'ecran. `docs/SAUVEGARDES.md` nomme
d'ailleurs `keys.json` et `sandbox-keys.json` parmi les fichiers a sauvegarder :
la sauvegarde qui s'egare est le cas realiste, pas une hypothese.

LE MOT JUSTE EST << VERROU ANTI-LECTURE LARGE >>, PAS << CHIFFREMENT AU REPOS >>.
La cle vit sur le meme disque que le magasin. Quelqu'un qui a le disque a les
deux, et aucune ligne d'ici ne l'en empeche -- un disque revendu n'est PAS
defendu. Ce qui est defendu, c'est le cas ou le magasin part SANS sa cle : une
sauvegarde du dossier de configuration, un fichier colle dans un rapport, un
filtre de lecture qui balaie `config/`. Appeler cela << vos cles sont protegees >>
serait un faux-vert ; le depot refuse deja ce genre de drapeau
(`garde_exposition.py`, qui n'en annonce aucun parce qu'il n'en avait aucun).

ET LA PORTEE S'ARRETE AUX DEUX MAGASINS JSON. `.env` porte les memes jetons EN
CLAIR, par conception : `docker-compose.yml` les y lit a la CREATION du
conteneur, donc les chiffrer casserait le mecanisme entier. Le canal `.env` a sa
propre regle, et c'est la seule qui le tient -- ne jamais l'afficher ni le
copier. Ecrire << la fuite par lecture large est fermee >> sans cette borne
serait faux : elle est fermee pour `config/keys.json` et
`config/sandbox-keys.json`, pas pour `.env`. (Trouve par relecture adverse le
22/09/2026 ; je l'avais ecrit sans borne.)

LES NOMS RESTENT EN CLAIR, ET C'EST VOULU. Savoir quels services sont branches
n'est pas un secret, et un magasin illisible en entier serait un magasin qu'on ne
sait plus reparer a la main -- exactement ce dont un debutant a besoin le jour ou
son installation ne repond plus.

REFUSER PLUTOT QUE PARIER. Sans cle et sans endroit ou en poser une, `chiffrer()`
leve `CoffreSansCle` : l'appelant refuse d'ecrire. Retomber en clair << juste
cette fois >> serait le defaut lui-meme, en silence et sans personne pour le voir.

ATTENTION -- ce fichier existe en deux exemplaires IDENTIQUES, un par service,
pour la meme raison que `garde_exposition.py` : `free-tier-manager/` et
`sandbox-manager/` ecrivent chacun leur magasin, leurs images ont des contextes
de construction separes, et le contexte ne peut pas etre la racine du depot --
elle contient `.env` et `config/`, c'est-a-dire precisement ce que ce module
protege. `tests/test_coffre.py` echoue si les deux copies divergent d'un octet.
"""

import logging
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

log = logging.getLogger("coffre")

# Le prefixe rend la migration DECIDABLE : une valeur qui ne le porte pas date
# d'avant le coffre et doit etre rechiffree. Il porte un numero parce qu'un jour
# la forme changera, et qu'un magasin muet sur sa forme est un magasin qu'on ne
# sait pas relire.
PREFIXE = "coffre-v1:"

# HORS de `config/`, et c'est tout l'objet : le geste qui a fui balayait le
# dossier de configuration. Une cle rangee a cote du magasin qu'elle ferme ne
# ferme rien. Ce fichier ne contient aucun nom de service, donc un filtre par nom
# ne le ramene jamais.
CLE_FICHIER_DEFAUT = "/secrets/coffre.cle"


class CoffreSansCle(RuntimeError):
    """Aucune cle lisible, et aucun endroit ou en poser une."""


# Le refus nomme le geste qui repare, pas seulement la panne : un refus dont on
# ne sait que faire finit desactive.
_SANS_ENDROIT = ("aucune cle de coffre : %s n'est pas accessible en ecriture (%s). "
                 "Recreez les conteneurs, ou posez STUDIO_COFFRE_CLE dans .env.")


class CoffreIllisible(ValueError):
    """Une valeur chiffree que la cle presente n'ouvre pas."""


def chemin_de_la_cle() -> Path:
    return Path(os.getenv("STUDIO_COFFRE_FICHIER", CLE_FICHIER_DEFAUT))


def cle() -> bytes:
    """La cle du coffre : le `.env` d'abord, le fichier engendre ensuite.

    Le `.env` d'abord parce qu'il est le canal des secrets de ce depot et qu'il
    survit a un `config/` efface ; le fichier ensuite parce qu'un debutant ne
    doit pas avoir a editer un fichier pour que la page /cles fonctionne."""
    depuis_env = os.getenv("STUDIO_COFFRE_CLE", "").strip()
    if depuis_env:
        return depuis_env.encode("ascii")

    chemin = chemin_de_la_cle()
    try:
        texte = chemin.read_bytes().strip()
    except OSError:
        texte = b""
    if texte:
        return texte
    return _engendrer(chemin)


def _engendrer(chemin: Path) -> bytes:
    """Pose une cle neuve, une seule fois, meme si les deux services demarrent
    ensemble.

    `O_EXCL` n'est pas une precaution de principe : les deux services partagent
    ce fichier et demarrent dans la meme seconde. Sans lui, chacun engendrerait
    sa cle, la derniere ecrite gagnerait, et le magasin de l'autre deviendrait
    illisible -- une perte de cles silencieuse, au premier demarrage."""
    nouvelle = Fernet.generate_key()

    # Les deux gestes sont separes EXPRES. `mkdir(exist_ok=True)` leve
    # FileExistsError quand le parent existe en tant que FICHIER, et cette
    # exception-la n'a rien a voir avec celle du dessous. Groupes, le cas
    # << pas d'endroit ou ecrire >> etait pris pour le cas << l'autre service a
    # deja pose la cle >>, et le coffre partait relire un fichier absent.
    try:
        chemin.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise CoffreSansCle(_SANS_ENDROIT % (chemin, exc)) from exc

    try:
        drapeaux = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        with os.fdopen(os.open(str(chemin), drapeaux, 0o600), "wb") as sortie:
            sortie.write(nouvelle)
    except FileExistsError:
        # L'autre service est passe le premier, dans la meme seconde. Sa cle
        # fait foi : c'est tout l'objet de O_EXCL.
        return chemin.read_bytes().strip()
    except OSError as exc:
        raise CoffreSansCle(_SANS_ENDROIT % (chemin, exc)) from exc
    try:
        chemin.chmod(0o600)
    except OSError:
        # Montage Windows : les droits POSIX n'y veulent rien dire. Le fichier
        # est ecrit, c'est ce qui compte ; ne pas echouer pour ca.
        pass
    return nouvelle


def est_chiffre(garde: str) -> bool:
    return isinstance(garde, str) and garde.startswith(PREFIXE)


def chiffrer(valeur: str) -> str:
    """Rend la forme a ecrire dans le magasin. Une valeur vide reste vide."""
    if not valeur:
        return valeur
    jeton = Fernet(cle()).encrypt(valeur.encode("utf-8"))
    return PREFIXE + jeton.decode("ascii")


def dechiffrer(garde: str) -> str:
    """Rend la valeur. Une forme sans prefixe est rendue telle quelle : c'est un
    magasin d'avant le coffre, que `migrer()` rechiffrera."""
    if not est_chiffre(garde):
        return garde
    try:
        return Fernet(cle()).decrypt(garde[len(PREFIXE):].encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, TypeError) as exc:
        raise CoffreIllisible(
            "valeur chiffree que la cle presente n'ouvre pas : %s" % exc) from exc


def ouvrir_le_magasin(data: dict) -> dict:
    """Dechiffre ce qui peut l'etre. Une valeur illisible est ECARTEE et dite,
    jamais devinee : mieux vaut un service qui annonce << non configure >> qu'un
    service qui s'authentifie avec une valeur fausse."""
    clair = {}
    for nom, garde in data.items():
        if not isinstance(garde, str):
            continue
        try:
            clair[nom] = dechiffrer(garde)
        except CoffreIllisible as exc:
            log.warning("%s illisible, ecarte : %s", nom, exc)
    return clair


def fermer_ce_qui_est_en_clair(data: dict) -> dict:
    """Chiffre les valeurs encore en clair et NE TOUCHE PAS aux autres.

    Le detour compte : rechiffrer un magasin en passant par `ouvrir_le_magasin`
    ecarterait une valeur que la cle courante n'ouvre pas, et la reecriture
    l'effacerait pour de bon. Ce sont les vraies cles de quelqu'un. Une valeur
    deja fermee est donc recopiee octet pour octet, meme -- surtout -- si elle
    est illisible aujourd'hui : illisible se repare, efface non."""
    ferme = {}
    for nom, garde in data.items():
        if not isinstance(garde, str):
            continue
        ferme[nom] = garde if (est_chiffre(garde) or not garde) else chiffrer(garde)
    return ferme


def doit_migrer(data: dict) -> bool:
    """Vrai des qu'une valeur non vide est encore en clair."""
    return any(v and not est_chiffre(v) for v in data.values() if isinstance(v, str))
