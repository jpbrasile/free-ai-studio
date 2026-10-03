"""Le film automatique : d'un texte simple à un film fini (03/10/2026).

Demande du propriétaire, 03/10 au soir : « nos idées doivent être implantées dans studio et
aller jusqu'à un film haute résolution compressé avec musique », « il part d'un texte simple et
tout se déroule automatiquement », « modal que pour la musique sinon en local ».

Un fil enchaîne les routes du Studio, comme la page les appellerait, sans rien retoucher :
  1. les personnages de l'histoire (chat du Studio) → une fiche chacun, portrait de face et
     planche faits par l'image du Studio (les attributs viennent des images, jamais du texte) ;
  2. le découpage en plans (/video-h3/scenario/decouper) ;
  3. la musique, lancée tout de suite, instrumentale, chez Modal (/chanson/creer) ;
  4. le clip maître, toute l'histoire en 15 s (/video-h3/maitre), jugé ; rejoué tant que le
     juge voit un défaut, ESSAIS_MAITRE fois au plus, le moins fautif gardé ;
  5. chaque plan déplié entre ses deux images du maître (/video-h3/maitre/{id}/deplier) ;
  6. le montage, l'agrandissement 4K sur la carte d'ici (/video-h3/finaliser, compressé en AV1
     par le Studio), puis la musique dessous (/video-h3/musique).
Chaque étape écrit l'état (fichier JSON) : la page, et le propriétaire au réveil, le lisent.
`appel(methode, chemin, corps)` rend (code, dict) ; `chat(consigne)` rend le texte du chat.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Callable

ESSAIS_MAITRE = 3
ESSAIS_PLAN = 2          # un plan déplié que le juge refuse est retourné une fois ; le moins fautif reste
PERSONNAGES_MAX = 2
PLANS_MAX = 8            # 15 s de maître : au-delà, des plans de moins de 2 s
DEFINITION = "768p"      # maître et plans dépliés : le maître 768p tient sur la carte de 24 Go (03/10)
ATTENTE_PAS_S = 15
ATTENTE_MAX_S = 4 * 3600
HISTOIRE_MAX = 2000
# L'essai à blanc (propriétaire, 03/10 : « un dry run deux clips de 2 s end to end (mvp) pour
# valider ») : deux plans, le maître le plus court de la grille (124 images, 5,2 s : H3 ne fait
# pas moins), 480p, un seul essai du maître ; toutes les étapes, jusqu'à la 4K et la musique.
REGLAGES = {"plans_max": PLANS_MAX, "longueur_maitre": 362, "definition": DEFINITION, "essais_maitre": ESSAIS_MAITRE}
REGLAGES_ESSAI = {"plans_max": 2, "longueur_maitre": 124, "definition": "480p", "essais_maitre": 1}

CONSIGNE_PERSONNAGES = (
    "Here is a short film story. List its characters who appear on screen (people or animals), at most %d, "
    "the main one first. For each, give the name used in the story and a visual description for a portrait "
    "artist: age, face, hair, build, clothes; one sentence, in French. Answer with JSON only: "
    "{\"personnages\": [{\"nom\": \"...\", \"description\": \"...\", \"genre\": \"personne\" or \"animal\"}]}"
    "\n\nStory:\n%s")
CONSIGNE_MUSIQUE = (
    "Here is a short film story. Write the style of an instrumental film score for it, in English, in at most "
    "25 words: genre, instruments, tempo, mood. No vocals. Answer with the style only.\n\nStory:\n%s")


def lire_personnages(reponse: str) -> list:
    t = str(reponse or "")
    debut, fin = t.find("{"), t.rfind("}")
    try:
        d = json.loads(t[debut:fin + 1]) if debut >= 0 else None
    except ValueError:
        d = None
    gens = (d or {}).get("personnages") if isinstance(d, dict) else None
    if not isinstance(gens, list):
        raise ValueError("Les personnages de l'histoire n'ont pas pu être lus.")
    propres = []
    for g in gens[:PERSONNAGES_MAX]:
        if not isinstance(g, dict):
            continue
        nom = " ".join(str(g.get("nom") or "").split())[:60]
        description = " ".join(str(g.get("description") or "").split())[:800]
        if nom and description:
            propres.append({"nom": nom, "description": description,
                            "genre": "animal" if g.get("genre") == "animal" else "personne"})
    if not propres:
        raise ValueError("L'histoire n'a aucun personnage lisible.")
    return propres


def lire_style(reponse: str) -> str:
    style = " ".join(str(reponse or "").replace("\"", "").split())[:300]
    if not style:
        raise ValueError("Le style de la musique n'a pas pu être lu.")
    return style


class Arret(Exception):
    """Une étape impossible : le film s'arrête là, et l'état dit pourquoi."""


class Film:
    def __init__(self, etat: dict, dossier: Path, appel: Callable, chat: Callable,
                 dormir: Callable = time.sleep):
        self.etat, self.dossier, self.appel, self.chat, self.dormir = etat, dossier, appel, chat, dormir

    # --- l'état, écrit à chaque pas ---
    def ecrire(self):
        chemin = self.dossier / (self.etat["id"] + ".json")
        chemin.parent.mkdir(parents=True, exist_ok=True)
        provisoire = chemin.with_suffix(".tmp")
        provisoire.write_text(json.dumps(self.etat, ensure_ascii=False, indent=1), encoding="utf-8")
        provisoire.replace(chemin)

    def noter(self, etape: str, **quoi):
        self.etat["etape"] = etape
        self.etat["journal"].append(dict({"le": round(time.time()), "etape": etape}, **quoi))
        self.ecrire()

    def route(self, methode: str, chemin: str, corps=None, attendu=(200,)) -> dict:
        code, rendu = self.appel(methode, chemin, corps)
        if code not in attendu:
            detail = rendu.get("detail") if isinstance(rendu, dict) else rendu
            raise Arret("%s %s : %s %s" % (methode, chemin, code, str(detail)[:600]))
        return rendu

    def attendre(self, jid: str) -> dict:
        """Le travail fini (réussi ou non) ; Arret s'il dépasse ATTENTE_MAX_S."""
        debut = time.time()
        while True:
            job = self.route("GET", "/jobs/" + jid)
            if job.get("status") not in ("queued", "running"):
                return job
            if time.time() - debut > ATTENTE_MAX_S:
                raise Arret("Le travail %s n'a pas fini en %d s." % (jid, ATTENTE_MAX_S))
            self.dormir(ATTENTE_PAS_S)

    def reussi(self, jid: str, quoi: str) -> dict:
        job = self.attendre(jid)
        if job.get("status") != "succeeded":
            raise Arret("%s a échoué : %s" % (quoi, str(job.get("error") or job.get("status"))[:600]))
        return job

    # --- les étapes ---
    def personnages(self):
        gens = lire_personnages(self.chat(CONSIGNE_PERSONNAGES % (PERSONNAGES_MAX, self.etat["histoire"])))
        fiches = []
        for g in gens:
            f = self.route("POST", "/video-h3/fiches", g)
            self.route("POST", "/video-h3/fiches/%s/images/face" % f["id"], {})
            self.route("POST", "/video-h3/fiches/%s/planche" % f["id"], {})
            fiches.append({"id": f["id"], "nom": g["nom"], "description": g["description"]})
        self.etat["fiches"] = fiches
        self.noter("personnages", fiches=[f["id"] for f in fiches])

    def decoupage(self):
        d = self.route("POST", "/video-h3/scenario/decouper",
                       {"scenario": self.etat["histoire"], "fiches": [f["id"] for f in self.etat["fiches"]]})
        plans = d.get("plans") or []
        if not plans:
            raise Arret("Le découpage n'a rendu aucun plan.")
        r = self.etat["reglages"]
        if r["plans_max"] < PLANS_MAX:
            plans = plans[:r["plans_max"]]   # l'essai à blanc : les premiers plans seulement
        elif len(plans) > PLANS_MAX:
            raise Arret("Le découpage a rendu %d plans : %d au plus tiennent dans un clip maître de 15 s."
                        % (len(plans), PLANS_MAX))
        self.etat["plans"] = plans
        self.noter("decoupage", plans=len(plans))

    def musique_lancee(self):
        style = lire_style(self.chat(CONSIGNE_MUSIQUE % self.etat["histoire"]))
        job = self.route("POST", "/chanson/creer", {"style": style, "lora": True, "duree": "1", "ou": "modal",
                                                    "titre": self.etat["titre"] + " (musique)"})
        self.etat["musique"] = {"job": job["id"], "style": style}
        self.noter("musique_lancee", job=job["id"])

    def _commun(self) -> dict:
        ids = [f["id"] for f in self.etat["fiches"]]
        return {"fiches": ids} if len(ids) > 1 else {"fiche": ids[0]}

    def maitre(self):
        essais, forcer = [], False
        r = self.etat["reglages"]
        for k in range(r["essais_maitre"]):
            corps = dict(self._commun(), plans=self.etat["plans"], definition=r["definition"], ou="maison",
                         longueur_maitre=r["longueur_maitre"], forcer=forcer)
            code, rendu = self.appel("POST", "/video-h3/maitre", corps)
            if code == 409 and not forcer:
                # Une règle d'avant tournage refusée : notée, puis « tourner quand même », comme la page
                # le propose ; la règle de la voix n'a jamais de passe-droit (le Studio refuse encore).
                self.noter("maitre_regles", refus=str((rendu or {}).get("detail"))[:1500])
                forcer = True
                code, rendu = self.appel("POST", "/video-h3/maitre", dict(corps, forcer=True))
            if code != 200:
                raise Arret("POST /video-h3/maitre : %s %s" % (code, str((rendu or {}).get("detail"))[:600]))
            self.reussi(rendu["id"], "Le clip maître")
            verdict = self.route("POST", "/video-h3/jobs/%s/juger" % rendu["id"], {})
            defauts = verdict.get("defauts") or []
            essais.append({"job": rendu["id"], "verdict": verdict.get("verdict"), "defauts": defauts})
            self.etat["maitres"] = essais
            self.noter("maitre", essai=k + 1, job=rendu["id"], verdict=verdict.get("verdict"),
                       defauts=[d.get("quoi") for d in defauts])
            if verdict.get("verdict") == "ok":
                break
        meilleur = min(essais, key=lambda e: (e["verdict"] != "ok", len(e["defauts"])))
        self.etat["maitre"] = meilleur
        self.ecrire()

    def deplier(self):
        m = self.etat["maitre"]
        d = self.route("POST", "/video-h3/maitre/%s/deplier" % m["job"],
                       {"definition": self.etat["reglages"]["definition"], "ou": "maison",
                        "forcer": m["verdict"] != "ok"})
        self.etat["clips"] = [{"job": j} for j in d["clips"]]
        self.noter("deplier", clips=d["clips"], cles=d.get("cles"))
        for k, c in enumerate(self.etat["clips"]):
            c.update(self._juge(c["job"]), essais=1)
            self.noter("clip", plan=k + 1, job=c["job"], verdict=c["verdict"], defauts=c["defauts"])
            # Essai à blanc du 03/10 : les deux plans refusés (geste manquant) étaient gardés tels quels.
            while c["verdict"] != "ok" and c["essais"] < ESSAIS_PLAN:
                r = self.route("POST", "/video-h3/maitre/%s/deplier" % m["job"],
                               {"definition": self.etat["reglages"]["definition"], "ou": "maison",
                                "forcer": m["verdict"] != "ok", "plans": [k + 1]})
                autre = dict(self._juge(r["clips"][0]), job=r["clips"][0])
                c["essais"] += 1
                self.noter("clip_rejoue", plan=k + 1, job=autre["job"], verdict=autre["verdict"],
                           defauts=autre["defauts"])
                if (autre["verdict"] != "ok", len(autre["defauts"])) < (True, len(c["defauts"])):
                    c.update(job=autre["job"], verdict=autre["verdict"], defauts=autre["defauts"])
                self.ecrire()

    def _juge(self, jid: str) -> dict:
        self.reussi(jid, "Un plan déplié")
        verdict = self.route("POST", "/video-h3/jobs/%s/juger" % jid, {})
        return {"verdict": verdict.get("verdict"), "defauts": [x.get("quoi") for x in verdict.get("defauts") or []]}

    def montage(self):
        film = self.route("POST", "/video-h3/montage", {"clips": [c["job"] for c in self.etat["clips"]],
                                                        "scenario": self.etat["titre"]})
        self.reussi(film["id"], "Le montage")
        self.etat["film_monte"] = film["id"]
        self.noter("montage", job=film["id"])

    def agrandir(self):
        fin = self.route("POST", "/video-h3/finaliser", {"job": self.etat["film_monte"], "echelle": "4k",
                                                         "ou": "maison"})
        job = self.reussi(fin["id"], "L'agrandissement 4K")
        # Le film 4K est un travail à part, que la finalisation nomme (essai à blanc du 03/10 : la
        # finalisation elle-même n'a pas de fichier, et la musique disait « ce film n'est plus là »).
        film = (job.get("finalisation") or {}).get("film")
        if not film:
            raise Arret("La finalisation a réussi sans nommer son film.")
        self.etat["film_4k"] = film
        self.noter("agrandir", job=fin["id"], film=film)

    def musique(self):
        chanson = self.reussi(self.etat["musique"]["job"], "La musique")
        film = self.route("POST", "/video-h3/musique", {"film": self.etat["film_4k"], "chanson": chanson["id"],
                                                        "volume": 0.35})
        self.reussi(film["id"], "La pose de la musique")
        self.etat["film"] = film["id"]
        self.noter("musique", job=film["id"])

    ETAPES = ("personnages", "decoupage", "musique_lancee", "maitre", "deplier", "montage", "agrandir", "musique")

    def derouler(self):
        """Chaque étape une fois, dans l'ordre ; une étape déjà faite (reprise) est sautée."""
        try:
            for etape in self.ETAPES:
                if etape in self.etat["faites"]:
                    continue
                getattr(self, etape)()
                self.etat["faites"].append(etape)
                self.ecrire()
            self.etat["statut"] = "fini"
        except Arret as exc:
            self.etat.update(statut="arrete", erreur=str(exc))
        except Exception as exc:  # noqa: BLE001 -- l'état dit la panne, le fil ne meurt pas muet
            self.etat.update(statut="arrete", erreur="%s : %s" % (type(exc).__name__, str(exc)[:600]))
        self.noter(self.etat["statut"])


def nouvel_etat(histoire: str, titre: str = "", essai: bool = False) -> dict:
    histoire = str(histoire or "").strip()
    if not histoire:
        raise ValueError("Écrivez l'histoire du film.")
    if len(histoire) > HISTOIRE_MAX:
        raise ValueError("Histoire trop longue (%d caractères au plus)." % HISTOIRE_MAX)
    titre = " ".join(str(titre or "").split())[:80] or re.split(r"[.!?\n]", histoire)[0][:60]
    return {"id": uuid.uuid4().hex, "cree_le": round(time.time()), "histoire": histoire, "titre": titre,
            "statut": "en cours", "etape": "", "faites": [], "journal": [], "erreur": "",
            "essai": bool(essai), "reglages": dict(REGLAGES_ESSAI if essai else REGLAGES)}
