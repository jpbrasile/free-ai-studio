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
import json
import subprocess

import pytest
from fastapi.testclient import TestClient

from conftest import RACINE


def _charger(nom: str, chemin):
    spec = importlib.util.spec_from_file_location(nom, chemin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _garde():
    """Les motifs de `scripts/verifier-francais.py`, charges depuis la source."""
    return _charger("garde_francais", RACINE / "scripts" / "verifier-francais.py")


format_fr = _charger("format_fr_garde", RACINE / "sandbox-manager" / "format_fr.py")

# La liste des pages vient de la garde, elle aussi : elle etait recopiee ici et
# avait deja divergé — `/composite` manquait. Une copie d'une regle finit
# toujours en retard sur l'original, et c'est la copie surveillée qui décide.
PAGES = _garde().PAGES


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

    collees = sorted({m.group(0) for m in garde.MEMOIRE_COLLEE.finditer(html)})
    assert not collees, "%s affiche une memoire collee : %s" % (chemin, collees)


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
    for appel, definition in (("fr(", "function fr("), ("dateFr(", "function dateFr("),
                              ("moFr(", "function moFr(")):
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


# --- 3. La memoire : le troisieme formateur, ne le 22/09/2026 -----------------

CAS_MEMOIRE = [
    (0, "0\u00a0Mo"),
    (512, "512\u00a0Mo"),
    (1024, "1\u00a0024\u00a0Mo"),
    (24138, "24\u00a0138\u00a0Mo"),
    (24564, "24\u00a0564\u00a0Mo"),
    (1234567, "1\u00a0234\u00a0567\u00a0Mo"),
    (-8600, "-8\u00a0600\u00a0Mo"),
]


@pytest.mark.parametrize("valeur,attendu", CAS_MEMOIRE)
def test_le_formateur_de_memoire_groupe_les_milliers(valeur, attendu):
    """<< 24 138 Mo >>, pas << 24138 Mo >>. Et l'unite ne se detache pas du nombre."""
    assert format_fr.en_memoire(valeur) == attendu


def test_le_formateur_ne_CHANGE_pas_le_nombre():
    """Un groupement, pas un arrondi : le nombre se relit a l'identique.

    C'est la garantie qui separe une mise en forme d'une conversion. Passer en
    giga-octets aurait fait lire << 23,6 Go libres, il en faut 23,6 >> sur un
    refus -- deux valeurs distinctes ramenees a la meme apparence.
    """
    for valeur in (0, 7, 999, 1000, 24138, 999999, 1000000, -8600):
        rendu = format_fr.en_memoire(valeur, "")
        assert int(rendu.replace(format_fr.INSECABLE, "")) == valeur


def test_un_nombre_deja_groupe_ne_fait_plus_rougir_la_garde():
    """L'echappement n'est pas ecrit, il est structurel.

    `\\d{4,}` ne franchit pas l'insecable : une fois groupe, le nombre cesse de
    declencher le controle sans qu'aucun laissez-passer n'ait ete pose quelque
    part. Un laissez-passer ecrit serait un interrupteur a surveiller de plus.
    """
    garde = _garde()
    assert garde.MEMOIRE_COLLEE.search("la carte a 24138 Mo libres")
    assert not garde.MEMOIRE_COLLEE.search("la carte a %s libres"
                                           % format_fr.en_memoire(24138))


def test_la_garde_MORD_sur_les_deux_langages():
    """Un controle qui ne peut pas rougir ne garde rien.

    Les deux ecrivains reels du 22/09 sont remis tels quels : le `%d Mo` de
    Python et la concatenation JavaScript. Et le sens INVERSE de la
    concatenation aussi -- sans lui, il suffirait d'ecrire l'unite avant la
    valeur pour sortir du controle sans rien changer a ce que le client lit.
    """
    garde = _garde()
    assert garde.PY_MEMOIRE.search('"%s : %d Mo libres sur %d."')
    assert garde.JS_MEMOIRE_NUE.search('" (" + c.libre_mo + " Mo libres sur "')
    assert garde.JS_MEMOIRE_NUE.search('"Mo libres : " + c.libre_mo')
    # Ce qui passe par un formateur ne doit PAS rougir, sinon la garde
    # punirait la reparation qu'elle reclame.
    assert not garde.PY_MEMOIRE.search('"%s : %s libres sur %s."')
    assert not garde.JS_MEMOIRE_NUE.search('" (" + moFr(c.libre_mo) + " libres)"')
    assert not garde.JS_MEMOIRE_NUE.search('fr((c.libre_mo/1024), 1) + " Go libres"')


def test_la_garde_des_guillemets_MORD_sur_une_phrase_et_pas_sur_un_commentaire():
    """La garde du 22/09 avait ete retiree : elle lisait les lignes, attrapait
    les commentaires, et toute apostrophe y ouvrait un faux litteral.

    Celle-ci lit les litteraux par `ast`. Elle doit rougir sur une phrase reelle
    (la forme de `ou_calculer.py` avant reparation) et se taire sur tout ce que
    le client ne voit pas.
    """
    garde = _garde()
    fautive = 'x = "Vous avez regle << toujours a la maison >>."\n'
    assert [n for n, _ in garde.guillemets_montres(fautive)] == [1]
    muettes = (
        'def f():\n    """Une docstring << citee >>."""\n'
        '# un commentaire << cite >>, l\'apostrophe n\'ouvre rien\n'
        'PAGE = """<!-- note << HTML >> -->\n// note << JS >>\nvar a = 1; // << fin >>\n"""\n'
        'y = "« Vrais guillemets »."\n'
    )
    assert garde.guillemets_montres(muettes) == []


def test_aucune_phrase_montree_n_ecrit_des_chevrons():
    """Le client lit « ceci », jamais << ceci >>."""
    assert _garde().bras_guillemets() == []


def test_le_module_qui_ecrit_les_phrases_de_carte_est_SOUS_garde():
    """`gpu_local` ecrit quatre phrases de memoire et n'etait surveille par rien.

    C'est par la que << 24138 Mo >> est arrive sur `/essai`. Un module qui parle
    au client et qu'aucune liste ne nomme est un angle mort, pas une exception.
    """
    assert "sandbox-manager/gpu_local.py" in _garde().MODULES


def test_le_decompte_NOMME_ce_qu_aucune_famille_ne_compte(capsys):
    """Le decompte de la garde a lui-meme ete pris en faute le 22/09.

    Il annoncait << 5 endroit(s) : 0 sur l'argent, 0 sur les dates >> le jour ou
    la famille de la memoire est nee : cinq fautes reelles, rangees nulle part.
    Une famille qu'aucune ligne ne compte est une famille invisible.
    """
    garde = _garde()
    garde.bras_source = lambda: ["SOURCE un/fichier.py:1  quelque chose d'inclassable"]
    assert garde.main(["--sans-rendu"]) == 1
    sortie = capsys.readouterr().out
    assert "qu'aucune famille ne compte" in sortie, sortie


def _node(programme: str, tmp_path) -> str:
    fichier = tmp_path / "formateur.js"
    fichier.write_text(programme, encoding="utf-8")
    fait = subprocess.run(["node", str(fichier)], capture_output=True,
                          text=True, encoding="utf-8")
    assert fait.returncode == 0, fait.stderr
    return fait.stdout


def test_les_DEUX_formateurs_de_memoire_disent_la_meme_chose(tmp_path):
    """Python et JavaScript ecrivent le meme nombre, ou l'un des deux ment.

    Les chiffres de memoire arrivent par le reseau APRES le chargement de la
    page : ils ne passent jamais par Python, et le bras du rendu de la garde ne
    les voit donc pas dans le HTML servi. Deux implementations d'une meme regle
    divergent toujours ; celle qu'on ne regarde pas est celle que le client lit.
    """
    valeurs = [v for v, _ in CAS_MEMOIRE]
    programme = (format_fr.JS_FORMATEURS
                 + "\nvar vs = " + json.dumps(valeurs) + ";\n"
                 + "console.log(JSON.stringify(vs.map(function(v){"
                 + "return [moFr(v), moFr(v, \"\")];})));\n")
    rendus = json.loads(_node(programme, tmp_path))
    attendus = [[format_fr.en_memoire(v), format_fr.en_memoire(v, "")] for v in valeurs]
    assert rendus == attendus


def test_le_formateur_JS_ne_tombe_pas_sur_une_valeur_absente(tmp_path):
    """`null` arrive vraiment : la sonde rend `libre_mo: null` sans carte.

    Une exception ici n'ecrirait pas << ? >>, elle effacerait la banniere
    entiere -- le meme degat silencieux que le formateur manquant.
    """
    programme = (format_fr.JS_FORMATEURS
                 + "\nconsole.log(JSON.stringify([moFr(null), moFr(undefined), "
                 + "moFr(\"bonjour\")]));\n")
    assert json.loads(_node(programme, tmp_path)) == ["?", "?", "?"]
    assert format_fr.en_memoire(None) == "?"
