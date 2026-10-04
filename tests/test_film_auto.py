"""Le film automatique (03/10/2026) : d'un texte simple au film fini, par les routes du Studio."""
import importlib
import json

import pytest


@pytest.fixture
def fa(sandbox):
    return importlib.import_module("film_auto")


class FauxStudio:
    """Les routes du Studio, simulées ; garde l'ordre des appels."""

    def __init__(self, verdicts_maitre=("ok",), refus_regles=False, verdicts_clips=()):
        self.appels, self.jobs, self.n = [], {}, 0
        self.verdicts_maitre, self.refus_regles = list(verdicts_maitre), refus_regles
        self.verdicts_clips = list(verdicts_clips)
        self.sans_coupe = set()   # les maîtres que le Studio refuse de déplier
        self.fiches = []          # les fiches déjà faites

    def job(self, statut="succeeded"):
        self.n += 1
        jid = "%032x" % self.n
        self.jobs[jid] = {"id": jid, "status": statut}
        return dict(self.jobs[jid])

    def __call__(self, methode, chemin, corps=None):
        self.appels.append((methode, chemin, json.loads(json.dumps(corps))))
        if methode == "GET" and chemin.startswith("/jobs/"):
            return 200, self.jobs[chemin.split("/")[-1]]
        if methode == "GET" and chemin == "/video-h3/fiches":
            return 200, {"fiches": list(self.fiches), "angles": []}
        if chemin == "/video-h3/fiches":
            return 200, {"id": "f%011d" % len(self.appels)}
        if chemin.startswith("/video-h3/fiches/"):
            return 200, {}
        if chemin == "/video-h3/scenario/decouper":
            return 200, {"plans": [{"image_paroles": "Plan %d." % k, "enchainement": "suite" if k else "coupe"} for k in range(4)]}
        if chemin == "/video-h3/maitre":
            if self.refus_regles and not corps.get("forcer"):
                return 409, {"detail": "Règle 2 : la lumière change."}
            return 200, self.job()
        if chemin.endswith("/juger"):
            if self.verdicts_maitre and "deplier" not in " ".join(c for _m, c, _x in self.appels):
                v = self.verdicts_maitre.pop(0)
                return 200, {"verdict": v, "defauts": [] if v == "ok" else [{"quoi": "deux fillettes"}]}
            v = self.verdicts_clips.pop(0) if self.verdicts_clips else "ok"
            return 200, {"verdict": v, "defauts": [] if v == "ok" else [{"quoi": "geste manquant"}]}
        if chemin.endswith("/deplier"):
            if chemin.split("/")[-2] in self.sans_coupe:
                return 409, {"detail": "Le clip maître n'a pas fait la coupe du plan 2 : rejouez-le avant de le déplier."}
            if corps.get("plans"):
                return 200, {"clips": [self.job()["id"]], "cles": [[62, 123]], "plans": corps["plans"]}
            return 200, {"clips": [self.job()["id"], self.job()["id"]], "cles": [[0, 60], [62, 123]]}
        if chemin == "/video-h3/finaliser":
            # Comme le Studio : le film 4K est un autre travail, nommé par la finalisation.
            film, fin = self.job()["id"], self.job()
            self.jobs[fin["id"]]["finalisation"] = {"film": film}
            return 200, fin
        if chemin in ("/chanson/creer", "/video-h3/montage", "/video-h3/musique"):
            return 200, self.job()
        return 404, {"detail": "route inconnue " + chemin}


def chat(consigne):
    if "characters" in consigne:
        return '{"personnages": [{"nom": "Oscar", "description": "un vieux gardien de phare", "genre": "personne"}]}'
    return "gentle orchestral score, strings and celesta, slow tempo, hopeful"


def chat_sf(consigne):
    if "characters" in consigne:
        return ('{"personnages": [{"nom": "Leila", "description": "une adolescente", "genre": "personne"},'
                ' {"nom": "Pixel", "description": "un petit robot rond", "genre": "animal"}]}')
    if "sequences" in consigne:
        n = int(consigne.split("exactly ")[1].split()[0])
        return json.dumps({"sequences": ["Leila trouve une capsule." if k == 0 else "Leila et Pixel montent. %d" % k
                                         for k in range(n)]})
    return "ambient synth score"


def test_un_film_de_2_minutes_se_tourne_en_huit_sequences_de_15_s(fa, tmp_path):
    """04/10, propriétaire : « un autre film de science fiction avec Leila de 2 mn (15 s par clip) »."""
    studio = FauxStudio(verdicts_maitre=("ok",) * 8)
    studio.fiches = [{"id": "c978c4e9daaa", "nom": "Leila", "angles": ["face", "trois_quarts", "pied", "profil"],
                      "cree_le": "2026-09-28 16:31:50", "description": "adolescente de 15 ans"},
                     {"id": "aaaaaaaaaaaa", "nom": "leila", "angles": ["face"], "cree_le": "2026-10-01 10:00:00"}]
    etat = fa.nouvel_etat("Leila trouve un robot tombé du ciel et l'aide à rentrer.", duree_s=120)
    fa.Film(etat, tmp_path, studio, chat_sf, dormir=lambda s: None).derouler()
    assert etat["statut"] == "fini", etat["erreur"]
    assert etat["faites"] == list(fa.Film.ETAPES_SEQUENCES)
    # Leila garde sa fiche (la plus complète) ; Pixel, nouveau, en reçoit une.
    assert etat["fiches"][0]["id"] == "c978c4e9daaa"
    assert [c for m, c, _x in studio.appels if c == "/video-h3/fiches" and m == "POST"] == ["/video-h3/fiches"]
    # Le chat dit « animal » pour le robot ; le Studio n'a que des fiches « personne » pour un personnage.
    assert next(x for m, c, x in studio.appels if c == "/video-h3/fiches" and m == "POST")["genre"] == "personne"
    maitres = [x for m, c, x in studio.appels if c == "/video-h3/maitre"]
    assert len(maitres) == 8 and {x["definition"] for x in maitres} == {"768p"}
    assert {x["longueur_maitre"] for x in maitres} == {362}
    # La séquence 1 ne nomme que Leila : Pixel n'est pas donné au clip.
    assert maitres[0].get("fiche") == "c978c4e9daaa" and len(maitres[1]["fiches"]) == 2
    assert not any(c.endswith("/deplier") for _m, c, _x in studio.appels)
    montage = next(x for m, c, x in studio.appels if c == "/video-h3/montage")
    assert montage["clips"] == [s["clip"] for s in etat["sequences"]]
    assert next(x for m, c, x in studio.appels if c == "/chanson/creer")["duree"] == "2"
    # Une suite dans le clip d'une séquence : H3 coupe ou fond quand même ; chaque plan y est une coupe.
    assert {p["enchainement"] for x in maitres for p in x["plans"]} == {"coupe"}


def test_une_sequence_fautive_est_rejouee_et_la_reprise_saute_les_tournees(fa, tmp_path):
    studio = FauxStudio(verdicts_maitre=("defaut", "ok", "ok"))
    etat = fa.nouvel_etat("Leila trouve un robot.", duree_s=30)
    film = fa.Film(etat, tmp_path, studio, chat_sf, dormir=lambda s: None)
    film.derouler()
    assert etat["statut"] == "fini", etat["erreur"]
    assert [len(s["maitres"]) for s in etat["sequences"]] == [2, 1]
    assert etat["sequences"][0]["clip"] == etat["sequences"][0]["maitres"][1]["job"]
    # Reprise d'un tournage interrompu après la séquence 1 : elle n'est pas retournée.
    etat["faites"] = etat["faites"][:3]
    del etat["sequences"][1]["clip"]
    avant = len(studio.appels)
    studio.verdicts_maitre = ["ok"]
    fa.Film(etat, tmp_path, studio, chat_sf, dormir=lambda s: None).derouler()
    assert len([1 for _m, c, _x in studio.appels[avant:] if c == "/video-h3/maitre"]) == 1


def test_la_duree_du_film_est_bornee_et_l_essai_a_deux_sequences(fa):
    assert "sequences" not in fa.nouvel_etat("Oscar allume le phare.", duree_s=15)["reglages"]
    essai = fa.nouvel_etat("Oscar allume le phare.", essai=True, duree_s=120)["reglages"]
    assert essai["sequences"] == 2 and essai["definition_maitre"] == "480p"
    with pytest.raises(ValueError):
        fa.nouvel_etat("Oscar allume le phare.", duree_s=121)
    with pytest.raises(ValueError):
        fa.lire_sequences('{"sequences": ["a", "b"]}', 3)
    # « Le robot perdu », 04/10 : un personnage absent de l'image de départ n'a que son nom.
    assert "visible, in plain view, at its very first moment" in fa.CONSIGNE_SEQUENCES


def test_chaque_plan_recoit_une_camera_du_menu_jamais_fixe_par_defaut(fa, tmp_path):
    """04/10, propriétaire : « la caméra doit être mise en œuvre aussi » (tout était « static shot »)."""
    cams = fa.lire_cameras('{"cameras": [{"mouvement": "suit", "amplitude": "", "vitesse": "lente"},'
                           ' {"mouvement": "fixe"}, {"mouvement": "fixe"}, {"mouvement": "envol"}]}', 5)
    assert [c["mouvement"] for c in cams] == ["suit", "fixe", "avance", "avance", "avance"]
    assert cams[0]["vitesse"] == "lente" and cams[2] == fa.CAMERA_SECOURS
    assert fa.lire_cameras("pas de json", 2) == [fa.CAMERA_SECOURS] * 2

    def chat_camera(consigne):
        if "camera movement" in consigne:
            assert '"bascule_haut"' in consigne and '"auto"' not in consigne
            return '{"cameras": [{"mouvement": "bascule_haut", "amplitude": "petite", "vitesse": "lente"}]}'
        return chat(consigne)
    studio = FauxStudio()
    etat = fa.nouvel_etat("Oscar allume le phare.")
    fa.Film(etat, tmp_path, studio, chat_camera, dormir=lambda s: None).derouler()
    assert etat["statut"] == "fini", etat["erreur"]
    maitre = next(x for m, c, x in studio.appels if c == "/video-h3/maitre")
    assert maitre["plans"][0]["camera"]["mouvement"] == "bascule_haut"
    assert maitre["plans"][1]["camera"] == fa.CAMERA_SECOURS


def test_l_essai_a_blanc_va_du_texte_au_film_par_les_routes_du_studio(fa, tmp_path):
    studio = FauxStudio()
    etat = fa.nouvel_etat("Oscar allume le phare. Un bateau rentre au port.", essai=True)
    fa.Film(etat, tmp_path, studio, chat, dormir=lambda s: None).derouler()
    assert etat["statut"] == "fini", etat["erreur"]
    routes = [c for m, c, _x in studio.appels if m == "POST"]
    assert routes[:4] == ["/video-h3/fiches", "/video-h3/fiches/f00000000002/images/face",
                          "/video-h3/fiches/f00000000002/planche", "/video-h3/scenario/decouper"]
    corps = dict((c, x) for m, c, x in studio.appels if m == "POST")
    # Essai à blanc : deux plans, maître de 124 images en 480p, sur la carte d'ici ; musique chez Modal.
    assert len(corps["/video-h3/maitre"]["plans"]) == 2
    assert corps["/video-h3/maitre"]["longueur_maitre"] == 124 and corps["/video-h3/maitre"]["ou"] == "maison"
    assert corps["/chanson/creer"]["ou"] == "modal" and corps["/chanson/creer"]["lora"] is True
    assert corps["/video-h3/finaliser"] == {"job": etat["film_monte"], "echelle": "4k", "ou": "maison"}
    assert corps["/video-h3/musique"]["film"] == etat["film_4k"] and etat["film"]
    assert studio.jobs[etat["film_4k"]].get("finalisation") is None   # le film, pas la finalisation
    assert etat["faites"] == list(fa.Film.ETAPES)
    assert json.loads((tmp_path / (etat["id"] + ".json")).read_text(encoding="utf-8"))["statut"] == "fini"


def test_le_maitre_fautif_est_rejoue_et_le_moins_fautif_deplie(fa, tmp_path):
    studio = FauxStudio(verdicts_maitre=("defaut", "defaut", "defaut"), refus_regles=True)
    etat = fa.nouvel_etat("Oscar allume le phare.")
    fa.Film(etat, tmp_path, studio, chat, dormir=lambda s: None).derouler()
    assert etat["statut"] == "fini", etat["erreur"]
    maitres = [x for m, c, x in studio.appels if c == "/video-h3/maitre"]
    # Refus des règles : noté, puis « tourner quand même » ; trois essais, aucun « ok ».
    assert [x["forcer"] for x in maitres] == [False, True, True, True]
    assert len(etat["maitres"]) == 3 and any(j["etape"] == "maitre_regles" for j in etat["journal"])
    deplier = next(x for m, c, x in studio.appels if c.endswith("/deplier"))
    assert deplier["forcer"] is True and deplier["definition"] == "768p"
    # Le maître en 480p (ses coupes franches), les plans dépliés en 768p.
    assert {x["definition"] for x in maitres} == {"480p"}


def test_une_etape_impossible_arrete_le_film_et_dit_pourquoi(fa, tmp_path):
    studio = FauxStudio()
    etat = fa.nouvel_etat("Oscar allume le phare.")

    def sans_montage(methode, chemin, corps=None):
        if chemin == "/video-h3/montage":
            return 404, {"detail": "Un des clips n'est plus sur ce Studio."}
        return studio(methode, chemin, corps)
    fa.Film(etat, tmp_path, sans_montage, chat, dormir=lambda s: None).derouler()
    assert etat["statut"] == "arrete" and "Un des clips" in etat["erreur"]
    assert "deplier" in etat["faites"] and "montage" not in etat["faites"]
    # Reprise : les étapes faites ne sont pas refaites.
    avant = len(studio.appels)
    fa.Film(etat, tmp_path, studio, chat, dormir=lambda s: None).derouler()
    assert etat["statut"] == "fini"
    assert not any(c == "/video-h3/maitre" for _m, c, _x in studio.appels[avant:])


def test_un_plan_refuse_par_le_juge_est_retourne_et_le_meilleur_garde(fa, tmp_path):
    # Plan 1 ok ; plan 2 refusé, retourné seul, et le second essai passe.
    studio = FauxStudio(verdicts_clips=("ok", "defaut", "ok"))
    etat = fa.nouvel_etat("Oscar allume le phare.", essai=True)
    fa.Film(etat, tmp_path, studio, chat, dormir=lambda s: None).derouler()
    assert etat["statut"] == "fini", etat["erreur"]
    depliers = [x for m, c, x in studio.appels if c.endswith("/deplier")]
    assert [x.get("plans") for x in depliers] == [None, [2]]
    rejoue = next(j for j in etat["journal"] if j["etape"] == "clip_rejoue")
    assert etat["clips"][1]["job"] == rejoue["job"] and etat["clips"][1]["verdict"] == "ok"
    montage = next(x for m, c, x in studio.appels if c == "/video-h3/montage")
    assert montage["clips"] == [c["job"] for c in etat["clips"]]


def test_un_plan_toujours_refuse_garde_le_moins_fautif(fa, tmp_path):
    studio = FauxStudio(verdicts_clips=("defaut", "defaut", "ok"))
    etat = fa.nouvel_etat("Oscar allume le phare.", essai=True)
    fa.Film(etat, tmp_path, studio, chat, dormir=lambda s: None).derouler()
    assert etat["statut"] == "fini", etat["erreur"]
    premier = etat["clips"][0]
    assert premier["essais"] == fa.ESSAIS_PLAN and premier["verdict"] == "defaut"


def test_un_maitre_qui_ne_se_deplie_pas_laisse_la_place_au_suivant(fa, tmp_path):
    """Film « Le phare », 03/10 : le moins fautif des trois maîtres n'avait pas fait deux coupes."""
    studio = FauxStudio(verdicts_maitre=("defaut", "defaut", "defaut"))
    etat = fa.nouvel_etat("Oscar allume le phare.")
    film = fa.Film(etat, tmp_path, studio, chat, dormir=lambda s: None)
    film.deplier_vrai = film.deplier

    def deplier():
        studio.sans_coupe.add(etat["maitres"][0]["job"])
        film.deplier_vrai()
    film.deplier = deplier
    film.derouler()
    assert etat["statut"] == "fini", etat["erreur"]
    assert etat["maitre"]["job"] == etat["maitres"][1]["job"]
    assert any(j["etape"] == "maitre_non_depliable" for j in etat["journal"])
    # Aucun ne se déplie : le film s'arrête et dit pourquoi.
    studio = FauxStudio(verdicts_maitre=("defaut", "defaut", "defaut"))
    etat = fa.nouvel_etat("Oscar allume le phare.")
    film = fa.Film(etat, tmp_path, studio, chat, dormir=lambda s: None)
    film.deplier_vrai = film.deplier

    def aucun():
        studio.sans_coupe.update(m["job"] for m in etat["maitres"])
        film.deplier_vrai()
    film.deplier = aucun
    film.derouler()
    assert etat["statut"] == "arrete" and "Aucun clip maître ne se déplie" in etat["erreur"]
