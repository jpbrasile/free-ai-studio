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
    """Le reglage le plus ferme ne fabrique pas ce que le modele ne sait pas faire.

    Et il ne LOUE pas non plus sans accord : jusqu'au 23/09 cette decision
    rendait MODAL, et la route lancait le clip chez le loueur. Elle rend
    maintenant la question -- louer ou annuler -- sans proposer d'attendre.
    """
    d = ou_calculer.decider(resume(image_fin=True), IMAGES_MESUREES,
                            reglage=ou_calculer.TOUJOURS_MAISON, sonde=sonde_libre)
    assert d["ou"] == ou_calculer.ON_DEMANDE
    assert d["sorties"] == [ou_calculer.MODAL, "annuler"]
    assert "Rien n'est parti" in d["pourquoi"]
    assert "image de fin" in d["pourquoi"].lower()


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


# --- 2. Un MAJORANT, ancre sur ce qui a ete mesure ---------------------------
# Jusqu'au 21/09/2026 cette section notait l'inverse : une duree absente de la
# table partait chez le loueur, motif << on ne lance pas sur un chiffre
# suppose >>. Le proprietaire a retire la regle, en deux phrases :
#   << a quoi sert cette estimation, a savoir si on a assez de vram ? si c'est
#      le cas un majorant pour eviter les oom suffit >>
#   << deux durees, 3 s et 5 s : ce n'est pas normal, le client doit pouvoir
#      choisir dans la limite des capacites du llm et de la vram possible >>
# Le chiffre ne repond qu'a une question -- reste-t-il assez de place a cette
# seconde -- et un majorant y repond aussi bien qu'une mesure, et mieux qu'un
# refus : le refus figeait la page a deux durees, pour toujours.
# Ces tests gardent donc l'exigence par l'autre bout : LA LOI NE PROMET JAMAIS
# MOINS QU'UNE MESURE.

def test_une_duree_sans_table_maison_part_chez_modal():
    """`video.images_maison()` rend None quand la duree n'est pas offerte ici."""
    d = ou_calculer.decider(resume(), None,
                            reglage=ou_calculer.MAISON_SI_LIBRE, sonde=sonde_libre)
    assert d["ou"] == ou_calculer.MODAL
    assert "pas encore ete mesuree" in d["pourquoi"]
    assert d["besoin_mo"] is None


def test_la_loi_ne_promet_JAMAIS_moins_qu_une_mesure():
    """Le seul controle qui compte : aucune ancre au-dessus de la loi.

    Une loi qui passerait sous une mesure ferait lancer sur la carte un clip
    dont on SAIT qu'il ne tient pas -- dix minutes de calcul pour un
    depassement memoire a la fin.
    """
    for images, ancre in ou_calculer.ANCRES.items():
        assert ou_calculer.besoin_mo(images) >= ancre["memoire_mo"], (
            "%d images : la loi promet %d Mo, la mesure en a pris %d"
            % (images, ou_calculer.besoin_mo(images), ancre["memoire_mo"]))


def test_la_loi_monte_avec_le_nombre_d_images():
    """Plus d'images ne peut pas demander moins de place."""
    besoins = [ou_calculer.besoin_mo(24 * s + 1) for s in range(1, 9)]
    assert besoins == sorted(besoins), besoins


def test_entre_deux_mesures_c_est_LA_MESURE_DU_DESSUS_qui_majore():
    """Le coeur de la reparation du 21/09, apres la relecture adverse.

    Ajouter des images ne peut pas faire BAISSER la memoire. Tout nombre
    d'images situe sous un palier mesure tient donc dans ce palier : pas de
    droite a ajuster, pas de marge a choisir, aucune hypothese sur la forme de
    la courbe -- seulement qu'elle monte.

    Le premier jet ajustait une droite et la relevait de 8 %. Resultat : 97
    images (4 s) reservaient 14 981 Mo quand 121 images (5 s) n'en avaient
    mesure que 14 902. La duree la plus courte demandait plus que la plus
    longue, et pouvait se voir refuser a la maison quand l'autre passait.

    Les points d'essai se DEDUISENT de la table au lieu d'etre ecrits a la
    main : le 21/09, la campagne a fait de 25 et 49 images des ancres, et ce
    test a rougi en exigeant que 49 reserve le palier de 73. Il avait raison de
    rougir -- mais pour la mauvaise raison, puisque 49 etait devenu une mesure.
    Un test qui nomme des nombres que la table peut s'approprier est un test
    qui rougira encore a la prochaine campagne, sans rien avoir garde.
    """
    paliers = sorted(ou_calculer.ANCRES)
    entre_deux = [(bas + haut) // 2 for bas, haut in zip(paliers, paliers[1:])
                  if haut - bas > 1]
    assert entre_deux, "la table n'a plus deux paliers voisins : rien a majorer"
    for images in entre_deux:
        assert images not in ou_calculer.ANCRES, images
        au_dessus = min(n for n in paliers if n > images)
        attendu = max(ou_calculer.ANCRES[n]["memoire_mo"]
                      for n in paliers if n <= au_dessus)
        assert ou_calculer.besoin_mo(images) == attendu, (
            "%d images ne prend pas le palier de %d" % (images, au_dessus))
    # Sous la plus petite mesure aussi : ce palier-la majore tout ce qui passe.
    if paliers[0] > 1:
        assert ou_calculer.besoin_mo(1) == ou_calculer.ANCRES[paliers[0]]["memoire_mo"]
    # Et au-dessus de tout ce qui est mesure, la droite reprend la main.
    assert ou_calculer.besoin_mo(max(paliers) + 24) > ou_calculer.ANCRES[max(paliers)]["memoire_mo"]


def test_la_place_reservee_ne_DESCEND_jamais_quand_le_clip_s_allonge():
    """La mesure brute descend, et c'est ce qui a impose le maximum courant.

    Campagne du 21/09, memoire libre consommee : 97 images en prennent 16 711
    et 121 seulement 16 351. Ce que le clip DEMANDE monte pourtant sans
    exception -- compteur d'allocation de torch : 11 111, 11 802, 12 828,
    13 855, 14 882, 15 909, 16 935, 17 962, soit +1 027 Mo toutes les 24
    images a un megaoctet pres -- et ce qui decroche est la RESERVE de
    l'allocateur, qui depend de l'etat de son cache, pas du travail.

    Laisser la table telle quelle ferait reserver a un clip de 5 s moins qu'a
    un clip de 4 s : le plus long des deux partirait a la maison sur une place
    trop petite, et mourrait apres plusieurs minutes de calcul.
    """
    paliers = sorted(ou_calculer.ANCRES)
    brut = [ou_calculer.ANCRES[n]["memoire_mo"] for n in paliers]
    assert brut != sorted(brut), (
        "les relevés bruts sont croissants : ce test n'a plus de danger a "
        "garder, et le maximum courant peut etre retire")
    reserve = [ou_calculer.besoin_mo(n) for n in paliers]
    assert reserve == sorted(reserve), reserve
    for n, valeur in zip(paliers, reserve):
        assert valeur >= ou_calculer.ANCRES[n]["memoire_mo"], (
            "%d images : la place reservee est sous sa propre mesure" % n)


def test_la_loi_du_TEMPS_ignore_les_ancres_qui_n_ont_pas_ete_chronometrees(monkeypatch):
    """Les deux champs de la table n'ont PAS ete pris dans les memes conditions.

    La memoire vient de la campagne du 21/09 a 2 passes, et le temoin a montre
    qu'elle n'en depend pas : 12 841 Mo a 50 passes, 12 828 a 2, soit 0,1 %. Le
    TEMPS, lui, en depend de plein fouet -- 412 s a 50 passes contre 170 s a 2
    pour le meme clip de 3 s. Une duree mesuree en memoire mais jamais
    chronometree a 50 passes ne porte donc pas de `secondes`, et elle ne doit
    pas tirer la droite du temps vers le bas.

    Sans ce filtre, une ancre sans `secondes` fait tomber `_loi` sur un
    KeyError -- ou, pire si un jour on y mettait le temps de la campagne, fait
    promettre a la page trois minutes pour un clip qui en prend sept.
    """
    monkeypatch.setattr(ou_calculer, "ANCRES", {
        73: {"memoire_mo": 14751, "secondes": 412.0},
        121: {"memoire_mo": 16351, "secondes": 598.0},
        193: {"memoire_mo": 19000},          # mesuree en memoire, jamais chronometree
    })
    avant = ou_calculer._loi("secondes")
    monkeypatch.setattr(ou_calculer, "ANCRES", {
        73: {"memoire_mo": 14751, "secondes": 412.0},
        121: {"memoire_mo": 16351, "secondes": 598.0},
    })
    assert ou_calculer._loi("secondes") == avant, (
        "une ancre sans `secondes` a deplace la loi du temps")
    # Et la memoire, elle, prend bien le troisieme point.
    monkeypatch.setattr(ou_calculer, "ANCRES", {
        73: {"memoire_mo": 14751, "secondes": 412.0},
        121: {"memoire_mo": 16351, "secondes": 598.0},
        193: {"memoire_mo": 19000},
    })
    assert ou_calculer.besoin_mo(193) == 19000


def test_un_champ_que_PERSONNE_ne_porte_se_plaint_au_lieu_de_rendre_zero(monkeypatch):
    """Une loi ajustee sur zero point rendrait (0, 0) : un besoin de 0 Mo.

    C'est le seul endroit ou le filtre ci-dessus pouvait devenir dangereux --
    il rend silencieusement vide ce qui etait plein. Un besoin nul enverrait
    tous les clips a la maison, quelle que soit la carte.
    """
    monkeypatch.setattr(ou_calculer, "ANCRES", {73: {"memoire_mo": 14751}})
    with pytest.raises(KeyError):
        ou_calculer._loi("secondes")


def test_la_marge_GRANDIT_avec_la_distance_aux_mesures():
    """Ce que la marge est LA POUR DIRE : plus loin des mesures, moins on sait.

    Mutation muette du 21/09 : en retournant le signe de la marge hors domaine
    -- elle retrecit au lieu de grandir -- aucun test n'a rouge. La monotonie
    tenait quand meme, la droite montant assez vite ; mais un majorant qui se
    resserre a mesure qu'on s'eloigne de ce qui a ete mesure est un majorant qui
    ment la ou il est le plus fragile.
    """
    origine, pente = ou_calculer._loi("memoire_mo")
    n_max = max(ou_calculer.ANCRES)
    marges = [ou_calculer.besoin_mo(n) / (origine + pente * n) - 1.0
              for n in (n_max + 24, n_max + 48, n_max + 72)]
    assert marges == sorted(marges), marges
    assert marges[0] < marges[-1], "la marge doit GRANDIR, pas stagner"
    assert marges[0] >= ou_calculer.MARGE_LOI, (
        "au-dela des mesures on ne descend jamais sous la marge de base")


def test_la_marge_ne_s_empile_JAMAIS_sur_une_mesure():
    """Grief principal de la relecture, verifie par le calcul.

    `gpu_local.utilisable()` ajoute deja 1 024 Mo. En majorant par-dessus un
    point mesure, on empilait deux prudences et on refusait a la maison un clip
    dont la mesure dit qu'il y tient. Majorer une mesure, ce n'est pas etre
    prudent, c'est jeter la mesure.

    Ce qui est verifie ici est donc l'ABSENCE de marge multiplicative sur un
    point mesure, et non l'egalite exacte : depuis le 21/09, `besoin_mo()`
    prend le maximum courant des relevés, parce que la suite des mesures n'est
    pas croissante. La place d'un clip de 5 s est donc celle relevee a 4 s.
    C'est un autre releve, pas une marge -- aucune des deux valeurs n'a ete
    multipliee par quoi que ce soit.
    """
    for images, ancre in ou_calculer.ANCRES.items():
        assert ou_calculer.besoin_mo(images) in {
            a["memoire_mo"] for a in ou_calculer.ANCRES.values()}, (
            "%d images : la place reservee n'est le releve d'aucun clip" % images)


def test_ce_qu_une_carte_de_16_Go_peut_VRAIMENT_faire():
    """Ce test portait une promesse fausse, et il la defendait.

    Il exigeait que TOUTE duree mesuree tienne dans 16 Go, marge comprise. Il
    passait parce que les deux ancres du 19/09 etaient prises au compteur
    interne de torch : le clip de 5 s y valait 14 902 Mo, et 14 902 + 1 024
    tient dans 16 384. La campagne du 21/09 a mesure la memoire LIBRE que ce
    meme clip consomme -- 16 351 Mo -- et il en faut donc 17 375. Une carte de
    16 Go ne peut PAS le faire, et le Studio le lui promettait : le client
    aurait attendu plusieurs minutes de calcul pour un depassement memoire.

    On ne garde donc plus une promesse, on ecrit ou passe la frontiere. Elle
    peut echouer : si quelqu'un remet des chiffres du mauvais instrument, ou
    deplace la marge, la liste change et ce test le dit.
    """
    carte_16_go = 16384
    tiennent = sorted(n for n, a in ou_calculer.ANCRES.items()
                      if a["memoire_mo"] + gpu_local.MARGE_MO <= carte_16_go)
    debordent = sorted(set(ou_calculer.ANCRES) - set(tiennent))
    assert tiennent, "aucune duree mesuree ne tiendrait dans 16 Go"
    assert debordent, (
        "toutes les durees mesurees tiennent dans 16 Go : c'est exactement ce "
        "que la table disait quand elle portait le compteur torch")
    # La frontiere est entre la plus grande qui tient et la plus petite qui deborde.
    assert max(tiennent) < min(debordent)
    assert (ou_calculer.ANCRES[min(debordent)]["memoire_mo"]
            + gpu_local.MARGE_MO) > carte_16_go


def test_trop_loin_des_ancres_le_clip_part_chez_le_loueur():
    """La loi majore pres des mesures. Loin, elle devinerait : on refuse.

    Cette borne n'est pas un chiffre grave : elle se deplace d'elle-meme des
    qu'un clip plus long a ete mesure.
    """
    tres_loin = max(ou_calculer.ANCRES) + 24 * (ou_calculer.IMAGES_MAX_EXTRAPOLATION + 1)
    d = ou_calculer.decider(resume(), tres_loin,
                            reglage=ou_calculer.MAISON_SI_LIBRE, sonde=sonde_libre)
    assert d["ou"] == ou_calculer.MODAL
    assert "trop loin de ce qui a ete mesure" in d["pourquoi"]


def test_une_duree_jamais_mesuree_mais_PROCHE_est_acceptee():
    """C'est le point de tout le changement : 161 images partaient chez le
    loueur hier, elles tiennent sur la carte aujourd'hui."""
    d = ou_calculer.decider(resume(), IMAGES_NON_MESUREES,
                            reglage=ou_calculer.MAISON_SI_LIBRE, sonde=sonde_libre)
    assert d["ou"] == ou_calculer.MAISON
    assert d["besoin_mo"] > ou_calculer.ANCRES[121]["memoire_mo"]


def test_les_ancres_restent_ce_qui_a_ete_MESURE():
    """`BESOIN_MO_MESURE` publie les mesures, jamais la loi.

    Le nom est reste parce que README.md le cite ; ce qu'il rend doit donc
    rester une mesure, sans quoi une page annoncerait un chiffre calcule en le
    presentant comme releve.

    Les valeurs ne sont plus ecrites ici. Elles l'etaient -- 12 841 et 14 902 --
    et c'etait une troisieme copie de la verite : le 21/09, quand la campagne a
    remplace ces deux nombres pris au compteur interne de torch par la memoire
    libre reellement consommee, ce test a defendu les anciens. Un test qui
    recopie la table ne garde pas la table, il la fige.
    """
    assert ou_calculer.BESOIN_MO_MESURE == {
        n: a["memoire_mo"] for n, a in ou_calculer.ANCRES.items()}
    # `besoin_est_mesure()` dit si le chiffre RENDU est la mesure de ce clip-la,
    # et non si la duree figure dans la table. Depuis le maximum courant les
    # deux different : 121 images sont mesurees, mais la place rendue est celle
    # relevee a 97. La page doit alors dire << au plus >>.
    for images in ou_calculer.ANCRES:
        rendu = ou_calculer.besoin_mo(images)
        propre = ou_calculer.ANCRES[images]["memoire_mo"]
        assert ou_calculer.besoin_est_mesure(images) is (rendu == propre), images
        assert rendu >= propre
    assert any(ou_calculer.besoin_est_mesure(n) for n in ou_calculer.ANCRES), (
        "aucune duree n'est annoncee comme mesuree : la page ne dirait plus rien")
    hors_table = max(ou_calculer.ANCRES) + 1
    assert not ou_calculer.besoin_est_mesure(hors_table)


def test_les_ancres_viennent_du_fichier_ENGENDRE_et_portent_leur_provenance():
    """La condition posee par la relecture en retirant `enregistrer_ancre()`.

    Une table reecrite sans sa provenance derive de ce qui l'a produite : on ne
    sait plus sur quelle carte, a quelle definition, avec combien de passes ni
    avec quel instrument un chiffre a ete pris. C'est precisement ce qui est
    arrive aux deux ancres du 19/09, appelees << pic memoire carte >> dans la
    documentation alors qu'elles portaient le compteur interne de torch.

    Ce test ne juge pas les nombres : il exige que le fichier dise d'ou ils
    viennent.
    """
    import ancres_video
    assert ou_calculer.ANCRES is ancres_video.ANCRES, (
        "la table a ete recopiee dans ou_calculer : elle va deriver")
    doc = ancres_video.__doc__ or ""
    for mot in ("Date de la campagne", "Carte et versions", "Definition",
                "Passes", "Machine hote", "TEMOINS"):
        assert mot in doc, "la provenance ne dit pas : %s" % mot
    assert ancres_video.ANCRES, "table vide"


def test_le_MAJORANT_est_passe_a_la_sonde_et_il_couvre_la_mesure():
    vu = {}

    def espion(besoin_mo, delai_s=None):
        vu["besoin"] = besoin_mo
        return sonde_libre(besoin_mo, delai_s)

    ou_calculer.decider(resume(), IMAGES_MESUREES,
                        reglage=ou_calculer.MAISON_SI_LIBRE, sonde=espion)
    assert vu["besoin"] == ou_calculer.besoin_mo(IMAGES_MESUREES)
    assert vu["besoin"] >= 12841


def test_le_temps_estime_reproduit_les_clips_reels():
    """Montre au client AVANT qu'il valide. Sur les ancres, il doit retomber
    sur ce que ces clips ont vraiment coute -- 412 s et 598 s."""
    assert abs(ou_calculer.secondes_estimees(73) - 412) <= 1
    assert abs(ou_calculer.secondes_estimees(121) - 598) <= 1
    assert ou_calculer.secondes_estimees(193) > ou_calculer.secondes_estimees(121)


# --- 3. Carte prise : on demande, on ne tranche pas --------------------------

def test_carte_prise_et_reglage_par_defaut_on_demande():
    d = ou_calculer.decider(resume(), IMAGES_MESUREES, prix_estime_usd=0.117,
                            reglage=ou_calculer.MAISON_SI_LIBRE, sonde=sonde_prise)
    assert d["ou"] == ou_calculer.ON_DEMANDE
    assert ou_calculer.ATTENTE in d["sorties"] and ou_calculer.MODAL in d["sorties"]
    # Virgule decimale : le client est francophone, et c'est son argent.
    assert "0,117" in d["pourquoi"]


def test_carte_prise_et_toujours_maison_on_attend_sans_rien_arreter():
    d = ou_calculer.decider(resume(), IMAGES_MESUREES,
                            reglage=ou_calculer.TOUJOURS_MAISON, sonde=sonde_prise)
    assert d["ou"] == ou_calculer.ATTENTE
    assert "on n'arrête jamais" in d["pourquoi"]


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


# « Toujours a la maison » ne loue JAMAIS en silence (friction du 23/09). Le
# reglage par defaut, lui, continue de louer : c'est le client sans carte.
TOUJOURS_MAISON_SANS_ISSUE = [
    ("aucune carte", dict(images=IMAGES_MESUREES, sonde=sonde_absente)),
    ("duree sans table", dict(images=None, sonde=sonde_libre)),
    ("trop loin", dict(images=max(ou_calculer.ANCRES) + 24 * (ou_calculer.IMAGES_MAX_EXTRAPOLATION + 1),
                       sonde=sonde_libre)),
]


@pytest.mark.parametrize("cas,kw", TOUJOURS_MAISON_SANS_ISSUE, ids=[c for c, _ in TOUJOURS_MAISON_SANS_ISSUE])
def test_toujours_maison_sans_issue_DEMANDE_au_lieu_de_louer(cas, kw):
    d = ou_calculer.decider(resume(), kw["images"], prix_estime_usd=0.117,
                            reglage=ou_calculer.TOUJOURS_MAISON, sonde=kw["sonde"])
    assert d["ou"] == ou_calculer.ON_DEMANDE
    assert list(d["sorties"]) == [ou_calculer.MODAL, "annuler"]
    assert "Rien n'est parti" in d["pourquoi"]


@pytest.mark.parametrize("cas,kw", TOUJOURS_MAISON_SANS_ISSUE, ids=[c for c, _ in TOUJOURS_MAISON_SANS_ISSUE])
def test_le_reglage_par_defaut_loue_toujours_dans_les_memes_cas(cas, kw):
    d = ou_calculer.decider(resume(), kw["images"], prix_estime_usd=0.117,
                            reglage=ou_calculer.MAISON_SI_LIBRE, sonde=kw["sonde"])
    assert d["ou"] == ou_calculer.MODAL


# --- 4. Le motif porte des chiffres ------------------------------------------

def test_le_refus_pour_carte_prise_dit_ce_qui_reste_et_ce_qu_il_faut():
    d = ou_calculer.decider(resume(), IMAGES_MESUREES, prix_estime_usd=0.117,
                            reglage=ou_calculer.MAISON_SI_LIBRE, sonde=sonde_prise)
    assert "3200" in d["pourquoi"]


def test_toutes_les_reponses_ont_les_memes_cles():
    """La page ne doit jamais deviner : la forme est la meme dans tous les cas."""
    cles = {"ou", "reglage", "pourquoi", "besoin_mo", "carte", "prix_estime_usd",
            "sorties", "secondes_estimees", "besoin_est_mesure"}
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


# --- La raison d'une carte prise voyage avec ses chiffres (24/09/2026) --------
# Verifie en vrai : la page affichait « 23,0 Go libres sur 24,0, il en faut
# 11,5 » et attendait. julia.exe tenait la carte ; seule la sonde le disait.

def sonde_tenue_par_julia(besoin_mo, delai_s=None):
    return False, ("NVIDIA GeForce RTX 4090 : julia.exe (PID 76088) tient la carte, même "
                   "sans y avoir encore écrit, et on ne l'arrête jamais."), CARTE_LIBRE


def test_une_carte_tenue_par_un_autre_calcul_dit_qui_la_tient():
    d = ou_calculer.decider(resume(), IMAGES_MESUREES,
                            reglage=ou_calculer.TOUJOURS_MAISON, sonde=sonde_tenue_par_julia)
    assert d["ou"] == ou_calculer.ATTENTE
    assert "julia.exe (PID 76088)" in d["carte"]["raison"]
    assert d["carte"]["libre_mo"] == CARTE_LIBRE["libre_mo"], "les chiffres restent"


def test_la_boite_d_attente_montre_la_raison_quand_la_memoire_suffit():
    import shutil
    import subprocess
    if not shutil.which("node"):
        pytest.skip("node absent")
    page = (RACINE / "sandbox-manager" / "video.py").read_text(encoding="utf-8")
    debut = page.index("function demanderAuClient(d){")
    fin = page.index("\n  boite.hidden = false;", debut)
    corps = page[debut:fin] + "\n  return chiffres;\n}"
    tenue = ou_calculer.decider(resume(), IMAGES_MESUREES,
                                reglage=ou_calculer.TOUJOURS_MAISON, sonde=sonde_tenue_par_julia)
    pleine = ou_calculer.decider(resume(), IMAGES_MESUREES,
                                 reglage=ou_calculer.TOUJOURS_MAISON, sonde=sonde_prise)
    code = ("const fr = (x, n) => x.toFixed(n).replace('.', ',');"
            + "\nconst document = {getElementById: () => ({})};\n" + corps
            + "\nconsole.log(demanderAuClient(" + json.dumps(tenue) + "));"
            + "\nconsole.log(demanderAuClient(" + json.dumps(pleine) + "));")
    sortie = subprocess.run(["node", "-e", code], capture_output=True, text=True,
                            encoding="utf-8", timeout=20)
    assert sortie.returncode == 0, sortie.stderr
    julia, memoire = sortie.stdout.strip().splitlines()
    assert "julia.exe (PID 76088) tient la carte" in julia
    assert "Go libres" in memoire and "julia" not in memoire, "une carte vraiment pleine garde ses chiffres"


def test_choisir_kaggle_quand_la_carte_passe_avant_se_voit_tout_de_suite():
    """23/09 : « phare lance » sur Kaggle, parti sur la carte d'ici, sans rappel.
    La note apparait au choix de Kaggle, et seulement quand la carte passe avant."""
    import shutil
    import subprocess
    if not shutil.which("node"):
        pytest.skip("node absent")
    page = (RACINE / "sandbox-manager" / "video.py").read_text(encoding="utf-8")
    debut = page.index("function majNoteLoueur(){")
    fin = page.index("\n}\n", debut) + 3
    corps = page[debut:fin]
    cas = [("kaggle", "maison-si-libre", True), ("kaggle", "toujours-maison", True),
           ("kaggle", "toujours-modal", True), ("modal", "maison-si-libre", True),
           ("kaggle", "maison-si-libre", False)]
    code = ("let CARTE_POSSIBLE, OU, REGLAGE; const note = {};\n"
            "const document = {getElementById: (i) => i === 'ou' ? {value: OU} : note};\n"
            "const reglageActuel = () => REGLAGE;\n" + corps
            + "".join("\nCARTE_POSSIBLE=%s; OU=%s; REGLAGE=%s; majNoteLoueur();"
                      " console.log(JSON.stringify([note.hidden, note.textContent]));"
                      % (json.dumps(c), json.dumps(o), json.dumps(r)) for o, r, c in cas))
    sortie = subprocess.run(["node", "-e", code], capture_output=True, text=True,
                            encoding="utf-8", timeout=20)
    assert sortie.returncode == 0, sortie.stderr
    vus = [json.loads(ligne) for ligne in sortie.stdout.strip().splitlines()]
    assert vus[0][0] is False and "Toujours sur une machine louée" in vus[0][1], vus[0]
    assert vus[1][0] is False and "Kaggle ne servira pas" in vus[1][1], vus[1]
    # Loue a coup sur, Modal choisi, ou pas de carte ici : rien a rappeler.
    assert all(v == [True, ""] for v in vus[2:]), vus[2:]
