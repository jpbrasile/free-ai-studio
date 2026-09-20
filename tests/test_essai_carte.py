"""La page d'essai VERIFIE si l'ordinateur a une carte, au lieu de l'affirmer.

Defaut releve par le proprietaire le 20/09/2026, sur sa propre machine :
<< affirmation fausse sur ce pc >>, a propos de la phrase

    La carte graphique n'existe pas sur le backend local.

Elle etait vraie le jour ou elle a ete ecrite. Depuis le 19/09/2026, la
surcouche `docker-compose.gpu.yml` donne la carte au gestionnaire ET un
deuxieme bac a sable qui sait s'en servir : sur ce PC, la page Video fabrique
des clips sur une RTX 4090. Un debutant muni d'une carte lisait donc, sur sa
propre page, que sa carte n'existe pas.

Ordre suivant du proprietaire : << fais en sorte que le test soit fait, le
client a ou pas de gpu >>. La page MESURE donc la machine par `/essai/carte`,
qui lance un vrai `nvidia-smi`. Elle ne pose la question a personne : un
debutant ne sait pas si son PC a une carte graphique, et c'est justement pour
lui que ce Studio existe.

Ce que ces tests gardent :

1. la route rend le releve REEL, et ne pretend pas que cette page s'en sert ;
2. la phrase montree suit le releve, dans les deux cas -- carte vue, carte
   absente -- et n'affirme JAMAIS qu'il n'y a pas de carte quand il y en a une ;
3. quand la carte existe, la page dit aussi que cette page-ci ne s'en sert pas.
   Remplacer une phrase fausse par une autre serait le meme defaut a l'envers ;
4. la case << carte graphique >> ne reste plus cochable pour << Votre
   ordinateur >>, ou elle etait IGNOREE en silence : `run_local` ne recoit meme
   pas le drapeau.

Aucun appel reseau, aucun nvidia-smi : la sonde est remplacee par un faux.
"""
from __future__ import annotations

import json
import subprocess

import pytest
from fastapi.testclient import TestClient

from conftest import RACINE

VUE = {"vue": True, "nom": "NVIDIA GeForce RTX 4090", "totale_mo": 24564,
       "libre_mo": 24138, "marge_mo": 1024, "motif": ""}
ABSENTE = {"vue": False, "nom": None, "totale_mo": None, "libre_mo": None,
           "marge_mo": 1024,
           "motif": "nvidia-smi absent du conteneur : la carte n'y est pas passee"}


def _client(sandbox):
    return TestClient(sandbox.app)


def _entetes(sandbox):
    return {"Authorization": "Bearer " + sandbox.KEY}


def _fonction_js(nom: str) -> str:
    """Sort une fonction de la page, telle qu'elle part dans le navigateur."""
    source = (RACINE / "sandbox-manager" / "app.py").read_text(encoding="utf-8")
    debut = source.index("function %s(" % nom)
    profondeur = 0
    for fin in range(source.index("{", debut), len(source)):
        if source[fin] == "{":
            profondeur += 1
        elif source[fin] == "}":
            profondeur -= 1
            if profondeur == 0:
                return source[debut:fin + 1]
    raise AssertionError("%s n'est pas refermee" % nom)


def _rendu(tmp_path, etat):
    """Execute carteTexte dans node : on veut la phrase qui SORT, pas le code.

    Le texte lu ici est celui que le client voit. Un test qui se contenterait de
    chercher des mots dans la source dirait seulement que les deux branches sont
    ECRITES, pas laquelle parle.
    """
    # MODAL_PLUS_VITE est declare hors de la fonction : sans lui, node leve.
    programme = ('const MODAL_PLUS_VITE = "Sur Modal, la carte consomme l\'offre '
                 'gratuite beaucoup plus vite qu\'un calcul sur processeur.";\n'
                 + _fonction_js("carteTexte")
                 + "\nconsole.log(carteTexte(" + json.dumps(etat) + "));\n")
    fichier = tmp_path / "carte.js"
    fichier.write_text(programme, encoding="utf-8")
    # encoding= explicite : node ecrit de l'UTF-8 et Python decoderait en cp1252.
    fait = subprocess.run(["node", str(fichier)], capture_output=True,
                          text=True, encoding="utf-8")
    assert fait.returncode == 0, fait.stderr
    return fait.stdout


# --- 1. La route mesure, et n'exagere pas ce qu'elle mesure ------------------

def test_la_route_rend_le_releve_reel_de_la_sonde(sandbox, monkeypatch):
    monkeypatch.setattr(sandbox.gpu_local, "releve", lambda *a, **k: VUE)
    corps = _client(sandbox).get("/essai/carte", headers=_entetes(sandbox)).json()
    assert corps["carte"] == VUE
    assert corps["carte"]["nom"] == "NVIDIA GeForce RTX 4090"


def test_la_route_n_affirme_pas_que_cette_page_utilise_la_carte(sandbox, monkeypatch):
    """La carte existe, et cette page ne s'en sert pas : les deux sont vrais.

    Dire le premier sans le second remplacerait une phrase fausse par une
    autre, dans le sens qui fait perdre du temps au lieu d'en faire perdre.
    """
    monkeypatch.setattr(sandbox.gpu_local, "releve", lambda *a, **k: VUE)
    corps = _client(sandbox).get("/essai/carte", headers=_entetes(sandbox)).json()
    assert corps["utilisee_par_cette_page"] is False


def test_la_route_dit_pourquoi_quand_il_n_y_a_pas_de_carte(sandbox, monkeypatch):
    """Un `vue: false` sans motif se lirait comme une panne du Studio."""
    monkeypatch.setattr(sandbox.gpu_local, "releve", lambda *a, **k: ABSENTE)
    corps = _client(sandbox).get("/essai/carte", headers=_entetes(sandbox)).json()
    assert corps["carte"]["vue"] is False
    assert corps["carte"]["motif"].strip()


def test_la_route_demande_la_cle(sandbox):
    assert _client(sandbox).get("/essai/carte").status_code in (401, 403)


# --- 2. La phrase montree suit le releve ------------------------------------

def test_avec_une_carte_la_page_la_nomme_et_ne_la_nie_pas(tmp_path):
    texte = _rendu(tmp_path, {"carte": VUE, "bac_a_sable_gpu": True,
                              "utilisee_par_cette_page": False})
    assert "NVIDIA GeForce RTX 4090" in texte
    assert "24138" in texte, "la memoire libre mesuree doit rester lisible"
    assert "n'a pas de carte" not in texte
    assert "n'existe pas" not in texte


def test_avec_une_carte_la_page_dit_que_cette_page_ne_s_en_sert_pas(tmp_path):
    texte = _rendu(tmp_path, {"carte": VUE, "bac_a_sable_gpu": True,
                              "utilisee_par_cette_page": False})
    assert "processeur" in texte
    assert "chiffre suppose" in texte, \
        "la raison du refus doit etre dite, sinon elle passe pour un oubli"


def test_sans_carte_la_page_le_dit_avec_son_motif(tmp_path):
    texte = _rendu(tmp_path, {"carte": ABSENTE, "bac_a_sable_gpu": False,
                              "utilisee_par_cette_page": False})
    assert "n'a pas de carte graphique" in texte
    assert "nvidia-smi" in texte, "le motif mesure doit accompagner le constat"


@pytest.mark.parametrize("releve", [VUE, ABSENTE], ids=["carte_vue", "carte_absente"])
def test_l_avertissement_sur_modal_reste_dans_les_deux_cas(tmp_path, releve):
    """Vrai avec ou sans carte : c'est la moitie de la phrase qui etait juste."""
    texte = _rendu(tmp_path, {"carte": releve, "bac_a_sable_gpu": bool(releve["vue"]),
                              "utilisee_par_cette_page": False})
    assert "offre gratuite beaucoup plus vite" in texte


# --- 3. La page elle-meme ----------------------------------------------------

def test_la_vieille_affirmation_a_disparu_de_la_page(sandbox):
    """Elle etait ecrite en dur, hors de toute condition."""
    page = _client(sandbox).get("/essai").text
    assert "La carte graphique n'existe pas sur le backend local" not in page


def test_la_page_interroge_vraiment_la_route(sandbox):
    """Une fonction que personne n'appelle ne repare rien."""
    page = _client(sandbox).get("/essai").text
    assert 'id="carte"' in page, "la boite ou ecrire la reponse a disparu"
    assert 'fetch("/essai/carte"' in page, "la page ne verifie plus l'etat de la carte"
    assert "carteTexte(d)" in page, "la reponse n'est plus mise dans la page"


def test_la_case_carte_ne_reste_pas_cochable_pour_votre_ordinateur(sandbox):
    """Elle etait IGNOREE en silence : `run_local` ne recoit meme pas `gpu`.

    Une case sans effet qui se laisse cocher est un mensonge de plus, et celui-la
    fait croire a un calcul sur la carte qui n'a jamais eu lieu.
    """
    page = _client(sandbox).get("/essai").text
    assert "function accorderLaCase()" in page
    assert 'case_.disabled = local' in page
    assert 'addEventListener("change", accorderLaCase)' in page


def test_le_lancement_local_ignore_toujours_le_drapeau_gpu(sandbox):
    """Ce test ECHOUERA le jour ou /essai saura utiliser la carte -- et c'est voulu.

    Il fige ce qui est VRAI aujourd'hui : `run_local` ne recoit pas `gpu`. Le
    jour ou quelqu'un branche la carte sur cette page, ce test tombe et oblige a
    revoir la phrase montree au client, qui deviendrait fausse a son tour.
    Sous-plan REG-1 de PLAN.md.
    """
    source = (RACINE / "sandbox-manager" / "app.py").read_text(encoding="utf-8")
    assert "threading.Thread(target=run_local, args=(jid, req.code), daemon=True)" in source
