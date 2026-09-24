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
    monkeypatch.setattr(sandbox, "maison_prete", lambda: (True, "", False))
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
    # Un MAJORANT, pas la mesure : il couvre les 12 841 Mo du clip du 19/09
    # sans pretendre les valoir. C'est ce qui permet d'offrir autre chose que
    # les deux durees mesurees (proprietaire, 21/09).
    assert fiche["ou_calculer"]["besoin_mo"] >= 12841
    assert fiche["ou_calculer"]["besoin_mo"] == studio.ou_calculer.besoin_mo(73)
    # Le temps attendu voyage avec la decision : la page le montre AVANT que le
    # client valide.
    assert fiche["ou_calculer"]["secondes_estimees"] == 412
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
    assert fiche["ou_calculer"]["besoin_mo"] >= 14902
    assert fiche["ou_calculer"]["besoin_mo"] == studio.ou_calculer.besoin_mo(121)
    assert fiche["ou_calculer"]["secondes_estimees"] == 598
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
    assert "on n'arrête jamais" in decision["pourquoi"]


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
    # Troisieme valeur False : ce Studio-la ne peut PAS telecharger lui-meme
    # (pas de cache monte dans le decideur), donc le clip part chez le loueur.
    # Le cas ou il peut a son propre test, juste en dessous.
    monkeypatch.setattr(sandbox, "maison_prete",
                        lambda: (False, "Les 34 Go du modele video ne sont pas encore telecharges", False))
    monkeypatch.setattr(sandbox.ou_calculer.gpu_local, "utilisable",
                        lambda *a, **k: pytest.fail("la carte ne doit pas etre sondee"))
    fiche = creer(sandbox).json()
    assert fiche["provider"] == "modal"
    assert "34 Go" in fiche["ou_calculer"]["pourquoi"]


def test_toujours_maison_et_bac_a_sable_muet_DEMANDE_au_lieu_de_louer(sandbox, monkeypatch):
    """La friction du 23/09 : reglage << toujours a la maison >>, bac a sable
    de la carte qui ne repond pas, et le clip partait chez le loueur sans un
    mot. Maintenant la question revient au client, et rien ne part."""
    monkeypatch.setattr(sandbox, "WORKER_GPU_URL", GPU_URL)
    monkeypatch.setattr(sandbox, "modal_configured", lambda: True)
    partis = []
    monkeypatch.setattr(sandbox, "run_video", lambda *a, **k: partis.append(a))
    monkeypatch.setattr(sandbox, "maison_prete",
                        lambda: (False, "Le bac a sable de la carte ne repond pas", False))
    r = creer(sandbox, ou_calculer="toujours-maison")
    assert r.status_code == 409
    decision = r.json()["detail"]
    assert decision["ou"] == "on-demande"
    assert decision["sorties"] == ["modal", "annuler"]
    assert "ne repond pas" in decision["pourquoi"]
    assert "rien n'est facturé" in decision["pourquoi"]
    assert partis == []
    # Le client repond << louer >> : la meme demande part, en location.
    fiche = creer(sandbox, ou_calculer="toujours-modal").json()
    assert fiche["provider"] == "modal"
    assert partis and partis[0][3] == "modal"


def test_la_page_ne_propose_d_attendre_que_si_le_serveur_l_offre(studio):
    page = TestClient(studio.app, base_url=LOCAL).get("/video", headers=CLE).text
    assert 'd.sorties.indexOf("attente")' in page


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
    assert sandbox.maison_prete() == (True, "", False)

    monkeypatch.setattr(sandbox.httpx, "Client",
                        lambda **k: FauxClient({"ok": True, "poids_presents": False}))
    prete, motif, ca_s_arrange = sandbox.maison_prete()
    assert prete is False and "telecharger-modele-video" in motif
    # Sans cache monte dans le decideur, il ne peut pas telecharger a la place
    # du client : il lui rend la commande, et ca ne s'arrange pas tout seul.
    assert ca_s_arrange is False


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


# --- 6. Le texte tape reste avec le clip -------------------------------------

def test_la_fiche_du_travail_garde_le_texte_du_clip(studio, monkeypatch):
    """Sans lui, deux clips ne se distinguent plus des le lendemain.

    Mesure du 19/09 : les deux clips fabriques ce soir-la pesent 1 901 468 et
    390 313 octets, et aucune des deux fiches ne dit sur quel texte. On ne peut
    donc ni refaire le meme clip, ni comparer deux modeles << sur le meme
    texte >> comme le plan le demande."""
    monkeypatch.setattr(studio.ou_calculer.gpu_local, "utilisable", sonde_libre)
    phrase = "un phare breton sous la pluie, la mer se souleve"
    r = creer(studio, description=phrase)
    assert r.status_code == 200
    assert r.json()["video"]["description"] == phrase


# --- 7. Le message nomme un script qui existe sur CETTE machine ---------------

def test_le_message_des_34_go_nomme_le_script_de_la_machine(studio, monkeypatch):
    """Dire << lancez ce script >> en nommant celui de l'autre systeme est un
    cul-de-sac : la personne tape une commande qui n'existe pas chez elle.

    Le service tourne dans un conteneur Linux quelle que soit la machine : il
    ne peut pas le deviner, c'est le lanceur qui le lui dit. Lanceur inconnu --
    un `docker compose up` tape a la main -- on nomme les DEUX plutot que d'en
    inventer un."""
    video = studio.video

    monkeypatch.setattr(video, "STUDIO_LANCEUR", "windows")
    assert video.commande_telechargement().endswith("telecharger-modele-video.ps1")

    monkeypatch.setattr(video, "STUDIO_LANCEUR", "linux")
    assert video.commande_telechargement() == "./scripts/telecharger-modele-video.sh"

    monkeypatch.setattr(video, "STUDIO_LANCEUR", "")
    deux = video.commande_telechargement()
    assert "telecharger-modele-video.sh" in deux and "telecharger-modele-video.ps1" in deux

    # Et la commande voyage AVEC le script envoye au bac a sable, qui ne sait
    # rien du systeme d'ou vient la demande.
    monkeypatch.setattr(video, "STUDIO_LANCEUR", "linux")
    prepare = video.preparer({"description": "un phare", "duree": "3"}, maison=True)
    assert prepare["demande"]["aide_poids"] == "./scripts/telecharger-modele-video.sh"


def test_une_duree_JAMAIS_mesuree_part_desormais_a_la_maison(studio, monkeypatch):
    """Le point de tout le changement du 21/09/2026.

    Hier, 7 secondes n'existaient pas dans le menu ; si on les avait forcees,
    le clip serait parti chez le loueur, motif << on ne lance pas sur un chiffre
    suppose >>. Le chiffre ne servait qu'a une chose -- ai-je assez de place --
    et un majorant y repond.
    """
    monkeypatch.setattr(studio.ou_calculer.gpu_local, "utilisable", sonde_libre)
    fiche = creer(studio, duree="7").json()
    assert fiche["provider"] == "maison"
    assert fiche["video"]["secondes_video"] == 7
    assert fiche["video"]["images_par_seconde"] == 24
    assert fiche["ou_calculer"]["besoin_mo"] > 14902
    assert fiche["ou_calculer"]["secondes_estimees"] > 598


def test_le_menu_offre_plus_que_deux_durees_et_annonce_le_temps(studio):
    """Ce que la page met dans son menu : chaque duree avec son temps attendu."""
    offres = studio.video.durees_offertes()
    assert len(offres) > 2, "le menu est encore fige"
    pas = studio.video.pas_temporel()
    for o in offres:
        assert o["images"] % pas == 1, (
            "le modele n'accepte qu'un multiple de %d plus un : %r" % (pas, o))
        assert o["besoin_mo"] > 0
        # Le temps n'est annonce QUE pour les durees qui tournent ici : celui
        # du loueur n'est pas le meme, et le donner pour l'autre serait pire
        # que ne rien donner.
        assert (o["secondes_estimees"] is None) is not o["tient_ici"]

    besoins = [o["besoin_mo"] for o in offres]
    assert besoins == sorted(besoins), besoins
    temps = [o["secondes_estimees"] for o in offres if o["tient_ici"]]
    assert temps == sorted(temps), temps


def test_le_menu_ne_se_vide_JAMAIS_meme_sur_une_petite_carte(studio):
    """Premier jet : on retirait du menu ce que la carte ne tient pas. Sur une
    carte de 12 Go le menu devenait VIDE, et le client n'avait plus rien a
    choisir -- alors que le loueur sait fabriquer ces clips."""
    petite = studio.video.durees_offertes(totale_mo=8192)
    assert petite, "un menu vide est un cul-de-sac"
    assert not any(o["tient_ici"] for o in petite)
    assert all(o["secondes_estimees"] is None for o in petite)

    # Sur une petite carte, TOUT passe par le loueur : aucune duree offerte ne
    # doit donc depasser ce que le loueur sait faire. Avant le 21/09 apres-midi,
    # ce menu proposait 9 s << chez le loueur >> alors que le plafond declare du
    # loueur est 5 s -- le clip y aurait ete rabattu a 5 s, en silence.
    plafond = studio.video.secondes_max_loueur()
    assert all(o["secondes"] <= plafond for o in petite), (
        "on offre une duree que personne ne sait faire")

    # Une grande carte en offre DAVANTAGE, et c'est le but : les durees en plus
    # sont celles qu'elle seule sait faire.
    grande = studio.video.durees_offertes(totale_mo=24564)
    assert len(grande) > len(petite)
    assert any(o["tient_ici"] for o in grande)
    for o in grande:
        if o["secondes"] > plafond:
            assert o["tient_ici"], (
                "%s s n'est ni faisable ici ni chez le loueur" % o["duree"])


def test_une_duree_connue_de_la_MAISON_SEULE_nest_jamais_rabattue(studio):
    """Le danger que nommait l'ancien test, garde ; son moyen, jete.

    L'ancien exigeait que les deux tables offrent les MEMES durees, pour que
    `preparer()` ne tombe jamais sur son `duree = "5"`. Le moyen etait faux : il
    faisait deriver le plafond du LOUEUR des ancres de la carte d'ici -- autre
    modele, autre machine. On a retire la substitution a la place, et les deux
    tables peuvent enfin differer sans mentir.

    Ce que la substitution cassait, et qu'on verifie ici : le client demandait
    7 s, recevait 5 s, et le ROUTAGE lui-meme decidait sur la memoire d'un clip
    de 5 s -- 14 902 Mo au lieu de 19 677.
    """
    assert set(studio.video.DUREES) != set(studio.video.DUREES_MAISON), (
        "les deux plafonds sont a nouveau couples : celui du loueur n'est pas "
        "celui de la maison")
    seule_maison = set(studio.video.DUREES_MAISON) - set(studio.video.DUREES)
    assert seule_maison, "aucune duree propre a la maison : le test ne teste rien"

    duree = sorted(seule_maison, key=int)[0]
    plan = studio.video.preparer({"description": "un chat", "duree": duree})
    attendu = studio.video.DUREES_MAISON[duree]["images"]
    assert plan["duree"] == duree, "la duree a ete rabattue sur %s" % plan["duree"]
    assert plan["demande"]["images"] == attendu, (
        "la duree a ete rabattue : %d images au lieu de %d"
        % (plan["demande"]["images"], attendu))
    assert plan["demande"]["modele"] == studio.video.MODELES["maison"]["hf"]
    assert plan["resume_public"]["secondes_video"] == int(duree)


def test_une_duree_que_PERSONNE_ne_sait_faire_est_refusee(studio):
    """Ni la maison ni le loueur : on le dit, on ne bricole pas."""
    trop = str(max(studio.video.secondes_max_maison(),
                   studio.video.secondes_max_loueur()) + 1)
    with pytest.raises(ValueError) as erreur:
        studio.video.preparer({"description": "un chat", "duree": trop})
    assert trop in str(erreur.value)


def test_carte_prise_et_loueur_incapable_on_ATTEND_sans_proposer_de_louer(studio):
    """Proposer une porte qui n'existe pas, c'est la substitution avec un bouton.

    Carte prise, duree que le loueur ne sait pas faire : le client ne doit pas
    se voir offrir << attendre ou louer >>, parce que louer lui rendrait un clip
    plus court sans le dire.
    """
    decision = studio.ou_calculer.decider(
        {}, studio.video.DUREES_MAISON[
            sorted(set(studio.video.DUREES_MAISON) - set(studio.video.DUREES),
                   key=int)[0]]["images"],
        prix_estime_usd=0.12, sonde=sonde_prise, loueur_peut=False)
    assert decision["ou"] == studio.ou_calculer.ATTENTE
    assert studio.ou_calculer.MODAL not in decision["sorties"]
    assert "QUE sur elle" in decision["pourquoi"]


def test_la_page_dit_AU_PLUS_quand_le_chiffre_est_majore(studio):
    """Grief no 2 de la relecture adverse du 21/09.

    Le chiffre montre au client est un besoin RELEVE sur les deux durees
    mesurees, et un majorant partout ailleurs. Annoncer un majorant comme un
    releve est un nombre fabrique -- la faute exacte que ce depot retire
    ailleurs. La boite << la carte est prise >> porte donc les deux phrases.
    """
    page = studio.video.PAGE_HTML
    assert '", il en faut au plus "' in page
    assert "d.besoin_est_mesure" in page


def test_la_reponse_dit_si_le_chiffre_est_mesure_ou_majore(studio, monkeypatch):
    """Les deux durees d'essai se DEDUISENT, elles ne s'ecrivent plus.

    Ce test nommait 5 s comme la duree mesuree. Le 21/09 il a rougi : 121
    images ont bien ete mesurees, a 16 351 Mo, mais 97 images en avaient pris
    16 711 -- la suite des relevés n'est pas croissante, parce que la reserve
    de l'allocateur torch depend de l'etat de son cache. La place reservee pour
    5 s est donc le maximum courant, 16 711, qui n'est la mesure de personne a
    cette duree : la reponse dit << au plus >>, et elle a raison.
    """
    monkeypatch.setattr(studio.ou_calculer.gpu_local, "utilisable", sonde_libre)
    table = studio.video.table_maison()
    mesurees = studio.video.durees_mesurees()
    majorees = [c for c in table if c not in mesurees]
    assert mesurees and majorees, (
        "il faut une duree de chaque sorte pour que ce test dise quelque chose")

    vu = creer(studio, duree=mesurees[0]).json()["ou_calculer"]
    assert vu["besoin_est_mesure"] is True

    vu = creer(studio, duree=majorees[0]).json()["ou_calculer"]
    assert vu["besoin_est_mesure"] is False


# --- 10. La phrase sous le menu ----------------------------------------------

def test_la_phrase_ne_dit_MESUREE_que_la_place_vraiment_relevee(studio):
    """Le defaut du 21/09, trouve en OUVRANT la page apres l'avoir deployee.

    La phrase listait les cles du menu. Tant que le menu tenait exactement les
    deux durees mesurees, elle disait vrai par coincidence ; le menu s'est
    ouvert a neuf durees et elle a annonce << Durees mesurees ici : 1 et 2 et
    ... et 9 secondes >>. Sept de ces neuf etaient majorees. Un nombre
    fabrique, et tous les tests passaient : aucun ne lisait la page.
    """
    mesurees = studio.video.durees_mesurees()
    offertes = [o["duree"] for o in studio.video.durees_offertes()]
    table = studio.video.table_maison()
    assert mesurees, "aucune place relevee : la phrase n'aurait rien a dire"
    # ON COMPTAIT, ET LE COMPTE NE VOULAIT RIEN DIRE SANS CARTE. `len(mesurees)
    # < len(offertes)` tenait sur une machine a carte -- 7 places relevees, 8
    # durees offertes. Sur un runner SANS carte, le menu retombe au plafond du
    # loueur (5 s) tandis que la liste des places garde les 7 de la 4090 :
    # << assert 7 < 5 >>, et la CI rougissait depuis le 21/09/2026 sans que le
    # produit ait quoi que ce soit. Ce qui est vraiment garde n'est pas un
    # compte, c'est que la phrase ne redise pas le menu : il reste au moins une
    # duree offerte qui n'est PAS mesuree. Vrai des deux cotes, et faux le jour
    # ou le defaut revient.
    non_mesurees = [cle for cle in offertes if cle not in mesurees]
    assert non_mesurees, (
        "toutes les durees du menu sont annoncees mesurees : soit le defaut du "
        "21/09 est revenu, soit la campagne les a vraiment toutes relevees -- "
        "dans ce second cas c'est CE controle qui doit partir, pas la phrase")
    for cle in offertes:
        attendu = studio.ou_calculer.besoin_est_mesure(table[cle]["images"])
        assert (cle in mesurees) is attendu, cle


def test_la_PLACE_et_le_TEMPS_ne_sont_pas_la_meme_liste(studio):
    """Le meme defaut un cran plus loin, et la campagne du 21/09 l'ouvrait.

    Une seule liste servait aux deux phrases. Elle disait vrai tant que les
    memes clips avaient donne la place ET le temps. La campagne a releve la
    place de toutes les durees du menu a 2 passes -- le temoin dit que la place
    n'en depend pas, 12 841 Mo a 50 passes contre 12 828 a 2 -- mais le temps,
    lui, en depend du simple au double : 412 s contre 170 s pour le meme clip
    de 3 s. Nommer << chronometree >> une duree dont le temps est extrapole
    serait exactement le defaut repare le matin meme.

    ET LES DEUX LISTES NE S'EMBOITENT PAS, contrairement a ce que j'avais
    ecrit d'abord. 5 s a bien ete chronometree le 19/09, et pourtant sa place
    est annoncee << au plus >> : 121 images ont pris 16 351 Mo, mais 97 en
    avaient pris 16 711, et la place reservee est le maximum courant. Un temps
    mesure n'entraine donc pas une place mesuree. Ce qu'il entraine, c'est
    qu'un clip a tourne -- donc une ancre.
    """
    place = studio.video.durees_mesurees()
    chrono = studio.video.durees_chronometrees()
    table = studio.video.table_maison()
    assert chrono, "aucun temps chronometre : la phrase n'aurait rien a dire"
    for cle in chrono:
        assert table[cle]["images"] in studio.ou_calculer.ANCRES, (
            "%s s est dite chronometree sans qu'aucun clip n'ait tourne" % cle)
    assert set(chrono) ^ set(place), (
        "les deux listes sont identiques : ce test ne distingue plus rien, et "
        "la page pourrait de nouveau n'en lire qu'une")
    for cle in table:
        attendu = studio.ou_calculer.temps_est_mesure(table[cle]["images"])
        assert (cle in chrono) is attendu, cle


def test_la_page_tire_la_phrase_des_MESURES_et_non_du_MENU(studio):
    """Le defaut etait dans le JavaScript, pas dans Python. Aucun test Python
    ne pouvait le voir ; celui-ci lit la page elle-meme."""
    with open(studio.video.__file__, encoding="utf-8") as fichier:
        page = fichier.read()
    assert "Object.keys(d.durees_maison" not in page, (
        "la phrase se rebranche sur le menu : elle redira neuf durees mesurees")
    assert "d.durees_mesurees" in page
    assert "d.durees_chronometrees" in page, (
        "la page ne lit qu'une liste : elle dira << chronometree >> d'un temps "
        "extrapole des que les deux listes cesseront de coincider")
    assert "chronom" in page, "la phrase ne dit plus ce qu'elle nomme"


def test_la_reponse_du_serveur_porte_les_TROIS_listes(studio, monkeypatch, tmp_path):
    """La page ne peut pas distinguer ce que le serveur ne lui dit pas."""
    monkeypatch.setattr(studio.ou_calculer, "FICHIER", tmp_path / "ou-calculer.json")
    client = TestClient(studio.app, base_url=LOCAL)
    vu = client.get("/video/ou-calculer", headers=CLE).json()
    assert set(vu["durees_mesurees"]) < set(vu["durees_maison"]), (
        "le menu et les places relevees doivent rester deux listes differentes")
    # Pas d'emboitement entre les deux : une duree peut avoir son temps
    # chronometre et sa place annoncee << au plus >>, parce que la place
    # reservee est le maximum courant des relevés (voir
    # `test_la_PLACE_et_le_TEMPS_ne_sont_pas_la_meme_liste`).
    assert set(vu["durees_chronometrees"]) <= set(vu["durees_maison"])
    assert set(vu["durees_chronometrees"]) ^ set(vu["durees_mesurees"]), (
        "les deux listes sont identiques : la page pourrait n'en lire qu'une")


def test_le_nombre_d_images_SUIT_la_granularite_DU_MODELE(studio, monkeypatch):
    """Le test precedent ne pouvait pas voir d'ou venait le pas.

    Il exigeait `images % pas == 1`. A 24 images par seconde, cette egalite
    tient pour un pas de 2, 3, 4, 6, 8, 12 ou 24 : la granularite pouvait etre
    recopiee a la main, fausse, et le test restait vert. On change ici la valeur
    que le MODELE annonce, et on exige que le compte bouge.
    """
    fps = studio.video.fps_de("maison")
    monkeypatch.setattr(studio.video, "pas_temporel", lambda: 4)
    a_quatre = studio.video.images_pour(3, fps)
    monkeypatch.setattr(studio.video, "pas_temporel", lambda: 5)
    a_cinq = studio.video.images_pour(3, fps)
    assert a_quatre % 4 == 1 and a_cinq % 5 == 1
    assert a_quatre != a_cinq, (
        "le compte ne suit pas le modele : la granularite est recopiee")


def test_par_lAPI_une_duree_hors_du_loueur_ne_propose_PAS_de_louer(studio, monkeypatch):
    """Le meme refus, mais par le vrai chemin -- page, routage, decision.

    Trois mutations muettes le 21/09 : `loueur_sait_faire()` pouvait mentir et
    dire toujours oui, `app.py` pouvait cesser de le demander, et rien ne
    rougissait -- le test precedent appelait `decider()` a la main avec
    `loueur_peut=False`, donc il ne verifiait pas le cablage. Celui-ci passe par
    l'API : carte prise, duree que seule la maison sait faire.
    """
    monkeypatch.setattr(studio.ou_calculer.gpu_local, "utilisable", sonde_prise)
    duree = sorted(set(studio.video.DUREES_MAISON) - set(studio.video.DUREES),
                   key=int)[0]
    r = creer(studio, duree=duree)
    assert r.status_code == 409
    decision = r.json()["detail"]
    assert decision["ou"] == "attente", (
        "on propose de louer une duree que le loueur ne sait pas faire")
    assert "modal" not in decision["sorties"]
    assert decision["sorties"] == ["attente", "annuler"]
    # Et le chiffre est bien celui de la duree DEMANDEE, pas d'un clip rabattu.
    assert decision["besoin_mo"] == studio.ou_calculer.besoin_mo(
        studio.video.DUREES_MAISON[duree]["images"])
    assert studio.partis == []


# --- La loi du temps CHEZ LE LOUEUR ------------------------------------------
#
# Jusqu'au 21/09/2026 il n'y avait pas de loi : une table a une entree, lue
# comme un dictionnaire. Un client qui demandait 1 s ou 5 s ne voyait ni temps
# ni prix avant de payer. La cause n'etait pas le code -- trois clips avaient
# ete fabriques chez Modal et LES TROIS faisaient 49 images. Une droite a deux
# inconnues ; trois mesures au meme point n'en determinent qu'une.


def _mesures_de(video, qualite):
    """Les durees de ce modele reellement chronometrees, triees."""
    return sorted((d for (q, d) in video.SECONDES_MESUREES if q == qualite),
                  key=int)


def test_la_droite_du_loueur_ne_promet_JAMAIS_moins_qu_un_clip_deja_paye(sandbox):
    """Un temps montre avant de depenser se majore ; il ne se minore pas.

    Meme regle que pour la place sur la carte d'ici, et pour la meme raison :
    ces deux chiffres sont lus par quelqu'un qui n'a pas encore paye. Une droite
    qui passerait SOUS une mesure promettrait moins que ce qui a deja ete
    constate, et la promesse serait dementie par un clip deja fabrique.
    """
    video = sandbox.video
    for qualite in ("rapide",):
        points = video._points_loueur(qualite)
        if len(points) < 2:
            continue
        origine, pente = sandbox.ou_calculer.droite_relevee(points)
        for images, mesure in points:
            assert origine + pente * images >= mesure - 1e-6, (
                "la droite de %s passe sous la mesure de %d images (%.1f s)"
                % (qualite, images, mesure))


def test_un_temps_chronometre_est_rendu_TEL_QUEL(sandbox):
    """Sur une duree mesuree, la fonction rend la mesure, pas la droite.

    Majorer une mesure n'est pas prudent : c'est jeter la mesure. Meme
    raisonnement que `besoin_mo()` sur un point mesure.
    """
    video = sandbox.video
    for (qualite, duree), secondes in video.SECONDES_MESUREES.items():
        assert video.secondes_loueur(qualite, duree) == float(secondes)
        assert video.temps_loueur_est_mesure(qualite, duree)


def test_le_temps_du_loueur_monte_avec_la_duree(sandbox):
    """Un clip plus long ne peut pas etre annonce plus court."""
    video = sandbox.video
    for qualite in ("rapide",):
        temps = [(d, video.secondes_loueur(qualite, d)) for d in video.DUREES]
        connus = [(int(d), s) for d, s in temps if s is not None]
        connus.sort()
        for (d1, s1), (d2, s2) in zip(connus, connus[1:]):
            assert s2 >= s1, ("%s : %d s annonce %.1f s, %d s annonce %.1f s"
                              % (qualite, d1, s1, d2, s2))


def test_UN_SEUL_clip_chronometre_ne_trace_pas_de_droite(sandbox, monkeypatch):
    """Une pente ne se devine pas sur un point, et c'etait tout le probleme.

    Ce test tient l'etat d'AVANT le 21/09 : une seule duree mesuree. La reponse
    juste est alors None -- la page montre le plafond du pire cas, qui est large
    mais honnete -- et surement pas une droite passant par l'origine.
    """
    video = sandbox.video
    monkeypatch.setattr(video, "SECONDES_MESUREES", {("rapide", "3"): 422})
    assert video.secondes_loueur("rapide", "3") == 422.0
    assert video.secondes_loueur("rapide", "1") is None
    assert video.prix_estime("rapide", "1") is None
    assert not video.temps_loueur_est_mesure("rapide", "1")


def test_le_prix_du_loueur_est_le_TEMPS_fois_le_TARIF(sandbox):
    """Le prix ne vit nulle part : il se recalcule a chaque lecture.

    C'est ce qui a sauve `prix_estime()` le 20/09, quand les tarifs des bacs a
    sable se sont reveles triples : la fonction a suivi toute seule, pendant que
    le registre gardait une copie 25 % trop basse.
    """
    video = sandbox.video
    for qualite in ("rapide",):
        carte = video.MODELES[qualite]["gpu"]
        for duree in video.DUREES:
            secondes = video.secondes_loueur(qualite, duree)
            attendu = (None if secondes is None
                       else round(video.prix_seconde(carte) * secondes, 4))
            assert video.prix_estime(qualite, duree) == attendu


def test_une_duree_que_le_modele_loue_ne_DECLARE_PAS_n_a_ni_temps_ni_prix(sandbox,
                                                                           monkeypatch):
    """Au-dela de ce que sa fiche annonce, on ne chiffre pas -- meme si on sait.

    DEUX GARDES SE RESSEMBLENT ET N'ONT PAS LE MEME ROLE. L'une refuse de
    chiffrer au-dela de la plus longue MESURE (la droite y mentirait, la courbe
    montant plus vite qu'elle) ; l'autre refuse de chiffrer une duree que le
    modele loue ne DECLARE pas savoir faire. Aujourd'hui les deux limites
    coincident -- le menu s'arrete a la plus longue duree mesuree -- et la
    premiere ecriture de ce test prenait donc une duree que les DEUX gardes
    rejettent : retirer la seconde du code ne le faisait pas echouer. Mesure du
    21/09 : cinq mutations attrapees sur six, celle-la muette.

    On met donc en place le seul cas qui les separe : un menu RACCOURCI sous ce
    qui a ete mesure. La loi saurait chiffrer cette duree ; elle doit se taire
    parce qu'elle n'est pas offerte.
    """
    video = sandbox.video
    mesurees = sorted((d for (q, d) in video.SECONDES_MESUREES if q == "rapide"), key=int)
    assert len(mesurees) >= 2, "il faut deux mesures pour que la loi sache chiffrer"
    hors_menu = mesurees[-1]
    # Le menu s'arrete AVANT cette duree, alors qu'elle est mesuree.
    monkeypatch.setattr(video, "DUREES",
                        {d: v for d, v in video.DUREES.items() if int(d) < int(hors_menu)})
    assert hors_menu not in video.DUREES
    assert video.secondes_loueur("rapide", hors_menu) is None, (
        "%s s n'est pas au menu du modele loue : rien ne doit etre chiffre"
        % hors_menu)
    assert video.prix_estime("rapide", hors_menu) is None
    # ... et ce qui reste au menu est toujours chiffre.
    assert video.secondes_loueur("rapide", mesurees[0]) is not None


def test_le_menu_DIT_le_temps_du_loueur_des_qu_il_sait_le_calculer(sandbox, monkeypatch):
    """Ecrit dans le sens reversible, comme la garde du modele jamais lance.

    Tant que la loi rend None, le menu n'a rien a dire et ne dit rien. Le jour
    ou deux durees sont chronometrees, la droite existe -- et le menu DOIT
    montrer les minutes au lieu de la phrase muette d'avant.
    """
    video = sandbox.video
    # Une carte trop petite pour tout : chaque duree part donc chez le loueur.
    # La sonde est POSEE, sans quoi `options_duree_html()` refait la sienne et
    # voit la carte de la machine qui fait tourner les tests -- ce qui a fait
    # echouer ce test a sa premiere ecriture, pour une raison etrangere a ce
    # qu'il juge.
    petite = {"vue": True, "nom": "carte minuscule", "totale_mo": 4096,
              "libre_mo": 4096, "marge_mo": 1024, "motif": ""}
    monkeypatch.setattr(sandbox.ou_calculer.gpu_local, "releve", lambda: petite)
    offres = video.durees_offertes()
    assert offres and not any(o["tient_ici"] for o in offres)
    menu = video.options_duree_html()
    for offre in offres:
        if offre["secondes_loueur"] is None:
            continue
        attendu = video._en_minutes(offre["secondes_loueur"])
        assert attendu in menu, (
            "le menu ne dit pas %r pour la duree %s alors que la loi la chiffre"
            % (attendu, offre["duree"]))


def test_au_DELA_de_la_plus_longue_mesure_la_droite_se_tait(sandbox, monkeypatch):
    """Une courbe convexe extrapolee par une droite promet moins cher que vrai.

    Trois clips loues le 21/09 : 17, 49 et 81 images. Le prix d'une image monte
    -- 8,22 s puis 10,97 s. Entre deux mesures la droite relevee majore encore,
    parce qu'une courbe convexe passe sous la corde ; au-dela, elle passe
    dessous, et un prix montre avant de depenser serait trop bas.

    Le cas ne se produit pas aujourd'hui (la plus longue duree offerte est aussi
    la plus longue mesuree). On le fabrique donc : une table amputee de son
    dernier point doit faire taire la loi sur ce point-la.
    """
    video = sandbox.video
    mesurees = sorted((d for (q, d) in video.SECONDES_MESUREES if q == "rapide"), key=int)
    if len(mesurees) < 3:
        pytest.skip("il faut au moins trois durees mesurees pour amputer la derniere")
    la_plus_longue = mesurees[-1]
    ampute = {c: v for c, v in video.SECONDES_MESUREES.items()
              if c != ("rapide", la_plus_longue)}
    monkeypatch.setattr(video, "SECONDES_MESUREES", ampute)
    assert video.secondes_loueur("rapide", la_plus_longue) is None, (
        "la loi chiffre %s s alors qu'aucune mesure ne va jusque-la"
        % la_plus_longue)
    assert video.prix_estime("rapide", la_plus_longue) is None
    # ... et elle parle toujours entre les mesures qui restent.
    assert video.secondes_loueur("rapide", mesurees[0]) is not None


def test_SANS_carte_le_menu_ne_dit_pas_que_le_clip_est_TROP_LONG(sandbox, monkeypatch):
    """Une machine sans carte n'a pas une carte trop petite.

    Vu le 21/09/2026 en imprimant le menu d'une machine sans carte : la page
    annoncait << 1 seconde -- trop long pour votre carte >>. Un clip d'une
    seconde n'est trop long pour rien ; la phrase disait au debutant que sa
    machine etait juste un peu faible, quand elle n'a pas de carte du tout.

    Les deux etats tenaient dans un seul `None`, d'ou la confusion. Ce test
    juge les DEUX cas, sans quoi il laisserait remettre la meme phrase partout.
    """
    video = sandbox.video
    sans = {"vue": False, "motif": "pas de carte", "totale_mo": 0, "libre_mo": 0,
            "marge_mo": 1024, "nom": ""}
    monkeypatch.setattr(sandbox.ou_calculer.gpu_local, "releve", lambda: sans)
    menu = video.options_duree_html()
    assert "trop long pour votre carte" not in menu, (
        "sans carte, aucune duree n'est << trop longue >> : %s" % menu[:200])
    assert "pas de carte" in menu

    petite = {"vue": True, "nom": "carte de portable", "totale_mo": 8192,
              "libre_mo": 8192, "marge_mo": 1024, "motif": ""}
    monkeypatch.setattr(sandbox.ou_calculer.gpu_local, "releve", lambda: petite)
    menu = video.options_duree_html()
    tient_ici = [o for o in video.durees_offertes(8192) if o["tient_ici"]]
    assert not tient_ici, (
        "ce cas a ete choisi parce qu'AUCUNE duree n'y tient ; si le modele a "
        "maigri, prendre une carte plus petite plutot que d'affaiblir le test")
    assert "trop petite pour ce mod\u00e8le" in menu, (
        "si meme 17 images debordent, c'est le MODELE qui ne rentre pas : dire "
        "<< trop long >> envoie le debutant essayer plus court en boucle")
    assert "trop long pour votre carte" not in menu

    moyenne = {"vue": True, "nom": "carte de 16 Go", "totale_mo": 16384,
               "libre_mo": 16384, "marge_mo": 1024, "motif": ""}
    monkeypatch.setattr(sandbox.ou_calculer.gpu_local, "releve", lambda: moyenne)
    menu = video.options_duree_html()
    assert "sur votre carte" in menu, "16 Go porte les clips courts"
    assert "trop long pour votre carte" in menu, (
        "quand le court tient et le long deborde, la DUREE est bien en cause")


def test_un_prix_montre_en_francais_prend_une_VIRGULE(sandbox, monkeypatch):
    """<< environ 0.06 $ >> etait ecrit avec un point. Page francaise."""
    video = sandbox.video
    sans = {"vue": False, "motif": "pas de carte", "totale_mo": 0, "libre_mo": 0,
            "marge_mo": 1024, "nom": ""}
    monkeypatch.setattr(sandbox.ou_calculer.gpu_local, "releve", lambda: sans)
    menu = video.options_duree_html()
    assert " $" in menu, "le menu doit chiffrer la location"
    import re
    assert not re.search(r"\d\.\d+ \$", menu), (
        "un prix a point decimal dans une page francaise : %s" % menu[:300])


def test_ouvrir_le_menu_ne_sonde_la_carte_QU_UNE_fois(sandbox, monkeypatch):
    """Une ouverture de page = une sonde, pas deux.

    Ce test compte des APPELS et non des phrases, parce que la deuxieme sonde
    rendait la meme reponse que la premiere : la page affichait exactement la
    meme chose avec une sonde ou avec deux, et rien d'autre n'aurait vu le
    doublon revenir. Sans carte est le cas qui doublait -- c'est aussi le cas
    le plus courant du produit.
    """
    video = sandbox.video
    sans = {"vue": False, "motif": "pas de carte", "totale_mo": 0, "libre_mo": 0,
            "marge_mo": 1024, "nom": ""}
    appels = []

    def compter():
        appels.append(1)
        return sans

    monkeypatch.setattr(sandbox.ou_calculer.gpu_local, "releve", compter)
    video.options_duree_html()
    assert len(appels) == 1, (
        "%d sondes pour une ouverture de page ; `durees_offertes` doit "
        "recevoir le verdict au lieu de resonder" % len(appels))


def test_la_page_ne_dit_pas_que_le_modele_est_CHARGE_une_seule_fois(sandbox):
    """<< Telecharge une fois puis garde en cache >> etait vrai et trompeur.

    Le client comprenait que le premier clip paie le modele et que les suivants
    n'y pensent plus. Mesure du 21/09/2026, meme clip relance sur la meme
    carte : la charge tombe de 382 s a 120 s -- les 75 Go ne redescendent donc
    pas, mais les remonter dans la carte coute 120 s A CHAQUE CLIP, un quart de
    la facture d'un clip d'une seconde.

    Ce test juge la page rendue, pas une constante : c'est la phrase que le
    client lit qui doit rester juste.
    """
    page = sandbox.video.PAGE_HTML
    assert "gard\u00e9 en cache" not in page, (
        "la page redit que le modele est mis en cache une fois pour toutes")
    assert "recharg\u00e9 \u00e0 chaque clip" in page, (
        "la page doit dire que le modele est recharge a chaque clip")


# --- Un clip qui meurt en manque de memoire le DIT (23/09/2026) ---
# Travail `4e92505679ad4ecc8fd8119c65374063` : le soigne 5 s est mort en
# `torch.OutOfMemoryError` et la page n'a montre que « Échec — voir le
# journal » au-dessus d'une trace Python.

TRACE_OOM = ("torch.OutOfMemoryError: CUDA out of memory. Tried to allocate "
             "1.44 GiB. GPU 0 has a total capacity of 39.49 GiB")


def _echec(sandbox, stderr, maison=False, error=None, voisins=None):
    jid = "e" * 32
    job = {"id": jid, "status": "failed", "artifacts": [], "stderr": stderr,
           "video": {"maison": maison}}
    if error:
        job["error"] = error
    if voisins is not None:
        job["voisins_a_l_echec"] = voisins
    sandbox.write_job(jid, job)
    r = TestClient(sandbox.app, base_url=LOCAL).get("/video/jobs/" + jid, headers=CLE)
    assert r.status_code == 200
    return r.json()


def test_un_manque_de_memoire_LOUE_recoit_une_phrase_et_dit_que_c_est_paye(sandbox):
    corps = _echec(sandbox, TRACE_OOM)
    assert "manqué de mémoire" in corps["message"]
    assert "durée plus courte" in corps["message"]
    assert "dépense du mois" in corps["message"]
    # La trace reste la, pour qui veut le detail.
    assert corps["stderr"] == TRACE_OOM


def test_un_manque_de_memoire_A_LA_MAISON_ne_parle_pas_de_depense(sandbox):
    corps = _echec(sandbox, TRACE_OOM, maison=True)
    assert "manqué de mémoire" in corps["message"]
    assert "dépense" not in corps["message"]


# --- ... et ne dit pas « trop lourd » quand un voisin a pris la place (point 15.5) ---
# La sonde du depart ne voit pas un julia lance PENDANT le calcul ; rien ne
# l'empeche et on ne l'arrete jamais. Le clip meurt alors en manque de memoire
# sans etre trop lourd : dire « durée plus courte » enverrait le client refaire
# plus court un clip qui passait.

def test_un_voisin_sur_la_carte_a_l_echec_est_nomme_au_lieu_de_trop_lourd(sandbox):
    corps = _echec(sandbox, TRACE_OOM, maison=True, voisins=["julia.exe (PID 64216)"])
    assert "julia.exe (PID 64216)" in corps["message"]
    assert "Relancez le clip quand il aura fini" in corps["message"]
    assert "trop lourd" not in corps["message"]
    assert "dépense" not in corps["message"]


def test_sans_voisin_ou_sans_releve_le_message_reste_trop_lourd(sandbox):
    for voisins in ([], None):
        corps = _echec(sandbox, TRACE_OOM, maison=True, voisins=voisins)
        assert "trop lourd" in corps["message"], voisins


def test_un_voisin_ne_change_rien_a_un_clip_loue(sandbox):
    # Chez le loueur, la carte n'est pas celle de julia.
    corps = _echec(sandbox, TRACE_OOM, maison=False, voisins=["julia.exe (PID 1)"])
    assert "julia" not in corps["message"]
    assert "dépense du mois" in corps["message"]


def test_le_voisin_est_releve_a_la_seconde_de_l_echec(sandbox, monkeypatch):
    """Releve a l'affichage, il serait peut-etre deja parti : on le garde avec
    le travail, au moment ou le calcul echoue."""
    jid = "f" * 32
    sandbox.write_job(jid, {"id": jid, "status": "queued", "artifacts": [],
                            "video": {"maison": True}})
    monkeypatch.setattr(sandbox, "maison_execute",
                        lambda *_a, **_k: {"exit_code": 1, "stderr": TRACE_OOM})
    monkeypatch.setattr(sandbox.gpu_local, "voisins", lambda: ["julia.exe (PID 64216)"])
    sandbox.run_video(jid, "print()", "L4", "maison")
    job = sandbox.read_job(jid)
    assert job["status"] == "failed"
    assert job["voisins_a_l_echec"] == ["julia.exe (PID 64216)"]


def test_un_clip_reussi_ne_releve_personne(sandbox, monkeypatch):
    jid = "a" * 32
    sandbox.write_job(jid, {"id": jid, "status": "queued", "artifacts": [],
                            "video": {"maison": True}})
    monkeypatch.setattr(sandbox, "maison_execute", lambda *_a, **_k: {"exit_code": 0})
    monkeypatch.setattr(sandbox.gpu_local, "voisins",
                        lambda: pytest.fail("releve inutile sur un succes"))
    sandbox.run_video(jid, "print()", "L4", "maison")
    assert "voisins_a_l_echec" not in sandbox.read_job(jid)


def test_une_cause_inconnue_garde_le_journal_et_n_invente_rien(sandbox):
    assert _echec(sandbox, "RuntimeError: autre chose")["message"] == ""


def test_un_message_deja_ecrit_n_est_pas_remplace(sandbox):
    corps = _echec(sandbox, TRACE_OOM, error="Arrêté à votre demande.")
    assert corps["message"] == "Arrêté à votre demande."


def test_la_page_n_a_plus_de_menu_de_qualite_et_loue_en_rapide(sandbox):
    """La qualite soignee retiree le 23/09/2026, le menu n'avait plus qu'un
    choix : il est parti. La page envoie la qualite du serveur, posee a
    l'affichage, et aucun marqueur ne reste en clair."""
    page = TestClient(sandbox.app, base_url=LOCAL).get("/video", headers=CLE).text
    assert 'id="qualite"' not in page
    assert 'const QUALITE_LOUEE = "%s";' % sandbox.video.QUALITE_LOUEE_PAR_DEFAUT in page
    assert "__QUALITE_LOUEE__" not in page
    assert "qualite: QUALITE_LOUEE" in page


# --- 7. Kaggle : lent, donc dit AVANT, et lance en tache de fond (24/09) -------

def test_le_temps_kaggle_est_servi_mesure_pour_1_s_estime_ailleurs(studio):
    """24/09 : 10 min 23 s pour 1 s sur Kaggle (T4, float16, `639ae707`). Le
    proprietaire : << on dit lent, a faire en tache de fond ; on peut extrapoler
    la duree max et son temps >>. Seul 1 s est mesure ; le reste est estime, et
    le plus long clip offert doit finir avant que Kaggle arrete le carnet."""
    video = studio.video
    client = TestClient(studio.app, base_url=LOCAL)
    temps = client.get("/video/budget", headers=CLE).json()["kaggle_temps"]
    assert set(temps) == set(video.DUREES)
    assert temps["1"] == {"secondes": 623, "mesure": True, "tient": True}
    autres = [temps[d] for d in video.DUREES if d != "1"]
    assert autres and not any(t["mesure"] for t in autres)
    # Plus long clip, plus long temps -- et jamais moins que le clip mesure.
    suite = [temps[d]["secondes"] for d in sorted(video.DUREES, key=int)]
    assert suite == sorted(suite) and suite[0] == 623
    plus_long = temps[str(max(map(int, video.DUREES)))]
    assert plus_long["tient"] and plus_long["secondes"] < video.KAGGLE_LIMITE_S
    # Le rapport vient des deux mesures a 17 images, pas d'un chiffre pose.
    assert round(video.RAPPORT_T4_L4, 2) == 2.98
