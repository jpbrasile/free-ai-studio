"""Les règles numérotées du Studio vidéo (30/09), rejouées sur les défauts de l'audit.

Demande du propriétaire : « add a reviewer that say for each clip that rule n° 1 to xx are
followed ». Chaque test part d'un défaut VU dans les deux films du 30/09 (PLAN.md, audit)
et vérifie que la règle le signale.
"""
import pytest


@pytest.fixture
def r(sandbox):
    return sandbox.regles


def el(nom, debut, fin="", mouvement="none"):
    return {"nom": nom, "debut": debut, "mouvement": mouvement, "fin": fin or debut}


LEILA = {"id": "l1", "nom": "Leila", "genre": "personne", "description": "girl", "voix": None}
MARC = {"id": "m1", "nom": "Marc", "genre": "personne", "description": "boy", "voix": None}
KITE = {"id": "k1", "nom": "yellow kite", "genre": "objet", "description": "kite", "voix": None}


def test_les_regles_sont_numerotees_par_etape(r):
    assert [n for n, _, _ in r.REGLES] == list(range(16))
    assert r.NUMEROS == {"texte": [0, 1, 2, 3, 4, 5, 13, 14], "depart": [6, 7, 8], "clip": [9, 10, 11, 12, 15]}
    assert r.AVANT_TOURNAGE == [0, 1, 2, 3, 4, 5, 13, 14, 6, 7, 8]


def _ecoute(r, texte, elements=None):
    plan = {"image_paroles": texte, "ambiance": "", "enchainement": "coupe",
            "elements": elements if elements is not None else
            [el("Leila", "foreground, centre"), el("Marc", "off-frame", "foreground, right", "walks in and stops")]}
    return r.regles_texte([plan], {"ok": True, "problemes": []}, [LEILA, MARC])[0][14]


def test_regle_14_qui_ecoute_reagit(r):
    """Campus, plan 1, 01/10, quatre graines : Tyler parle, Leila garde les yeux sur la carte.
    Le texte ne disait rien d'elle après la réplique."""
    x = _ecoute(r, "In a medium shot, Leila stands at the centre holding the map. Marc walks in, stops at "
                   "the right, facing left towards Leila, and says, amused: « Hey, are you lost? »")
    assert x["ok"] is False and "Leila" in x["pourquoi"] and "Marc" in x["pourquoi"]


@pytest.mark.parametrize("apres", [
    "Leila looks up from the map and turns her head towards him.",
    "Leila keeps reading without looking at him.",
    "Leila answers: « A little. »",
])
def test_regle_14_la_reaction_ou_l_absence_voulue_passent(r, apres):
    x = _ecoute(r, "Leila stands at the centre holding the map. Marc walks in, stops at the right, facing "
                   "Leila, and says: « Hey, are you lost? » " + apres)
    assert x["ok"] is True, x


def test_regle_14_ne_s_applique_qu_a_un_dialogue_entre_presents(r):
    seul = _ecoute(r, "Leila looks at the map and says: « Where am I? »", [el("Leila", "foreground, centre")])
    assert seul["ok"] is None
    sans = _ecoute(r, "Leila looks at the map. Marc walks in and stops at the right.")
    assert sans["ok"] is None


@pytest.mark.parametrize("texte", [
    # Campus, plan 1, 01/10 : la phrase même qui a fait traverser puis tourner Tyler.
    "Tyler walks in from off-frame at the left, stops in the foreground at the right, facing left.",
    "Tyler comes in from the right and stops beside Leila.",
    "Marc walks past Leila and stops at the left.",
    "Lea passes in front of James, then sits down.",
    "Marc crosses the frame and stops at the bench.",
])
def test_regle_13_le_trajet_d_un_personnage_n_est_pas_ecrit(r, texte):
    """Propriétaire, 01/10 : « simply say the start and the end pose and leave H3 free to execute »."""
    plan = {"image_paroles": texte, "ambiance": "", "enchainement": "coupe", "elements": []}
    x = r.regles_texte([plan], {"ok": True, "problemes": []}, [LEILA, MARC])[0]
    assert x[13]["ok"] is False and "Trajet" in x[13]["pourquoi"]


def test_regle_13_le_depart_et_l_arrivee_seuls_passent(r):
    """Le départ et l'arrivée, sans chemin ; le trajet d'un objet (PHYSIQUE l'exige) et
    une réplique qui dit « left » ne comptent pas. Le trajet dans le tableau, si."""
    plan = {"image_paroles": "Tyler walks in and stops in the foreground at the right, facing left towards "
                             "Leila. The only ball rolls from the left and stops against the wall. "
                             "Leila says: « I came from the left side of campus. »",
            "ambiance": "", "enchainement": "coupe",
            "elements": [el("Tyler", "off-frame", "foreground, right, facing left", "walks in and stops")]}
    x = r.regles_texte([plan], {"ok": True, "problemes": []}, [LEILA, MARC])[0]
    assert x[13]["ok"] is True, x[13]
    plan["elements"] = [el("Tyler", "off-frame", "foreground, right", "walks in from the left, stops")]
    x = r.regles_texte([plan], {"ok": True, "problemes": []}, [LEILA, MARC])[0]
    assert x[13]["ok"] is False and "from the left" in x[13]["pourquoi"]


def test_regle_1_un_present_absent_du_texte(r):
    """Parc, plan 1 : Marc au tableau, absent du texte, absent de l'image."""
    plan = {"image_paroles": "Leila holds the yellow kite.", "ambiance": "", "enchainement": "coupe",
            "elements": [el("Leila", "foreground, centre"), el("Marc", "background, left"),
                         el("the yellow kite", "held by Leila")]}
    x = r.regles_texte([plan], {"ok": True, "problemes": []}, [LEILA, MARC, KITE])[0]
    assert x[1]["ok"] is False and "Marc" in x[1]["pourquoi"] and "kite" not in x[1]["pourquoi"]


def test_regle_0_le_francais_qui_reste(r):
    plan = {"image_paroles": "La petite librairie est dans le fond, avec une étagère.", "ambiance": "",
            "enchainement": "coupe", "elements": []}
    x = r.regles_texte([plan], {"ok": True, "problemes": []}, [])[0]
    assert x[0]["ok"] is False and x[1]["ok"] is None


def test_regle_2_une_remarque_bloquante_restee(r):
    """Parc, plan 2 : la remarque bloquante et la correction ratée, tournées quand même."""
    plans = [{"image_paroles": "A.", "ambiance": "", "enchainement": "coupe", "elements": []}] * 2
    x = r.regles_texte(plans, {"ok": False, "problemes": [{"plan": 2, "quoi": "deux actions"}]}, [])
    assert x[0][2]["ok"] is True and x[1][2] == {"ok": False, "pourquoi": "deux actions"}
    assert r.regles_texte(plans, {"ok": None}, [])[0][2]["ok"] is None


def test_regle_3_deux_personnages_au_meme_endroit(r):
    """Librairie, plan 3 : James et Léa tous deux « foreground, left »."""
    lea = dict(LEILA, id="lea", nom="Léa")
    james = dict(MARC, id="ja", nom="James")
    plan = {"image_paroles": "James and Léa stand.", "ambiance": "", "enchainement": "coupe",
            "elements": [el("James", "in the foreground, left, standing"), el("Léa", "in the foreground, left")]}
    x = r.regles_texte([plan], {"ok": True, "problemes": []}, [lea, james])[0]
    assert x[3]["ok"] is False and "James et Léa" in x[3]["pourquoi"]
    plan["elements"][1] = el("Léa", "in the background, right")
    assert r.regles_texte([plan], {"ok": True, "problemes": []}, [lea, james])[0][3]["ok"] is True


def test_regle_4_chaque_locuteur_a_sa_voix_dans_sa_langue(r):
    """Décision du 30/09 : « all speaker is created with a profile before hand including
    its voice in the appropriate language ». Aucune fiche des deux films n'avait de voix."""
    plan = {"image_paroles": "Leila looks up. Marc points and says : « Il vole ! »", "ambiance": "",
            "enchainement": "coupe", "elements": []}
    regle = lambda fiches, langues=None: r.regle_voix(plan, fiches, langues or {}, "French")
    x = regle([LEILA, MARC])
    assert x["ok"] is False and "Marc n'a pas de voix" in x["pourquoi"]
    marc = dict(MARC, voix={"source": "generee", "duree_s": 5.0})
    assert "n'est pas notée" in regle([LEILA, marc])["pourquoi"]
    marc["voix"]["langue"] = "English"
    x = regle([LEILA, marc])
    assert x["ok"] is False and "Marc parle français, sa voix est en anglais" in x["pourquoi"]
    assert regle([LEILA, marc], {"m1": "English"})["ok"] is True
    marc["voix"]["langue"] = "French"
    assert regle([LEILA, marc]) == {"ok": True, "pourquoi": ""}
    # La marque de langue d'une réplique l'emporte.
    plan["image_paroles"] = "Marc says : « [English] It flies! »"
    assert "parle anglais" in regle([LEILA, marc])["pourquoi"]
    # Personne de nommé, ou un nom sans fiche.
    plan["image_paroles"] = "« Il vole ! »"
    assert "aucun personnage de fiche n'est nommé" in regle([LEILA, marc])["pourquoi"]
    plan.update(image_paroles="Tom says : « Il vole ! »", elements=[el("Tom", "left")])
    assert "Tom n'a pas de fiche de personne" in regle([LEILA, marc])["pourquoi"]
    # Revue du 30/09 : un nom du tableau sans verbe de parole ne vole pas la réplique.
    plan.update(image_paroles="The yellow kite dips. Marc shouts « Il vole ! »",
                elements=[el("the yellow kite", "sky"), el("Marc", "left")])
    assert regle([LEILA, marc, KITE])["ok"] is True
    # La voix qui ne part pas avec ce plan (mode première image, ou au-delà de trois).
    plan["image_paroles"] = "Marc says : « Il vole ! »"
    assert "ne part pas avec ce plan" in r.regle_voix(plan, [LEILA, marc], {}, "French", envoyees=set())["pourquoi"]
    assert r.regle_voix(plan, [LEILA, marc], {}, "French", envoyees={"m1"})["ok"] is True
    # Pas de réplique : sans objet.
    plan["image_paroles"] = "Leila runs."
    assert regle([LEILA])["ok"] is None


def test_regle_4_une_suite_sans_fiche_part_sans_voix(r):
    """Parc, plan 3 : « Ils volent ! » dans une suite, dit d'un timbre inventé. Depuis le
    30/09, une suite garde ses fiches et ses voix quand elles tiennent avec la dernière
    image ; sinon (envoyees vide) la faute reste."""
    marc = dict(MARC, voix={"source": "generee", "duree_s": 5.0, "langue": "French"})
    plan = {"image_paroles": "Marc says : « Il vole ! »", "ambiance": "", "enchainement": "suite", "elements": []}
    x = r.regle_voix(plan, [marc], {}, "French", envoyees=set())
    assert x["ok"] is False and "ne part pas avec ce plan (plan « suite »" in x["pourquoi"]
    assert r.regle_voix(plan, [marc], {}, "French", envoyees={"m1"})["ok"] is True


def test_qui_parle_suit_la_regle_d_attribution(r):
    t = "Léa smiles. James turns to Léa and says « Of course. » She answers « Merci. »"
    assert r.qui_parle(t, ["Léa", "James"]) == [("Of course.", 1, None), ("Merci.", 0, None)]
    assert r.qui_parle("« Hi. »", ["Léa"]) == [("Hi.", None, None)]
    assert r.qui_parle("Lea says « Hi. »", ["Léa"]) == [("Hi.", 0, None)]
    assert r.qui_parle("Tom asks « Hi? »", ["Léa"], ["Tom"]) == [("Hi?", None, "Tom")]


def test_position_ignore_le_regard_et_la_main(r):
    """Revue du 30/09 : « facing left » ou « right hand » n'est pas une place du cadre."""
    assert r.position("in the foreground, right, facing left") == ("foreground", "right")
    assert r.position("background, centre, kite in her left hand") == ("background", "centre")


def test_regle_5_rien_n_est_cree_deux_fois(r):
    """Présent au début ET « enters » : le modèle le dessine deux fois (Léa, librairie)."""
    plan = {"image_paroles": "Léa enters through the door and stops.", "ambiance": "", "enchainement": "coupe",
            "elements": [el("Léa", "in the foreground, left")]}
    x = r.regle_deux_fois([plan], 1)
    assert x["ok"] is False and "Léa est déjà à l'image au début" in x["pourquoi"]
    plan["elements"] = [el("Léa", "off-frame", "in the foreground, left")]
    assert r.regle_deux_fois([plan], 1)["ok"] is True
    # Le mot d'une réplique n'est pas une action.
    plan.update(image_paroles="Léa says « It appears now. »", elements=[el("Léa", "in the foreground, left")])
    assert r.regle_deux_fois([plan], 1)["ok"] is True


@pytest.mark.parametrize("texte", ["Léa walks into the room.", "Léa comes back to the counter.",
                                   "Léa reappears behind the shelf.", "Léa runs in.", "Léa is back.",
                                   "James waits. She enters the shop."])
def test_regle_5_les_entrees_que_la_revue_a_trouvees(r, texte):
    """Revue du 30/09 : seules « enters » et « walks in » étaient lues ; le pronom échappait."""
    plan = {"image_paroles": texte, "ambiance": "", "enchainement": "suite",
            "elements": [el("Léa", "in the foreground, left"), el("James", "background, right")]}
    x = r.regle_deux_fois([plan], 1)
    assert x["ok"] is False and ("Léa" in x["pourquoi"] or "James" in x["pourquoi"])


def test_regle_5_revenir_dans_le_cadre_n_est_pas_entrer(r):
    """Film parc2, 30/09 : « walks back to the middle ground » est un déplacement."""
    plan = {"image_paroles": "Marc picks up the kite, walks back to the middle ground, centre, and stops.",
            "ambiance": "", "enchainement": "suite",
            "elements": [el("Marc", "background, right"), el("the kite", "on the grass")]}
    assert r.regle_deux_fois([plan], 1)["ok"] is True
    plan["image_paroles"] = "Marc walks back into the shop."
    assert r.regle_deux_fois([plan], 1)["ok"] is False


def test_regle_5_un_second_exemplaire_et_une_entree_sans_nom(r):
    plan = {"image_paroles": "A second Léa walks up.", "ambiance": "", "enchainement": "coupe",
            "elements": [el("Léa", "in the foreground, left")]}
    assert "un second Léa" in r.regle_deux_fois([plan], 1)["pourquoi"]
    plan["image_paroles"] = "She enters the shop."
    assert "par un pronom" in r.regle_deux_fois([plan], 1)["pourquoi"]


def test_regle_5_une_action_refaite_au_plan_suivant(r):
    """Revue du 30/09 : le cerf-volant retombe une seconde fois, coupe ou suite."""
    p1 = {"image_paroles": "The kite falls.", "enchainement": "coupe",
          "elements": [el("kite", "sky", "on the grass", "falls down to the grass")]}
    for enchainement in ("coupe", "suite"):
        p2 = {"image_paroles": "The kite falls.", "enchainement": enchainement,
              "elements": [el("kite", "on the grass", "on the grass", "falls down onto the grass")]}
        assert "kite refait au plan 2 le mouvement du plan 1" in r.regle_deux_fois([p1, p2], 2)["pourquoi"]
    p2["elements"][0]["mouvement"] = "is picked up by Marc"
    assert r.regle_deux_fois([p1, p2], 2)["ok"] is True


def test_hors_champ_est_une_seule_regle(sandbox):
    """Revue du 30/09 : « out of frame » comptait présent pour une règle, absent pour l'autre."""
    v = sandbox.video_h3
    assert v.hors_champ("off-frame") and v.hors_champ("out of frame") and v.hors_champ("not yet visible")
    assert not v.hors_champ("in the foreground, left")


def test_regle_5_une_suite_repart_de_la_derniere_image_du_plan_d_avant(r):
    """Une suite part de la dernière image : ce qui y est ne s'y recrée pas."""
    avant = {"image_paroles": "x", "enchainement": "coupe",
             "elements": [el("Marc", "background, left", "foreground, centre, standing"),
                          el("the kite", "held", "off-frame at the top"),
                          el("Leila", "background, right")]}
    suite = {"image_paroles": "Marc waves. Leila walks in from the left.", "enchainement": "suite",
             "elements": [el("Marc", "background, left, standing"), el("Leila", "off-frame")]}
    x = r.regle_deux_fois([avant, suite], 2)
    assert x["ok"] is False
    assert "Marc finit le plan d'avant foreground, centre et repart background, left" in x["pourquoi"]
    assert "Leila est déjà sur la dernière image du plan d'avant, pas hors champ" in x["pourquoi"]
    assert "kite" not in x["pourquoi"]   # parti hors champ : il peut revenir
    suite["elements"] = [el("Marc", "foreground, centre")]
    assert "Leila est sur la dernière image du plan d'avant mais absent du tableau" in \
        r.regle_deux_fois([avant, suite], 2)["pourquoi"]
    suite["elements"] = [el("Marc", "foreground, centre"), el("Leila", "background, right")]
    suite["image_paroles"] = "Marc waves. Leila smiles."
    assert r.regle_deux_fois([avant, suite], 2) == {"ok": True, "pourquoi": ""}
    # Une coupe peut tout reposer : pas de contrôle contre le plan d'avant.
    suite.update(enchainement="coupe", elements=[el("Marc", "background, left")])
    assert r.regle_deux_fois([avant, suite], 2)["ok"] is True


def test_regles_6_a_8_l_image_de_depart(r):
    """Parc, plan 1 : Marc absent, deux cerfs-volants ; bulles de mon script du 30/09."""
    plan = {"elements": [el("Leila", "foreground, centre"), el("Marc", "background, left"),
                         el("the yellow kite", "held by Leila"), el("Tom", "off-frame")]}
    att = r.attendus_du_depart(plan, [("Leila", "girl", "personne"), ("yellow kite", "kite", "objet")])
    assert [a["nom"] for a in att] == ["Leila", "Marc", "the yellow kite"]
    assert att[0]["personne"] and not att[1]["personne"] and att[2]["description"] == "kite"
    consigne = r.consigne_presence(att)
    assert "each exactly once" in consigne and "2. Marc, expected: background, left." in consigne
    presence = r.lire_presence('ok {"comptes": [1, 0, 2], "texte_ajoute": true, "remarque": "x"}', 3)
    x = r.regles_depart(att, presence, {"Leila": "faible"})
    assert x[6] == {"ok": False, "pourquoi": "Compté : Marc ×0, the yellow kite ×2."}
    assert x[7]["ok"] is False and x[8]["ok"] is False
    x = r.regles_depart(att, None, {"Leila": None})
    assert x[6]["ok"] is None and x[7]["ok"] is None
    # 02/10 : un visage trop petit ne se juge pas ; un autre visage faible reste une faute.
    x = r.regles_depart(att, presence, {"Leila": "trop petit"})
    assert x[7]["ok"] is None and "trop petit" in x[7]["pourquoi"]
    assert r.regles_depart(att, presence, {"Leila": "trop petit", "Marc": "faible"})[7]["ok"] is False
    assert r.regles_depart(att, presence, {"Leila": "forte"})[7]["ok"] is True
    with pytest.raises(ValueError):
        r.lire_presence('{"comptes": [1], "texte_ajoute": false}', 3)
    assert set(r.sans_depart({"enchainement": "suite"})) == {6, 7, 8}


def test_l_age_d_un_personnage_ne_part_pas_aux_juges_d_image(r):
    """02/10, Leila : « adolescente de 15 ans » à côté de l'image, et Gemini refusait tout
    (PROHIBITED_CONTENT) ; sans le chiffre, le même contrôle répondait."""
    v = r.video_h3
    leila = "adolescente de 15 ans, cheveux châtain clair, sweat jaune"
    assert v.sans_age(leila) == "adolescente, cheveux châtain clair, sweat jaune"
    assert v.sans_age("a 15-year-old girl in a yellow hoodie") == "a girl in a yellow hoodie"
    assert v.sans_age("a girl aged 15, 15 years old") == "a girl,"
    assert v.sans_age("âgée de 9 ans") == ""
    assert v.sans_age("deux antennes, une ceinture bleue") == "deux antennes, une ceinture bleue"
    att = r.attendus_du_depart({"elements": [el("Leila", "foreground, left")]}, [("Leila", leila, "personne")])
    consigne = r.consigne_presence(att)
    assert "15" not in consigne and "Leila (adolescente, cheveux châtain clair" in consigne
    assert "15" not in v.consigne_jugement(["Leila"], "Leila, a 15-year-old girl, looks up.")
    # Ailleurs, la fiche garde son âge.
    assert att[0]["description"] == leila


def test_regles_9_a_12_le_plan_tourne(r):
    plan = {"elements": [el("Marc", "left", "foreground, centre, clapping")]}
    consigne = r.consigne_regles_clip(["Marc"], plan)
    assert "Image 2 is a contact sheet" in consigne and "Marc: foreground, centre, clapping." in consigne
    assert "walks in or appears a second time" in consigne
    x = r.lire_regles_clip('{"regles": [{"n": 10, "ok": false, "pourquoi": "deux Marc"}, {"n": 11, "ok": true}]}')
    assert x[10] == {"ok": False, "pourquoi": "deux Marc"} and x[11]["ok"] is True and x[12]["ok"] is None
    assert all(v["ok"] is None for v in r.lire_regles_clip("rien").values())
    assert r.regle_paroles({"attendu": "Il vole", "entendu": "Ils volent", "ok": False})["ok"] is False
    assert r.regle_paroles({"attendu": ""})["ok"] is None
    rapport = [{"plan": 1, "regles": r.en_liste({9: r.resultat(True), 10: r.resultat(False, "deux Marc")})}]
    assert rapport[0]["regles"][1]["regle"].startswith("Aucun personnage")
    assert r.non_suivies(rapport) == [(1, 10, "deux Marc")] and r.non_suivies(rapport, [9]) == []
