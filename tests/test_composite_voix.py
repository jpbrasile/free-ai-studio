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
    assert "lue à haute voix" in oral and "en anglais" in oral and "pas de titre" in oral
    assert "en français" in composite._consigne_du_chat(dict(etape, suivante="voix_fr"), None)
    # « décris DANS LE DÉTAIL … à voix haute » a rendu une phrase (23/09) :
    # la consigne orale règle la forme, pas la longueur.
    assert "niveau de détail demandés" in oral


def test_la_lecture_d_image_sait_aussi_qu_elle_ecrit_pour_une_voix(composite):
    etape = {"brique": "image_lecture", "fonction": "Lecture", "demande": "décris en anglais"}
    assert "lue à haute voix" not in composite._consigne_de_l_image(etape)
    oral = composite._consigne_de_l_image(dict(etape, suivante="voix_en"))
    assert oral.startswith("décris en anglais")
    assert "lue à haute voix" in oral and "en anglais" in oral and "pas de titre" in oral


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
    rendu_debut = page.index("    const d = await r.corps.json();")
    rendu_fin = page.index("  } finally {", rendu_debut)
    reponse = {"fichier": "UklGRg==", "type": "audio/wav", "nom": "s.wav", "derniere": "Voix",
               "textes": [{"fonction": "Chat", "texte": "A lighthouse."}],
               "ecoute": {"texte_dit": "A lighthouse.", "fait": False, "motif": "test"},
               "traduction": {"langue": "français", "texte": "Un **phare**.", "motif": None}}
    code = (extrait(page)
            + "\nconst champs = {resultat: {innerHTML: ''}};"
            + "\nconst document = {getElementById: id => champs[id]};"
            + "\nconst URL = {createObjectURL: () => 'blob:x'};"
            + "\n(async () => {\nconst r = {corps: {json: async () => (" + json.dumps(reponse) + ")}};\n"
            + page[rendu_debut:rendu_fin]
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
