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

    def job(self, statut="succeeded"):
        self.n += 1
        jid = "%032x" % self.n
        self.jobs[jid] = {"id": jid, "status": statut}
        return dict(self.jobs[jid])

    def __call__(self, methode, chemin, corps=None):
        self.appels.append((methode, chemin, json.loads(json.dumps(corps))))
        if methode == "GET" and chemin.startswith("/jobs/"):
            return 200, self.jobs[chemin.split("/")[-1]]
        if chemin == "/video-h3/fiches":
            return 200, {"id": "f%011d" % len(self.appels)}
        if chemin.startswith("/video-h3/fiches/"):
            return 200, {}
        if chemin == "/video-h3/scenario/decouper":
            return 200, {"plans": [{"image_paroles": "Plan %d." % k, "enchainement": "coupe"} for k in range(4)]}
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


def test_l_essai_a_blanc_va_du_texte_au_film_par_les_routes_du_studio(fa, tmp_path):
    studio = FauxStudio()
    etat = fa.nouvel_etat("Oscar allume le phare. Un bateau rentre au port.", essai=True)
    fa.Film(etat, tmp_path, studio, chat, dormir=lambda s: None).derouler()
    assert etat["statut"] == "fini", etat["erreur"]
    routes = [c for m, c, _x in studio.appels if m == "POST"]
    assert routes[:4] == ["/video-h3/fiches", "/video-h3/fiches/f00000000001/images/face",
                          "/video-h3/fiches/f00000000001/planche", "/video-h3/scenario/decouper"]
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
