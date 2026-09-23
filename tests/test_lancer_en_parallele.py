"""Un second travail peut partir pendant que le premier tourne.

Signalé le 23/09/2026 : « on ne peut pas lancer sur kaggle quand une vidéo est
lancée sur la carte locale ». Rien ne l'interdisait côté serveur : la page
gardait « Fabriquer » éteint tant qu'elle suivait un travail.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

LOCAL = "http://127.0.0.1:8020"


@pytest.mark.parametrize("usage", ["video", "chanson", "dialogue"])
def test_le_bouton_se_rallume_des_que_le_travail_est_parti(sandbox, usage):
    page = TestClient(sandbox.app, base_url=LOCAL).get("/" + usage).text
    suivre = page[page.index("function suivre(id){"):]
    assert suivre.index("if(minuteur){ clearInterval(minuteur); minuteur = null; }") < suivre.index("const tour"), (
        "un second suivi laisserait l'ancien minuteur ecrire par-dessus le nouveau."
    )
    apres = page[page.index("suivre(d.id);"):][:400]
    assert "bouton.disabled = false;" in apres, "le bouton reste eteint jusqu'a la fin du travail"


@pytest.mark.parametrize("usage", ["video", "chanson", "dialogue"])
def test_suivre_un_ancien_travail_n_eteint_pas_le_bouton(sandbox, usage):
    page = TestClient(sandbox.app, base_url=LOCAL).get("/" + usage).text
    revoir = page[page.index("function revoir(id, defiler){"):]
    revoir = revoir[:revoir.index("\n  }\n")]
    assert "disabled = true" not in revoir
