"""Chanson : paroles chantees par YuE2-3B, sur Modal, Kaggle ou Colab.

Aucun appel reseau : Modal, Kaggle et le GPU ne sont jamais touches. Ce qui est
verifie ici, c'est ce qui se decide AVANT de lancer (demande bornee, plafond,
garde Kaggle, carte demandee) et que le script envoye au GPU est du Python valide.
"""
from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

CLE = {"Authorization": "Bearer cle-sandbox-de-test"}
LOCAL = "http://127.0.0.1:8020"
RESEAU = "http://192.168.1.20:8020"
PAROLES = "[Verse]\nPaper boats along the stream\n[Chorus]\nSing it low and sing it clear"


@pytest.fixture
def ch(sandbox, monkeypatch, tmp_path):
    """Le module chanson, avec un compteur de depense jetable."""
    module = sandbox.chanson
    monkeypatch.setattr(module, "BUDGET_FICHIER", tmp_path / "chanson-budget.json")
    return module


def test_demande_bornee(ch):
    with pytest.raises(ValueError):
        ch.preparer({"style": "pop", "paroles": "  "})
    with pytest.raises(ValueError):
        ch.preparer({"style": "", "paroles": PAROLES})
    with pytest.raises(ValueError):
        ch.preparer({"style": "pop", "paroles": "la " * 2000})

    plan = ch.preparer({"style": "English, folk", "paroles": PAROLES, "duree": "2", "graine": 7})
    d = plan["demande"]
    assert d["jetons"] == 3000 and d["graine"] == 7
    assert d["paroles"] == PAROLES
    assert d["revision"] == ch.MODELE["revision"]
    assert plan["resume_public"]["balise_ajoutee"] is False

    # Duree inconnue : la plus courte. Pas de section : un couplet, et c'est dit.
    plan = ch.preparer({"style": "pop", "paroles": "juste une ligne", "duree": "9", "graine": -3})
    assert plan["demande"]["jetons"] == 1500
    assert plan["demande"]["paroles"].startswith("[Verse]\n")
    assert plan["resume_public"]["balise_ajoutee"] is True
    assert 0 <= plan["demande"]["graine"] < 2 ** 31


def test_modal_garde_le_cache_kaggle_installe(ch):
    modal = ch.preparer({"style": "pop", "paroles": PAROLES}, "modal")["demande"]
    assert modal["cache"] == ch.CACHE_MODAL and modal["installer"] is False
    for ou in ("kaggle", "colab"):
        autre = ch.preparer({"style": "pop", "paroles": PAROLES}, ou)["demande"]
        assert autre["cache"] == "" and autre["installer"] is True


def test_script_et_carnet_sont_du_python_valide(ch):
    demande = ch.preparer({"style": "pop « é »", "paroles": PAROLES}, "colab")["demande"]
    script = ch.construire_script(demande)
    assert "__DEMANDE__" not in script
    compile(script, "chanson_job.py", "exec")

    carnet = ch.carnet_colab(demande)
    codes = [c["source"] for c in carnet["cells"] if c["cell_type"] == "code"]
    assert script in codes
    for source in codes:
        compile(source, "cellule", "exec")
    assert "CC BY-NC 4.0" in carnet["cells"][0]["source"]


def test_prix_compte_la_memoire(ch, monkeypatch):
    monkeypatch.setenv("MODAL_CPU", "1.0")
    attendu = 0.000222 + 0.0000131 + 0.00000222 * ch.MEMOIRE_MB / 1024
    assert ch.prix_seconde("L4") == pytest.approx(attendu)
    # Carte inconnue : comptee au prix de la plus chere, jamais moins.
    assert ch.prix_seconde("X9") > ch.prix_seconde("L40S") - 1e-12


def test_compteur_video_compte_aussi_cpu_memoire(sandbox, monkeypatch):
    """Jusqu'au 15/09, la video ne comptait que la carte : 18 % de moins en L4."""
    monkeypatch.setenv("MODAL_CPU", "1.0")
    monkeypatch.setenv("VIDEO_MEMORY_MB", "16384")
    assert sandbox.video.prix_seconde("L4") == pytest.approx(0.000222 + 0.0000131 + 0.00000222 * 16)


def test_les_deux_tables_de_prix_ne_divergent_pas(sandbox, ch):
    """chanson.py et video.py recopient les MEMES prix Modal, chacun de son cote.

    Le 17/09 ils portaient deux dates de releve differentes -- 15/09 et 09/09 :
    une table relue, l'autre oubliee, et rien ne le signalait. Les prix se
    trouvaient identiques cette fois-la ; la prochaine, ce sera un compteur qui
    refuse ou laisse passer un lancement au mauvais seuil.

    Ce controle compare les cartes communes aux deux fichiers. Il ne verifie pas
    que les prix sont JUSTES -- seule une lecture de modal.com/pricing le dit --
    mais qu'une lecture faite d'un cote a bien ete reportee de l'autre.
    """
    v = sandbox.video
    communes = sorted(set(ch.PRIX_GPU_USD_S) & set(v.PRIX_GPU_USD_S))
    assert communes, "les deux tables n'ont plus aucune carte en commun"

    ecarts = {c: (ch.PRIX_GPU_USD_S[c], v.PRIX_GPU_USD_S[c])
              for c in communes if ch.PRIX_GPU_USD_S[c] != v.PRIX_GPU_USD_S[c]}
    assert not ecarts, (
        "chanson.py et video.py comptent la meme carte a des prix differents : "
        "%s. Une des deux lectures n'a pas ete reportee." % ecarts)

    assert ch.PRIX_CPU_USD_S == v.PRIX_CPU_USD_S, "prix du coeur divergent"
    assert ch.PRIX_MEMOIRE_USD_S == v.PRIX_MEMOIRE_USD_S, "prix de la memoire divergent"


def test_plafond_refuse_avant_de_lancer(sandbox, ch, monkeypatch):
    lances = []
    monkeypatch.setattr(sandbox, "modal_configured", lambda: True)
    monkeypatch.setattr(sandbox, "run_chanson", lambda *args: lances.append(args))
    ch.budget_ecrire(0, ch.BUDGET_MENSUEL_USD - 0.01, 3)

    client = TestClient(sandbox.app, base_url=LOCAL)
    r = client.post("/chanson/creer", headers=CLE, json={"style": "pop", "paroles": PAROLES})
    assert r.status_code == 429
    assert "Kaggle reste possible" in r.json()["detail"]
    assert lances == []

    ch.budget_ecrire(0, 0, 0)
    r = client.post("/chanson/creer", headers=CLE, json={"style": "pop", "paroles": PAROLES})
    assert r.status_code == 200
    for _ in range(50):
        if lances:
            break
        time.sleep(0.02)
    assert len(lances) == 1 and lances[0][2] == "modal"


def test_modal_absent_503(sandbox, ch):
    r = TestClient(sandbox.app, base_url=LOCAL).post(
        "/chanson/creer", headers=CLE, json={"style": "pop", "paroles": PAROLES})
    assert r.status_code == 503


def test_echec_modal_encaisse_quand_meme(sandbox, ch, monkeypatch):
    def en_panne(*args, **kwargs):
        raise sandbox.BackendUnavailable("Modal unavailable: essai")

    monkeypatch.setattr(sandbox, "modal_execute", en_panne)
    jid = "f" * 32
    sandbox.write_job(jid, {"id": jid, "status": "queued", "artifacts": []})
    sandbox.run_chanson(jid, "print(1)", "modal")
    job = sandbox.read_job(jid)
    assert job["status"] == "failed"
    assert ch.budget_lire()["chansons"] == 1
    assert job["budget"]["chansons"] == 1


def test_kaggle_coupe_par_le_reseau(sandbox, ch):
    client = TestClient(sandbox.app, base_url=RESEAU)
    r = client.post("/chanson/creer", headers=CLE,
                    json={"ou": "kaggle", "style": "pop", "paroles": PAROLES})
    assert r.status_code == 403
    assert client.get("/chanson/etat", headers=CLE).json()["kaggle_permis"] is False

    # Le carnet Colab part chez la personne, sur son compte : pas de garde.
    r = client.post("/chanson/colab", headers=CLE, json={"style": "pop", "paroles": PAROLES})
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    assert json.loads(r.content)["nbformat"] == 4


def test_kaggle_demande_un_t4_seulement_pour_la_chanson(sandbox, monkeypatch):
    class Refus:
        returncode = 1
        stdout = ""
        stderr = "refus d'essai"

    monkeypatch.setattr(sandbox, "kaggle_configured", lambda: True)
    monkeypatch.setenv("KAGGLE_USERNAME", "moi")
    monkeypatch.setattr(sandbox.subprocess, "run", lambda *a, **k: Refus())
    for jid, forme in (("d" * 32, "NvidiaTeslaT4"), ("e" * 32, None)):
        sandbox.write_job(jid, {"id": jid, "status": "queued", "artifacts": []})
        sandbox.run_kaggle(jid, "print(1)", True, True, machine_shape=forme)
        meta = json.loads((sandbox.JOBS / jid / "kaggle" / "kernel-metadata.json").read_text(encoding="utf-8"))
        assert meta.get("machine_shape") == forme
        assert sandbox.read_job(jid)["status"] == "failed"


def test_kaggle_arrete_le_notebook_a_son_delai(sandbox, monkeypatch):
    """Kaggle arrete lui-meme le notebook au delai (-t) : plus de notebook laisse en route."""
    appels = []

    class Refus:
        returncode = 1
        stdout = ""
        stderr = "refus d'essai"

    def faux_run(args, **kwargs):
        appels.append(list(args))
        return Refus()

    monkeypatch.setattr(sandbox, "kaggle_configured", lambda: True)
    monkeypatch.setenv("KAGGLE_USERNAME", "moi")
    monkeypatch.delenv("KAGGLE_JOB_TIMEOUT_SECONDS", raising=False)
    monkeypatch.setattr(sandbox.subprocess, "run", faux_run)
    for jid, delai, attendu in (("a" * 32, 5400, "5400"), ("b" * 32, None, "3600")):
        sandbox.write_job(jid, {"id": jid, "status": "queued", "artifacts": []})
        sandbox.run_kaggle(jid, "print(1)", True, True, timeout_s=delai)
        push = [a for a in appels if a[:3] == ["kaggle", "kernels", "push"]][-1]
        assert push[push.index("-t") + 1] == attendu


def test_page_etat_et_jeton(sandbox, ch):
    client = TestClient(sandbox.app, base_url=LOCAL)
    page = client.get("/chanson")
    assert page.status_code == 200 and "cle-sandbox-de-test" in page.text
    assert client.get("/chanson/etat").status_code == 401
    etat = client.get("/chanson/etat", headers=CLE).json()
    assert etat["kaggle_permis"] is True
    assert etat["modele"]["licence"] == "CC BY-NC 4.0"
    assert etat["cout_max_modal_usd"] > 0

    jid = "0" * 32
    sandbox.write_job(jid, {"id": jid, "status": "succeeded", "artifacts": []})
    assert client.get(f"/chanson/jobs/{jid}/fichier?cle=faux").status_code == 401
    bon = sandbox.jeton_chanson(jid)
    assert bon != sandbox.jeton_video(jid)
    assert client.get(f"/chanson/jobs/{jid}/fichier?cle={bon}").status_code == 404


# --- Choix entre YuE2-3B seul et YuE2-3B + LoRA instrumentale (17/09/2026) ----
#
# La LoRA se FUSIONNE dans les poids du modele de base : ce n'est pas un autre
# modele, c'est le meme, modifie avant de composer. Essayee en reel le 17/09 :
# la mecanique de fusion marche (196 couples A/B). Ce que l'essai n'a PAS
# etabli, corrige le soir meme : que ce soit elle qui supprime le chant -- le
# temoin rendu sans LoRA n'avait pas de voix non plus.


def test_sans_lora_rien_ne_change(ch):
    plan = ch.preparer({"style": "pop", "paroles": PAROLES}, "modal")
    assert plan["demande"]["lora"] is None
    assert plan["resume_public"]["instrumental"] is False
    assert plan["resume_public"]["lora"] is None


def test_lora_ne_reclame_pas_de_paroles(ch):
    """Cette version ne chante pas : exiger des paroles serait absurde."""
    plan = ch.preparer({"style": "chamber orchestra", "lora": True}, "modal")
    demande = plan["demande"]
    assert demande["paroles"] == "[Instrumental]"
    assert demande["lora"]["hf"] == ch.LORA["hf"]
    assert demande["lora"]["couples"] == 196
    assert plan["resume_public"]["instrumental"] is True
    # Aucun [Verse] pose d'office : il n'y a rien a decouper en couplets.
    assert plan["resume_public"]["balise_ajoutee"] is False
    assert not demande["paroles"].startswith("[Verse]")


def test_lora_dit_sa_licence_et_sa_reserve(ch):
    """La licence voyage avec le choix, et la reserve avec la licence."""
    public = ch.preparer({"style": "x", "lora": True}, "modal")["resume_public"]["lora"]
    assert ch.LORA["licence"] in public and ch.LORA["restriction"] in public
    # La revision n'est PAS epinglee, contrairement au modele de base. Tant que
    # c'est vrai, la fiche du travail doit le dire.
    assert ch.LORA["revision"] is None
    assert "non épinglée" in public


def test_lora_refusee_partout_sauf_modal(ch):
    """Jamais essayee sur le chemin Turing : on refuse au lieu de parier."""
    for ou in ("kaggle", "colab"):
        with pytest.raises(ValueError) as exc:
            ch.preparer({"style": "x", "lora": True}, ou)
        assert "Modal" in str(exc.value)


def test_script_lora_est_du_python_valide(ch):
    sans = ch.construire_script(
        ch.preparer({"style": "p", "paroles": PAROLES}, "modal")["demande"])
    avec = ch.construire_script(ch.preparer({"style": "p", "lora": True}, "modal")["demande"])
    for source in (sans, avec):
        assert "__DEMANDE__" not in source
        compile(source, "chanson_job.py", "exec")
    # Un seul script, porteur des deux chemins : c'est la demande qui decide.
    # Sans ce controle, une faute dans la fusion ne se verrait qu'apres le
    # chargement du modele sur une carte louee, c'est-a-dire une fois paye.
    assert "_load_model" in avec and "_load_model" in sans


def test_lora_hors_modal_refusee_par_la_route(sandbox, ch):
    client = TestClient(sandbox.app, base_url=LOCAL)
    r = client.post("/chanson/creer", headers=CLE,
                    json={"ou": "kaggle", "style": "x", "lora": True})
    assert r.status_code == 400
    assert "Modal" in r.json()["detail"]


def test_la_page_offre_le_choix_et_letat_porte_la_licence(sandbox, ch):
    client = TestClient(sandbox.app, base_url=LOCAL)
    page = client.get("/chanson").text
    # Le selecteur, et la zone ou sa licence s'affiche. Le second manquait :
    # majModele() lisait un element inexistant, ce qui tue TOUT le script de la
    # page par une TypeError, en silence.
    assert 'id="modele"' in page
    assert 'id="modele-texte"' in page

    lora = client.get("/chanson/etat", headers=CLE).json()["lora"]
    assert lora["licence"] == "CC BY-NC 4.0"
    assert lora["restriction"] == "usage non commercial"
    assert lora["couples"] == 196
    assert lora["fiche"].startswith("https://huggingface.co/")


def test_la_page_offre_un_arret_durgence_hors_du_bloc_reecrit(sandbox, ch):
    """Le bouton doit exister ET survivre au rafraichissement.

    Defaut reel, 17/09 : aucune route n'existait pour arreter un travail. Un
    travail a tourne 2335 s pour 60 s demandees, sans artefact, et la fiche est
    restee « running » pour toujours -- le fil bloque n'atteint jamais son
    finally.

    Le piege de placement : suivre() reecrit etat.innerHTML toutes les 5 s. Un
    bouton pose DANS #etat serait detruit et recree a chaque tour, et l'etat
    « Arret demande... » disparaitrait sous les doigts de l'utilisateur. On
    exige donc qu'il soit declare dans le corps de la page, hors de #etat.
    """
    page = TestClient(sandbox.app, base_url=LOCAL).get("/chanson").text
    assert 'id="arreter"' in page, "la page n'offre aucun arret d'urgence"

    bloc_etat = page[page.index('<div id="etat"'):]
    bloc_etat = bloc_etat[:bloc_etat.index("</div>")]
    assert 'id="arreter"' not in bloc_etat, (
        "le bouton est dans #etat, que suivre() reecrit toutes les 5 s : "
        "il serait recree a chaque tour et perdrait son etat."
    )
    assert "/arreter" in page, "la page ne sait pas appeler la route d'arret"


def test_l_exemple_grise_est_reutilisable_comme_modele(sandbox, ch):
    """Un exemple en grise disparait au premier caractere : il ne sert qu'une fois.

    Demande de l'utilisateur, 17/09 : « tu as mis un exemple en grise qui
    pourrait servir de template plutot que de disparaitre ». Un bouton le depose
    dans le champ, ou il devient modifiable.
    """
    page = TestClient(sandbox.app, base_url=LOCAL).get("/chanson").text

    assert 'id="modele-paroles"' in page, "aucun moyen de reprendre l'exemple de paroles"
    assert 'id="modele-style"' in page, "aucun moyen de reprendre l'exemple de style"

    # Le texte depose vient de la constante capturee au chargement, JAMAIS de
    # .placeholder : sous LoRA le placeholder devient « Ignore ici... », et
    # deposer cette phrase comme paroles n'aurait aucun sens.
    assert 'deposerExemple("paroles", PAROLES_ORIGINE' in page, (
        "le bouton ne depose pas l'exemple d'origine : sous LoRA il collerait "
        "le texte « Ignoré ici… » dans les paroles."
    )
    assert 'deposerExemple("style", exempleStyle()' in page, (
        "le bouton depose un exemple fixe : il collerait l'exemple chante alors "
        "que la version instrumentale est choisie."
    )


def test_la_version_instrumentale_a_son_propre_exemple_de_style(sandbox, ch):
    """L'exemple chante reclame une « warm female voice » : absurde sans voix.

    Demande de l'utilisateur, 17/09 : « et tu pourrais mettre un exemple plus
    complet pour lora ». Quand les paroles sont eteintes, le style est la SEULE
    entree qui reste : il merite l'exemple le plus riche, pas le plus pauvre.
    """
    page = TestClient(sandbox.app, base_url=LOCAL).get("/chanson").text

    assert "const STYLE_LORA" in page, "la version instrumentale n'a pas d'exemple propre"
    debut = page.index("const STYLE_LORA")
    exemple = page[debut:page.index(";", debut)].lower()

    assert "instrumental" in exemple and "no vocals" in exemple, (
        "l'exemple de la version instrumentale ne dit pas qu'il est instrumental."
    )
    assert "voice" not in exemple, (
        "l'exemple de la version instrumentale reclame une voix."
    )
    assert 'getElementById("style").placeholder = STYLE_LORA' in page, (
        "choisir la version instrumentale laisse a l'ecran l'exemple chante."
    )


def test_les_notes_se_surlignent_sur_le_son_reellement_rendu(sandbox, ch):
    """Demande de l'utilisateur, 17/09 : « pourrais-je avoir un highlight style
    caraoke sur les note de musique qd elles sont jouees ».

    Le minutage vient de la partition -- setTiming(0, 0) garde le Q:1/4=96 que le
    modele ecrit lui-meme en tete de ses ABC -- mais l'HORLOGE est celle du FLAC
    rendu : audio.currentTime. La valeur de retour de renderAbc etait JETEE ;
    c'est elle qui porte le minutage et les noeuds SVG, sans elle il n'y a
    strictement rien a surligner.
    """
    page = TestClient(sandbox.app, base_url=LOCAL).get("/chanson").text

    assert 'id="lecteur"' in page, "le lecteur n'a pas d'identifiant : introuvable"
    assert "function suivreAuSon" in page, "aucun suivi des notes pendant la lecture"
    assert "const objets = lib.renderAbc(" in page, (
        "la valeur de retour de renderAbc est jetee : ni minutage ni noeuds SVG."
    )
    assert "setTiming(0, 0)" in page, (
        "le tempo que le modele a ecrit dans sa partition est ignore."
    )
    assert "audio.currentTime" in page, (
        "le surlignage n'est pas mene par l'horloge du son reellement rendu."
    )
    # Defaut mesure le 17/09 : requestAnimationFrame ne tourne pas dans un
    # onglet en arriere-plan, le curseur restait fige sur la premiere note
    # pendant 8,9 s de lecture reelle. « timeupdate » est emis onglet cache.
    assert '"timeupdate"' in page, (
        "le surlignage gele des que l'onglet passe en arriere-plan."
    )


def test_le_surlignage_n_ajoute_aucune_source_sonore(sandbox, ch):
    """La page ne doit avoir qu'UN seul son : le FLAC rendu par le modele.

    abcjs sait jouer une partition en MIDI. Un bouton de lecture ferait entendre
    autre chose que ce qui a ete genere -- deux sons differents pour une meme
    partition. La regle est ecrite en tete de la page depuis le debut ; elle
    n'etait tenue que par ce commentaire, ce test la tient maintenant pour de
    bon, le surlignage passant tout pres de la franchir.
    """
    page = TestClient(sandbox.app, base_url=LOCAL).get("/chanson").text

    # Le commentaire qui ENONCE la regle contient lui-meme « <audio controls> ».
    # Compte sans le retirer, ce garde echouait sur sa propre documentation --
    # troisieme fois que ce piege se presente ici : un motif qui decrit une regle
    # ressemble a une violation de cette regle. On compte le balisage servi, pas
    # la prose qui l'explique.
    corps = page
    while "<!--" in corps:
        debut = corps.index("<!--")
        fin = corps.find("-->", debut)
        if fin < 0:
            break
        corps = corps[:debut] + corps[fin + 3:]

    assert corps.count("<audio") == 1, "la page a plus d'une source sonore"
    for interdit in ("CreateSynth", "synthController", "MidiBuffer", "playMidi"):
        assert interdit not in page, (
            "la page fabrique un second son avec " + interdit + "."
        )


def test_la_page_dit_ce_que_le_surlignage_suit_vraiment(sandbox, ch):
    """Un curseur qui pretend suivre la voix alors qu'il suit le papier ment.

    Rien ne garantit que le modele ait chante au tempo qu'il a note. La partition
    est recalee sur la duree reelle du son, ce qui la rend juste aux deux bouts
    sans rien prouver au milieu -- et AUCUNE ECOUTE n'a jamais ete faite sur ce
    projet. La page doit le dire a l'utilisateur, pas le taire.
    """
    page = TestClient(sandbox.app, base_url=LOCAL).get("/chanson").text

    assert 'id="note-surlignage"' in page, (
        "la page n'a nulle part ou dire ce qu'elle surligne."
    )
    assert "partition écrite" in page, (
        "la page ne dit pas que le surlignage suit la partition, pas la voix."
    )
    assert "recalée sur les" in page, (
        "la page ne dit pas que la partition est recalee sur la duree du son."
    )
    assert "oreille" in page, (
        "la page laisse croire que la synchronisation a ete verifiee a l'oreille."
    )
    assert "grossier" in page, (
        "rien n'avertit l'utilisateur quand la partition et le chant divergent."
    )


def test_le_modele_n_ecrase_jamais_ce_qui_est_deja_ecrit(sandbox, ch):
    """Ecraser le texte de l'utilisateur d'un clic serait pire que pas de bouton.

    Et le bouton doit suivre le champ : la LoRA eteint les paroles, il ne faut
    pas les ressusciter par la bande.
    """
    page = TestClient(sandbox.app, base_url=LOCAL).get("/chanson").text
    debut = page.index("function deposerExemple")
    corps = page[debut:page.index("document.getElementById(\"modele-style\")", debut)]

    assert "champ.value.trim()" in corps, (
        "rien n'empeche le bouton d'effacer un texte deja saisi."
    )
    assert "champ.disabled" in corps, (
        "le bouton remplit meme un champ desactive par la LoRA."
    )
    assert 'getElementById("modele-paroles").disabled = true' in page, (
        "le bouton reste actif alors que la LoRA a eteint les paroles."
    )


def test_un_arret_voulu_n_est_pas_repeint_en_panne(sandbox, ch):
    """Le fil de travail ne doit PAS repeindre un arret voulu en panne.

    Defaut reel, 17/09, au tout premier essai du bouton : la page a affiche en
    rouge « Modal unavailable: NotFoundError ... This Sandbox has already shut
    down ». C'etait la PREUVE QUE L'ARRET AVAIT REUSSI -- la machine n'existait
    plus parce qu'on venait de la terminer -- presentee comme un plantage, et en
    anglais. La route ecrivait « cancelled », le fil ecrasait avec « failed »
    une seconde plus tard, et le compte-rendu partait avec.
    """
    brut = ("Modal unavailable: NotFoundError: Modal Sandbox with container ID "
            "ta-01M2QATMZG93ADCY41F3CGB6ZS not found. This means this Sandbox "
            "has already shut down.")

    sandbox.write_job("arrete", {"id": "arrete", "status": "running",
                                 "arret_demande": True,
                                 "arret_detail": "1 machine(s) arrêtée(s) chez Modal."})
    sandbox.terminer_en_echec("arrete", brut)
    fiche = sandbox.read_job("arrete")

    assert fiche["status"] == "cancelled", (
        "un arret demande est repeint en « failed » : l'utilisateur ne peut plus "
        "distinguer son propre arret d'une panne du service."
    )
    assert "demande" in fiche["error"], fiche["error"]
    assert brut in fiche.get("erreur_technique", ""), (
        "l'erreur brute doit rester consultable, mais hors du message montre."
    )
    assert fiche["arret_detail"] == "1 machine(s) arrêtée(s) chez Modal.", (
        "le compte-rendu de la route a ete detruit : on ne peut plus dire si le "
        "bouton a reellement termine une machine."
    )

    # L'AUTRE SENS, tout aussi important : une vraie panne garde son message,
    # mot pour mot. Un correctif qui adoucirait aussi les pannes reelles
    # cacherait les defauts au lieu d'en cacher un seul.
    sandbox.write_job("casse", {"id": "casse", "status": "running"})
    sandbox.terminer_en_echec("casse", brut)
    casse = sandbox.read_job("casse")
    assert casse["status"] == "failed"
    assert casse["error"] == brut


def test_aucun_chemin_n_ecrit_un_echec_a_la_main(sandbox, ch):
    """Les memes trois lignes etaient recopiees dans CINQ chemins d'execution.

    local, modal, kaggle, video, chanson. Corriger la seule qui avait mordu
    aurait laisse le piege arme sur les quatre autres, et le prochain
    fournisseur ajoute l'aurait recopie a son tour.

    Le motif cherche existe forcement une fois : dans terminer_en_echec()
    lui-meme. On exige donc UNE occurrence, et a l'interieur de cette
    fonction -- un test qui exigerait zero echouerait sur le correctif.
    """
    with open(sandbox.__file__, encoding="utf-8") as f:
        source = f.read()
    motif = '"status": "failed", "finished_at"'

    assert "def terminer_en_echec" in source, "le garde partage a disparu"
    assert source.count(motif) == 1, (
        f"{source.count(motif)} chemins ecrivent l'echec a la main ; il n'en "
        f"faut qu'un, dans terminer_en_echec(), sinon un arret voulu sera "
        f"repeint en panne."
    )
    debut = source.index("def terminer_en_echec")
    fin = source.index("\ndef ", debut + 1)
    assert motif in source[debut:fin], (
        "l'unique ecriture d'echec n'est pas dans terminer_en_echec()."
    )


def test_la_page_distingue_un_arret_d_une_panne(sandbox, ch):
    """Un arret voulu ne doit pas s'afficher en rouge sous le mot « Échec »."""
    page = TestClient(sandbox.app, base_url=LOCAL).get("/chanson").text

    assert 'j.status === "cancelled"' in page, (
        "la page ne sait pas reconnaitre un travail arrete : il retombe dans la "
        "branche d'echec."
    )
    assert page.index('j.status === "cancelled"') < page.index("✖ Échec"), (
        "la branche d'arret doit etre examinee AVANT celle d'echec, sinon un "
        "arret voulu s'affiche quand meme en panne."
    )
    assert "arret_detail" in page, (
        "la page n'affiche pas ce que l'arret a reellement fait."
    )


def test_la_route_darret_refuse_un_travail_inconnu(sandbox, ch):
    client = TestClient(sandbox.app, base_url=LOCAL)
    assert client.post("/jobs/inexistant/arreter", headers=CLE).status_code == 404
    assert client.post("/jobs/inexistant/arreter").status_code == 401


def test_larret_kaggle_ne_promet_pas_une_annulation(sandbox, ch):
    """Kaggle n'a AUCUNE annulation : le bouton doit le dire, pas le cacher.

    CLI 2.2.4 sans commande d'annulation ; cancel_kernel_session reclame un
    numero de session qu'aucune reponse de l'envoi ni de l'etat ne donne
    (constat du 15/09, PLAN.md). Promettre un arret ici ferait croire un quota
    libere qui court toujours.
    """
    # sandbox EST le module app.py deja charge : son __file__ donne le chemin
    # sans dependre d'un RACINE que ce module de test n'a jamais defini
    # (il vit dans conftest.py et dans test_dockerfiles.py, pas ici).
    with open(sandbox.__file__, encoding="utf-8") as f:
        source = f.read()
    debut = source.index('@app.post("/jobs/{jid}/arreter")')
    corps = source[debut:debut + 4000]
    assert "quota" in corps, (
        "la reponse Kaggle ne parle pas du quota qui continue de courir"
    )
    assert "cancelled" in corps, "l'arret n'ecrit pas d'etat terminal dans la fiche"


def test_la_page_previent_quand_la_partition_est_tronquee(sandbox, ch):
    """Une partition tronquee VIDE le morceau ; l'ecran doit le dire.

    Defaut reel, 17/09 au soir : un rendu a donne 60 s d'audio depuis une
    partition de 422 lignes ne contenant PAS UNE SEULE note -- le plan avait
    epuise son plafond de jetons en bouclant sur une mesure vide (« Dm »z16 a la
    voix, Z4 a l'instrument) sans jamais quitter « % intro ».

    La page n'avertissait que sur « coupee.son ». C'est pourtant l'autre cas qui
    est grave : une chanson ecourtee reste une chanson, une partition tronquee
    peut ne rien prescrire du tout. L'utilisateur recevait un fichier et aucune
    explication.

    On cherche la forme EXECUTABLE, « r.coupee.X) notes.push( », et non le seul
    mot « coupee.son » : le commentaire pose au-dessus du correctif contient ce
    mot, et un motif qui matche sa propre documentation ne detecte rien.
    """
    page = TestClient(sandbox.app, base_url=LOCAL).get("/chanson").text
    debut = page.index("const notes = [];")
    bloc = page[debut:page.index("if(notes.length)", debut)]
    assert "r.coupee.partition) notes.push(" in bloc, (
        "La page ne previent pas quand la partition est tronquee : le morceau "
        "peut ne contenir aucune note et rien a l'ecran ne le signale."
    )
    assert "r.coupee.son) notes.push(" in bloc, (
        "L'avertissement de duree a disparu en ajoutant celui de la partition."
    )


def test_la_page_transmet_le_choix_du_modele(sandbox, ch):
    """Le choix doit ARRIVER au serveur, pas seulement s'afficher.

    Defaut reel, 17/09 : la page declarait #modele, changeait le libelle du
    bouton, affichait la licence, desactivait Kaggle -- et postait un corps sans
    « lora ». Le menu marchait entierement a l'ecran et ne changeait rien au
    rendu : on choisissait l'instrumental, le modele chantait.

    Les 147 tests d'alors etaient verts. Ils couvraient preparer() d'un cote et
    l'existence du <select> de l'autre ; aucun ne suivait le fil entre les deux.
    """
    page = TestClient(sandbox.app, base_url=LOCAL).get("/chanson").text
    debut = page.index("const corps = {")
    corps = page[debut:page.index("}", debut)]
    assert "lora" in corps, (
        "La page construit sa requete sans « lora » : le choix instrumental "
        "s'affiche, mais rien ne l'envoie au serveur."
    )
