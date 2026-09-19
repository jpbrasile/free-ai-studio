"""Les deux dates du 31/10/2026, et ce qui arrive le lendemain.

Le controle lui-meme est scripts/verifier-echeances.py ; ces tests jouent ses
bras un par un, dont celui qu'on ne peut pas attendre : le 1er novembre.

Ce qu'ils gardent, defaut par defaut :

1. l'arbre REEL passe aujourd'hui -- la ligne d'echeance est bien dans les deux
   documents, bien formee, et le butoir y est celui du script ;
2. << en attente >> apres le butoir echoue, et le message dit quoi ecrire ;
3. la ligne effacee, dupliquee ou deplacee echoue -- sinon le controle se
   desarme en silence, ce qui est pire que pas de controle ;
4. << tenue >> et << abandonnee >> exigent leur preuve ;
5. << abandonnee >> exige que le document porte les mots de l'abandon, comme la
   decision 9 le demande.

Aucun reseau, aucun git, aucun service charge.
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location(
    "verifier_echeances", RACINE / "scripts" / "verifier-echeances.py"
)
verifier_echeances = importlib.util.module_from_spec(_spec)
# Inscrit AVANT l'execution : @dataclass resout ses annotations en relisant
# sys.modules[cls.__module__], et un module charge par chemin n'y est pas. Sans
# cette ligne, l'import casse sur AttributeError: 'NoneType' has no '__dict__'.
sys.modules[_spec.name] = verifier_echeances
_spec.loader.exec_module(verifier_echeances)

AVANT = date(2026, 9, 19)
LE_JOUR = date(2026, 10, 31)
APRES = date(2026, 11, 1)

EN_ATTENTE = {
    e.id: "<!-- echeance: %s | butoir: 2026-10-31 | etat: en-attente -->\n" % e.id
    for e in verifier_echeances.ECHEANCES
}


def arbre(tmp_path, **documents):
    """Ecrit les deux documents attendus ; documents = id -> contenu complet."""
    for echeance in verifier_echeances.ECHEANCES:
        chemin = tmp_path / echeance.fichier
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(documents.get(echeance.id, EN_ATTENTE[echeance.id]), encoding="utf-8")
    return tmp_path


def test_arbre_reel_en_regle_aujourdhui():
    """Le depot tel qu'il est, a la date du jour."""
    problemes, etats = verifier_echeances.verifier(RACINE, date.today())
    assert problemes == [], problemes
    assert len(etats) == len(verifier_echeances.ECHEANCES)


def test_arbre_reel_le_jour_du_butoir():
    """Le 31/10 lui-meme est encore dans les temps : le butoir est inclusif."""
    problemes, _ = verifier_echeances.verifier(RACINE, LE_JOUR)
    assert problemes == []


def test_deux_echeances_declarees():
    """Decisions 9 et 15 : deux dates, pas une."""
    ids = {e.id for e in verifier_echeances.ECHEANCES}
    assert ids == {"essai-machine-neuve", "restauration-sauvegardes"}
    assert all(e.butoir == LE_JOUR for e in verifier_echeances.ECHEANCES)


def test_en_attente_apres_le_butoir_echoue(tmp_path):
    """Le seul etat que la date interdit, et le message dit quoi ecrire."""
    problemes, _ = verifier_echeances.verifier(arbre(tmp_path), APRES)
    assert len(problemes) == 2
    for texte in problemes:
        assert "BUTOIR DEPASSE" in texte
        assert "abandonnee" in texte


def test_en_attente_avant_le_butoir_passe(tmp_path):
    problemes, etats = verifier_echeances.verifier(arbre(tmp_path), AVANT)
    assert problemes == []
    assert any("42 jour(s)" in ligne for ligne in etats)


@pytest.mark.parametrize("aujourdhui", [AVANT, APRES])
def test_ligne_effacee_echoue(tmp_path, aujourdhui):
    """Supprimer la ligne desarmerait le controle : c'est refuse aux deux dates."""
    racine = arbre(tmp_path, **{"essai-machine-neuve": "un document sans echeance\n"})
    problemes, _ = verifier_echeances.verifier(racine, aujourdhui)
    assert any("aucune ligne" in p for p in problemes)


def test_document_absent_echoue(tmp_path):
    racine = arbre(tmp_path)
    (racine / "docs" / "SAUVEGARDES.md").unlink()
    problemes, _ = verifier_echeances.verifier(racine, AVANT)
    assert any("est absent" in p for p in problemes)


def test_ligne_dupliquee_echoue(tmp_path):
    """Deux lignes se contredisent le jour ou elles divergent."""
    doublon = EN_ATTENTE["essai-machine-neuve"] * 2
    racine = arbre(tmp_path, **{"essai-machine-neuve": doublon})
    problemes, _ = verifier_echeances.verifier(racine, AVANT)
    assert any("2 lignes d'echeance" in p for p in problemes)


def test_butoir_deplace_dans_le_document_seul_echoue(tmp_path):
    """Reporter la date demande de toucher AUSSI au script : c'est le garde-fou."""
    repousse = "<!-- echeance: essai-machine-neuve | butoir: 2026-12-31 | etat: en-attente -->\n"
    racine = arbre(tmp_path, **{"essai-machine-neuve": repousse})
    problemes, _ = verifier_echeances.verifier(racine, AVANT)
    assert any("2026-12-31" in p and "2026-10-31" in p for p in problemes)


def test_butoir_illisible_echoue(tmp_path):
    cassee = "<!-- echeance: essai-machine-neuve | butoir: bientot | etat: en-attente -->\n"
    racine = arbre(tmp_path, **{"essai-machine-neuve": cassee})
    problemes, _ = verifier_echeances.verifier(racine, AVANT)
    assert any("butoir illisible" in p for p in problemes)


def test_etat_inconnu_echoue(tmp_path):
    invente = "<!-- echeance: essai-machine-neuve | butoir: 2026-10-31 | etat: en-cours -->\n"
    racine = arbre(tmp_path, **{"essai-machine-neuve": invente})
    problemes, _ = verifier_echeances.verifier(racine, AVANT)
    assert any("inconnu" in p for p in problemes)


def test_tenue_sans_preuve_echoue(tmp_path):
    """Un fait cite sa preuve ; sans elle c'est << non verifie >>."""
    sans = "<!-- echeance: essai-machine-neuve | butoir: 2026-10-31 | etat: tenue -->\n"
    racine = arbre(tmp_path, **{"essai-machine-neuve": sans})
    problemes, _ = verifier_echeances.verifier(racine, APRES)
    assert any("sans preuve" in p for p in problemes)


def test_tenue_avec_preuve_passe_meme_apres_le_butoir(tmp_path):
    avec = (
        "<!-- echeance: essai-machine-neuve | butoir: 2026-10-31 | etat: tenue"
        " | preuve: joue le 2026-10-20, 4/6, version 1.4.2 -->\n"
    )
    racine = arbre(tmp_path, **{"essai-machine-neuve": avec})
    problemes, etats = verifier_echeances.verifier(racine, APRES)
    assert [p for p in problemes if "essai-machine-neuve" in p] == []
    assert any("tenue" in ligne and "4/6" in ligne for ligne in etats)


def test_abandon_sans_les_mots_echoue(tmp_path):
    """La decision se lit dans le document, pas seulement dans un commentaire."""
    muet = (
        "<!-- echeance: essai-machine-neuve | butoir: 2026-10-31 | etat: abandonnee"
        " | preuve: decision du 2026-11-02 -->\n\nOn verra plus tard.\n"
    )
    racine = arbre(tmp_path, **{"essai-machine-neuve": muet})
    problemes, _ = verifier_echeances.verifier(racine, APRES)
    assert any("n'ecrit nulle part" in p for p in problemes)


def test_abandon_ecrit_en_toutes_lettres_passe(tmp_path):
    """Decision 9 : le document ecrit << mesure abandonnee >>, pas << en attente >>."""
    dit = (
        "<!-- echeance: essai-machine-neuve | butoir: 2026-10-31 | etat: abandonnee"
        " | preuve: decision du 2026-11-02 -->\n\n"
        "**Mesure abandonnée** le 02/11/2026 : personne n'a joue la grille.\n"
    )
    racine = arbre(tmp_path, **{"essai-machine-neuve": dit})
    problemes, etats = verifier_echeances.verifier(racine, APRES)
    assert [p for p in problemes if "essai-machine-neuve" in p] == []
    assert any("abandonnee" in ligne for ligne in etats)


def test_les_accents_ne_decident_de_rien(tmp_path):
    """<< abandonne >> sans accent vaut << abandonné >> : le controle lit le sens."""
    sans_accent = (
        "<!-- echeance: restauration-sauvegardes | butoir: 2026-10-31 | etat: abandonnee"
        " | preuve: decision du 2026-11-02 -->\n\nEssai abandonne le 02/11/2026.\n"
    )
    racine = arbre(tmp_path, **{"restauration-sauvegardes": sans_accent})
    problemes, _ = verifier_echeances.verifier(racine, APRES)
    assert [p for p in problemes if "restauration-sauvegardes" in p] == []
