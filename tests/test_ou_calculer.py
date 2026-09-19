"""Ou fabriquer un clip : ce que le module tranche, et ce qu'il RENVOIE au client.

Ce que ces tests gardent, defaut par defaut :

1. **Une commande que la maison ne sait pas faire gagne contre tous les
   reglages**, y compris << toujours a la maison >>. L'image de fin et l'image
   de reference sont des fonctions de VACE ; la Wan 2.2 n'en a pas (releve du
   19/09). Un routage qui les ignorerait rendrait un clip qui ne suit pas la
   consigne -- un faux vert, et c'est pire qu'un clip paye.
2. **Un besoin memoire non mesure ne part pas a la maison.** La table ne porte
   que des nombres releves sur cette machine ; une duree absente va chez Modal
   avec son motif. La gene est voulue : c'est elle qui fait mesurer.
3. **Carte prise + reglage par defaut = on DEMANDE**, on ne tranche pas. C'est
   l'ordre du proprietaire du 19/09 au soir, apres quinze minutes d'attente
   (18:20:54 -> 18:35:52) pour une fabrication de quelques minutes : depenser
   sans demander etait faux, et attendre sans demander l'est autant.
4. **Le motif porte toujours des chiffres.** Un << non >> sans nombre envoie
   chercher une panne qui n'existe pas.

Aucune carte n'est sondee : la sonde est remplacee partout.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
SRC = RACINE / "sandbox-manager"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _charger(nom: str):
    spec = importlib.util.spec_from_file_location(nom, SRC / (nom + ".py"))
    module = importlib.util.module_from_spec(spec)
    # Inscrit AVANT l'execution : un module charge par chemin n'est pas dans
    # sys.modules, et ce qui s'y annote ne saurait pas se relire.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gpu_local = _charger("gpu_local")
ou_calculer = _charger("ou_calculer")

# Le relevé exact rendu par la carte le 19/09/2026 depuis le conteneur.
CARTE_LIBRE = {"vue": True, "nom": "NVIDIA GeForce RTX 4090", "totale_mo": 24564,
               "libre_mo": 24138, "marge_mo": 1024, "motif": ""}
CARTE_PRISE = dict(CARTE_LIBRE, libre_mo=3200)
AUCUNE_CARTE = {"vue": False, "nom": None, "totale_mo": None, "libre_mo": None,
                "marge_mo": 1024, "motif": "nvidia-smi absent du conteneur"}

# 73 images = 3,04 s et 121 images = 5,04 s a 24 im/s : les deux durees dont le
# besoin a ete MESURE le 19/09 (12 841 et 14 902 Mo de pic). 161 images -- 6,7 s
# -- ne l'a pas ete, et c'est ce que ce troisieme nombre teste.
IMAGES_MESUREES = 73
IMAGES_MESUREES_5S = 121
IMAGES_NON_MESUREES = 161


def sonde_libre(besoin_mo, delai_s=None):
    return True, "NVIDIA GeForce RTX 4090 : 24138 Mo libres pour %d demandes (marge 1024)." % besoin_mo, CARTE_LIBRE


def sonde_prise(besoin_mo, delai_s=None):
    return False, ("NVIDIA GeForce RTX 4090 : 3200 Mo libres, il en faut %d. "
                   "La carte est partagee : on va chez Modal, on n'arrete personne."
                   % (besoin_mo + 1024)), CARTE_PRISE


def sonde_absente(besoin_mo, delai_s=None):
    return False, AUCUNE_CARTE["motif"], AUCUNE_CARTE


def resume(**kw):
    base = {"image_depart": False, "image_fin": False, "image_reference": False}
    base.update(kw)
    return base


# --- 1. Ce que la maison ne sait pas faire -----------------------------------

@pytest.mark.parametrize("commande, mot", [
    ("image_fin", "image de fin"),
    ("image_reference", "image de reference"),
])
def test_une_commande_sans_vace_part_chez_modal_meme_carte_libre(commande, mot):
    d = ou_calculer.decider(resume(**{commande: True}), IMAGES_MESUREES,
                            prix_estime_usd=0.117,
                            reglage=ou_calculer.MAISON_SI_LIBRE, sonde=sonde_libre)
    assert d["ou"] == ou_calculer.MODAL
    assert mot in d["pourquoi"]


def test_toujours_maison_ne_peut_pas_forcer_une_commande_que_la_maison_ignore():
    """Le reglage le plus ferme ne fabrique pas ce que le modele ne sait pas faire."""
    d = ou_calculer.decider(resume(image_fin=True), IMAGES_MESUREES,
                            reglage=ou_calculer.TOUJOURS_MAISON, sonde=sonde_libre)
    assert d["ou"] == ou_calculer.MODAL
    assert "ne peut pas etre fabrique ici" in d["pourquoi"]


def test_les_deux_commandes_manquantes_sont_nommees_ensemble():
    d = ou_calculer.decider(resume(image_fin=True, image_reference=True),
                            IMAGES_MESUREES, sonde=sonde_libre,
                            reglage=ou_calculer.MAISON_SI_LIBRE)
    assert "image de fin" in d["pourquoi"] and "image de reference" in d["pourquoi"]


def test_l_image_de_depart_part_chez_modal_tant_que_l_autre_classe_n_est_pas_essayee():
    """L'image de DEPART n'est pas une fonction de VACE -- et part quand meme.

    Elle passe par `WanImageToVideoPipeline` ; le script du Studio emploie
    `WanPipeline`, qui n'a meme pas d'argument `image` (verifie dans diffusers
    0.40.0 le 19/09). Router ce clip a la maison rendrait une video sans
    l'image demandee, SANS un mot. Ce test garde la porte fermee tant que
    l'autre classe n'a pas ete essayee ici."""
    d = ou_calculer.decider(resume(image_depart=True), IMAGES_MESUREES,
                            reglage=ou_calculer.MAISON_SI_LIBRE, sonde=sonde_libre)
    assert d["ou"] == ou_calculer.MODAL
    assert "image de depart" in d["pourquoi"]


# --- 2. Un besoin non mesure ne se devine pas --------------------------------

def test_une_duree_sans_table_maison_part_chez_modal():
    """`video.images_maison()` rend None pour une duree jamais mesuree ici."""
    d = ou_calculer.decider(resume(), None,
                            reglage=ou_calculer.MAISON_SI_LIBRE, sonde=sonde_libre)
    assert d["ou"] == ou_calculer.MODAL
    assert "pas encore ete mesuree" in d["pourquoi"]
    assert d["besoin_mo"] is None


def test_une_duree_non_mesuree_part_chez_modal_avec_son_motif():
    d = ou_calculer.decider(resume(), IMAGES_NON_MESUREES,
                            reglage=ou_calculer.MAISON_SI_LIBRE, sonde=sonde_libre)
    assert d["ou"] == ou_calculer.MODAL
    assert "pas encore ete mesuree" in d["pourquoi"]
    assert str(IMAGES_NON_MESUREES) in d["pourquoi"]
    assert d["besoin_mo"] is None


def test_la_table_des_besoins_ne_porte_que_du_mesure():
    """Les deux pics du 19/09. Aucun autre nombre, et surtout aucun extrapole.

    Le rapport entre les deux lignes est la raison meme de ce test : 66 %
    d'images en plus ne prennent que 16 % de memoire en plus. Qui extrapolerait
    la troisieme ligne a partir des deux premieres se tromperait -- dans le sens
    qui fait planter un calcul de dix minutes a la derniere seconde."""
    assert ou_calculer.BESOIN_MO_MESURE[73] == 12841
    assert ou_calculer.BESOIN_MO_MESURE[121] == 14902
    assert set(ou_calculer.BESOIN_MO_MESURE) == {73, 121}


def test_le_besoin_mesure_est_passe_a_la_sonde():
    vu = {}

    def espion(besoin_mo, delai_s=None):
        vu["besoin"] = besoin_mo
        return sonde_libre(besoin_mo, delai_s)

    ou_calculer.decider(resume(), IMAGES_MESUREES,
                        reglage=ou_calculer.MAISON_SI_LIBRE, sonde=espion)
    assert vu["besoin"] == 12841


# --- 3. Carte prise : on demande, on ne tranche pas --------------------------

def test_carte_prise_et_reglage_par_defaut_on_demande():
    d = ou_calculer.decider(resume(), IMAGES_MESUREES, prix_estime_usd=0.117,
                            reglage=ou_calculer.MAISON_SI_LIBRE, sonde=sonde_prise)
    assert d["ou"] == ou_calculer.ON_DEMANDE
    assert ou_calculer.ATTENTE in d["sorties"] and ou_calculer.MODAL in d["sorties"]
    assert "0.117" in d["pourquoi"]


def test_carte_prise_et_toujours_maison_on_attend_sans_rien_arreter():
    d = ou_calculer.decider(resume(), IMAGES_MESUREES,
                            reglage=ou_calculer.TOUJOURS_MAISON, sonde=sonde_prise)
    assert d["ou"] == ou_calculer.ATTENTE
    assert "on n'arrete jamais" in d["pourquoi"]


def test_carte_libre_on_fabrique_ici_et_ca_ne_coute_rien():
    d = ou_calculer.decider(resume(), IMAGES_MESUREES, prix_estime_usd=0.117,
                            reglage=ou_calculer.MAISON_SI_LIBRE, sonde=sonde_libre)
    assert d["ou"] == ou_calculer.MAISON
    assert d["prix_estime_usd"] is None
    assert "gratuitement" in d["pourquoi"]


def test_toujours_modal_ne_sonde_meme_pas_la_carte():
    def interdite(besoin_mo, delai_s=None):
        raise AssertionError("la carte ne doit pas etre sondee sous ce reglage")

    d = ou_calculer.decider(resume(), IMAGES_MESUREES,
                            reglage=ou_calculer.TOUJOURS_MODAL, sonde=interdite)
    assert d["ou"] == ou_calculer.MODAL


def test_aucune_carte_va_chez_modal_et_dit_pourquoi():
    d = ou_calculer.decider(resume(), IMAGES_MESUREES,
                            reglage=ou_calculer.MAISON_SI_LIBRE, sonde=sonde_absente)
    assert d["ou"] == ou_calculer.MODAL
    assert "nvidia-smi absent" in d["pourquoi"]


# --- 4. Le motif porte des chiffres ------------------------------------------

def test_le_refus_pour_carte_prise_dit_ce_qui_reste_et_ce_qu_il_faut():
    d = ou_calculer.decider(resume(), IMAGES_MESUREES, prix_estime_usd=0.117,
                            reglage=ou_calculer.MAISON_SI_LIBRE, sonde=sonde_prise)
    assert "3200" in d["pourquoi"]


def test_toutes_les_reponses_ont_les_memes_cles():
    """La page ne doit jamais deviner : la forme est la meme dans tous les cas."""
    cles = {"ou", "reglage", "pourquoi", "besoin_mo", "carte", "prix_estime_usd", "sorties"}
    cas = [
        (resume(), IMAGES_MESUREES, ou_calculer.MAISON_SI_LIBRE, sonde_libre),
        (resume(), IMAGES_MESUREES, ou_calculer.MAISON_SI_LIBRE, sonde_prise),
        (resume(), IMAGES_NON_MESUREES, ou_calculer.MAISON_SI_LIBRE, sonde_libre),
        (resume(image_fin=True), IMAGES_MESUREES, ou_calculer.MAISON_SI_LIBRE, sonde_libre),
        (resume(), IMAGES_MESUREES, ou_calculer.TOUJOURS_MODAL, sonde_libre),
        (resume(), IMAGES_MESUREES, ou_calculer.TOUJOURS_MAISON, sonde_prise),
        (resume(), IMAGES_MESUREES, ou_calculer.MAISON_SI_LIBRE, sonde_absente),
    ]
    for r, n, reg, s in cas:
        assert set(ou_calculer.decider(r, n, reglage=reg, sonde=s)) == cles


# --- Le reglage se garde d'un redemarrage a l'autre --------------------------

def test_le_reglage_se_relit_apres_ecriture(tmp_path, monkeypatch):
    monkeypatch.setattr(ou_calculer, "FICHIER", tmp_path / "ou-calculer.json")
    assert ou_calculer.reglage_lu() == ou_calculer.REGLAGE_DEFAUT
    ou_calculer.reglage_ecrit(ou_calculer.TOUJOURS_MAISON)
    assert ou_calculer.reglage_lu() == ou_calculer.TOUJOURS_MAISON


def test_un_reglage_inconnu_est_refuse_et_nomme_les_trois_possibles(tmp_path, monkeypatch):
    monkeypatch.setattr(ou_calculer, "FICHIER", tmp_path / "ou-calculer.json")
    with pytest.raises(ValueError) as erreur:
        ou_calculer.reglage_ecrit("sur-la-lune")
    for r in ou_calculer.REGLAGES:
        assert r in str(erreur.value)


def test_un_fichier_illisible_rend_le_defaut_sans_casser(tmp_path, monkeypatch):
    chemin = tmp_path / "ou-calculer.json"
    chemin.write_text("{ceci n'est pas du json", encoding="utf-8")
    monkeypatch.setattr(ou_calculer, "FICHIER", chemin)
    assert ou_calculer.reglage_lu() == ou_calculer.REGLAGE_DEFAUT


def test_un_reglage_inconnu_dans_le_fichier_rend_le_defaut(tmp_path, monkeypatch):
    chemin = tmp_path / "ou-calculer.json"
    chemin.write_text(json.dumps({"reglage": "ailleurs"}), encoding="utf-8")
    monkeypatch.setattr(ou_calculer, "FICHIER", chemin)
    assert ou_calculer.reglage_lu() == ou_calculer.REGLAGE_DEFAUT
