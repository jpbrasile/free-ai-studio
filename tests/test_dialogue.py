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

import ast
import time

import pytest
from fastapi.testclient import TestClient

CLE = {"Authorization": "Bearer cle-sandbox-de-test"}
LOCAL = "http://127.0.0.1:8020"
# Une adresse qui n'est PAS localhost : c'est ce qui declenche la garde de
# contexte partage. Meme valeur que dans test_chanson.py, pour que les deux
# suites parlent du meme cas.
RESEAU = "http://192.168.1.20:8020"
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
    noms = {p.split("==")[0] for p in di.PAQUETS_MODAL}
    assert "torchtune" in noms, (
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


def test_le_requirements_de_l_amont_est_execute_tel_quel(di):
    """RENVERSEMENT ASSUME du 17/09/2026, avec sa raison.

    Ce test interdisait gradio, optuna et tensorboard dans l'image, au motif
    qu'ils ne servent qu'a la demonstration et au developpement. C'etait sans
    doute vrai -- mais ce n'etait qu'un raisonnement, et aucune mesure ne le
    soutenait, alors que DEUX lancements payes ont ete perdus ce jour-la a
    s'ecarter de la procedure documentee. Les auteurs ecrivent
    « pip install -r requirements.txt » : le Studio l'execute tel quel.

    PAQUETS_MODAL ne garde donc que ce que leur fichier ne peut pas donner : ce
    qu'il OUBLIE et ce qu'il SOUS-SPECIFIE. Un doublon ici serait une seconde
    liste a maintenir, c'est-a-dire la derive a recommencer.
    """
    assert any("requirements.txt" in c for c in di.COMMANDES_MODAL), (
        "le requirements.txt des auteurs n'est plus execute : le Studio est "
        "retourne a une liste maison, ce qui a deja coute deux lancements."
    )
    for double in ("transformers", "einops", "librosa", "gradio", "optuna"):
        assert not any(p.split("==")[0] == double for p in di.PAQUETS_MODAL), (
            double + " est liste a la main alors que le requirements.txt de "
            "l'amont le fournit : deux listes a maintenir au lieu d'une."
        )


def test_le_code_ne_s_installe_pas_par_pip_depuis_git(di):
    """LA PANNE DU 17/09/2026, ET LE GARDE QUI L'EMPECHE DE REVENIR.

    « pip install git+https://github.com/FireRedTeam/FireRedTTS2.git » parait la
    facon naturelle d'installer ce code. Elle est fausse, et elle se paie au
    tarif de la carte :

        ModuleNotFoundError: No module named 'fireredtts2.utils'

    leve APRES le telechargement des poids. Leur setup.py tient en une ligne --
    setup(name="fireredtts2", version="0.1", packages=find_packages()) -- et
    fireredtts2/utils/ ne contient que spliter.py, SANS __init__.py.
    find_packages() ne retient que les dossiers qui en ont un : l'installation
    livre un paquet ampute. Releve sur le depot : llm/ et codec/ ont le leur,
    utils/ non, donc le trou est unique.

    MECANISME MESURE, pas raisonne (sonde locale, Python 3.11.5, sur un paquet
    fabrique imitant la structure, avec un sous-paquet TEMOIN muni de son
    __init__.py) :
        pip install .     -> temoin OK, dossier sans __init__.py ECHEC
                             (ModuleNotFoundError, meme forme qu'en production)
        pip install -e .  -> les deux OK
    Le temoin passe dans les deux cas : la sonde discrimine, elle n'est pas
    cassee. NON VERIFIE en Python 3.12, la version de l'image Modal.

    Remettre git+ ici rejouerait la panne, qui ne se montre qu'une fois paye.
    """
    assert not any(p.startswith("git+") for p in di.PAQUETS_MODAL), (
        "le code repasse par pip+git : find_packages() laissera fireredtts2.utils "
        "de cote et le travail mourra a l'import, apres le telechargement des poids."
    )
    assert "git" in di.APT_MODAL, "sans git dans l'image, le clone echoue."


def test_les_commandes_reproduisent_la_procedure_des_auteurs(di):
    """La procedure documentee, et non une reconstruction a partir des imports.

    Les gestes du README : cloner, se placer sur une revision, installer en
    EDITABLE, puis poser le requirements.txt. Le « -e » est le point qui compte :
    c'est lui qui laisse fireredtts2/utils s'importer malgre l'absence
    d'__init__.py.
    """
    jointes = " ; ".join(di.COMMANDES_MODAL)
    assert "git clone" in jointes, "le depot n'est plus clone."
    assert "pip install -e ." in jointes, (
        "l'installation n'est plus en editable : sans -e, fireredtts2.utils "
        "disparait de l'image et le travail meurt a l'import, une fois paye."
    )
    assert "-r requirements.txt" in jointes, (
        "le requirements.txt des auteurs n'est plus execute."
    )


def test_les_epingles_ne_sont_pas_reposees_apres_le_requirements(di):
    """L'ordre suffit, et c'est MESURE -- pas besoin de re-epingler par prudence.

    Sonde locale : packaging==23.0 pose, puis un requirements.txt demandant
    « packaging » nu. pip repond « Requirement already satisfied ... (23.0) » et
    ne remonte rien ; il ne met a niveau que sur -U. Les epingles vivent donc
    dans PAQUETS_MODAL, pose AVANT les commandes, et nulle part ailleurs.

    Une re-pose apres coup serait du bruit defensif masquant une question non
    tranchee. Si ce test tombe, c'est qu'on a doute de l'ordre sans le remesurer.
    """
    epingles = dict(p.split("==") for p in di.PAQUETS_MODAL if "==" in p)
    assert epingles.get("torchao") == "0.17.0", "l'epingle a quitte PAQUETS_MODAL."
    for commande in di.COMMANDES_MODAL:
        assert "torchao" not in commande, (
            "torchao est re-epingle dans les commandes : soit l'ordre ne protege "
            "plus l'epingle et il faut le remesurer, soit c'est une precaution "
            "inutile qui cache la vraie garantie."
        )


def test_les_commandes_partent_vraiment_a_modal(sandbox, di, monkeypatch):
    """Une constante definie et jamais transmise serait un silence paye.

    COMMANDES_MODAL peut etre parfaite et ne jamais quitter le module : c'est
    app.py qui doit la passer a modal_execute. Ce test attrape les arguments
    reels de l'appel, puis fait echouer le fournisseur pour ne dependre d'aucun
    contrat de sortie.
    """
    recu = {}

    def espion(*args, **kwargs):
        recu.update(kwargs)
        raise sandbox.BackendUnavailable("capture")

    monkeypatch.setattr(sandbox, "modal_execute", espion)
    jid = "d" * 32
    sandbox.write_job(jid, {"id": jid, "status": "queued", "artifacts": []})
    sandbox.run_dialogue(jid, "print(1)", "modal")
    assert recu.get("commandes") == di.COMMANDES_MODAL, (
        "les commandes d'installation n'arrivent pas jusqu'a Modal : l'image se "
        "construirait sans le code, et l'echec n'apparaitrait que sur la carte."
    )
    assert recu.get("apt") == di.APT_MODAL, "git ne part pas dans l'image."


def test_script_est_du_python_valide(di):
    """Une faute de frappe dans le script ne se verrait qu'apres le chargement du
    modele sur une carte louee, c'est-a-dire une fois paye."""
    script = di.construire_script(di.preparer({"texte": "[S1]Accentué « é ».\n[S2]Oui."})["demande"])
    assert "__DEMANDE__" not in script
    compile(script, "dialogue_job.py", "exec")
    # Le mode compte : gen_type="dialogue" est ce qui choisit llm_posttrain.pt.
    assert 'gen_type="dialogue"' in script


def test_le_script_kaggle_met_le_depot_sur_le_chemin_d_import(di):
    """DEFAUT REEL du 17/09/2026, paye par un travail Kaggle mort a 83 s.

    Le script clonait le depot des auteurs, l'installait par << pip install -e >>
    -- code de retour 0, pas une plainte -- puis importait fireredtts2 et mourait
    sur ModuleNotFoundError, les 12,6 Go de poids deja telecharges.

    CAUSE, reproduite hors Kaggle AVANT d'etre corrigee, sur un paquet d'essai de
    la meme forme : une installation editable ne prend pas effet dans le
    processus qui la lance. Elle ne copie rien -- elle depose un .pth dans
    site-packages -- et un .pth n'est lu qu'au DEMARRAGE de l'interpreteur. Meme
    paquet, meme pip, meme machine : processus courant -> ModuleNotFoundError,
    processus neuf -> succes.

    Sur Modal la panne est structurellement impossible : l'installation a lieu a
    la construction de l'image, le rendu demarre apres, dans un interpreteur
    neuf. Sur Kaggle, installer et importer sont le meme processus. Le meme code
    marche donc d'un cote et meurt de l'autre, ce qui est exactement le genre
    d'ecart qu'un test unique sur le chemin paye ne verra jamais.

    CE QUE CE TEST NE PEUT PAS FAIRE : executer cette branche. Il n'y a ici ni
    /kaggle/working, ni carte, ni depot clone. Il garde ce qui reste gardable --
    que le correctif soit dans le script livre.
    """
    script = di.construire_script(di.preparer({"texte": DIALOGUE})["demande"])

    # SUR LE CODE, PAS SUR LA PROSE. Le commentaire qui explique ce correctif
    # cite << sys.path >> plusieurs fois : une recherche de texte passerait au
    # vert sur le seul commentaire, correctif retire. La lecon a deja ete payee
    # par le test voisin sur torchaudio ; on ne la repaie pas.
    code_seul = ast.unparse(ast.parse(script))
    assert "sys.path.insert(0, depot)" in code_seul, (
        "le depot clone n'est plus ajoute au chemin d'import. Sur Kaggle, "
        "l'installation editable qui precede ne prend pas effet dans ce "
        "processus : le travail mourra sur ModuleNotFoundError, apres avoir "
        "telecharge 12,6 Go de poids et occupe une carte pour rien."
    )
    assert "importlib.invalidate_caches()" in code_seul, (
        "le cache d'importation n'est plus invalide alors que le depot vient "
        "d'etre clone, c'est-a-dire apres le demarrage de l'interpreteur."
    )
    importes = {a.name for n in ast.walk(ast.parse(script))
                if isinstance(n, ast.Import) for a in n.names}
    assert "importlib" in importes, (
        "importlib n'est pas importe : le correctif ci-dessus leverait un "
        "NameError, et on aurait echange une panne contre une autre."
    )


def test_le_script_ecrit_le_wav_sans_torchaudio(di):
    """TROISIEME PANNE DU 17/09/2026, et la plus couteuse en information.

    Le premier rendu reel du projet a abouti : le modele a charge (80 s) et
    generate_dialogue a rendu (28 s, 5 pas). La parole EXISTAIT en memoire. Elle
    a ete perdue a la derniere ligne :

        ImportError: TorchCodec is required for save_with_torchcodec.

    torchaudio.save() ne sait plus ecrire seul depuis sa migration vers
    TorchCodec, absent de l'image -- et qui reclamerait en prime FFmpeg. Les
    auteurs ne voient pas ce defaut : leur torchaudio==2.7.1 ecrivait encore
    lui-meme.

    Le correctif RETIRE une dependance au lieu d'en ajouter une : le module wave
    de la bibliotheque standard ecrit un WAV PCM 16 bits sans rien installer.
    Installer torchcodec aurait ete un troisieme pari sur une dependance apres
    deux qui ont coute une carte chacun.

    Le bloc est en outre exerce hors ligne par une sonde qui le DECOUPE dans
    _SCRIPT et l'execute sur un vrai tenseur (bornage, entrelacement, relecture).
    """
    script = di.construire_script(di.preparer({"texte": DIALOGUE})["demande"])

    # DEFAUT DE CE TEST LUI-MEME, corrige aussitot. Sa premiere version cherchait
    # « torchaudio.save » dans le script entier -- et tombait, parce que le
    # COMMENTAIRE du bloc cite precisement cet appel pour expliquer pourquoi il a
    # disparu. Le garde confondait la prose et le code, et declarait rouge un
    # script correct. On compare donc du CODE : ast.unparse regenere la source
    # sans le moindre commentaire.
    code_seul = ast.unparse(ast.parse(script))
    assert "torchaudio" not in code_seul, (
        "torchaudio est de retour dans le CODE du script : sa fonction save "
        "delegue a TorchCodec, absent de l'image, et l'echec arrive APRES la "
        "synthese -- carte payee, parole jetee."
    )
    assert "wave.open" in code_seul, "plus rien n'ecrit le fichier."
    assert "clamp(-1.0, 1.0)" in code_seul, (
        "le bornage a disparu : un echantillon au-dela de 1.0 deborde l'entier "
        "signe et repasse par zero. Aucun chiffre du resume ne le montrerait, "
        "mais ca s'entend comme un claquement."
    )
    # Les marqueurs, eux, VIVENT dans les commentaires : ils sont le contrat avec
    # la sonde hors ligne, qui decoupe le bloc entre eux. Ils se cherchent donc
    # dans le script brut, pas dans le code regenere.
    assert "# --- DEBUT ecriture du WAV" in script
    assert "# --- FIN ecriture du WAV" in script


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
    sandbox.run_dialogue(jid, "print(1)", "modal")
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


def test_la_revision_du_code_est_dite_telle_qu_elle_est(sandbox, di):
    """Les POIDS sont epingles a un commit -- ce sont des pickles, torch.load les
    execute, l'epinglage est une barriere de securite autant qu'une garantie de
    reproductibilite. Le CODE le merite pour la meme raison : c'est LUI qui
    appelle torch.load.

    Epinglee le 17/09/2026 a la tete de la branche principale (26/10/2025),
    apres etre restee ouverte deux commits durant faute d'avoir releve le moindre
    commit du depot -- un manque avoue valant mieux qu'un SHA plausible invente.

    Ce test couvre les DEUX etats, pour ne pas devenir vide le jour ou l'un
    disparait : tant que c'est None, la page doit prevenir ; des que c'est un
    SHA, il doit etre complet ET reellement pose par une commande.
    """
    assert di.MODELE["revision"] and len(di.MODELE["revision"]) == 40, (
        "les poids ne sont plus epingles a un commit complet"
    )
    sha = di.MODELE["code_revision"]
    public = di.preparer({"texte": DIALOGUE})["resume_public"]
    page = TestClient(sandbox.app, base_url=LOCAL).get("/dialogue").text
    if sha is None:
        assert public["code_revision_epinglee"] is False
        assert "code_revision" in page, (
            "la page ne previent pas que le code n'est pas epingle."
        )
    else:
        assert len(sha) == 40, "un SHA tronque n'identifie pas un commit."
        assert public["code_revision_epinglee"] is True
        assert any(sha in c for c in di.COMMANDES_MODAL), (
            "la fiche annonce une revision epinglee mais aucune commande ne la "
            "pose : la page affirmerait « epingle » sur du code pris a la branche "
            "principale. C'est exactement le mensonge que l'aveu precedent evitait."
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


def test_la_page_propose_kaggle_mesure_et_refuse_toujours_colab(sandbox, di):
    """Kaggle est offert depuis le 17/09/2026, et SEULEMENT parce qu'il a tourne.

    Ce test en remplace un qui interdisait Kaggle ici. Son motif n'a pas ete
    desserre pour faire passer une demonstration : il a CESSE D'EXISTER. Sa
    docstring disait << rien n'a jamais tourne nulle part >> ; deux mesures du
    17/09 l'ont dementi -- 12,13 Go sur 14,56 pour 9,5 s d'audio, puis 12,95 Go
    pour 147,5 s, en float32 sur une Tesla T4.

    COLAB RESTE INTERDIT, et c'est la moitie du test qui ne bouge pas : la
    mesure du 16/09 montre qu'il manque de memoire VIVE (~12,7 Go) pour des
    poids de 12,6 Go. Un endroit se propose quand il a tourne, pas quand il est
    plausible.
    """
    page = TestClient(sandbox.app, base_url=LOCAL).get("/dialogue").text
    assert '"kaggle"' in page, (
        "Kaggle a tourne en vrai deux fois : la page doit pouvoir le proposer."
    )
    assert 'value="colab"' not in page, (
        "Colab n'a jamais tourne ici, et la mesure du 16/09 dit qu'il ne le peut pas."
    )
    assert "/dialogue/colab" not in page
    # La borne mesuree et le verrou du Studio partage doivent vivre DANS la page,
    # la ou l'on choisit -- pas seulement cote serveur.
    assert "kaggle_max_caracteres" in page, (
        "la page doit dire jusqu'ou Kaggle a ete mesure, a l'endroit du choix."
    )
    assert "kaggle_permis" in page, (
        "la page doit griser Kaggle quand le Studio est partage."
    )


def test_kaggle_refuse_ce_qui_depasse_ce_qui_a_tourne(di):
    """La borne Kaggle est un RELEVE, pas un reglage de confort.

    2 725 caracteres, 35 repliques, 147,5 s d'audio : c'est exactement ce qui a
    tourne, pour un pic de 12,95 Go sur 14,56. Au-dela, personne n'a jamais
    essaye -- l'extrapolation donnerait ~13,2 Go et tiendrait sans doute, mais
    c'est en prenant une extrapolation pour un fait qu'un faux verdict a ete
    publie le matin du 17/09. Le meme texte passe sur Modal, dont la carte a
    24 Go.
    """
    texte = "[S1]" + "la " * 1200
    assert di.KAGGLE_MAX_CARACTERES < len(texte) <= di.MAX_CARACTERES
    with pytest.raises(ValueError) as exc:
        di.preparer({"texte": texte}, "kaggle")
    message = str(exc.value)
    assert "Kaggle" in message
    assert "Modal" in message, "un refus doit dire ou aller, pas seulement non."
    # Le meme texte, sur Modal : accepte. La borne est propre a l'endroit.
    di.preparer({"texte": texte}, "modal")


def test_le_choix_de_l_endroit_change_ce_qui_part(di):
    """Modal : image construite et poids en cache. Kaggle : tout dans le script.

    Une constante juste qui ne voyage pas ne sert a rien : ce test regarde la
    demande REELLEMENT construite, pas les constantes du module.
    """
    modal = di.preparer({"texte": DIALOGUE}, "modal")["demande"]
    kaggle = di.preparer({"texte": DIALOGUE}, "kaggle")["demande"]
    assert modal["cache"] == di.CACHE_MODAL and modal["installer"] is False
    assert kaggle["cache"] == "" and kaggle["installer"] is True
    # Sur Kaggle on GARDE leur PyTorch : il est compile pour leur carte, et le
    # remplacer casserait CUDA. Meme regle que pour la chanson.
    assert "torch" not in kaggle["paquets"]
    assert "torchaudio" not in kaggle["paquets"]
    assert "torchao==0.17.0" in kaggle["paquets"], (
        "l'epingle qui evite la panne nf4tensor doit voyager jusqu'a Kaggle."
    )


def test_un_endroit_inconnu_est_refuse_et_non_devine(sandbox, di):
    """Une faute de frappe ne doit pas demarrer une machine PAYANTE.

    /chanson ramene un << ou >> inconnu a << modal >> en silence. Ici on refuse :
    qui ecrit << kagle >> demandait le gratuit, et lui louer une carte a la
    seconde serait une facture que personne n'a voulue. Le refus coute une
    phrase ; la supposition coute de l'argent.
    """
    client = TestClient(sandbox.app, base_url=LOCAL)
    r = client.post("/dialogue/creer", headers=CLE,
                    json={"texte": DIALOGUE, "ou": "kagle"})
    assert r.status_code == 400
    assert "kagle" in r.json()["detail"], "le message doit montrer la faute de frappe."


def test_kaggle_est_coupe_quand_le_studio_est_partage(sandbox, di):
    """LA GARDE D'AGENTS.md, ET ELLE NE SE DESSERRE JAMAIS.

    Kaggle automatique se sert des identifiants PERSONNELS du proprietaire de
    cette machine. Des que le Studio est ouvert autrement que par localhost --
    donc potentiellement pour quelqu'un d'autre -- il doit etre coupe, et la
    page doit le dire d'avance plutot que de laisser cliquer sur un refus.

    Ce test existe deja pour /chanson (test_chanson.py). Ouvrir Kaggle au
    dialogue sans l'ecrire ici aurait laisse la route neuve sans le garde que
    l'ancienne possede : c'est exactement la forme de trou que terminer_en_echec
    documente -- corriger la copie qui a mordu et laisser le piege arme sur les
    autres.
    """
    partage = TestClient(sandbox.app, base_url=RESEAU)
    r = partage.post("/dialogue/creer", headers=CLE,
                     json={"texte": DIALOGUE, "ou": "kaggle"})
    assert r.status_code == 403, "Kaggle automatique doit etre refuse hors de localhost."
    assert partage.get("/dialogue/etat", headers=CLE).json()["kaggle_permis"] is False

    # Sur un Studio personnel, rien n'est coupe : la garde vise le partage, pas
    # Kaggle en soi.
    perso = TestClient(sandbox.app, base_url=LOCAL)
    assert perso.get("/dialogue/etat", headers=CLE).json()["kaggle_permis"] is True


# --- Le nettoyage du rendu ----------------------------------------------------
#
# Ces tests gardent DEUX corrections payees chacune par un essai rate et une
# livraison refusee le 17/09/2026. Ce ne sont pas des preferences de style :
# sans elles, le nettoyage DETRUIT de la parole voulue.

def _wav_avec_creux(chemin, taux=24000, secondes=3.0, creux=()):
    """Un WAV carre, fort partout sauf dans les intervalles donnes.

    Du signal, pas du silence : une coupe qui tombe dans du silence ne prouve
    rien. Les creux donnent au recalage de vraies vallees ou couper, comme la
    parole en offre entre deux mots.
    """
    import array
    import wave

    def fort(i):
        t = i / float(taux)
        return 0 if any(a <= t <= b for a, b in creux) else 8000

    x = array.array("h", [fort(i) * (1 if (i // 60) % 2 else -1)
                          for i in range(int(taux * secondes))])
    with wave.open(str(chemin), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(taux)
        f.writeframes(x.tobytes())
    return chemin


def test_le_nettoyage_retire_ce_qui_n_a_pas_ete_demande(sandbox, tmp_path):
    """Un cas fabrique, entierement connu d'avance : un mot en trop, et lui seul."""
    nd = sandbox.nettoyage_dialogue

    source = _wav_avec_creux(tmp_path / "dialogue.wav", creux=((1.53, 1.60), (2.18, 2.25)))
    cible = tmp_path / "dialogue-nettoye.wav"
    mots = [
        {"mot": "Bonjour", "debut": 0.0, "fin": 0.5},
        {"mot": "le", "debut": 0.5, "fin": 1.0},
        {"mot": "monde", "debut": 1.0, "fin": 1.5},
        # Jamais envoye : c'est l'intrusion.
        {"mot": "whatever", "debut": 1.65, "fin": 2.20},
    ]
    rapport = nd.nettoyer(str(source), str(cible), ["[S1]Bonjour le monde"], mots)
    assert rapport["coupes"] == 1
    assert 0.4 < rapport["secondes_retirees"] < 0.9
    assert rapport["duree_apres_s"] < rapport["duree_avant_s"]
    # Le fichier reste un WAV lisible, au meme format que l'original.
    import wave
    with wave.open(str(cible), "rb") as f:
        assert f.getframerate() == 24000 and f.getnchannels() == 1 and f.getsampwidth() == 2


def test_le_nettoyage_ne_coupe_pas_un_nombre_reellement_prononce(sandbox, tmp_path):
    """PREMIERE GARDE, payee par un essai rate : << 10 cm >> vs << dix centimetres >>.

    Whisper ecrit les nombres en chiffres ; le texte envoye les ecrivait en
    lettres. Le SON est identique, seule la convention d'ecriture differe. Sans
    conversion, l'alignement au caractere declare << 10 >> etranger -- les
    lettres << 10 >> ne figurent pas dans << dixcentimetres >> -- et la
    reparation retire un mot REELLEMENT prononce. C'est arrive : << dix >>,
    << quarante >> et << quinze >> coupes, environ 1,3 s de parole voulue. Le
    fichier n'a pas ete livre.
    """
    nd = sandbox.nettoyage_dialogue

    assert nd.convertir("10") == "dix"
    assert nd.convertir("40") == "quarante"
    assert nd.convertir("15") == "quinze"
    assert nd.convertir("cm") == "centimetres"

    source = _wav_avec_creux(tmp_path / "dialogue.wav", secondes=2.0)
    cible = tmp_path / "dialogue-nettoye.wav"
    mots = [
        {"mot": "Il", "debut": 0.0, "fin": 0.3},
        {"mot": "fait", "debut": 0.3, "fin": 0.6},
        {"mot": "10", "debut": 0.6, "fin": 0.9},
        {"mot": "cm", "debut": 0.9, "fin": 1.2},
    ]
    rapport = nd.nettoyer(str(source), str(cible), ["[S1]Il fait dix centimètres"], mots)
    assert rapport["coupes"] == 0, (
        "un nombre ecrit en chiffres par Whisper mais bel et bien prononce a ete coupe."
    )


def test_aucune_unite_d_une_seule_lettre(sandbox):
    """SECONDE GARDE, volontairement redondante avec la premiere.

    Premiere correction : la cle 's' -> 'secondes' a transforme le << s' >> de
    << elles s'etalent >> en mot etranger, et une coupe de 125 ms entamait le
    mot. La cle 'h' tendait le meme piege (<< m'a dit >>, << l'eau >>). En
    francais, une lettre seule est presque toujours une elision.

    Les cles d'une lettre ont ete retirees ET le module refuse desormais toute
    coupe d'un fragment d'une seule lettre. Si une table fautive revenait un
    jour, la seconde garde tiendrait quand meme -- c'est sa raison d'etre.
    """
    nd = sandbox.nettoyage_dialogue

    for cle in nd.UNITES:
        assert len(cle) > 1, (
            "une cle d'une seule lettre percute les elisions francaises (s', m', l', d')."
        )


def test_la_page_dit_ce_qu_elle_a_retire_et_garde_l_original(sandbox):
    """DEFAUT REEL du 17/09, trouve en lancant un vrai dialogue, pas par un test.

    Le serveur renvoyait correctement << son_original_url >> et << nettoyage >>
    -- verifie sur l'API vivante -- mais afficherDialogue() n'utilisait que
    << son_url >>. La page a donc retire 4,67 s sur 65,12 s SANS L'ECRIRE, alors
    que ses propres reserves promettent que << le fichier d'origine reste
    telechargeable : rien n'est coupe en douce >>.

    Rien ne l'avait vu : node --check validait la page, la suite passait au
    complet. Aucun controle ne reliait la promesse affichee au code qui
    l'honore. C'est ce lien que ce test garde.
    """
    page = sandbox.dialogue.PAGE_HTML
    assert "son_original_url" in page, (
        "la page ne propose pas l'original : la promesse de ses reserves est fausse a l'ecran."
    )
    assert "blocNettoyage" in page, (
        "la page n'affiche pas ce que le nettoyage a retire."
    )
    assert "n’a pas eu lieu" in page, (
        "le cas ou le nettoyage a echoue doit se dire aussi, sinon un rendu non verifie "
        "passe pour un rendu verifie."
    )


def test_le_temoin_dit_que_le_nettoyage_n_est_pas_fini(sandbox, monkeypatch):
    """LA COURSE DU 18/09, trouvee par un lancement reel et par lui seul.

    run_dialogue marque le travail << succeeded >> puis nettoie. La page arrete
    de scruter des qu'elle voit ce mot : elle affichait donc le dialogue avant
    que le rapport et le lien vers l'original n'existent, et ne regardait plus
    jamais. Mesure sur les deux onglets d'un MEME lancement : celui au premier
    plan (scrutation toutes les 5 s) n'a rien vu ; celui en arriere-plan, dont
    Chrome bride les minuteurs, a tout vu. Le hasard decidait, et l'utilisateur
    qui regardait sa page etait celui qui etait puni.

    Aucun test ne pouvait le voir : ceux de la page lisent son code, et la
    verification du 17/09 rejouait l'affichage sur une fiche DEJA TERMINEE, ce
    qui contourne exactement la course. Celui-ci regarde la fiche PENDANT le
    nettoyage, le seul instant ou la question se pose.
    """
    vu = {}

    def faux_nettoyage(jid):
        vu["pendant"] = sandbox.read_job(jid).get("nettoyage_en_cours")
        job = sandbox.read_job(jid)
        job["nettoyage"] = {"fait": True, "coupes": 0}
        sandbox.write_job(jid, job)

    def kaggle_qui_reussit(jid, *args, **kwargs):
        job = sandbox.read_job(jid)
        job["status"] = "succeeded"
        sandbox.write_job(jid, job)

    monkeypatch.setattr(sandbox, "run_kaggle", kaggle_qui_reussit)
    monkeypatch.setattr(sandbox, "nettoyer_dialogue", faux_nettoyage)
    jid = "d" * 32
    sandbox.write_job(jid, {"id": jid, "status": "queued", "artifacts": []})
    sandbox.run_dialogue(jid, "print(1)", "kaggle")

    assert vu.get("pendant") is True, (
        "pendant le nettoyage, la fiche ne dit pas qu'il reste quelque chose a "
        "attendre : la page affichera un dialogue deja coupe sans l'ecrire."
    )
    assert "nettoyage_en_cours" not in sandbox.read_job(jid), (
        "le temoin reste leve apres le nettoyage : la page attendrait pour rien."
    )


def test_le_temoin_se_retire_meme_si_le_nettoyage_casse(sandbox, monkeypatch):
    """Un temoin qui reste leve fait attendre la page sans fin. Le finally le retire.

    nettoyer_dialogue avale deja toutes ses pannes -- c'est voulu, un rendu paye
    ne doit pas devenir un echec. Mais << deja >> n'est pas << toujours >> : si
    quoi que ce soit remonte, le temoin doit tomber quand meme.
    """
    def nettoyage_qui_casse(jid):
        raise RuntimeError("panne pendant le nettoyage")

    def kaggle_qui_reussit(jid, *args, **kwargs):
        job = sandbox.read_job(jid)
        job["status"] = "succeeded"
        sandbox.write_job(jid, job)

    monkeypatch.setattr(sandbox, "run_kaggle", kaggle_qui_reussit)
    monkeypatch.setattr(sandbox, "nettoyer_dialogue", nettoyage_qui_casse)
    jid = "e" * 32
    sandbox.write_job(jid, {"id": jid, "status": "queued", "artifacts": []})
    with pytest.raises(RuntimeError):
        sandbox.run_dialogue(jid, "print(1)", "kaggle")

    assert "nettoyage_en_cours" not in sandbox.read_job(jid), (
        "le temoin survit a une panne du nettoyage : la page attendrait 5 minutes "
        "pour rien avant de se rabattre sur sa borne."
    )


def test_la_page_attend_le_nettoyage_et_ne_se_tait_jamais(sandbox):
    """Les deux moities de la correction, cote page.

    (1) Elle attend tant que le temoin est leve, au lieu de couper sa
    scrutation. (2) Un rapport ABSENT ne la rend plus muette : c'etait le
    silence, et non l'erreur, qui a permis les deux defauts -- celui du 17/09
    ou l'affichage jetait les champs, et celui du 18/09 ou il affichait trop
    tot. Dans les deux cas la page ne disait RIEN.
    """
    page = sandbox.dialogue.PAGE_HTML
    assert "nettoyage_en_cours" in page, (
        "la page ne regarde pas le temoin : elle affichera de nouveau avant le rapport."
    )
    assert "état inconnu" in page, (
        "sans rapport, la page redevient muette -- et un son deja coupe passerait "
        "pour un son intact."
    )


def test_un_point_d_interrogation_n_est_pas_annonce_comme_une_elision(sandbox, tmp_path):
    """DEFAUT REEL du rendu Kaggle du 17/09, laisse ouvert ce soir-la puis corrige.

    Whisper rend parfois un << mot >> qui n'est QUE de la ponctuation : un
    << ? >> seul, horodate comme le reste. normaliser() le vide de ses
    caracteres, il ne peut donc s'apparier a rien, et l'alignement le declare
    intrus. La garde des fragments l'attrapait : le SON etait sauve -- bon
    resultat -- mais la page l'annoncait comme << une elision ou un nombre
    reellement prononce >>. Sur ce rendu, 8 passages epargnes, TOUS des << ? >>.

    Le fichier etait juste et le motif affiche etait faux : c'est precisement ce
    qu'un test doit tenir, parce que rien dans le son ne le trahit.
    """
    nd = sandbox.nettoyage_dialogue

    source = _wav_avec_creux(tmp_path / "dialogue.wav", secondes=2.0)
    cible = tmp_path / "dialogue-nettoye.wav"
    mots = [
        {"mot": "Tu", "debut": 0.0, "fin": 0.3},
        {"mot": "as", "debut": 0.3, "fin": 0.6},
        {"mot": "vu", "debut": 0.6, "fin": 0.9},
        # Ce que Whisper ajoute de lui-meme : de la ponctuation, pas un mot.
        {"mot": "?", "debut": 0.9, "fin": 1.0},
    ]
    rapport = nd.nettoyer(str(source), str(cible), ["[S1]Tu as vu"], mots)

    assert rapport["coupes"] == 0, (
        "de la ponctuation ne se coupe pas : il n'y a pas de parole dessous."
    )
    motifs = [d["garde"] for d in rapport["details"] if d.get("garde")]
    assert motifs == ["ponctuation, pas de la parole"], (
        "la ponctuation est epargnee sous un autre motif : la garde a raison, la "
        "raison rendue est fausse. Motifs rendus : %r" % (motifs,)
    )


def test_la_page_n_invente_pas_le_motif_d_un_passage_epargne(sandbox):
    """La page rapporte le motif porte par le rapport, elle n'en fabrique pas un.

    Sa version precedente annoncait << une elision ou un nombre reellement
    prononce >> pour TOUT passage epargne, quel que soit le motif reel range
    dans details[].garde. Une phrase en dur ne peut pas etre vraie pour trois
    gardes differentes : elle en decrivait deux et mentait sur la troisieme.
    """
    page = sandbox.dialogue.PAGE_HTML
    assert "nombre réellement prononcé ne se coupe pas" not in page, (
        "le motif en dur est de retour : il redeviendra faux des que le module "
        "epargnera un passage pour une autre raison."
    )
    assert "parMotif[d.garde]" in page, (
        "la page n'affiche plus le motif que le rapport lui donne."
    )


def test_le_script_normalise_l_onde_au_lieu_de_l_ecreter(di):
    """Le clamp seul ne deborde pas -- il APLATIT, et c'est un defaut a nous.

    Mesure sur le rendu de 147 s du 17/09 : 753 echantillons colles a la pleine
    echelle. Le modele rend des flottants qui passent 1.0, ce qui est normal ;
    c'est a l'ecriture de faire tenir l'echelle, en divisant par la crete plutot
    qu'en rabotant ce qui depasse.

    Le bornage RESTE, et il n'est pas decoratif : une valeur non finie ne se
    normalise pas, la condition l'ecarte, et le clamp garde le dernier mot.
    """
    script = di.construire_script(di.preparer({"texte": DIALOGUE})["demande"])
    code_seul = ast.unparse(ast.parse(script))

    assert "onde.abs().max()" in code_seul, (
        "plus rien ne mesure la crete : le clamp ecretera de nouveau en silence."
    )
    assert "onde / crete" in code_seul, (
        "la crete est mesuree mais l'onde n'est pas normalisee -- une mesure qui "
        "ne sert a rien est pire que pas de mesure, elle rassure."
    )
    assert "clamp(-1.0, 1.0)" in code_seul, (
        "le bornage a disparu : la normalisation ne rattrape ni nan ni inf."
    )


def test_le_bloc_d_ecriture_du_wav_tient_sur_un_vrai_tenseur(di, tmp_path):
    """SONDE HORS LIGNE : le bloc est DECOUPE du script et execute pour de vrai.

    Les deux tests precedents lisent du code. Celui-ci le FAIT TOURNER sur un
    tenseur qui depasse 1.0 -- le cas meme ou le clamp seul aplatissait -- et
    relit le fichier ecrit. C'est la seule facon de voir le resultat sans payer
    une carte : ce bloc ne tourne ailleurs que sur Modal ou Kaggle.

    SAUTE LA OU torch EST ABSENT, donc en CI, qui n'installe que les
    dependances des services. Ce test protege la machine de developpement, pas
    le runner -- le dire plutot que laisser croire le contraire.
    """
    torch = pytest.importorskip(
        "torch", reason="torch n'est pas une dependance des services ; ce bloc ne "
                        "tourne que sur le GPU distant.")
    import array
    import os
    import wave

    script = di.construire_script(di.preparer({"texte": DIALOGUE})["demande"])
    debut = script.index("# --- DEBUT ecriture du WAV")
    fin = script.index("# --- FIN ecriture du WAV")
    bloc = script[debut:fin]

    # Une rampe qui sort des bornes des DEUX cotes. Avec le clamp seul, tout ce
    # qui depasse devient plat ; avec la normalisation, seules les deux vraies
    # cretes touchent la pleine echelle.
    n = 480
    espace = {"torch": torch, "os": os, "son": torch.linspace(-1.4, 1.4, n).unsqueeze(0),
              "SORTIE": str(tmp_path), "D": {"echantillonnage": 24000}}
    exec(compile(bloc, "<bloc-wav>", "exec"), espace)  # noqa: S102

    with wave.open(os.path.join(str(tmp_path), "dialogue.wav"), "rb") as f:
        assert (f.getnchannels(), f.getsampwidth(), f.getframerate()) == (1, 2, 24000)
        brut = f.readframes(f.getnframes())
    x = array.array("h")
    x.frombytes(brut)

    assert len(x) == n, "le bloc n'a pas ecrit tous les echantillons."
    colles = sum(1 for v in x if v >= 32767 or v <= -32767)
    assert colles == 2, (
        "%d echantillons a la pleine echelle. Deux sont attendus -- les cretes "
        "reelles de la rampe, qui touchent l'echelle sans etre rabotees. Au-dela, "
        "le bloc ecrete : c'est le defaut de 753 echantillons du 17/09." % colles
    )
    # La forme est conservee : une rampe reste une rampe, seul le niveau change.
    assert x[0] == -32767 and x[-1] == 32767
    assert abs(x[n // 2]) < 100, "le milieu de la rampe devrait rester proche de zero."


def test_torchao_reste_epingle_avant_la_disparition_de_nf4tensor(di):
    """Panne reelle du 17/09, au tout premier lancement, APRES le telechargement.

    L'image s'etait construite (torch, torchtune, torchao, transformers
    s'installent bien sur Python 3.12), les 14 fichiers de poids etaient la en
    66 s, et le travail est mort a l'import :

        ModuleNotFoundError: No module named 'torchao.dtypes.nf4tensor'

    leve depuis torchtune/modules/common_utils.py. Noter l'endroit : PAS
    << No module named 'torchao' >>. torchao etait bien installe -- c'est le
    chemin du sous-module qui n'existait plus.

    pytorch/ao 60b42ac6 (13/04/2026, << Move NF4Tensor to
    quantization.quantize_.workflows >>) a deplace le fichier vers
    torchao/quantization/quantize_/workflows/nf4/nf4_tensor.py et, dit le commit
    lui-meme, << after this commit torchao/dtypes/ is now empty >>.

    Pourquoi pip ne pouvait pas s'en sortir seul : le pyproject.toml de torchtune
    ne declare NI torch NI torchao, alors qu'il importe les deux. Aucune
    contrainte a resoudre, donc la derniere version. L'epinglage ne peut venir
    que de nous.

    Frontiere relevee par sondage des tags publies : present en v0.15.0, v0.16.0
    et v0.17.0, ABSENT en v0.18.0. Desepingler ces deux lignes rejoue la panne a
    l'identique -- et elle ne se montre qu'apres avoir paye un telechargement de
    poids au tarif de la carte.
    """
    epingles = dict(p.split("==") for p in di.PAQUETS_MODAL if "==" in p)

    assert epingles.get("torchao") == "0.17.0", (
        "torchao n'est plus epingle a 0.17.0 : au-dela, torchao.dtypes.nf4tensor "
        "n'existe plus et torchtune meurt a l'import, apres le telechargement des "
        "poids, c'est-a-dire une fois paye."
    )
    assert epingles.get("torchtune") == "0.6.1", (
        "torchtune n'est plus epingle : il ne declare aucune contrainte sur "
        "torchao, donc une version future peut changer l'import et rejouer la "
        "meme panne sans que rien ne l'annonce."
    )
