"""Le film automatique (03/10/2026) : d'un texte simple au film fini, par les routes du Studio."""
import importlib
import json

import pytest


@pytest.fixture
def fa(sandbox):
    return importlib.import_module("film_auto")


class FauxStudio:
    """Les routes du Studio, simulées ; garde l'ordre des appels."""

    def __init__(self, verdicts_maitre=("ok",), refus_regles=False):
        self.appels, self.jobs, self.n = [], {}, 0
        self.verdicts_maitre, self.refus_regles = list(verdicts_maitre), refus_regles

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
            return 200, {"verdict": "ok", "defauts": []}
        if chemin.endswith("/deplier"):
            return 200, {"clips": [self.job()["id"], self.job()["id"]], "cles": [[0, 60], [62, 123]]}
        if chemin in ("/chanson/creer", "/video-h3/montage", "/video-h3/finaliser", "/video-h3/musique"):
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
