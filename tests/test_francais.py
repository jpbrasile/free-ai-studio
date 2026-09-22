"""Les pages parlent francais de l'argent et des dates -- verifie sur le RENDU.

POURQUOI CE FICHIER. Le 21/09/2026 la page video annoncait << 4.88 $ sur les
15.00 $ >> et << releve chez Modal le 2026-09-21 10:58:42 >>. Point decimal
anglais et date de journal de machine, sur la premiere ligne que le client lit --
et elle parle de son argent.

POURQUOI ICI ET PAS SEULEMENT DANS `scripts/verifier-francais.py`. Cette garde-la
interroge le service qui tourne. Or le service tourne dans un conteneur qui porte
sa propre copie du code : le 22/09/2026 il repondait encore avec la version de la
veille, et une garde satisfaite d'une vieille page ne garde rien. Ici les pages
sont fabriquees a partir de l'arbre, a l'instant, sans reseau et sans conteneur.

LES MOTIFS NE SONT PAS RECOPIES : ils sont importes de la garde. Deux copies
d'une regle divergent, et c'est toujours la copie surveillee qui reste en retard.
"""
from __future__ import annotations

import importlib.util

import pytest
from fastapi.testclient import TestClient

from conftest import RACINE

PAGES = ["/", "/essai", "/video", "/chanson", "/dialogue"]


def _garde():
    """Les motifs de `scripts/verifier-francais.py`, charges depuis la source."""
    chemin = RACINE / "scripts" / "verifier-francais.py"
    spec = importlib.util.spec_from_file_location("garde_francais", chemin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("chemin", PAGES)
def test_la_page_rendue_ecrit_l_argent_et_les_dates_en_francais(sandbox, chemin):
    """Ce que le client VOIT, pas ce que le code contient.

    CE QUE CE TEST NE PEUT PAS VOIR, et il faut le dire : les montants du
    compteur arrivent APRES, par `fetch("/budget/modal")`, et sont ecrits par le
    JavaScript. Ils ne sont pas dans le HTML servi. Ce test-ci ne couvre donc que
    ce que Python imprime lui-meme ; le JavaScript est couvert par le bras source
    de `verifier-francais.py` et par les tests a node de `test_budget_modal.py`,
    qui executent la fonction et lisent la phrase qui en sort.
    """
    garde = _garde()
    html = TestClient(sandbox.app).get(chemin).text

    montants = sorted({m.group(0) for m in garde.MONTANT_A_POINT.finditer(html)})
    assert not montants, "%s affiche un montant a point : %s" % (chemin, montants)

    dates = sorted({m.group(0) for m in garde.DATE_ISO.finditer(html)})
    assert not dates, "%s affiche une date de machine : %s" % (chemin, dates)


@pytest.mark.parametrize("chemin", PAGES)
def test_la_page_qui_appelle_les_formateurs_les_porte(sandbox, chemin):
    """Le defaut le plus couteux de cette famille, et le plus silencieux.

    Une page qui appelle `fr(...)` sans porter sa definition ne s'affiche pas
    << a l'anglaise >> : elle ne s'affiche PAS. Le JavaScript s'arrete sur
    << fr is not defined >> et la banniere entiere disparait, sans un mot dans
    les journaux du serveur. Un rendu qui oublie `format_fr.avec_formateurs`
    suffit. Mesure le 22/09/2026 : le banc a node l'a trouve avant le navigateur.
    """
    html = TestClient(sandbox.app).get(chemin).text
    for appel, definition in (("fr(", "function fr("), ("dateFr(", "function dateFr(")):
        if appel in html:
            assert definition in html, (
                "%s appelle « %s » sans le definir : la banniere sera vide "
                "(le rendu a oublie format_fr.avec_formateurs)" % (chemin, appel))


@pytest.mark.parametrize("chemin", ["/essai", "/video", "/chanson", "/dialogue"])
def test_le_controle_du_dessus_mord_vraiment(sandbox, monkeypatch, chemin):
    """Un controle vert qui ne peut pas rougir ne garde rien.

    On retire `avec_formateurs` du rendu -- l'oubli exact contre lequel le test
    precedent existe -- et on verifie que la page le montre. Si cette assertion
    tombe, c'est le test precedent qui est a jeter, pas celui-ci.
    """
    monkeypatch.setattr(sandbox.format_fr, "avec_formateurs", lambda page: page)
    html = TestClient(sandbox.app).get(chemin).text
    assert "fr(" in html, "%s n'affiche aucun nombre : ce test n'y prouve rien" % chemin
    assert "function fr(" not in html, (
        "la page porte les formateurs sans passer par avec_formateurs : "
        "le controle precedent ne peut plus rougir")
