"""Dialogue : un script a plusieurs voix rendu par FireRedTTS-2, sur Modal.

Aucun appel reseau : ni Modal, ni Hugging Face, ni le GPU ne sont touches. Ce
qui est verifie ici, c'est ce qui se decide AVANT de lancer -- demande bornee,
plafond, fichiers telecharges, licence affichee -- et que le script envoye au
GPU est du Python valide.

Rien dans ce fichier ne dit que le modele SONNE bien, ni meme qu'il parle
francais : personne ne l'a jamais entendu. Ces tests gardent les decisions, pas
la qualite du son.
"""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

CLE = {"Authorization": "Bearer cle-sandbox-de-test"}
LOCAL = "http://127.0.0.1:8020"
DIALOGUE = "[S1]Tu as vu ça ?\n[S2]Non, raconte.\n[S1]Deux voix, un seul fichier."


@pytest.fixture
def di(sandbox, monkeypatch, tmp_path):
    """Le module dialogue, avec un compteur de depense jetable."""
    module = sandbox.dialogue
    monkeypatch.setattr(module, "BUDGET_FICHIER", tmp_path / "dialogue-budget.json")
    return module


# --- Ce qui est refuse AVANT de payer la carte --------------------------------

def test_demande_bornee(di):
    with pytest.raises(ValueError):
        di.preparer({"texte": "   "})
    with pytest.raises(ValueError):
        di.preparer({"texte": "[S1]" + "la " * 4000})

    plan = di.preparer({"texte": DIALOGUE})
    d = plan["demande"]
    assert d["repliques"] == ["[S1]Tu as vu ça ?", "[S2]Non, raconte.",
                              "[S1]Deux voix, un seul fichier."]
    assert d["locuteurs"] == [1, 2]
    assert d["revision"] == di.MODELE["revision"]
    assert plan["resume_public"]["repliques"] == 3


def test_une_ligne_sans_balise_est_refusee_avant_de_lancer(di):
    """Sans balise, le modele ne sait pas qui parle : le travail echouerait APRES
    avoir paye le telechargement des poids et le chargement du modele. On refuse
    au moment ou ca ne coute rien, et on dit QUELLE ligne et a quoi ca ressemble.
    """
    with pytest.raises(ValueError) as exc:
        di.preparer({"texte": "[S1]Bonjour.\nEt moi je reponds sans balise."})
    message = str(exc.value)
    assert "Ligne 2" in message, "l'erreur ne dit pas quelle ligne corriger"
    assert "[S1]" in message, "l'erreur ne montre pas la forme attendue"


def test_un_locuteur_hors_des_quatre_est_refuse(di):
    """Les auteurs annoncent quatre locuteurs au plus. [S7] passerait la balise
    mais pas le modele."""
    with pytest.raises(ValueError) as exc:
        di.preparer({"texte": "[S1]Salut.\n[S7]Je n'existe pas."})
    assert "[S7]" in str(exc.value)
    assert str(di.LOCUTEURS_MAX) in str(exc.value)


def test_une_replique_vide_est_refusee(di):
    with pytest.raises(ValueError) as exc:
        di.preparer({"texte": "[S1]Bonjour.\n[S2]   "})
    assert "vide" in str(exc.value)


def test_la_balise_est_recollee_au_texte(di):
    """Les exemples des auteurs collent la balise au texte, SANS espace :
    « [S1]那可能说对对... ». Une espace derriere la balise est une frappe
    naturelle en francais ; le Studio la retire plutot que de parier sur la
    tolerance du modele, qu'il n'a pas mesuree.
    """
    d = di.preparer({"texte": "[S1]   Avec des espaces.\n[S2]\tEt une tabulation."})["demande"]
    assert d["repliques"] == ["[S1]Avec des espaces.", "[S2]Et une tabulation."]
    for replique in d["repliques"]:
        assert "] " not in replique, "une espace subsiste apres la balise"


# --- Ce qui part sur la machine, et ce qui n'en part pas ----------------------

def test_le_mode_dialogue_ne_telecharge_pas_le_modele_du_monologue(di):
    """8,27 Go payes au tarif de la carte pour un fichier jamais ouvert.

    La source choisit le poids selon le mode :
        if gen_type == "monologue": ... "llm_pretrain.pt"
        else:                       ... "llm_posttrain.pt"
    Le mode dialogue ne lit donc jamais llm_pretrain.pt. Comme le compteur
    facture le temps d'horloge, un telechargement inutile se paie au prix du GPU.
    """
    fichiers = di.preparer({"texte": DIALOGUE})["demande"]["fichiers"]
    assert "llm_posttrain.pt" in fichiers, "le poids du mode dialogue n'est pas telecharge"
    assert "llm_pretrain.pt" not in fichiers, (
        "llm_pretrain.pt (8,27 Go) sert au mode monologue et n'est jamais lu ici : "
        "le telecharger serait payer 8,27 Go au tarif de la carte pour rien."
    )
    # Sans le tokenizer, le modele ne charge pas du tout.
    assert any(n.startswith("Qwen2.5-1.5B") for n in fichiers)


def test_torchtune_part_bien_dans_l_image(di):
    """Defaut de raisonnement, 17/09, rattrape de justesse.

    Une premiere lecture s'etait arretee a fireredtts2/llm/llm.py, qui ne fait
    que re-exporter FLAVORS, et avait conclu « torchtune n'est pas necessaire ».
    Le fichier d'en dessous, modules.py, fait
    « from torchtune.models.qwen2 import qwen2 » et construit par la TOUS les
    transformeurs. Sans torchtune dans l'image, le travail meurt a l'import,
    apres le telechargement des poids -- c'est-a-dire une fois paye.
    """
    assert "torchtune" in di.PAQUETS_MODAL, (
        "torchtune manque : fireredtts2/llm/modules.py en a besoin pour construire "
        "les transformeurs, et l'echec arriverait apres le telechargement des poids."
    )


def test_huggingface_hub_part_bien_dans_l_image(di):
    """Le requirements.txt de l'amont est INCOMPLET : il oublie huggingface_hub.

    llm.py fait « from huggingface_hub import PyTorchModelHubMixin », et le
    script s'en sert aussi pour snapshot_download. Recopier le requirements.txt
    de l'amont a la lettre donnerait une image qui tombe au premier import.
    """
    assert "huggingface_hub" in di.PAQUETS_MODAL


def test_les_outils_de_developpement_ne_partent_pas(di):
    """gradio, optuna et tensorboard sont au requirements.txt de l'amont et ne
    servent qu'a la demonstration et au developpement. Les embarquer alourdirait
    l'image sans que l'inference les appelle jamais."""
    for inutile in ("gradio", "optuna", "tensorboard"):
        assert not any(p.startswith(inutile) for p in di.PAQUETS_MODAL), (
            inutile + " part dans l'image alors que l'inference ne l'appelle pas."
        )


def test_le_paquet_a_besoin_de_git(di):
    """Le code s'installe depuis GitHub : sans git dans l'image, pip echoue."""
    assert any(p.startswith("git+") for p in di.PAQUETS_MODAL)
    assert "git" in di.APT_MODAL


def test_script_est_du_python_valide(di):
    """Une faute de frappe dans le script ne se verrait qu'apres le chargement du
    modele sur une carte louee, c'est-a-dire une fois paye."""
    script = di.construire_script(di.preparer({"texte": "[S1]Accentué « é ».\n[S2]Oui."})["demande"])
    assert "__DEMANDE__" not in script
    compile(script, "dialogue_job.py", "exec")
    # Le mode compte : gen_type="dialogue" est ce qui choisit llm_posttrain.pt.
    assert 'gen_type="dialogue"' in script


# --- Le compteur de depense ---------------------------------------------------

def test_prix_compte_la_memoire(di, monkeypatch):
    monkeypatch.setenv("MODAL_CPU", "1.0")
    attendu = 0.000222 + 0.0000131 + 0.00000222 * di.MEMOIRE_MB / 1024
    assert di.prix_seconde("L4") == pytest.approx(attendu)
    # Carte inconnue : comptee au prix de la plus chere, jamais moins.
    assert di.prix_seconde("X9") > di.prix_seconde("L40S") - 1e-12


def test_les_trois_tables_de_prix_ne_divergent_pas(sandbox, di):
    """chanson.py, video.py et dialogue.py recopient les MEMES prix Modal.

    Le 17/09, deux de ces tables portaient deja deux dates de releve
    differentes -- 15/09 et 09/09 : une table relue, l'autre oubliee, et rien ne
    le signalait. Une troisieme copie multiplie l'occasion de diverger.

    Ce controle ne verifie pas que les prix sont JUSTES -- seule une lecture de
    modal.com/pricing le dit -- mais qu'une lecture faite d'un cote a bien ete
    reportee des deux autres.
    """
    for autre in (sandbox.chanson, sandbox.video):
        communes = sorted(set(di.PRIX_GPU_USD_S) & set(autre.PRIX_GPU_USD_S))
        assert communes, "les tables n'ont plus aucune carte en commun"
        ecarts = {c: (di.PRIX_GPU_USD_S[c], autre.PRIX_GPU_USD_S[c])
                  for c in communes if di.PRIX_GPU_USD_S[c] != autre.PRIX_GPU_USD_S[c]}
        assert not ecarts, (
            "dialogue.py compte la meme carte a un autre prix : %s. Une des "
            "lectures n'a pas ete reportee." % ecarts)
        assert di.PRIX_CPU_USD_S == autre.PRIX_CPU_USD_S, "prix du coeur divergent"
        assert di.PRIX_MEMOIRE_USD_S == autre.PRIX_MEMOIRE_USD_S, "prix de la memoire divergent"


def test_le_compteur_est_separe_de_celui_de_la_chanson(sandbox, di):
    """Trois plafonds etanches : 5 + 20 + 5 = exactement le credit declare.

    Un compteur partage ferait qu'un dialogue mange le budget des chansons sans
    que rien ne le dise. Des fichiers distincts, c'est ce qui rend les plafonds
    reellement separes.
    """
    assert di.BUDGET_FICHIER != sandbox.chanson.BUDGET_FICHIER
    assert "dialogue" in di.BUDGET_FICHIER.name


def test_plafond_refuse_avant_de_lancer(sandbox, di, monkeypatch):
    lances = []
    monkeypatch.setattr(sandbox, "modal_configured", lambda: True)
    monkeypatch.setattr(sandbox, "run_dialogue", lambda *args: lances.append(args))
    di.budget_ecrire(0, di.BUDGET_MENSUEL_USD - 0.01, 3)

    client = TestClient(sandbox.app, base_url=LOCAL)
    r = client.post("/dialogue/creer", headers=CLE, json={"texte": DIALOGUE})
    assert r.status_code == 429
    assert lances == [], "le travail est parti alors que le plafond etait atteint"

    di.budget_ecrire(0, 0, 0)
    r = client.post("/dialogue/creer", headers=CLE, json={"texte": DIALOGUE})
    assert r.status_code == 200
    for _ in range(50):
        if lances:
            break
        time.sleep(0.02)
    assert len(lances) == 1


def test_modal_absent_503(sandbox, di):
    r = TestClient(sandbox.app, base_url=LOCAL).post(
        "/dialogue/creer", headers=CLE, json={"texte": DIALOGUE})
    assert r.status_code == 503


def test_texte_invalide_refuse_par_la_route(sandbox, di):
    r = TestClient(sandbox.app, base_url=LOCAL).post(
        "/dialogue/creer", headers=CLE, json={"texte": "pas de balise ici"})
    assert r.status_code == 400
    assert "[S1]" in r.json()["detail"]


def test_echec_modal_encaisse_quand_meme(sandbox, di, monkeypatch):
    """Une machine qui tombe a quand meme tourne : le temps se paie."""
    def en_panne(*args, **kwargs):
        raise sandbox.BackendUnavailable("Modal unavailable: essai")

    monkeypatch.setattr(sandbox, "modal_execute", en_panne)
    jid = "c" * 32
    sandbox.write_job(jid, {"id": jid, "status": "queued", "artifacts": []})
    sandbox.run_dialogue(jid, "print(1)")
    job = sandbox.read_job(jid)
    assert job["status"] == "failed"
    assert di.budget_lire()["dialogues"] == 1
    assert job["budget"]["dialogues"] == 1


# --- La page, et ce qu'elle doit avouer ---------------------------------------

def test_page_etat_et_jeton(sandbox, di):
    client = TestClient(sandbox.app, base_url=LOCAL)
    page = client.get("/dialogue")
    assert page.status_code == 200 and "cle-sandbox-de-test" in page.text
    assert client.get("/dialogue/etat").status_code == 401
    etat = client.get("/dialogue/etat", headers=CLE).json()
    assert etat["modele"]["licence"] == "Apache 2.0"
    assert etat["cout_max_modal_usd"] > 0

    jid = "1" * 32
    sandbox.write_job(jid, {"id": jid, "status": "succeeded", "artifacts": []})
    assert client.get(f"/dialogue/jobs/{jid}/fichier?cle=faux").status_code == 401
    bon = sandbox.jeton_dialogue(jid)
    # Un laissez-passer par route : celui d'une chanson ne doit pas ouvrir un
    # dialogue, meme travail.
    assert bon != sandbox.jeton_chanson(jid)
    assert bon != sandbox.jeton_video(jid)
    assert client.get(f"/dialogue/jobs/{jid}/fichier?cle={bon}").status_code == 404


def test_la_licence_et_la_reserve_des_auteurs_voyagent_ensemble(sandbox, di):
    """Apache 2.0 n'interdit rien ; les auteurs ecrivent pourtant que c'est
    « intended solely for academic research purposes ».

    Defaut de la premiere redaction du 17/09, corrige le jour meme : l'exception
    au gel n'avait retenu que la licence -- « usage commercial permis, aucune
    restriction a afficher » -- parce que la phrase des auteurs n'avait pas
    encore ete lue. Ne garder que celle des deux qui arrange, c'est fabriquer
    une autorisation. La page affiche les DEUX, la ou le modele se choisit.
    """
    etat = TestClient(sandbox.app, base_url=LOCAL).get("/dialogue/etat", headers=CLE).json()
    assert "academic research" in etat["modele"]["reserve_auteurs"], (
        "la reserve des auteurs ne voyage pas avec la licence"
    )

    public = di.preparer({"texte": DIALOGUE})["resume_public"]["licence"]
    assert "Apache 2.0" in public
    assert "academic research" in public, (
        "la fiche du travail ne garde que la licence permissive : elle laisse "
        "croire a une autorisation que les auteurs ne donnent pas."
    )

    page = TestClient(sandbox.app, base_url=LOCAL).get("/dialogue").text
    assert "reserve_auteurs" in page, (
        "la page n'affiche pas la reserve des auteurs a l'endroit du choix."
    )


def test_la_page_avoue_que_les_voix_sont_inventees(sandbox, di):
    """Aucun son de reference n'est envoye : generate_dialogue accepte
    prompt_wav_list, on ne le remplit pas. Le modele invente donc les voix, et
    rien ne garantit qu'elles soient les memes au rendu suivant. Un utilisateur
    qui relance pour corriger une phrase doit le savoir AVANT."""
    page = TestClient(sandbox.app, base_url=LOCAL).get("/dialogue").text
    assert "inventent" in page or "invente" in page, (
        "la page ne dit pas que les voix changent d'un rendu a l'autre."
    )
    assert di.preparer({"texte": DIALOGUE})["resume_public"]["voix_inventees"] is True


def test_la_page_avoue_que_le_francais_n_est_mesure_par_personne(sandbox, di):
    """Le modele annonce sept langues dont le francais. PodEval, SoulX-Podcast,
    le tableau des auteurs et celui de MOSS-TTSD portent TOUS sur le mandarin et
    l'anglais. « Supporte le francais » est une annonce de capacite sans un seul
    chiffre derriere, et personne n'a encore ecoute."""
    page = TestClient(sandbox.app, base_url=LOCAL).get("/dialogue").text
    assert "français" in page
    assert "écouté" in page, (
        "la page laisse croire que quelqu'un a verifie le rendu en francais."
    )


def test_la_revision_du_code_n_est_pas_presentee_comme_epinglee(sandbox, di):
    """Les POIDS sont epingles a un commit -- ce sont des pickles, torch.load les
    execute, l'epinglage est une barriere de securite autant qu'une garantie de
    reproductibilite. Le CODE vient de GitHub et son commit n'a jamais ete
    releve. Tant que c'est vrai, il faut le dire plutot que d'inventer un SHA
    plausible."""
    assert di.MODELE["revision"] and len(di.MODELE["revision"]) == 40, (
        "les poids ne sont plus epingles a un commit complet"
    )
    if di.MODELE["code_revision"] is None:
        public = di.preparer({"texte": DIALOGUE})["resume_public"]
        assert public["code_revision_epinglee"] is False
        page = TestClient(sandbox.app, base_url=LOCAL).get("/dialogue").text
        assert "code_revision" in page, (
            "la page ne previent pas que le code n'est pas epingle."
        )


def test_la_page_offre_un_arret_durgence_hors_du_bloc_reecrit(sandbox, di):
    """Meme piege que /chanson : suivre() reecrit etat.innerHTML toutes les 5 s.
    Un bouton pose DANS #etat serait detruit et recree a chaque tour, et l'etat
    « Arret demande... » disparaitrait sous les doigts de l'utilisateur."""
    page = TestClient(sandbox.app, base_url=LOCAL).get("/dialogue").text
    assert 'id="arreter"' in page, "la page n'offre aucun arret d'urgence"

    bloc_etat = page[page.index('<div id="etat"'):]
    bloc_etat = bloc_etat[:bloc_etat.index("</div>")]
    assert 'id="arreter"' not in bloc_etat, (
        "le bouton est dans #etat, que suivre() reecrit toutes les 5 s."
    )
    assert "/arreter" in page, "la page ne sait pas appeler la route d'arret"


def test_la_page_distingue_un_arret_d_une_panne(sandbox, di):
    """Un arret voulu ne doit pas s'afficher en rouge sous le mot « Échec ».
    Defaut reel constate sur /chanson le 17/09 : la PREUVE que l'arret avait
    reussi s'affichait comme un plantage, et en anglais."""
    page = TestClient(sandbox.app, base_url=LOCAL).get("/dialogue").text
    assert 'j.status === "cancelled"' in page
    assert page.index('j.status === "cancelled"') < page.index("✖ Échec"), (
        "la branche d'arret doit etre examinee AVANT celle d'echec."
    )


def test_la_page_ne_propose_aucun_endroit_non_verifie(sandbox, di):
    """/chanson offre Kaggle et Colab parce que son chemin T4 a ete essaye en
    vrai le 15/09. Ici rien n'a jamais tourne nulle part : proposer un endroit
    gratuit non verifie reviendrait a vendre un essai dont personne ne connait
    le resultat."""
    page = TestClient(sandbox.app, base_url=LOCAL).get("/dialogue").text
    assert "/dialogue/colab" not in page
    assert '"kaggle"' not in page, (
        "la page propose un endroit sur lequel ce modele n'a jamais tourne."
    )
