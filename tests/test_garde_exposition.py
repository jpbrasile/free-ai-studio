"""Le refus au demarrage quand les cles seraient exposees.

Decision du 19/09/2026 (docs/PLAN-PLATEFORME.md, paragraphe 2.1 option (c), et
paragraphe 8 decision 3). Ces tests gardent trois choses :

1. que le refus tombe quand il doit tomber, et JAMAIS sur un Studio personnel --
   un garde-fou qui refuse le cas normal est desactive dans la semaine ;
2. que le message dit quoi faire, parce qu'un refus muet se contourne au hasard ;
3. que les DEUX exemplaires du module ne divergent pas d'un octet. C'est le meme
   remede que test_les_deux_tables_de_prix_ne_divergent_pas : le depot a deja ete
   mordu par deux copies d'une meme verite relues separement.
"""
from __future__ import annotations

import importlib.util

import pytest

from conftest import RACINE, charger

EXEMPLAIRES = [
    RACINE / "free-tier-manager" / "garde_exposition.py",
    RACINE / "sandbox-manager" / "garde_exposition.py",
]


def _garde():
    """Charge l'exemplaire du routeur. Les deux sont identiques, cf. le test."""
    spec = importlib.util.spec_from_file_location("garde_exposition_test", EXEMPLAIRES[0])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- Les deux exemplaires -----------------------------------------------------

def test_les_deux_exemplaires_de_la_garde_ne_divergent_pas():
    """Deux services, deux images, deux contextes de construction, une regle.

    Le contexte ne peut pas etre la racine du depot : elle contient .env et
    config/, c'est-a-dire les secrets que ce module protege. La duplication est
    donc subie ; ce test la rend sure.
    """
    for chemin in EXEMPLAIRES:
        assert chemin.exists(), "exemplaire manquant : %s" % chemin
    octets = {c: c.read_bytes() for c in EXEMPLAIRES}
    premier = octets[EXEMPLAIRES[0]]
    for chemin, contenu in octets.items():
        assert contenu == premier, (
            "%s a divergé de %s. Les deux exemplaires doivent rester identiques : "
            "recopiez l'un sur l'autre." % (chemin.name, EXEMPLAIRES[0])
        )


# --- Le cas normal : on ne refuse rien ----------------------------------------

@pytest.mark.parametrize("adresse", ["127.0.0.1", "localhost", "::1", "[::1]",
                                     "  127.0.0.1  ", "LOCALHOST", None, ""])
def test_un_studio_personnel_demarre(adresse):
    """La boucle locale, sous toutes ses formes, ne declenche rien."""
    garde = _garde()
    assert garde.motifs_d_exposition("false", adresse) == []


def test_sans_aucune_variable_on_demarre():
    """Le defaut doit etre le cas normal, sinon personne ne garde le garde-fou."""
    garde = _garde()
    assert garde.motifs_d_exposition(None, None) == []
    garde.verifier_ou_refuser("/config/keys.json", env={})


# --- Les deux conditions ------------------------------------------------------

def test_instance_declaree_hebergee_refusee():
    garde = _garde()
    motifs = garde.motifs_d_exposition("true", "127.0.0.1")
    assert len(motifs) == 1
    assert "STUDIO_HEBERGE" in motifs[0]


@pytest.mark.parametrize("adresse", ["0.0.0.0", "192.168.1.20", "10.0.0.5", "::"])
def test_publication_hors_boucle_locale_refusee(adresse):
    garde = _garde()
    motifs = garde.motifs_d_exposition("false", adresse)
    assert len(motifs) == 1
    assert "STUDIO_ADRESSE_PUBLIEE" in motifs[0]
    assert adresse in motifs[0], "le motif doit citer l'adresse constatée"


def test_les_deux_conditions_donnent_les_deux_motifs():
    """Deux causes, deux lignes : corriger l'une ne doit pas cacher l'autre."""
    garde = _garde()
    assert len(garde.motifs_d_exposition("true", "0.0.0.0")) == 2


def test_le_refus_nomme_le_magasin_et_dit_quoi_faire():
    garde = _garde()
    with pytest.raises(garde.ClesExposees) as leve:
        garde.verifier_ou_refuser("/config/keys.json",
                                  env={"STUDIO_ADRESSE_PUBLIEE": "0.0.0.0"})
    texte = str(leve.value)
    assert "/config/keys.json" in texte
    assert "EN CLAIR" in texte
    assert "0.0.0.0" in texte
    assert "STUDIO_ADRESSE_PUBLIEE=127.0.0.1" in texte, "le message doit donner la sortie"


def test_aucun_interrupteur_ne_desactive_le_refus():
    """Un garde-fou qu'une variable eteint n'est pas un garde-fou.

    Ce test est la pour qu'on ne rajoute pas << une petite option >> plus tard
    sans le decider explicitement : il echouera le jour ou elle apparaitra.
    """
    source = EXEMPLAIRES[0].read_text(encoding="utf-8")
    for mot in ("AUTORISE", "FORCE", "IGNORE", "SKIP", "BYPASS", "_OVERRIDE"):
        assert mot not in source.upper().replace("N'A PAS D'INTERRUPTEUR", "")


# --- Le branchement reel dans les deux services -------------------------------

def test_le_routeur_refuse_de_charger_quand_il_est_expose(monkeypatch):
    """uvicorn doit echouer a l'IMPORT, pas servir l'application a moitie."""
    monkeypatch.setenv("STUDIO_ADRESSE_PUBLIEE", "0.0.0.0")
    monkeypatch.setenv("FREE_TIER_MANAGER_KEY", "cle-interne-de-test")
    with pytest.raises(Exception) as leve:
        charger("free-tier-manager")
    assert "DEMARRAGE REFUSE" in str(leve.value)


def test_le_bac_a_sable_refuse_de_charger_quand_il_est_heberge(monkeypatch):
    """Le paragraphe 2.1 ne nommait que keys.json ; sandbox-keys.json existe aussi."""
    monkeypatch.setenv("STUDIO_HEBERGE", "true")
    monkeypatch.setenv("SANDBOX_MANAGER_KEY", "cle-sandbox-de-test")
    monkeypatch.setattr("os.chown", lambda *args: None, raising=False)
    with pytest.raises(Exception) as leve:
        charger("sandbox-manager")
    texte = str(leve.value)
    assert "DEMARRAGE REFUSE" in texte
    assert "sandbox-keys.json" in texte


def test_les_deux_services_demarrent_sur_un_poste_personnel(routeur, sandbox):
    """Le contre-test du precedent : sans rien declarer, tout charge.

    Sans lui, les deux tests ci-dessus passeraient meme si la garde refusait
    TOUJOURS -- et c'est exactement la panne qu'on ne verrait qu'en production.
    """
    assert routeur.app is not None
    assert sandbox.app is not None
