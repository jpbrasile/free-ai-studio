"""Ce que /cles et /diagnostic montrent : une carte par cle, des noms lisibles.

Deux dettes d'affichage de la revue du 11/09, refermees le 20/09/2026. Aucune
des deux routes n'avait de test. Elles ne cassent rien -- elles font douter, ce
qui revient au meme pour quelqu'un qui n'a pas de terminal pour verifier.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]


def cles(routeur):
    return asyncio.run(routeur.cles_etat())


def diagnostic(routeur, monkeypatch):
    """Sans l'aller-retour vers Open WebUI : ce test juge la liste, pas la liaison."""
    async def pas_de_liaison():
        return {}
    monkeypatch.setattr(routeur, "etat_liaison", pas_de_liaison)
    return asyncio.run(routeur.diagnostic_etat())


# --- /cles : une carte par CLE, pas par service ------------------------------


def test_un_service_qui_partage_la_cle_n_a_pas_de_carte_a_lui(routeur, monkeypatch):
    """Free AI Max porte la cle de Gemini : la redemander ferait douter.

    Jusqu'au 20/09/2026, un `FREE_PROVIDER_ORDER` contenant `gemini_max` posait
    une deuxieme carte sur /cles -- sans titre, sans mode d'emploi, et qui
    demandait la cle saisie juste au-dessus.
    """
    monkeypatch.setenv("FREE_PROVIDER_ORDER", "gemini,gemini_max,openrouter")
    noms = [f["nom"] for f in cles(routeur)["fournisseurs"]]
    assert noms == ["gemini", "openrouter"]


def test_aucune_carte_ne_s_affiche_sous_un_nom_de_code(routeur, monkeypatch):
    """`gemini_max` n'est pas un titre : c'est le nom de la variable.

    Il est mis EN TETE exprès : derrière Gemini il n'a pas de carte du tout, et
    le test ne jugerait alors plus rien. Une première version le plaçait en
    deuxième, et une mutation du titre passait sans la faire tomber.
    """
    monkeypatch.setenv("FREE_PROVIDER_ORDER", "gemini_max,openrouter,groq")
    for fiche in cles(routeur)["fournisseurs"]:
        assert fiche["titre"] != fiche["nom"], fiche["nom"]
        assert "_" not in fiche["titre"]


def test_un_service_seul_dans_l_ordre_garde_sa_carte(routeur, monkeypatch):
    """Le filtre porte sur la cle DEJA demandee, pas sur le nom du service.

    Sans cette distinction, il aurait suffi d'ecrire `gemini_max` en premier
    pour perdre la seule carte qui demande la cle Google.
    """
    monkeypatch.setenv("FREE_PROVIDER_ORDER", "gemini_max,openrouter")
    fiches = cles(routeur)["fournisseurs"]
    assert [f["nom"] for f in fiches] == ["gemini_max", "openrouter"]
    assert fiches[0]["titre"] == "Gemini Max (Google)"


# --- /diagnostic : la liste des services branches ----------------------------


def test_les_services_branches_suivent_l_ordre_d_affichage(routeur, monkeypatch):
    """Le dictionnaire du code rend openrouter d'abord, la page montre Gemini.

    La ligne du diagnostic ne coincidait donc avec aucune autre liste de la
    page. Les cles posees par la fixture sont Gemini et OpenRouter.
    """
    assert diagnostic(routeur, monkeypatch)["fournisseurs_branches"] == ["gemini", "openrouter"]


def test_une_cle_laissee_par_un_service_retire_de_l_ordre_n_est_pas_annoncee(routeur, monkeypatch):
    """Plus qu'un detail d'affichage : la ligne disait vrai pour un service muet.

    L'ancienne version parcourait `PROVIDERS`, c'est-a-dire TOUS les services
    ecrits dans le code, y compris ceux que `FREE_PROVIDER_ORDER` ne nomme pas.
    Une cle Groq laissee la apres avoir retire Groq de l'ordre faisait annoncer
    << un service gratuit est branche >> pour un service que le chat n'appelle
    jamais.
    """
    monkeypatch.setenv("GROQ_API_KEY", "groq-factice")
    monkeypatch.setenv("FREE_PROVIDER_ORDER", "gemini")
    assert diagnostic(routeur, monkeypatch)["fournisseurs_branches"] == ["gemini"]


def test_gemini_max_n_est_jamais_compte_comme_une_cle_de_plus(routeur, monkeypatch):
    monkeypatch.setenv("FREE_PROVIDER_ORDER", "gemini,gemini_max,openrouter")
    assert "gemini_max" not in diagnostic(routeur, monkeypatch)["fournisseurs_branches"]


def test_la_page_de_diagnostic_traduit_les_noms_de_code(routeur):
    """La route rend des noms de code ; la page doit montrer les titres.

    Ils viennent du meme endroit que partout ailleurs, `quotas.fournisseurs`,
    et le nom de code reste en repli.
    """
    source = (RACINE / "free-tier-manager" / "app.py").read_text(encoding="utf-8")
    debut = source.index("Au moins un service gratuit est branche")
    bloc = source[debut - 800:debut + 200]
    assert "titres[f.nom] = f.titre" in bloc
    assert "titres[n] || n" in bloc
    assert "d.fournisseurs_branches.join" not in bloc, "les noms de code sont encore affiches"
