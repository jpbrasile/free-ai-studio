"""La garde des renvois `fichier:ligne` (22/09/2026).

Un renvoi périmé ne casse rien : il envoie le prochain lecteur sur une autre
ligne, qui a l'air d'une réponse. Le jour où cette garde a été écrite, elle a
trouvé **4 fautes sur les 4 renvois motivés** que le dépôt portait — dont un
écrit trois heures plus tôt, déplacé par un correctif de la même journée.

Ce que ces tests fixent, c'est surtout ce que la garde ne fait PAS : elle ignore
les renvois sans motif. C'est ce qui lui permet d'entrer dans la CI sans imposer
de reprendre à la main les 177 renvois muets du dépôt.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location(
    "verifier_renvois", RACINE / "scripts" / "verifier-renvois.py"
)
vr = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = vr
_spec.loader.exec_module(vr)


def fautes(tmp_path, monkeypatch, fichiers: dict[str, str]) -> list[str]:
    """Pose un petit dépôt de papier, y branche la garde, et rend ses fautes.

    `fichiers_suivis` est remplacé plutôt que contourné : la garde s'en sert
    aussi pour lever une ambiguïté de chemin, et un test qui ne le poserait pas
    interrogerait le vrai dépôt sans le dire.
    """
    ecrits = []
    for nom, contenu in fichiers.items():
        chemin = tmp_path / nom
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(contenu, encoding="utf-8")
        ecrits.append(chemin)
    monkeypatch.setattr(vr, "RACINE", tmp_path)
    monkeypatch.setattr(vr, "fichiers_suivis", lambda motifs=None: list(ecrits))
    lus = [f for f in ecrits if f.suffix == ".md"]
    assert lus, "le banc n'a pose aucun document a lire"
    return vr.parcourir(lus)[0]


# --- ce que la garde attrape --------------------------------------------------


def test_un_renvoi_dont_le_motif_est_sur_la_ligne_ne_dit_rien(tmp_path, monkeypatch):
    assert fautes(tmp_path, monkeypatch, {
        "note.md": "Voir `code.py:2` (`def depart`) pour le détail.",
        "code.py": "# en tete\ndef depart():\n    return 0\n",
    }) == []


def test_un_renvoi_decale_est_dit_AVEC_son_numero_reel(tmp_path, monkeypatch):
    """Dire « faux » ne suffit pas : sans le vrai numéro, la réparation est une enquête."""
    trouvees = fautes(tmp_path, monkeypatch, {
        "note.md": "Voir `code.py:2` (`def depart`).",
        "code.py": "# une ligne\n# deux\n# trois\ndef depart():\n    return 0\n",
    })
    assert len(trouvees) == 1, trouvees
    assert "il est en realite ligne 4" in trouvees[0], trouvees[0]


def test_un_numero_au_dela_de_la_fin_du_fichier_est_dit(tmp_path, monkeypatch):
    trouvees = fautes(tmp_path, monkeypatch, {
        "note.md": "Voir `code.py:99` (`def depart`).",
        "code.py": "def depart():\n    return 0\n",
    })
    assert len(trouvees) == 1, trouvees
    assert "depasse la fin du fichier" in trouvees[0], trouvees[0]


def test_un_chemin_nu_qui_existe_deux_fois_est_refuse_sans_en_choisir_un(
        tmp_path, monkeypatch):
    """`app.py` existe trois fois dans ce dépôt. En choisir un serait deviner."""
    trouvees = fautes(tmp_path, monkeypatch, {
        "note.md": "Voir `app.py:1` (`salut`).",
        "un/app.py": "salut\n",
        "deux/app.py": "salut\n",
    })
    assert len(trouvees) == 1, trouvees
    assert "chemin ambigu" in trouvees[0], trouvees[0]


def test_un_fichier_absent_est_dit(tmp_path, monkeypatch):
    trouvees = fautes(tmp_path, monkeypatch, {
        "note.md": "Voir `disparu.py:1` (`salut`).",
    })
    assert len(trouvees) == 1 and "introuvable" in trouvees[0], trouvees


# --- ce que la garde laisse passer, et c'est voulu -----------------------------


def test_un_renvoi_SANS_motif_est_IGNORE(tmp_path, monkeypatch):
    """Sans ce silence, la garde rougirait sur les 177 renvois muets du dépôt.

    Les reprendre un par un est une décision du propriétaire, pas un effet de
    bord de l'installation d'une garde. Un renvoi sans motif reste un pari ; il
    n'est simplement pas encore tenu.
    """
    assert fautes(tmp_path, monkeypatch, {
        "note.md": "Voir `code.py:99` et aussi `code.py:1000`.",
        "code.py": "def depart():\n",
    }) == []


def test_un_exemple_au_deux_points_ESPACE_n_est_pas_pris_pour_un_renvoi(
        tmp_path, monkeypatch):
    """Un exemple doit pouvoir s'écrire sans être pris pour la chose qu'il illustre.

    La garde elle-même documente sa forme ; écrite collée, l'illustration
    devenait un renvoi vers un fichier nommé « chemin/fichier.ext », et la CI
    rougissait sur un mode d'emploi. L'espace autour des deux-points est
    l'échappement, et il n'a besoin d'aucune machinerie.
    """
    assert fautes(tmp_path, monkeypatch, {
        "note.md": "La forme est `chemin/fichier.ext : 123` (`motif`), "
                   "et l'abrégée `... : 12-18`.",
    }) == []


# --- la forme abregee ----------------------------------------------------------


def test_la_forme_abregee_herite_du_fichier_de_la_MEME_ligne(tmp_path, monkeypatch):
    assert fautes(tmp_path, monkeypatch, {
        "note.md": "Voir `code.py:1` (`def depart`), `:3` (`def arret`).",
        "code.py": "def depart():\n    pass\ndef arret():\n",
    }) == []


def test_l_heritage_ne_franchit_PAS_la_fin_de_la_ligne(tmp_path, monkeypatch):
    """Un héritage qui courrait sur tout un document ferait pointer un renvoi
    vers un fichier nommé trois paragraphes plus haut — ce qu'aucun lecteur
    ne fait. Sans ce bras, la portée pourrait s'élargir sans que rien ne sonne.
    """
    trouvees = fautes(tmp_path, monkeypatch, {
        "note.md": "Voir `code.py:1` (`def depart`).\nEt puis `:3` (`def arret`).",
        "code.py": "def depart():\n    pass\ndef arret():\n",
    })
    assert len(trouvees) == 1, trouvees
    assert "renvoi abrege" in trouvees[0], trouvees[0]


def test_un_intervalle_accepte_le_motif_n_importe_ou_dedans(tmp_path, monkeypatch):
    assert fautes(tmp_path, monkeypatch, {
        "note.md": "Voir `code.py:1-4` (`def arret`).",
        "code.py": "def depart():\n    pass\n\ndef arret():\n",
    }) == []


def test_un_intervalle_ne_couvre_pas_ce_qui_est_dehors(tmp_path, monkeypatch):
    """Sans ce bras, l'intervalle pourrait balayer tout le fichier sans sonner."""
    trouvees = fautes(tmp_path, monkeypatch, {
        "note.md": "Voir `code.py:1-2` (`def arret`).",
        "code.py": "def depart():\n    pass\n\ndef arret():\n",
    })
    assert len(trouvees) == 1, trouvees


# --- le depot lui-meme ---------------------------------------------------------


def test_le_depot_lui_meme_n_a_aucun_renvoi_motive_faux():
    """Le cliquet. Il lit le dépôt, pas la machine : même verdict partout.

    C'est ce test qui rougira le jour où une insertion décalera un renvoi —
    exactement ce qui est arrivé deux fois le 22/09/2026 sans aucun signal.
    """
    trouvees, vus = vr.parcourir(vr.fichiers_suivis())
    assert trouvees == [], trouvees
    assert vus, "aucun renvoi motive : la garde ne garderait rien"
