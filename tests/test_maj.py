"""Bouton « Mettre a jour » : sans veilleur, le message renvoie au geste du debutant."""
from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

RACINE = Path(__file__).resolve().parents[1]


def demande_de_la_page():
    """Ce que le navigateur envoie depuis la page du Studio."""
    return SimpleNamespace(headers={"sec-fetch-site": "same-origin",
                                    "content-type": "application/json"})


def test_sans_veilleur_renvoie_vers_demarrer(routeur):
    with pytest.raises(HTTPException) as refus:
        asyncio.run(routeur.maj_lancer(demande_de_la_page()))
    assert refus.value.status_code == 503
    assert "demarrer.cmd" in refus.value.detail
    # start.ps1 n'est pas le chemin du debutant (README, geste 5). Jusqu'au
    # 14/09/2026, le message y renvoyait.
    assert "start.ps1" not in refus.value.detail
    assert not routeur.MAJ_DEMANDE.exists()


def test_veilleur_vivant_recoit_la_demande(routeur):
    routeur.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    routeur.MAJ_VEILLEUSE.write_text("{}", encoding="utf-8")
    reponse = asyncio.run(routeur.maj_lancer(demande_de_la_page()))
    assert reponse["demande"] is True
    assert routeur.MAJ_DEMANDE.exists()


def test_signe_de_vie_date_du_futur_compte(routeur):
    # Horloge du conteneur en retard sur celle de Windows : le fichier porte une
    # date a venir. Jusqu'au 16/09/2026, le Studio tenait ce veilleur pour mort
    # et renvoyait vers demarrer.cmd.
    routeur.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    routeur.MAJ_VEILLEUSE.write_text("{}", encoding="utf-8")
    futur = time.time() + 20
    os.utime(routeur.MAJ_VEILLEUSE, (futur, futur))
    reponse = asyncio.run(routeur.maj_lancer(demande_de_la_page()))
    assert reponse["demande"] is True


def test_signe_de_vie_tres_en_avance_refuse(routeur):
    # Deux heures d'avance : ce n'est plus un ecart d'horloge, c'est un fichier
    # laisse la. Le veilleur est tenu pour absent.
    routeur.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    routeur.MAJ_VEILLEUSE.write_text("{}", encoding="utf-8")
    futur = time.time() + 7200
    os.utime(routeur.MAJ_VEILLEUSE, (futur, futur))
    with pytest.raises(HTTPException):
        asyncio.run(routeur.maj_lancer(demande_de_la_page()))
    assert not routeur.MAJ_DEMANDE.exists()


def test_veilleur_muet_depuis_une_minute(routeur):
    # Un signe de vie trop vieux vaut un veilleur absent : la demande resterait
    # sur la table, et la page attendrait pour rien.
    routeur.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    routeur.MAJ_VEILLEUSE.write_text("{}", encoding="utf-8")
    vieux = time.time() - 60
    os.utime(routeur.MAJ_VEILLEUSE, (vieux, vieux))
    with pytest.raises(HTTPException):
        asyncio.run(routeur.maj_lancer(demande_de_la_page()))
    assert not routeur.MAJ_DEMANDE.exists()


# --- La comparaison de version, par BRANCHE (20/09/2026) ---------------------
#
# Defaut trouve en ouvrant la page, pas en lisant le code : sur la branche
# `audit-20260911`, qui est EN AVANCE sur `main`, le Studio affichait
# << Une version plus recente existe >>. Le bouton d'a cote aurait ramene un
# debutant en arriere, sur le depot le moins a jour des deux.
#
# Deux causes, dans cet ordre : la branche etait ecrite en dur (`main`), et
# << je ne trouve pas votre commit >> etait rendu par << vous etes en retard >>.
# Une incertitude affichee comme un verdict est pire qu'une case vide : elle
# fait agir.
#
# Cette route n'avait AUCUN test. Ceux-ci simulent GitHub, donc ils ne
# dependent d'aucun reseau.


class GitHubSimule:
    """Les deux routes de GitHub que `/maj/etat` touche, et rien d'autre."""

    def __init__(self, commits=None, comparaison=None, code_commits=200,
                 code_comparaison=200):
        self.commits = commits or []
        self.comparaison = comparaison or {}
        self.code_commits = code_commits
        self.code_comparaison = code_comparaison
        self.demandes = []

    async def handler(self, requete: httpx.Request) -> httpx.Response:
        self.demandes.append(str(requete.url))
        if "/compare/" in requete.url.path:
            return httpx.Response(self.code_comparaison, json=self.comparaison)
        return httpx.Response(self.code_commits, json=self.commits)


def commit(sha, titre="un commit"):
    return {"sha": sha, "commit": {"message": titre}}


def brancher(routeur, monkeypatch, github, branche="audit-20260911", locale="aaa111"):
    """Le routeur croit etre sur `branche`, au commit `locale`, et GitHub est simule."""
    monkeypatch.setattr(routeur, "branche_locale", lambda: branche)
    monkeypatch.setattr(routeur, "version_locale", lambda: locale)
    monkeypatch.setattr(routeur, "depot_github", lambda: "jpbrasile/free-ai-studio")
    monkeypatch.setattr(routeur, "_GITHUB_CACHE", {"cle": None, "quand": 0.0, "valeur": {}})
    transport = httpx.MockTransport(github.handler)
    vrai = httpx.AsyncClient

    def client(*args, **kwargs):
        kwargs["transport"] = transport
        return vrai(*args, **kwargs)

    monkeypatch.setattr(routeur.httpx, "AsyncClient", client)


def etat(routeur):
    """Sans `with` : la route seule, pas le cycle de vie du service.

    Le `with` declenche le demarrage, donc les trois taches detachees -- dont
    le prechauffage de la dictee, qui telecharge 464 Mo. Mesure ici le
    20/09/2026 : la premiere demande vue par le faux GitHub etait celle
    d'Open WebUI, et ce fichier passait de 0,5 s a 19 s. Ces tests-la jugent
    une comparaison de version, pas un demarrage.
    """
    return TestClient(routeur.app).get("/maj/etat").json()


def demandes_github(github):
    return [u for u in github.demandes if "api.github.com" in u]


def test_la_comparaison_suit_la_branche_du_dossier_pas_main(routeur, monkeypatch):
    """LE defaut : `main` etait ecrit en dur dans la demande a GitHub."""
    github = GitHubSimule(commits=[commit("aaa111")])
    brancher(routeur, monkeypatch, github, branche="audit-20260911")
    reponse = etat(routeur)
    assert reponse["branche"] == "audit-20260911"
    assert "sha=audit-20260911" in demandes_github(github)[0]
    assert reponse["a_jour"] is True


def test_une_branche_imposee_garde_la_main(routeur, monkeypatch):
    """`DEPOT_BRANCHE` sert a suivre une autre branche que la sienne."""
    github = GitHubSimule(commits=[commit("aaa111")])
    brancher(routeur, monkeypatch, github, branche="audit-20260911")
    monkeypatch.setenv("DEPOT_BRANCHE", "main")
    reponse = etat(routeur)
    assert reponse["branche"] == "main"
    assert "sha=main" in demandes_github(github)[0]


def test_un_dossier_en_avance_n_est_pas_annonce_en_retard(routeur, monkeypatch):
    """Le cas exact du 20/09 : ce dossier a deux commits que la branche n'a pas.

    GitHub rend `status: behind` pour la branche comparee au commit installe.
    La page doit dire << en avance >>, et surtout PAS proposer de revenir en
    arriere.
    """
    github = GitHubSimule(
        commits=[commit("zzz999"), commit("yyy888")],       # notre sha absent
        comparaison={"status": "behind", "behind_by": 2, "ahead_by": 0, "commits": []})
    brancher(routeur, monkeypatch, github)
    reponse = etat(routeur)
    assert reponse["comparaison"] == "en_avance"
    assert reponse["avance_de"] == 2
    assert reponse["a_jour"] is not False, "un dossier en avance annonce comme en retard"


def test_un_dossier_vraiment_en_retard_le_dit_toujours(routeur, monkeypatch):
    """La reparation ne doit pas avoir eteint l'alerte utile."""
    github = GitHubSimule(
        commits=[commit("zzz999"), commit("yyy888")],
        comparaison={"status": "ahead", "ahead_by": 2, "behind_by": 0,
                     "commits": [commit("yyy888", "repare la dictee"),
                                 commit("zzz999", "ajoute la video")]})
    brancher(routeur, monkeypatch, github)
    reponse = etat(routeur)
    assert reponse["a_jour"] is False
    assert [c["titre"] for c in reponse["retard"]] == ["ajoute la video", "repare la dictee"]


def test_un_commit_jamais_pousse_ne_se_fait_pas_passer_pour_du_retard(routeur, monkeypatch):
    """GitHub rend 404 quand le commit installe ne lui est pas connu.

    C'est le cas normal d'un travail local pas encore pousse. Dire << vous etes
    en retard >> ferait perdre ce travail au premier clic.
    """
    github = GitHubSimule(commits=[commit("zzz999")], code_comparaison=404)
    brancher(routeur, monkeypatch, github)
    reponse = etat(routeur)
    assert reponse["comparaison"] == "commit_local_inconnu"
    assert reponse["a_jour"] is None


def test_deux_histoires_separees_sont_dites_telles_quelles(routeur, monkeypatch):
    github = GitHubSimule(
        commits=[commit("zzz999")],
        comparaison={"status": "diverged", "ahead_by": 3, "behind_by": 1, "commits": []})
    brancher(routeur, monkeypatch, github)
    reponse = etat(routeur)
    assert reponse["comparaison"] == "divergee"
    assert reponse["avance_de"] == 1 and reponse["retard_de"] == 3
    assert reponse["a_jour"] is None


def _page_de_maj() -> str:
    source = (RACINE / "free-tier-manager" / "app.py").read_text(encoding="utf-8")
    debut = source.index("majBouton.disabled = false;")
    return source[debut:debut + 3200]


def test_la_page_sait_dire_les_trois_nouveaux_etats(routeur):
    """Un etat rendu par la route et muet dans la page ne sert a rien."""
    page = _page_de_maj()
    for etiquette in ("en_avance", "divergee", "commit_local_inconnu"):
        assert '"' + etiquette + '"' in page, etiquette
    assert "en avance" in page


def test_la_page_n_annonce_pas_une_perte_que_le_bouton_ne_peut_pas_faire():
    """La premiere reparation avait remplace une fausse alarme par une autre.

    Ecrit d'abord le 20/09/2026 : << Mettre a jour vous les ferait perdre >> et
    << le bouton mettrait votre travail de cote >>. Lu ensuite dans
    `scripts/mettre-a-jour.ps1` : la mise a jour est un `git pull --ff-only`,
    qui n'avance qu'en ligne droite et sort en erreur sinon. Aucun commit, aucune
    modification locale ne peut etre perdue. Effrayer un debutant sur un danger
    qui n'existe pas le bloque aussi surement qu'un faux feu vert le pousse.

    Ce test tient les deux bouts : le mot de la page ET le fait du script. Si
    quelqu'un remplace un jour `--ff-only` par un `reset --hard`, la page redirait
    faux, et ce test tombe.
    """
    maj = (RACINE / "scripts" / "mettre-a-jour.ps1").read_text(encoding="utf-8")
    assert "'pull', '--ff-only'" in maj, "la mise a jour n'avance plus en ligne droite"
    for destructeur in ("reset', '--hard", "checkout', '-f", "clean', '-fd", "stash"):
        assert destructeur not in maj, destructeur
    page = _page_de_maj()
    assert "perdre" not in page
    assert "travail de côté" not in page
    assert "ligne droite" in page
