"""Le clip part-il sur la carte d'ici, ou sur une machine louee ?

Ces tests-ci ne jugent pas le module de decision -- c'est le role de
`test_ou_calculer.py`. Ils jugent le SERVICE : ce que la page recoit, ce qui est
ecrit dans la fiche du travail, et ce qui ne bouge pas pour celui qui n'a pas de
carte.

Quatre garanties, dans cet ordre d'importance :

1. **Sans carte branchee au Studio, RIEN ne change.** C'est le cas le plus
   courant -- le debutant sans carte -- et la promesse du produit. Le chantier
   GPU ne doit pas se voir chez lui.
2. **Carte prise + reglage par defaut : 409 et la question rendue au client**,
   avec le releve chiffre et les sorties possibles. Pas de depense decidee a sa
   place, pas d'attente decidee a sa place non plus (ordre du proprietaire du
   19/09 au soir, apres quinze minutes d'attente subie).
3. **Une commande que la maison ne sait pas faire part chez le loueur meme
   carte libre.** Sinon le Studio rend un clip qui ignore la consigne.
4. **Ce qui a ete decide reste ecrit dans la fiche du travail.** Six mois plus
   tard, personne ne refait le raisonnement de tete.

Aucune carte n'est sondee et aucun bac a sable n'est appele : la sonde et le
lancement sont remplaces.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

CLE = {"Authorization": "Bearer cle-sandbox-de-test"}
LOCAL = "http://127.0.0.1:8020"
GPU_URL = "http://sandbox-worker-gpu:8000"

# Le releve exact rendu par la carte le 19/09/2026 depuis le conteneur.
CARTE_LIBRE = {"vue": True, "nom": "NVIDIA GeForce RTX 4090", "totale_mo": 24564,
               "libre_mo": 24138, "marge_mo": 1024, "motif": ""}
CARTE_PRISE = dict(CARTE_LIBRE, libre_mo=3200)


def sonde_libre(besoin_mo, delai_s=None):
    return True, "NVIDIA GeForce RTX 4090 : 24138 Mo libres pour %d demandes (marge 1024)." % besoin_mo, CARTE_LIBRE


def sonde_prise(besoin_mo, delai_s=None):
    return False, ("NVIDIA GeForce RTX 4090 : 3200 Mo libres, il en faut %d." % (besoin_mo + 1024)), CARTE_PRISE


@pytest.fixture
def studio(sandbox, monkeypatch):
    """Le gestionnaire AVEC un bac a sable GPU declare, et rien qui parte.

    `run_video` est remplace : ces tests jugent le routage, pas la fabrication.
    Le vrai `run_video` est juge par la mesure -- le clip du 19/09 --, pas par
    un test qui ne peut pas allumer une carte."""
    monkeypatch.setattr(sandbox, "WORKER_GPU_URL", GPU_URL)
    monkeypatch.setattr(sandbox, "modal_configured", lambda: True)
    # Le bac a sable de la carte repond et porte ses 34 Go. Son absence et ses
    # poids manquants ont leurs propres tests, plus bas.
    monkeypatch.setattr(sandbox, "maison_prete", lambda: (True, ""))
    partis = []
    monkeypatch.setattr(sandbox, "run_video", lambda *a, **k: partis.append(a))
    sandbox.partis = partis
    return sandbox


def creer(studio, **payload):
    corps = {"description": "un phare dans la tempete", "duree": "3", "ou": "modal"}
    corps.update(payload)
    return TestClient(studio.app, base_url=LOCAL).post("/video/creer", headers=CLE, json=corps)


# --- 1. Celui qui n'a pas de carte ne voit rien de ce chantier ----------------

def test_sans_bac_a_sable_gpu_le_clip_part_chez_le_loueur_comme_avant(sandbox, monkeypatch):
    monkeypatch.setattr(sandbox, "WORKER_GPU_URL", "")
    monkeypatch.setattr(sandbox, "modal_configured", lambda: True)
    monkeypatch.setattr(sandbox, "run_video", lambda *a, **k: None)
    # La sonde n'est meme pas appelee : elle leve si on y touche.
    monkeypatch.setattr(sandbox.ou_calculer.gpu_local, "utilisable",
                        lambda *a, **k: pytest.fail("la carte ne doit pas etre sondee"))
    r = creer(sandbox)
    assert r.status_code == 200
    fiche = r.json()
    assert fiche["provider"] == "modal"
    assert fiche["ou_calculer"]["ou"] == "modal"
    assert "pas de carte" in fiche["ou_calculer"]["pourquoi"].lower()


# --- 2. Carte libre : on fabrique ici, gratuitement ---------------------------

def test_carte_libre_le_clip_se_fabrique_a_la_maison(studio, monkeypatch):
    monkeypatch.setattr(studio.ou_calculer.gpu_local, "utilisable", sonde_libre)
    r = creer(studio)
    assert r.status_code == 200
    fiche = r.json()
    assert fiche["provider"] == "maison"
    assert fiche["ou_calculer"]["besoin_mo"] == 12841
    # Le modele de la maison, pas celui qu'on loue : 24 images/s et 1280x704.
    assert fiche["video"]["maison"] is True
    assert fiche["video"]["images_par_seconde"] == 24
    assert fiche["video"]["definition"] == "1280x704"
    # Rien n'est facture pour un calcul qui ne coute rien.
    assert fiche["ou_calculer"]["prix_estime_usd"] is None
    assert studio.partis and studio.partis[0][3] == "maison"


def test_les_cinq_secondes_mesurees_le_19_09_partent_aussi_a_la_maison(studio, monkeypatch):
    """121 images, 14 902 Mo : mesure du 19/09, clip_4090_5s.mp4."""
    monkeypatch.setattr(studio.ou_calculer.gpu_local, "utilisable", sonde_libre)
    fiche = creer(studio, duree="5").json()
    assert fiche["provider"] == "maison"
    assert fiche["ou_calculer"]["besoin_mo"] == 14902
    assert fiche["video"]["secondes_video"] == 5


# --- 3. Carte prise : la question revient au client ---------------------------

def test_carte_prise_le_studio_demande_au_lieu_de_decider(studio, monkeypatch):
    monkeypatch.setattr(studio.ou_calculer.gpu_local, "utilisable", sonde_prise)
    r = creer(studio)
    assert r.status_code == 409
    decision = r.json()["detail"]
    assert decision["ou"] == "on-demande"
    # Ce qui bloque, avec le nombre : jamais << indisponible >> tout seul.
    assert "3200" in decision["pourquoi"]
    assert decision["carte"]["libre_mo"] == 3200
    # Les trois sorties, pour que la page n'ait pas a les inventer.
    assert decision["sorties"] == ["attente", "modal", "annuler"]
    # Et surtout : rien n'est parti, donc rien n'est facture.
    assert studio.partis == []


def test_j_attends_garde_la_demande_sur_la_carte_d_ici(studio, monkeypatch):
    monkeypatch.setattr(studio.ou_calculer.gpu_local, "utilisable", sonde_prise)
    r = creer(studio, attendre=True)
    assert r.status_code == 409
    decision = r.json()["detail"]
    assert decision["ou"] == "attente"
    assert "on n'arrete jamais" in decision["pourquoi"]


def test_le_client_presse_paye_et_part_tout_de_suite(studio, monkeypatch):
    """La carte est prise, il repond << louer >> : le clip part, en location."""
    monkeypatch.setattr(studio.ou_calculer.gpu_local, "utilisable", sonde_prise)
    fiche = creer(studio, ou_calculer="toujours-modal").json()
    assert fiche["provider"] == "modal"
    assert fiche["video"]["maison"] is False
    assert studio.partis and studio.partis[0][3] == "modal"


# --- 4. Ce que la maison ne sait pas faire gagne contre la carte libre --------

@pytest.mark.parametrize("commande", ["image_depart", "image_fin", "image_reference"])
def test_une_image_jointe_part_chez_le_loueur_meme_carte_libre(studio, monkeypatch, commande):
    """Trois commandes, deux raisons, une seule conclusion.

    L'image de fin et celle de reference sont des fonctions de VACE, absentes de
    la Wan 2.2. L'image de depart, elle, demande une AUTRE classe de diffusers
    (`WanImageToVideoPipeline`), jamais essayee ici. Dans les trois cas, router
    a la maison rendrait un clip qui ignore l'image -- sans un mot."""
    monkeypatch.setattr(studio.ou_calculer.gpu_local, "utilisable", sonde_libre)
    # Un PNG d'un pixel, assez pour que la demande porte une image.
    pixel = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
             "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
    fiche = creer(studio, **{commande: pixel}).json()
    assert fiche["provider"] == "modal"
    assert fiche["video"]["maison"] is False
    assert commande.replace("_", " de ") in fiche["ou_calculer"]["pourquoi"]


# --- 5. Le reglage, pose et relu ---------------------------------------------

def test_le_reglage_se_pose_et_se_relit(studio, monkeypatch, tmp_path):
    monkeypatch.setattr(studio.ou_calculer, "FICHIER", tmp_path / "ou-calculer.json")
    client = TestClient(studio.app, base_url=LOCAL)
    vu = client.get("/video/ou-calculer", headers=CLE).json()
    assert vu["reglage"] == "maison-si-libre"
    assert vu["carte_possible"] is True

    r = client.post("/video/ou-calculer", headers=CLE, json={"reglage": "toujours-maison"})
    assert r.status_code == 200
    assert client.get("/video/ou-calculer", headers=CLE).json()["reglage"] == "toujours-maison"


def test_un_reglage_inconnu_est_refuse_en_nommant_les_trois(studio, monkeypatch, tmp_path):
    monkeypatch.setattr(studio.ou_calculer, "FICHIER", tmp_path / "ou-calculer.json")
    client = TestClient(studio.app, base_url=LOCAL)
    r = client.post("/video/ou-calculer", headers=CLE, json={"reglage": "sur-la-lune"})
    assert r.status_code == 400
    for reglage in ("maison-si-libre", "toujours-modal", "toujours-maison"):
        assert reglage in r.json()["detail"]


# --- 6. Le bac a sable de la maison ------------------------------------------

def test_sans_poids_le_clip_part_chez_le_loueur_au_lieu_d_echouer_dix_minutes_plus_tard(
        sandbox, monkeypatch):
    """Le defaut trouve le 19/09 en passant enfin par la pile complete.

    Le bac a sable de la carte n'a pas internet : si les 34 Go manquent, il ne
    les trouvera JAMAIS. Router quand meme << maison >> donnerait un echec au
    bout de dix minutes, pour une raison que personne ne lit. On le sait avant
    de lancer, et on le dit."""
    monkeypatch.setattr(sandbox, "WORKER_GPU_URL", GPU_URL)
    monkeypatch.setattr(sandbox, "modal_configured", lambda: True)
    monkeypatch.setattr(sandbox, "run_video", lambda *a, **k: None)
    monkeypatch.setattr(sandbox, "maison_prete",
                        lambda: (False, "Les 34 Go du modele video ne sont pas encore telecharges"))
    monkeypatch.setattr(sandbox.ou_calculer.gpu_local, "utilisable",
                        lambda *a, **k: pytest.fail("la carte ne doit pas etre sondee"))
    fiche = creer(sandbox).json()
    assert fiche["provider"] == "modal"
    assert "34 Go" in fiche["ou_calculer"]["pourquoi"]


def test_maison_prete_lit_ce_que_le_bac_a_sable_repond(sandbox, monkeypatch):
    """Trois reponses possibles, trois verdicts, aucun devine."""
    monkeypatch.setattr(sandbox, "WORKER_GPU_URL", "")
    assert sandbox.maison_prete()[0] is False

    class FausseReponse:
        def __init__(self, charge): self._charge = charge
        def json(self): return self._charge

    class FauxClient:
        def __init__(self, charge): self._charge = charge
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, url): return FausseReponse(self._charge)

    monkeypatch.setattr(sandbox, "WORKER_GPU_URL", GPU_URL)
    monkeypatch.setattr(sandbox.httpx, "Client",
                        lambda **k: FauxClient({"ok": True, "poids_presents": True}))
    assert sandbox.maison_prete() == (True, "")

    monkeypatch.setattr(sandbox.httpx, "Client",
                        lambda **k: FauxClient({"ok": True, "poids_presents": False}))
    prete, motif = sandbox.maison_prete()
    assert prete is False and "telecharger-modele-video" in motif


def test_sans_bac_a_sable_gpu_l_execution_maison_refuse_clairement(sandbox):
    """Le cas ne doit pas arriver ; s'il arrive, il le dit au lieu d'appeler
    une adresse vide."""
    with pytest.raises(sandbox.BackendUnavailable) as erreur:
        sandbox.maison_execute("abc", "print(1)")
    assert "docker-compose.gpu.yml" in str(erreur.value)


# --- 5. La page nomme le modele qui fabrique vraiment le clip -----------------

def test_la_page_nomme_le_modele_de_la_maison(studio):
    """Defaut vu par le proprietaire le 19/09 : << pas de Wan 2.2 sur /video >>.

    La page ne nommait que la Wan 2.1, celle qu'on LOUE, alors que le reglage
    par defaut fabrique le clip ici avec la Wan 2.2 -- 1280x704 a 24 images/s
    au lieu de 832x480 a 16. Un nom affiche pour un modele qui ne tourne pas
    est un faux vert d'interface : il se lit comme une mesure.

    Ce test ne juge pas du rendu, il juge que le nom est LA : servi par
    /video/budget, et utilise par la page."""
    client = TestClient(studio.app, base_url=LOCAL)

    budget = client.get("/video/budget", headers=CLE).json()
    maison = budget["modeles"]["maison"]
    assert maison["hf"] == "Wan-AI/Wan2.2-TI2V-5B-Diffusers"
    assert maison["images_par_seconde"] == 24
    assert (maison["largeur"], maison["hauteur"]) == (1280, 704)

    page = client.get("/video", headers=CLE).text
    assert 'MODELES["maison"]' in page          # la ligne de licence la nomme
    assert "Qualité si on loue" in page         # le menu ne promet plus l'autre
