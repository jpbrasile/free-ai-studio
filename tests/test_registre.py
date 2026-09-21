"""Le registre des applications, et l'interdiction de diverger du code.

Le defaut repare, mesure le 20/09/2026 : la meme verite etait recopiee a six
endroits, et quatre avaient diverge. << FireRedTTS2 >> apparaissait 28 fois dans
le code et 0 fois dans le README ; << Wan2.2 >> 10 fois et 0 fois ; << maison >>
99 fois et 0 fois. Le README -- le seul document qu'un debutant lit AVANT
d'installer -- annoncait donc que la video exige une carte bancaire, alors
qu'elle se fabrique gratuitement sur la carte du PC depuis le 19/09/2026.

Ce que ces tests gardent, et c'est le seul point qui compte :

1. le registre dit du code ce que le code dit de lui-meme -- modele par modele,
   licence par licence, dans les deux sens ;
2. une application que le code sert SANS ligne au registre fait tomber la suite.
   C'est ce controle-la qui aurait attrape le dialogue et la video de la maison,
   et c'est pour cela qu'il est ecrit sur les tables du code et non sur une
   liste recopiee ici ;
3. le README nomme chaque application du registre.

Aucun appel reseau.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import unicodedata

import pytest

from conftest import RACINE

REGISTRE = RACINE / "registry" / "apps.json"
CHAMPS = ("id", "fonction", "fournisseur", "modele", "nature", "licence",
          "territoire", "vram_min_go", "modes", "cout", "source", "verifie_le")
MODES_CONNUS = {"api", "local", "modal", "kaggle", "colab"}


def _nu(texte: str) -> str:
    """Le mot tel qu'on le compare : sans accents.

    Le registre part tel quel dans le README et s'ecrit donc en francais
    accentue ; les tables du code suivent la convention du depot et s'ecrivent
    en ASCII. Comparer au caractere pres ferait tomber ces tests sur
    << trouvee >> contre << trouvee >>, c'est-a-dire sur une convention
    d'ecriture et non sur un desaccord de fond -- le genre de rouge qu'on
    finit par desactiver, ce qui rendrait la vraie garde muette.
    """
    decompose = unicodedata.normalize("NFKD", texte)
    return "".join(c for c in decompose if not unicodedata.combining(c))


@pytest.fixture
def registre():
    return json.loads(REGISTRE.read_text(encoding="utf-8"))


@pytest.fixture
def par_id(registre):
    return {a["id"]: a for a in registre["applications"]}


# --- 1. La forme -------------------------------------------------------------

def test_chaque_entree_porte_tous_les_champs(registre):
    """Un champ absent se lirait comme << rien a dire >>, pas comme un oubli."""
    for app in registre["applications"]:
        manquants = [c for c in CHAMPS if c not in app]
        assert not manquants, "%s : champs absents %s" % (app.get("id"), manquants)


def test_les_champs_qui_engagent_ne_sont_jamais_vides(registre):
    """`licence` et `territoire` engagent l'utilisateur devant la loi.

    `modele` et `vram_min_go` ont le droit d'etre nuls -- DuckDuckGo n'a pas de
    modele, une API n'a pas de carte graphique -- mais un null y est une reponse,
    pas un blanc : il se lit << sans objet >>.
    """
    for app in registre["applications"]:
        for champ in ("id", "fonction", "fournisseur", "nature", "licence",
                      "territoire", "cout", "source", "verifie_le"):
            valeur = app[champ]
            assert isinstance(valeur, str) and valeur.strip(), \
                "%s : %s est vide" % (app["id"], champ)


def test_les_identifiants_sont_uniques(registre):
    ids = [a["id"] for a in registre["applications"]]
    assert len(ids) == len(set(ids)), "identifiant en double : %s" % ids


def test_les_dates_de_verification_sont_des_dates(registre):
    """`verifie_le` sert a savoir ce qui a vieilli : une date molle ne sert a rien."""
    for app in registre["applications"]:
        assert re.fullmatch(r"20\d\d-\d\d-\d\d", app["verifie_le"]), \
            "%s : verifie_le = %r" % (app["id"], app["verifie_le"])


def test_les_modes_sont_des_modes_connus(registre):
    for app in registre["applications"]:
        assert app["modes"], "%s : aucun mode" % app["id"]
        inconnus = set(app["modes"]) - MODES_CONNUS
        assert not inconnus, "%s : modes inconnus %s" % (app["id"], inconnus)


# --- 2. Le registre dit du code ce que le code dit de lui-meme ---------------

def test_les_modeles_du_routeur_sont_ceux_du_registre(routeur, par_id):
    """Un modele change dans le code et pas ici ferait mentir le README."""
    attendus = {
        "chat_auto": routeur.PROVIDERS["gemini"]["model"],
        "chat_max": routeur.PROVIDERS["gemini_max"]["model"],
        "chat_secours_openrouter": routeur.PROVIDERS["openrouter"]["model"],
        "chat_secours_groq": routeur.PROVIDERS["groq"]["model"],
        "image_lecture": routeur.PROVIDERS["gemini"]["model"],
        "image_fabrication": routeur.GEMINI_IMAGE_MODEL,
        "voix_fr": routeur.VOIX["fr"]["nom"],
        "voix_en": routeur.VOIX["en"]["nom"],
        "dictee_locale": routeur.WHISPER_LOCAL,
        "dictee_groq": routeur.GROQ_DICTEE_MODELE,
    }
    for identifiant, modele in attendus.items():
        assert par_id[identifiant]["modele"] == modele, \
            "%s : registre %r, code %r" % (identifiant, par_id[identifiant]["modele"], modele)


VIDEOS = [("video_rapide", "rapide"), ("video_soignee", "soigne"),
          ("video_maison", "maison")]


@pytest.mark.parametrize("identifiant,cle", VIDEOS)
def test_les_videos_disent_la_meme_licence_des_deux_cotes(sandbox, par_id, identifiant, cle):
    """La licence est ce qui autorise ou interdit un usage commercial.

    Deux endroits qui n'en disent pas la meme chose, c'est pire qu'un seul qui
    se tait : le lecteur croit avoir verifie.
    """
    code = sandbox.video.MODELES[cle]
    app = par_id[identifiant]
    assert app["modele"] == code["hf"]
    assert _nu(code["licence"]) in _nu(app["licence"])
    assert _nu(app["territoire"]) == _nu(code["territoire"])


def test_la_chanson_dit_la_meme_chose_des_deux_cotes(sandbox, par_id):
    code = sandbox.chanson.MODELE
    app = par_id["chanson"]
    assert app["modele"] == code["hf"]
    assert _nu(code["licence"]) in _nu(app["licence"]), \
        "la licence des poids a disparu du registre"
    assert _nu(code["code_licence"]) in _nu(app["licence"]), \
        "la licence du code a disparu du registre"
    assert _nu(app["territoire"]) == _nu(code["territoire"])


def test_le_dialogue_garde_la_reserve_de_ses_auteurs(sandbox, par_id):
    """La nuance qui protege, et qui n'est PAS dans la licence.

    Les auteurs ecrivent que cette capacite est reservee a la recherche
    academique, alors que leur licence Apache 2.0 n'interdit rien. Le Studio
    affiche les deux ; un registre qui ne garderait que la licence serait le
    plus trompeur des deux documents.
    """
    code = sandbox.dialogue.MODELE
    app = par_id["dialogue"]
    assert app["modele"] == code["hf"]
    assert _nu(code["licence"]) in _nu(app["licence"])
    assert _nu(app["territoire"]) == _nu(code["territoire"])
    assert "academic research purposes" in app.get("note", ""), \
        "la reserve des auteurs a disparu du registre"
    assert "trouvee" in _nu(app["territoire"]), \
        "<< aucune restriction TROUVEE >> ne doit pas devenir << aucune restriction >>"


def test_la_place_sur_la_carte_est_celle_qui_a_ete_MESUREE(sandbox, par_id):
    """Ce nombre n'est pas une estimation : c'est ce qu'un vrai clip a pris.

    Si quelqu'un arrondissait ce nombre vers le bas, le Studio lancerait un clip
    sur une carte qui ne peut pas le tenir.

    C'est arrive, et ce test l'a attrape le 21/09 : le registre annoncait
    12,5 Go, qui etait le compteur interne de torch. La campagne a mesure la
    memoire LIBRE que le meme clip consomme -- 14 751 Mo, soit 14,4 Go. Le
    registre promettait 1,9 Go de moins que la realite. Il a rougi parce qu'il
    DEDUIT la valeur attendue de la table du code au lieu de la recopier ; les
    trois tests qui recopiaient les nombres, eux, ont defendu les anciens.
    """
    mesure_mo = sandbox.ou_calculer.BESOIN_MO_MESURE[73]
    assert par_id["video_maison"]["vram_min_go"] == round(mesure_mo / 1024, 1)


def test_le_prix_du_clip_loue_suit_le_TARIF_et_non_un_souvenir(sandbox, par_id):
    """Le registre annoncait 0,117 $, le code en calcule 0,155.

    Meme famille que le 12,5 Go, et trouvee le meme jour. Le 20/09,
    `modal billing rates` a revele que les bacs a sable paient le processeur et
    la memoire TROIS FOIS le tarif ordinaire ; `budget_modal` a ete corrige, et
    `prix_estime()` a suivi puisqu'il multiplie le temps mesure par le tarif du
    jour. Le registre, lui, portait un nombre recopie : il est reste sur
    l'ancien, 25 % sous la realite, et c'est un client qui l'aurait paye.

    Ce test DEDUIT le prix attendu du code. Un test qui l'aurait recopie serait
    reste d'accord avec le registre le jour ou les deux avaient tort.
    """
    attendu = sandbox.video.prix_estime("rapide", "3")
    assert attendu is not None, "la mesure du clip de 3 s a disparu de SECONDES_MESUREES"
    ecrit = "%.3f" % attendu
    ecrit = ecrit.replace(".", ",")
    assert ecrit in par_id["video_rapide"]["cout"], (
        "le registre annonce %r, le code calcule %s $"
        % (par_id["video_rapide"]["cout"], ecrit))


def test_un_modele_JAMAIS_lance_n_annonce_pas_un_prix(sandbox, par_id):
    """Le registre disait << environ six fois le prix de Rapide >>.

    Ce nombre n'avait de source nulle part dans le depot, et le modele soigne
    n'a jamais ete lance une seule fois : `prix_estime("soigne", ...)` rend
    None pour toutes les durees. Un multiple annonce au client est alors un
    nombre fabrique, quelle que soit sa vraisemblance.

    Le controle est ecrit dans ce sens-la, et non sur le texte : tant que le
    code ne sait pas chiffrer ce clip, le registre ne doit pas le chiffrer non
    plus. Le jour ou une mesure entre dans `SECONDES_MESUREES`, ce test demande
    de lui-meme que le registre porte enfin un prix.
    """
    sait_chiffrer = any(sandbox.video.prix_estime("soigne", str(d)) is not None
                        for d in range(1, 13))
    cout = par_id["video_soignee"]["cout"]
    if sait_chiffrer:
        assert "INCONNU" not in cout, (
            "une mesure existe desormais : le registre doit donner le prix")
        # Et ce doit etre LE prix, pas un prix. Tant que rien n'etait mesure,
        # ce test ne pouvait demander que la disparition d'un mot ; la mesure
        # entree le 21/09, il deduit le nombre comme celui du modele rapide.
        duree = next(d for d in map(str, range(1, 13))
                     if sandbox.video.prix_estime("soigne", d) is not None)
        ecrit = ("%.3f" % sandbox.video.prix_estime("soigne", duree)).replace(".", ",")
        assert ecrit in cout, (
            "le registre annonce %r, le code calcule %s $ pour %s s"
            % (cout, ecrit, duree))
    else:
        assert "INCONNU" in cout and "jamais" in cout, (
            "aucune mesure n'existe pour ce modele, et le registre annonce %r" % cout)


# --- 3. Rien ne se sert sans ligne au registre -------------------------------

def test_aucune_application_du_code_n_est_absente_du_registre(routeur, sandbox, registre):
    """LE controle qui aurait attrape le defaut d'origine.

    Il est ecrit sur les tables DU CODE et non sur une liste recopiee ici :
    une liste recopiee serait une septieme copie de la verite, et se tairait
    exactement le jour ou elle devrait parler.

    Ce qu'il compare sont des MODELES, pas des applications, et la nuance a ete
    mesuree le 20/09/2026 : les 15 entrees retirees une a une font toutes
    tomber le fichier, mais `chat_auto` et `image_lecture` partagent le modele
    de discussion de Gemini -- pour ces deux-la, c'est
    `test_les_modeles_du_routeur_sont_ceux_du_registre` qui parle, pas ce
    test-ci. Aucune licence ne peut donc disparaitre du README ; une LIGNE du
    tableau ne tiendrait, elle, que par ce nom ecrit en clair au-dessus.
    """
    au_registre = {a["modele"] for a in registre["applications"] if a["modele"]}
    servis = {m["hf"] for m in sandbox.video.MODELES.values()}
    servis.add(sandbox.chanson.MODELE["hf"])
    servis.add(sandbox.dialogue.MODELE["hf"])
    servis.update(p["model"] for p in routeur.PROVIDERS.values())
    servis.add(routeur.GEMINI_IMAGE_MODEL)
    servis.update(v["nom"] for v in routeur.VOIX.values())
    servis.update({routeur.WHISPER_LOCAL, routeur.GROQ_DICTEE_MODELE})

    absents = sorted(servis - au_registre)
    assert not absents, "servi par le Studio, absent du registre : %s" % absents


# --- 4. Le README nomme ce que le registre declare ---------------------------

def test_le_readme_nomme_chaque_application(registre):
    """Le README est le seul document lu AVANT l'installation.

    C'est la qu'ont manque le dialogue et la video de la maison, et c'est la que
    le manque coutait le plus cher : quelqu'un lisait << carte bancaire exigee >>
    pour une video que sa propre carte graphique fabrique gratuitement.
    """
    readme = (RACINE / "README.md").read_text(encoding="utf-8")
    absents = [a["id"] for a in registre["applications"]
               if a["modele"] and a["modele"] not in readme]
    assert not absents, "au registre, jamais nomme dans le README : %s" % absents


GENERATEUR = "scripts/engendrer-depuis-registre.py"

# (fichier, repere de debut, repere de fin)
BLOCS_ENGENDRES = [
    ("README.md",
     "<!-- TABLEAU-LICENCES: engendre par %s -->" % GENERATEUR,
     "<!-- FIN-TABLEAU-LICENCES -->"),
    ("notebooks/SOTA_LINKS.md",
     "<!-- EN-SERVICE: engendre par %s -->" % GENERATEUR,
     "<!-- FIN-EN-SERVICE -->"),
]


def test_les_blocs_engendres_suivent_encore_le_registre():
    """Le controle qui empeche la septieme copie de renaitre.

    Deux blocs sont ENGENDRES depuis le registre, entre deux reperes : le
    tableau des licences du README, et << ce que le Studio sert aujourd'hui >>
    dans notebooks/SOTA_LINKS.md. Sans ce test, plus rien n'obligerait a
    relancer le generateur : ces documents redeviendraient, en quelques
    semaines, des copies manuscrites qui ont diverge -- exactement le defaut
    repare le 20/09/2026.

    L'echec se repare par une commande, ecrite dans le message.
    """
    fait = subprocess.run([sys.executable, GENERATEUR, "--verifier"],
                          cwd=RACINE, capture_output=True, text=True)
    assert fait.returncode == 0, (
        "%s\nReparer par : python %s"
        % ((fait.stdout + fait.stderr).strip(), GENERATEUR))


@pytest.mark.parametrize("fichier,debut,fin", BLOCS_ENGENDRES,
                         ids=[b[0] for b in BLOCS_ENGENDRES])
def test_les_reperes_des_blocs_engendres_sont_toujours_la(fichier, debut, fin):
    """Sans eux, le generateur n'a plus ou ecrire -- et se taire serait pire.

    Quelqu'un qui reecrit la section a la main les efface sans le vouloir. Le
    test precedent leverait alors une erreur brute ; celui-ci dit ce qui manque.
    """
    texte = (RACINE / fichier).read_text(encoding="utf-8")
    for repere in (debut, fin):
        assert repere in texte, "repere absent de %s : %s" % (fichier, repere)
