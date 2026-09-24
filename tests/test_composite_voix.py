"""Chaîne : la voix dit des phrases, pas du Markdown, et passe par l'écoute.

23/09/2026, image → chat → voix anglaise : Piper a lu « ### », « ** », des
numéros de liste et le titre « English Text to Read Aloud ». Et le
propriétaire : « on avait évité les erreurs dans la restitution vocale en ayant
ajouté un filtre basé sur la cohérence avec le stt » -- le filtre du dialogue,
que la voix d'une chaîne ne traversait pas. Le texte montré, lui, restait en
Markdown brut.
"""
from __future__ import annotations

import array
import io
import json
import math
import shutil
import subprocess
import wave

import pytest
from fastapi.testclient import TestClient

LOCAL = "http://127.0.0.1:8020"

EXPOSE = """### Description
Here is the text:

### English Text to Read Aloud
**A lighthouse** stands in the *rain*.
1. The sea is grey.
- Waves hit the rocks
---
| a | b |
|---|---|
"""


@pytest.fixture
def composite(sandbox):
    return sandbox.composite


def test_la_voix_ne_lit_ni_titres_ni_symboles(composite):
    dit = composite.texte_a_dire(EXPOSE)
    assert "English Text to Read Aloud" not in dit
    assert "#" not in dit and "*" not in dit and "---" not in dit
    assert dit.splitlines() == ["Here is the text:", "A lighthouse stands in the rain.",
                                "The sea is grey.", "Waves hit the rocks.", "a, b."]


def test_le_chat_sait_qu_il_ecrit_pour_une_voix(composite):
    etape = {"brique": "chat_auto", "fonction": "Chat", "demande": "décris en anglais"}
    assert "lue à haute voix" not in composite._consigne_du_chat(etape, "texte")
    oral = composite._consigne_du_chat(dict(etape, suivante="voix_en"), "texte")
    assert "lue à haute voix" in oral and "en anglais" in oral and "pas de titre" in oral.lower()
    assert "en français" in composite._consigne_du_chat(dict(etape, suivante="voix_fr"), None)
    # « décris DANS LE DÉTAIL … à voix haute » a rendu une phrase (23/09) :
    # la consigne orale règle la forme, pas la longueur.
    assert "niveau de détail demandés" in oral


def test_la_lecture_d_image_sait_aussi_qu_elle_ecrit_pour_une_voix(composite):
    etape = {"brique": "image_lecture", "fonction": "Lecture", "demande": "décris en anglais"}
    assert "lue à haute voix" not in composite._consigne_de_l_image(etape)
    oral = composite._consigne_de_l_image(dict(etape, suivante="voix_en"))
    assert oral.startswith("décris en anglais")
    assert "lue à haute voix" in oral and "en anglais" in oral and "pas de titre" in oral.lower()


def test_executer_dit_a_chaque_etape_ce_qui_suit(composite):
    vus = []

    def lancer(etape, entree):
        vus.append((etape["brique"], etape["suivante"]))
        return "texte"

    chaine = {"phrase": "p", "etapes": [{"brique": "image_lecture", "fonction": "a"},
                                        {"brique": "chat_auto", "fonction": "b"},
                                        {"brique": "voix_en", "fonction": "c"}]}
    composite.executer(chaine, lancer, garde_budget=lambda e: None)
    assert vus == [("image_lecture", "chat_auto"), ("chat_auto", "voix_en"), ("voix_en", None)]


def son_de(secondes: float, taux: int = 16000) -> bytes:
    x = array.array("h", (int(8000 * math.sin(2 * math.pi * 220 * i / taux))
                          for i in range(int(secondes * taux))))
    tampon = io.BytesIO()
    with wave.open(tampon, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(taux)
        w.writeframes(x.tobytes())
    return tampon.getvalue()


class Reponse:
    def __init__(self, mots):
        self.mots = mots

    def raise_for_status(self):
        pass

    def json(self):
        return {"mots": self.mots}


class Client:
    def __init__(self, mots=None, panne=None):
        self.mots, self.panne, self.appels = mots, panne, []

    def post(self, url, **k):
        self.appels.append((url, k.get("data")))
        if self.panne:
            raise self.panne
        return Reponse(self.mots)


def mots(*triplets):
    return [{"mot": m, "debut": a, "fin": b} for m, a, b in triplets]


def test_l_ecoute_retire_la_parole_ajoutee(composite):
    son = son_de(3.0)
    client = Client(mots(("The", 0.1, 0.3), ("sea", 0.35, 0.6), ("banana", 1.0, 1.6),
                         ("is", 2.0, 2.2), ("grey.", 2.3, 2.7)))
    rendu = composite.ecouter(son, "The sea is grey.", "en", client, {})
    e = rendu.ecoute
    assert client.appels == [(composite.ROUTEUR + "/v1/audio/alignement", {"langue": "en"})]
    assert e["fait"] and e["attendus"] == 4 and e["retrouves"] == 4 and not e["ecart"]
    assert e["coupes"] == 1 and e["retires"] == ["banana"]
    assert len(rendu) < len(son), "le son nettoye n'a pas remplace l'original"


def test_une_voix_qui_s_ecarte_se_dit(composite):
    e = composite.ecouter(son_de(2.0), "The sea is grey and calm today.", "en",
                          Client(mots(("The", 0.1, 0.3), ("sky", 0.4, 0.8))), {}).ecoute
    assert e["fait"] and e["ecart"]


def test_l_ecoute_en_panne_garde_le_son(composite):
    son = son_de(1.0)
    rendu = composite.ecouter(son, "Hello.", "en", Client(panne=OSError("injoignable")), {})
    assert bytes(rendu) == son
    assert rendu.ecoute["fait"] is False and "injoignable" in rendu.ecoute["motif"]


def test_un_nombre_en_chiffres_n_est_pas_coupe(composite):
    rendu = composite.ecouter(son_de(2.0), "I see ten boats.", "en",
                              Client(mots(("I", 0.1, 0.2), ("see", 0.3, 0.5),
                                          ("10", 0.6, 1.0), ("boats.", 1.1, 1.5))), {})
    assert rendu.ecoute["coupes"] == 0


def extrait(page: str) -> str:
    debut = page.index("function phraseEcoute(e){")
    return page[debut:page.index("\n// Un verdict rendu pour un autre fichier", debut)]


def node(code: str) -> str:
    sortie = subprocess.run(["node", "-e", code], capture_output=True, text=True,
                            encoding="utf-8", timeout=20)
    assert sortie.returncode == 0, sortie.stderr
    return sortie.stdout


@pytest.fixture
def page(sandbox):
    if not shutil.which("node"):
        pytest.skip("node absent")
    return TestClient(sandbox.app, base_url=LOCAL).get("/composite").text


def test_le_markdown_est_mis_en_forme_et_reste_echappe(page):
    html = node(extrait(page) + "\nconsole.log(miseEnForme(" + json.dumps(
        EXPOSE + "\n<script>alert(1)</script> et `code`") + "));")
    assert "<h4>English Text to Read Aloud</h4>" in html
    assert "<strong>A lighthouse</strong>" in html and "<em>rain</em>" in html
    assert "<ol><li>The sea is grey.</li></ol><ul><li>Waves hit the rocks</li></ul><hr>" in html
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "<code>code</code>" in html


def test_l_ecoute_se_lit_sur_la_page(page):
    html = node(extrait(page) + "\nconsole.log(phraseEcoute(" + json.dumps(
        {"fait": True, "attendus": 12, "retrouves": 11, "coupes": 1, "retires": ["banana"],
         "ecart": False}) + "));\nconsole.log(phraseEcoute({fait: false, motif: 'lent'}));")
    assert "11 mots retrouvés sur 12" in html and "« banana »" in html
    assert "non faite (lent)" in html


def test_le_fichier_joint_se_montre(page):
    code = (extrait(page)
            + "\nconst zone = {innerHTML: ''};"
            + "\nconst document = {getElementById: () => zone};"
            + "\nconst URL = {createObjectURL: () => 'blob:x', revokeObjectURL: () => {}};"
            + "\nmontrerFichier({name: 'phare<1>.jpg', type: 'image/jpeg', size: 2048});"
            + "\nconsole.log(zone.innerHTML);"
            + "\nmontrerFichier({name: 'notes.pdf', type: 'application/pdf', size: 3145728});"
            + "\nconsole.log(zone.innerHTML);")
    html = node(code)
    assert "<img class=vignette src='blob:x'" in html
    assert "phare&lt;1&gt;.jpg — 2 ko" in html
    assert "notes.pdf — 3,0 Mo" in html


# --- Les réglages d'une chaîne (23/09) ------------------------------------------
# « une voix en anglais et un texte en français », puis « attacher au composite
# un champ propriété compatible de l'exécution », puis « généralise ces cas
# particuliers à tous les composites ». Trois sortes : variante d'une étape,
# langue de la réponse, texte affiché en.

def etape_de(composite, brique):
    return composite._etape({a["id"]: a for a in composite.charger_registre()}[brique])


def chaine_de(composite, briques, proprietes=None):
    return {"phrase": "p", "proprietes": proprietes or {},
            "etapes": [etape_de(composite, b) for b in briques]}


def trace_dite(composite, texte):
    son = composite.Son(b"RIFF")
    son.ecoute = {"texte_dit": texte, "fait": True}
    return {"sortie": son}


def par_id(montrees):
    return {p["id"]: p for p in montrees}


def test_chaque_famille_de_briques_offre_sa_variante(composite):
    for briques, ident, attendu in (
            (["voix_en"], "voix@0", {"voix_fr", "voix_en"}),
            (["chat_auto"], "chat@0", {"chat_auto", "chat_max"}),
            (["dictee_locale"], "dictee@0", {"dictee_locale", "dictee_groq"}),
            (["video_maison"], "video@0", {"video_maison", "video_rapide"})):
        p = par_id(composite.proprietes_montrees(chaine_de(composite, briques)))[ident]
        assert p["variante"] and p["valeur"] == briques[0]
        assert {c["valeur"] for c in p["choix"]} == attendu


def test_une_brique_sans_famille_n_a_pas_de_variante(composite):
    ids = par_id(composite.proprietes_montrees(chaine_de(composite, ["image_lecture"])))
    assert list(ids) == ["langue_reponse@0"]


def test_une_image_fabriquee_offre_son_format(composite):
    ids = par_id(composite.proprietes_montrees(chaine_de(composite, ["image_fabrication"])))
    assert list(ids) == ["format@0"]
    assert [c["valeur"] for c in ids["format@0"]["choix"]] == ["libre", "1:1", "16:9", "9:16"]
    assert ids["format@0"]["valeur"] == "libre"
    assert composite.reglages_de_l_etape(
        chaine_de(composite, ["image_fabrication"], {"format@0": "16:9"}), 0) == {"format": "16:9"}


def test_le_format_propose_par_le_lecteur_de_phrase(composite):
    graphe = composite.compiler("p", lambda _c: json.dumps(
        {"noeuds": ["fabrication_image"], "proprietes": {"format": "9:16"}}))
    valeurs, sans_effet = composite.appliquer_proposees(composite.lier(graphe), graphe)
    assert valeurs == {"format@0": "9:16"} and sans_effet == []
    # une proportion que l'execution ne tient pas est dite, jamais retenue
    graphe = composite.compiler("p", lambda _c: json.dumps(
        {"noeuds": ["fabrication_image"], "proprietes": {"format": "4:3"}}))
    assert graphe["proprietes"] == {}
    assert graphe["proprietes_sans_effet"] == [
        "« format = 4:3 » : aucune étape de ce Studio ne sait respecter ce réglage."]
    # un format sans image a fabriquer : dit aussi
    graphe = composite.compiler("p", lambda _c: json.dumps(
        {"noeuds": ["lecture_image"], "proprietes": {"format": "16:9"}}), entree="image")
    _, sans_effet = composite.appliquer_proposees(composite.lier(graphe), graphe)
    assert sans_effet == ["« Format 16:9 » : aucune étape de cette chaîne ne fabrique d'image."]


def test_un_format_hors_des_choix_est_refuse(composite):
    chaine = chaine_de(composite, ["image_fabrication"])
    assert composite.proprietes_lues('{"format@0": "16:9"}', chaine) == {"format@0": "16:9"}
    assert composite.proprietes_lues('{"format@0": "libre"}', chaine) == {}
    with pytest.raises(composite.CompositeRefuse):
        composite.proprietes_lues('{"format@0": "1920x1080"}', chaine)


def test_un_travail_offre_sa_duree_lue_dans_son_module(composite):
    import chanson
    import video

    ids = par_id(composite.proprietes_montrees(chaine_de(composite, ["video_maison"])))
    assert [c["valeur"] for c in ids["duree@0"]["choix"]] == list(video.DUREES_MAISON)
    assert ids["duree@0"]["defaut"] == video.DUREE_PAR_DEFAUT
    ids = par_id(composite.proprietes_montrees(chaine_de(composite, ["video_rapide"])))
    assert [c["valeur"] for c in ids["duree@0"]["choix"]] == list(video.DUREES)
    ids = par_id(composite.proprietes_montrees(chaine_de(composite, ["chat_auto", "chanson"])))
    assert [c["valeur"] for c in ids["duree@1"]["choix"]] == list(chanson.DUREES)
    assert ids["duree@1"]["choix"][0]["nom"] == "1 min au plus"
    with pytest.raises(composite.CompositeRefuse):
        composite.proprietes_lues('{"duree@0": "12"}', chaine_de(composite, ["video_rapide"]))


def test_le_format_de_la_video_est_montre_jamais_offert(composite):
    import video

    ids = par_id(composite.proprietes_montrees(chaine_de(composite, ["video_maison"])))
    maison = video.MODELES["maison"]
    assert ids["definition@0"]["choix"] == [
        {"valeur": "%dx%d" % (maison["largeur"], maison["hauteur"]),
         "nom": "%d × %d sur cette carte (fixé par le modèle)" % (maison["largeur"], maison["hauteur"])}]
    rapide = par_id(composite.proprietes_montrees(chaine_de(composite, ["video_rapide"])))
    assert "chez le loueur" in rapide["definition@0"]["choix"][0]["nom"]
    assert "sur cette carte" in rapide["definition@0"]["choix"][0]["nom"], "elle peut tourner ici"


def test_la_duree_proposee_en_secondes(composite):
    def appliquer(briques, duree):
        graphe = composite.compiler("p", lambda _c: json.dumps(
            {"noeuds": briques, "proprietes": {"duree": duree}}))
        return composite.appliquer_proposees(composite.lier(graphe), graphe)

    assert appliquer(["video_maison"], 3) == ({"duree@0": "3"}, [])
    valeurs, sans_effet = appliquer(["video_maison"], 60)
    assert valeurs == {} and sans_effet[0].startswith("« Durée de 60 s » : « Vidéo")
    assert "ne propose que 1 s, 2 s" in sans_effet[0], "jamais arrondie en silence"
    assert appliquer(["fabrication_image"], 3)[1] == [
        "« Durée de 3 s » : aucune étape de cette chaîne n'a de durée à choisir."]


# --- 24/09 : « tous les paramètres doivent être passés » ------------------------
# Les champs que les pages des travaux envoient : machine louée (vidéo Rapide,
# chanson, dialogue), carte de cet ordinateur (vidéo Rapide), version (chanson).

def test_chaque_travail_offre_les_champs_de_sa_page(composite):
    def ids_de(briques):
        return list(par_id(composite.proprietes_montrees(chaine_de(composite, briques))))

    chanson = ids_de(["chat_auto", "chanson"])
    assert {"duree@1", "loueur@1", "version@1"} <= set(chanson)
    assert {"loueur@1"} <= set(ids_de(["chat_auto", "dialogue"]))
    rapide = ids_de(["video_rapide"])
    assert {"definition@0", "duree@0", "loueur@0", "ou_calculer@0"} <= set(rapide)
    maison = ids_de(["video_maison"])
    assert "loueur@0" not in maison and "ou_calculer@0" not in maison, "la maison ne loue rien"


def test_les_placements_sont_ceux_du_studio(composite):
    import ou_calculer

    assert set(composite.PLACEMENTS) == set(ou_calculer.REGLAGES)


def test_les_parametres_partent_avec_le_travail(composite):
    _, demande = composite.demande_du_travail(
        {"brique": "chanson", "demande": "douce",
         "reglages": {"loueur": "kaggle", "duree": "2"}}, "la la")
    assert demande["ou"] == "kaggle" and demande["duree"] == "2" and "lora" not in demande
    _, demande = composite.demande_du_travail(
        {"brique": "chanson", "demande": "douce", "reglages": {"version": "instrumentale"}}, "")
    assert demande["lora"] is True and "ou" not in demande
    _, demande = composite.demande_du_travail(
        {"brique": "video_rapide", "demande": "un phare",
         "reglages": {"ou_calculer": "toujours-modal"}}, "")
    assert demande["ou_calculer"] == "toujours-modal" and demande["qualite"] == "rapide"
    _, demande = composite.demande_du_travail({"brique": "dialogue", "demande": "d"}, "[S1] a")
    assert "ou" not in demande, "sans reglage, le defaut de la route"


def test_instrumentale_chez_kaggle_est_refusee_avant_de_lancer(composite):
    chaine = chaine_de(composite, ["chat_auto", "chanson"])
    assert composite.proprietes_lues('{"version@1": "instrumentale"}', chaine) == {
        "version@1": "instrumentale"}
    with pytest.raises(composite.CompositeRefuse) as refus:
        composite.proprietes_lues('{"version@1": "instrumentale", "loueur@1": "kaggle"}', chaine)
    assert refus.value.motif == "instrumentale_sur_kaggle"


def test_kaggle_ne_compte_pas_au_budget_modal(composite):
    """Comme la route (app.py, /chanson/creer) : chez Kaggle, aucune garde Modal."""
    chaine = chaine_de(composite, ["chat_auto", "chanson"], {"loueur@1": "kaggle"})
    reglees = composite.etapes_reglees(chaine)
    assert reglees[1]["cout_max_usd"] == 0.0
    assert not composite.loue_chez_modal(reglees[1])
    assert composite.mesure_du_noeud(reglees[1]) is None
    modal = composite.etapes_reglees(chaine_de(composite, ["chat_auto", "chanson"]))
    assert composite.loue_chez_modal(modal[1])
    assert chaine["etapes"][1]["cout_max_usd"] == modal[1]["cout_max_usd"], "la chaine n'est pas mutee"


def test_le_loueur_propose_vaut_pour_chaque_etape_louee(composite):
    graphe = composite.compiler("p", lambda _c: json.dumps(
        {"noeuds": ["chanson"], "proprietes": {"loueur": "kaggle", "version": "instrumentale"}}),
        entree="texte")
    valeurs, _ = composite.appliquer_proposees(composite.lier(graphe), graphe)
    assert valeurs == {"loueur@0": "kaggle", "version@0": "instrumentale"}


def test_un_reglage_refait_refait_le_verdict(page):
    debut = page.index("function changerReglage(")
    fin = page.index("\n}\n", debut) + 3
    v = {"etapes": [{"brique": "chanson"}],
         "proprietes": [{"id": "loueur@0", "etape": 0, "refait": True, "valeur": "modal",
                         "defaut": "modal", "choix": [{"valeur": "modal"}, {"valeur": "kaggle"}]},
                        {"id": "version@0", "etape": 0, "valeur": "chantee", "defaut": "chantee",
                         "choix": [{"valeur": "chantee"}, {"valeur": "instrumentale"}]}]}
    code = (page[debut:fin] + "\nconst v = " + json.dumps(v) + ";"
            + "\nconsole.log(changerReglage(v, 0, 'kaggle'), changerReglage(v, 1, 'instrumentale'),"
            + " v.proprietes[1].valeur);")
    assert node(code).strip() == "chaine valeur instrumentale", "le loueur ne remet rien a zero"


def test_la_page_montre_les_dimensions_vraies(page):
    debut = page.index("function dimensions(")
    fin = page.index("}", debut) + 1
    assert node(page[debut:fin] + "\nconsole.log(dimensions(1344, 768));").strip() == "Image de 1344 × 768 pixels"
    assert "naturalWidth" in page and "img class=sortie" in page


def test_la_langue_de_reponse_seulement_pour_un_texte_lu(composite):
    ids = par_id(composite.proprietes_montrees(
        chaine_de(composite, ["image_lecture", "chat_auto", "voix_en"])))
    # la lecture d'image est lue par le chat, le chat est dit par la voix :
    assert "langue_reponse@0" in ids
    assert "langue_reponse@1" not in ids, "la voix decide de la langue du chat"
    assert ids["langue_ecrite"]["choix"][0] == {"valeur": "meme", "nom": "la langue de la voix"}
    assert "OpenRouter" in ids["langue_ecrite"]["note"], "la traduction fait sortir le texte"


def test_le_lecteur_de_phrase_propose_et_la_chaine_dispose(composite):
    graphe = composite.compiler(
        "voix en anglais, texte en français", lambda _c: json.dumps(
            {"noeuds": ["lecture_image", "synthese_vocale_en"],
             "proprietes": {"langue_ecrite": "fr", "langue_reponse": "es", "couleur": "bleu"}}),
        entree="image")
    chaine = composite.lier(graphe)
    valeurs, sans_effet = composite.appliquer_proposees(chaine, graphe)
    # la lecture d'image est dite par la voix : « réponse en espagnol » n'a
    # aucune étape où s'appliquer, et c'est dit.
    assert valeurs == {"langue_ecrite": "fr"}
    assert sans_effet == ["« couleur = bleu » : aucune étape de ce Studio ne sait respecter ce réglage.",
                          "« Réponse en espagnol » : aucune étape de cette chaîne n'écrit un texte "
                          "montré tel quel."]


def test_une_proposition_sans_etape_pour_la_tenir_est_dite(composite):
    graphe = {"phrase": "p", "noeuds": [{"capacite": "fabrication_image"}],
              "proprietes": {"langue_ecrite": "fr", "langue_reponse": "en"}}
    chaine = composite.lier(graphe)
    valeurs, sans_effet = composite.appliquer_proposees(chaine, graphe)
    assert valeurs == {}
    assert "ne finit pas par une voix" in sans_effet[0]
    assert "« Réponse en anglais »" in sans_effet[1]


def test_la_consigne_du_lecteur_parle_des_proprietes(composite):
    vues = []
    composite.compiler("dis-le", lambda c: vues.append(c) or '{"noeuds": ["conversation"]}')
    assert '"langue_reponse"' in vues[0] and '"langue_ecrite": "fr"' in vues[0]


def test_les_reglages_renvoyes_sont_verifies_sur_la_chaine(composite):
    chaine = chaine_de(composite, ["chat_auto", "voix_en"])
    assert composite.proprietes_lues('{"langue_ecrite": "fr"}', chaine) == {"langue_ecrite": "fr"}
    assert composite.proprietes_lues('{"langue_ecrite": "meme"}', chaine) == {}
    assert composite.proprietes_lues(None, chaine) == {}
    for mauvais in ('{"langue_ecrite": "klingon"}', '{"couleur": "bleu"}',
                    '{"langue_reponse@0": "fr"}',  # le chat est dit par la voix
                    '{"voix@1": "voix_fr"}',       # une variante passe par les briques
                    "[1]", "{"):
        with pytest.raises(composite.CompositeRefuse):
            composite.proprietes_lues(mauvais, chaine)


def test_la_langue_de_reponse_part_dans_la_consigne(composite):
    vues = []

    def lancer(etape, entree):
        vues.append(composite._consigne_du_chat(etape, entree))
        return "texte"

    chaine = chaine_de(composite, ["chat_auto", "chat_auto"], {"langue_reponse@1": "en"})
    composite.executer(chaine, lancer, garde_budget=lambda e: None)
    assert "Répondez en anglais." not in vues[0]
    assert vues[1].endswith("Répondez en anglais.")
    image = composite._consigne_de_l_image(
        dict(etape_de(composite, "image_lecture"), demande="décris",
             reglages={"langue_reponse": "de"}))
    assert image.endswith("Répondez en allemand.")


def test_le_texte_dit_est_traduit_selon_le_reglage(composite):
    vus = []

    def lancer(etape, entree):
        vus.append((etape["brique"], etape["demande"], entree))
        return "Un phare sous la pluie."

    tr = composite.traduire_le_texte_dit(
        chaine_de(composite, ["image_lecture", "voix_en"], {"langue_ecrite": "fr"}),
        trace_dite(composite, "A lighthouse in the rain."), lancer)
    assert tr == {"langue": "français", "texte": "Un phare sous la pluie.", "motif": None}
    assert vus[0][0] == "chat_auto" and "en français" in vus[0][1]
    assert vus[0][2] == "A lighthouse in the rain."


def test_rien_a_traduire_sans_reglage_ou_dans_la_meme_langue(composite):
    def lancer(etape, entree):
        raise AssertionError("aucune traduction attendue")

    dite = trace_dite(composite, "A lighthouse.")
    for proprietes in ({}, {"langue_ecrite": "en"}):
        assert composite.traduire_le_texte_dit(
            chaine_de(composite, ["image_lecture", "voix_en"], proprietes), dite, lancer) is None


def test_une_traduction_manquee_ne_casse_rien(composite):
    def lancer(etape, entree):
        raise composite.CompositeRefuse("x", "Aucun service de chat ne répond.", ou="execution")

    tr = composite.traduire_le_texte_dit(
        chaine_de(composite, ["image_lecture", "voix_en"], {"langue_ecrite": "fr"}),
        trace_dite(composite, "A lighthouse."), lancer)
    assert tr["texte"] is None and tr["motif"] == "Aucun service de chat ne répond."


def lancer_faux(sandbox):
    def lancer(etape, entree):
        if etape["brique"] in ("voix_en", "voix_fr"):
            son = sandbox.composite.Son(b"RIFF\x24\x00\x00\x00WAVEfmt ")
            son.ecoute = {"texte_dit": entree, "fait": False, "motif": "test"}
            return son
        if etape["fonction"] == "Traduction":
            return "Un phare."
        return "A lighthouse."
    return lancer


CLE_TEST = {"Authorization": "Bearer cle-sandbox-de-test"}


def test_la_route_suit_les_reglages_renvoyes(sandbox, monkeypatch):
    monkeypatch.setattr(sandbox.composite, "lancer_par_le_routeur", lancer_faux(sandbox))
    client = TestClient(sandbox.app, base_url=LOCAL)

    def lancer(proprietes):
        return client.post("/composite/lancer", headers=CLE_TEST,
                           data={"phrase": "dis-le", "briques": "chat_auto,voix_en",
                                 "proprietes": proprietes})

    r = lancer('{"langue_ecrite": "fr"}')
    assert r.status_code == 200, r.text
    assert r.json()["traduction"] == {"langue": "français", "texte": "Un phare.", "motif": None}
    r = lancer('{"langue_ecrite": "meme"}')
    assert r.status_code == 200 and r.json()["traduction"] is None
    r = lancer('{"couleur": "bleu"}')
    assert r.status_code == 409 and "couleur" in r.json()["detail"]


def test_le_verdict_porte_les_reglages_proposes(sandbox, monkeypatch):
    monkeypatch.setattr(sandbox.composite, "appeler_le_modele", lambda _c: json.dumps(
        {"noeuds": ["conversation", "synthese_vocale_en"], "proprietes": {"langue_ecrite": "fr"}}))
    monkeypatch.setattr(sandbox.composite, "rediger", lambda v: "ok")
    r = TestClient(sandbox.app, base_url=LOCAL).post(
        "/composite/verdict", headers=CLE_TEST, data={"phrase": "dis-le en anglais, texte en français"})
    assert r.status_code == 200, r.text
    v = r.json()
    assert [p["id"] for p in v["proprietes"]] == ["chat@0", "voix@1", "langue_ecrite"]
    assert v["proprietes"][2]["valeur"] == "fr"
    assert v["proprietes_sans_effet"] == []


def test_le_verdict_se_refait_sur_les_briques_sans_relire_la_phrase(sandbox, monkeypatch):
    def jamais(_c):
        raise AssertionError("le modele ne doit pas relire la phrase")

    monkeypatch.setattr(sandbox.composite, "appeler_le_modele", jamais)
    monkeypatch.setattr(sandbox.composite, "rediger", lambda v: "ok")
    r = TestClient(sandbox.app, base_url=LOCAL).post(
        "/composite/verdict", headers=CLE_TEST,
        data={"phrase": "p", "briques": "chat_max,voix_fr", "proprietes": '{"langue_ecrite": "en"}'})
    assert r.status_code == 200, r.text
    v = r.json()
    assert [e["brique"] for e in v["etapes"]] == ["chat_max", "voix_fr"]
    assert par_id(v["proprietes"])["langue_ecrite"]["valeur"] == "en"


def test_la_page_montre_la_traduction(page):
    rendu_debut = page.index("function montrerResultat(d){")
    rendu_fin = page.index("\n</script>", rendu_debut)
    reponse = {"fichier": "UklGRg==", "type": "audio/wav", "nom": "s.wav", "derniere": "Voix",
               "textes": [{"fonction": "Chat", "texte": "A lighthouse."}],
               "ecoute": {"texte_dit": "A lighthouse.", "fait": False, "motif": "test"},
               "traduction": {"langue": "français", "texte": "Un **phare**.", "motif": None}}
    code = (extrait(page)
            + "\nconst champs = {resultat: {innerHTML: ''}};"
            + "\nconst document = {getElementById: id => champs[id], querySelector: () => null};"
            + "\nconst URL = {createObjectURL: () => 'blob:x'};"
            + "\n(async () => {\nconst r = {corps: {json: async () => (" + json.dumps(reponse) + ")}};\n"
            + page[rendu_debut:rendu_fin] + "\nmontrerResultat(await r.corps.json());"
            + "\nconsole.log(champs.resultat.innerHTML);\n})();")
    html = node(code)
    assert "Le même texte en français" in html
    assert "<p>Un <strong>phare</strong>.</p>" in html


def test_la_page_montre_et_change_les_reglages(page):
    debut = page.index("function bloc(v){")
    fin = page.index("\nfunction typeDuFichier", debut)
    verdict = {"atteignable": "oui", "phrase": "ok",
               "etapes": [{"fonction": "Chat", "brique": "chat_auto", "entrees": ["texte"], "sorties": ["texte"]},
                          {"fonction": "Lire, anglais", "brique": "voix_en", "entrees": ["texte"], "sorties": ["audio"]}],
               "proprietes": [
                   {"id": "voix@1", "nom": "Langue de la voix", "etape": 1, "variante": True,
                    "valeur": "voix_en", "defaut": "voix_en",
                    "choix": [{"valeur": "voix_fr", "nom": "français"}, {"valeur": "voix_en", "nom": "anglais"}]},
                   {"id": "langue_ecrite", "nom": "Texte affiché en", "valeur": "meme", "defaut": "meme",
                    "note": "part chez <Google>",
                    "choix": [{"valeur": "meme", "nom": "la langue de la voix"}, {"valeur": "fr", "nom": "français"}]}],
               "proprietes_sans_effet": ["« couleur = bleu » : aucune étape"]}
    code = (page[debut:fin]
            + "\nconst v = " + json.dumps(verdict) + ";"
            + "\nconsole.log(bloc(v));"
            + "\nconsole.log('---');"
            + "\nconsole.log(changerReglage(v, 0, 'voix_fr'), changerReglage(v, 1, 'fr'),"
            + " changerReglage(v, 1, 'klingon'));"
            + "\nconsole.log(v.etapes[1].brique, JSON.stringify(reglagesChoisis(v)));"
            + "\nconsole.log(bloc(v));")
    avant, apres = node(code).split("---")
    assert "<select data-i='0'>" in avant and "<option value='voix_en' selected>anglais</option>" in avant
    assert "part chez" not in avant, "la note ne se montre que si le texte est traduit"
    assert "« couleur = bleu » : aucune étape" in avant
    assert "chaine valeur null" in apres
    assert 'voix_fr {"langue_ecrite":"fr"}' in apres, "une variante ne part pas comme valeur"
    assert "part chez &lt;Google&gt;" in apres


def test_changer_de_brique_remet_les_reglages_de_l_etape(page):
    debut = page.index("function changerReglage(")
    fin = page.index("\n}\n", debut) + 3
    v = {"etapes": [{"brique": "video_maison"}],
         "proprietes": [{"id": "video@0", "etape": 0, "variante": True, "valeur": "video_maison",
                         "defaut": "video_maison", "choix": [{"valeur": "video_maison"},
                                                             {"valeur": "video_rapide"}]},
                        {"id": "duree@0", "etape": 0, "valeur": "12", "defaut": "5",
                         "choix": [{"valeur": "5"}, {"valeur": "12"}]}]}
    code = (page[debut:fin] + "\nconst v = " + json.dumps(v) + ";"
            + "\nconsole.log(changerReglage(v, 0, 'video_rapide'), v.proprietes[1].valeur);")
    assert node(code).strip() == "chaine 5"


def test_un_reglage_a_choix_unique_est_grise(page):
    debut = page.index("function reglages(")
    fin = page.index("\n}\n", debut) + 3
    v = {"proprietes": [{"id": "definition@0", "nom": "Format", "valeur": "a", "defaut": "a",
                         "choix": [{"valeur": "a", "nom": "1280 × 704"}]}]}
    code = (page[debut:fin] + "\nfunction echapper(s){ return String(s); }"
            + "\nconsole.log(reglages(" + json.dumps(v) + "));")
    assert "<select data-i='0' disabled>" in node(code)


# --- Chaque étape reçoit SA consigne (23/09) -------------------------------------
# « very detailed description … voice spoken in french, and text written in
# english » : la lecture d'image recevait « text written in english » ET
# « Répondez en français », et la description tenait en deux phrases.

REPONSE_AVEC_CONSIGNES = json.dumps(
    {"noeuds": ["lecture_image", "synthese_vocale_fr"],
     "consignes": ["Décris cette image de façon très détaillée.", "Lis en français."],
     "proprietes": {"langue_ecrite": "en"}})


def test_le_lecteur_rend_une_consigne_par_etape(composite):
    graphe = composite.compiler("very detailed … voice in french, text in english",
                                lambda _c: REPONSE_AVEC_CONSIGNES, entree="image")
    chaine = composite.lier(graphe)
    assert chaine["etapes"][0]["consigne"] == "Décris cette image de façon très détaillée."
    assert "consigne" not in chaine["etapes"][1], "une voix ne suit aucune consigne"


def test_sans_consignes_lisibles_on_garde_la_phrase(composite):
    for brut in ('{"noeuds": ["lecture_image"]}',
                 '{"noeuds": ["lecture_image"], "consignes": ["a", "b"]}',
                 '{"noeuds": ["lecture_image"], "consignes": [3]}'):
        chaine = composite.lier(composite.compiler("p", lambda _c, b=brut: b, entree="image"))
        assert "consigne" not in chaine["etapes"][0]


def test_chaque_etape_part_avec_sa_consigne(composite):
    vues = []

    def lancer(etape, entree):
        vues.append((etape["brique"], etape["demande"]))
        return "texte"

    chaine = composite.lier(composite.compiler("la phrase entière", lambda _c: json.dumps(
        {"noeuds": ["conversation", "conversation"], "consignes": ["Traduis.", ""]})))
    composite.executer(chaine, lancer, garde_budget=lambda e: None)
    assert vues == [("chat_auto", "Traduis."), ("chat_auto", "la phrase entière")]


def test_la_consigne_de_la_lecture_d_image_ne_porte_plus_la_phrase(composite):
    etape = dict(etape_de(composite, "image_lecture"),
                 demande="Décris cette image de façon très détaillée.",
                 suivante="voix_fr", reglages={})
    consigne = composite._consigne_de_l_image(etape)
    assert "english" not in consigne and consigne.startswith("Décris cette image")


def test_les_consignes_renvoyees_sont_verifiees(composite):
    chaine = chaine_de(composite, ["image_lecture", "voix_fr"])
    composite.consignes_lues('["Décris en détail.", null]', chaine)
    assert chaine["etapes"][0]["consigne"] == "Décris en détail."
    composite.consignes_lues('["", null]', chaine)
    assert chaine["etapes"][0]["consigne"] is None
    for mauvais in ('["a"]', '{"a": 1}', '["a", "lis-le fort"]', '[1, null]',
                    '["' + "x" * 2001 + '", null]', "["):
        with pytest.raises(composite.CompositeRefuse):
            composite.consignes_lues(mauvais, chaine_de(composite, ["image_lecture", "voix_fr"]))


def test_le_verdict_montre_et_garde_les_consignes(sandbox, monkeypatch):
    monkeypatch.setattr(sandbox.composite, "appeler_le_modele", lambda _c: REPONSE_AVEC_CONSIGNES)
    monkeypatch.setattr(sandbox.composite, "rediger", lambda v: "ok")
    client = TestClient(sandbox.app, base_url=LOCAL)
    v = client.post("/composite/verdict", headers=CLE_TEST,
                    data={"phrase": "p", "entree": "image"}).json()
    assert v["etapes"][0]["consigne"] == "Décris cette image de façon très détaillée."
    assert "consigne" not in v["etapes"][1]
    # un reglage change : le verdict se refait, la consigne tapee reste
    v = client.post("/composite/verdict", headers=CLE_TEST,
                    data={"phrase": "p", "entree": "image", "briques": "image_lecture,voix_en",
                          "consignes": '["Compte les chats.", null]'}).json()
    assert v["etapes"][0]["consigne"] == "Compte les chats."


def test_la_route_lance_avec_la_consigne_montree(sandbox, monkeypatch):
    vues = []

    def lancer(etape, entree):
        vues.append(etape["demande"])
        return "Bonjour."

    monkeypatch.setattr(sandbox.composite, "lancer_par_le_routeur", lancer)
    r = TestClient(sandbox.app, base_url=LOCAL).post(
        "/composite/lancer", headers=CLE_TEST,
        data={"phrase": "la phrase", "briques": "chat_auto", "consignes": '["Dis bonjour."]'})
    assert r.status_code == 200, r.text
    assert vues == ["Dis bonjour."]


def test_la_page_montre_la_consigne_modifiable(page):
    debut = page.index("function bloc(v){")
    fin = page.index("\nfunction typeDuFichier", debut)
    verdict = {"atteignable": "oui", "phrase": "ok",
               "etapes": [{"fonction": "Lecture", "brique": "image_lecture", "entrees": ["image"],
                           "sorties": ["texte"], "consigne": "Décris <tout>"},
                          {"fonction": "Voix", "brique": "voix_fr", "entrees": ["texte"], "sorties": ["audio"]}]}
    code = (page[debut:fin] + "\nconst v = " + json.dumps(verdict) + ";"
            + "\nconsole.log(bloc(v));\nconsole.log(JSON.stringify(consignesChoisies(v)));")
    html = node(code)
    assert "<input data-c='0' value='Décris &lt;tout&gt;'" in html
    assert html.count("data-c=") == 1, "pas de consigne pour la voix"
    assert '["Décris <tout>",null]' in html
