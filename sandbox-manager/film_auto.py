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
DEFINITION = "768p"      # les plans dépliés
# Le maître est un story-board : 480p. Mesuré le 03/10 (ffmpeg, scene > 0,3) : en 768p, 1 coupe
# franche sur 8 demandées (quatre maîtres « Le phare ») — H3 fond les plans l'un dans l'autre, et le
# fondu montre Oscar deux fois ; en 480p, 6 sur 6 (« Le jardin de verre » 5/5, essai à blanc 1/1).
DEFINITION_MAITRE = "480p"
ATTENTE_PAS_S = 15
ATTENTE_MAX_S = 4 * 3600
HISTOIRE_MAX = 2000
# L'essai à blanc (propriétaire, 03/10 : « un dry run deux clips de 2 s end to end (mvp) pour
# valider ») : deux plans, le maître le plus court de la grille (124 images, 5,2 s : H3 ne fait
# pas moins), 480p, un seul essai du maître ; toutes les étapes, jusqu'à la 4K et la musique.
REGLAGES = {"plans_max": PLANS_MAX, "longueur_maitre": 362, "definition": DEFINITION,
            "definition_maitre": DEFINITION_MAITRE, "essais_maitre": ESSAIS_MAITRE}
REGLAGES_ESSAI = {"plans_max": 2, "longueur_maitre": 124, "definition": "480p", "definition_maitre": "480p",
                  "essais_maitre": 1}
# Le film en séquences (04/10, propriétaire : « un autre film de science-fiction avec Leila de 2 mn
# (15 s par clip) »). L'histoire est coupée en séquences de 15 s ; le maître joue les N séquences
# en 15 s (un plan chacune, en 768p), puis chaque séquence est dépliée en un clip de 15 s
# à vitesse normale, depuis sa première image dans le maître.
# Propriétaire, 04/10 : « la bonne solution pour avoir un film consistant était d'en faire 1 où tout
# le scénario se joue en 15 s ; on en extrait les images des 8 clips à vitesse normale ». Film 1 à 3
# du « Robot perdu » tournaient chaque séquence seule, d'une image de départ à elle : rien ne tenait
# le décor ni les personnages d'une séquence à l'autre.
# Le clip ne reçoit que son image de départ : un personnage absent de cette image n'a que son nom.
# « Le robot perdu », essai à blanc, 04/10 : Pixel, encore dans sa capsule au départ, est sorti en
# « tête cubique jaune pixélisée » (son nom pris au mot). Chaque séquence montre donc ses personnages
# dès sa première image ; une apparition se fait à la coupe entre deux séquences.
SEQUENCE_S = 15
SEQUENCES_MAX = 8
LONGUEUR_SEQUENCE = 362   # 15,1 s, le plus long clip de la grille H3

CONSIGNE_PERSONNAGES = (
    "Here is a short film story. List its characters who appear on screen (people, animals, robots...), at most %d, "
    "the main one first. For each, give the name used in the story and a visual description for a portrait "
    "artist: age, face, hair, build, clothes; one sentence, in French. Answer with JSON only: "
    "{\"personnages\": [{\"nom\": \"...\", \"description\": \"...\", \"genre\": \"personne\" or \"animal\"}]}"
    "\n\nStory:\n%s")
CONSIGNE_SEQUENCES = (
    "Here is a short film story. Split it into exactly %d consecutive sequences of 15 seconds each, in story "
    "order, covering the whole story. Each sequence is one or two sentences in French describing only what "
    "is seen (actions, places, light), with 2 or 3 visible actions at most, and names each character it shows "
    "by the name used in the story. Every character a sequence shows is already visible, in plain view, at its "
    "very first moment: nobody arrives, emerges, wakes up inside something or is discovered during a sequence; "
    "such a reveal happens at the cut between two sequences, the next one opening on the revealed character. "
    "Each sequence opens by naming its place and its time of day or light, as the story sets them "
    "(\"Dans le jardin, la nuit, ...\"), so that it reads alone; it never changes them unless the story does. "
    "No dialogue. Answer with JSON only: {\"sequences\": [\"...\", \"...\"]}"
    "\n\nStory:\n%s")
# « Le robot perdu », film 4, 04/10 : chaque séquence est découpée seule ; « Pixel flotte dans les
# airs » sans « la nuit » est sorti « in the evening sun », la colline « in the afternoon sun » —
# le moment de l'histoire perdu d'une séquence à l'autre. Chaque séquence le dit donc elle-même.
# Le même film : les 8 séquences jointes faisaient une invite de maître de 4 254 caractères (4 000 au
# plus pour H3) ; le Studio y ajoute environ 180 caractères par plan (coupe datée, caméra). Chaque
# texte de séquence tient donc dans sa part de TEXTES_MAITRE_MAX, condensé par le chat sans perdre
# d'action (le clip déplié joue ce même texte pendant 15 s).
TEXTES_MAITRE_MAX = 2200
CONSIGNE_CONDENSER = (
    "Shorten this film shot description to at most %d characters. Keep the shot size, the light, every "
    "character with where they stand and face, and every action in order; drop repetitions and adjectives "
    "that change nothing on screen. English. Answer with the shortened text only.\n\n%s")
# La caméra (04/10, propriétaire : « la caméra doit être mise en œuvre aussi ») : le découpage laisse la
# caméra au Studio (le menu de la page), et le film automatique n'en choisissait aucune — « The camera
# holds a static shot » dans chaque plan. Le chat en choisit une par plan, dans le menu du Studio.
CONSIGNE_CAMERA = (
    "Here are the shots of a short film, in order. Choose ONE camera movement for each shot, as a "
    "cinematographer would, to tell the story: the camera moves in most shots; \"fixe\" (static) only for "
    "a shot that needs stillness, never twice in a row. Follow a character who walks or flies (\"suit\"), "
    "push in on a discovery or an emotion (\"avance\"), tilt up to the sky (\"bascule_haut\"), pull out "
    "or rise to reveal a place (\"recule\", \"monte\"), arc around a meeting (\"arc\"). Keep the faces as "
    "they are: amplitude \"petite\" or \"\" (normal), never \"grande\" when a face is in close-up. "
    "Allowed movements: %s. Allowed amplitudes: \"petite\", \"\", \"grande\". Allowed speeds: \"lente\", "
    "\"\", \"rapide\". Answer with JSON only: {\"cameras\": [{\"mouvement\": \"...\", \"amplitude\": \"...\", "
    "\"vitesse\": \"...\"}]}, one per shot, in order.\n\nShots:\n%s")
CAMERA_SECOURS = {"mouvement": "avance", "amplitude": "petite", "vitesse": "lente"}
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
            # Le Studio n'a pas de fiche « animal » (personne, objet, pose, décor) : un personnage à
            # l'écran est une « personne », comme Zib le Martien. 04/10, robot Pixel classé « animal »
            # par le chat → 400, le film arrêté à sa première étape.
            propres.append({"nom": nom, "description": description, "genre": "personne"})
    if not propres:
        raise ValueError("L'histoire n'a aucun personnage lisible.")
    return propres


def lire_sequences(reponse: str, nombre: int) -> list:
    t = str(reponse or "")
    debut, fin = t.find("{"), t.rfind("}")
    try:
        d = json.loads(t[debut:fin + 1]) if debut >= 0 else None
    except ValueError:
        d = None
    brutes = (d or {}).get("sequences") if isinstance(d, dict) else None
    textes = [" ".join(str(s or "").split())[:600] for s in brutes] if isinstance(brutes, list) else []
    textes = [s for s in textes if s]
    if len(textes) != nombre:
        raise ValueError("L'histoire devait tenir en %d séquences, le chat en a rendu %d." % (nombre, len(textes)))
    return textes


def fiche_du_nom(fiches: list, nom: str):
    """La fiche déjà faite qui porte ce nom : la plus complète (angles), puis la plus récente.
    04/10, « un autre film avec Leila » : Leila a sa fiche (4 angles) depuis le 28/09 ; en refaire
    une changerait son visage. Et « Le phare » avait laissé sept Oscar, un par film."""
    cle = " ".join(str(nom or "").split()).casefold()
    memes = [f for f in fiches or [] if isinstance(f, dict) and f.get("id")
             and " ".join(str(f.get("nom") or "").split()).casefold() == cle]
    return max(memes, key=lambda f: (len(f.get("angles") or []), str(f.get("cree_le") or ""))) if memes else None


def lire_cameras(reponse: str, nombre: int) -> list:
    """Une caméra du menu du Studio par plan ; un choix illisible ou hors menu devient CAMERA_SECOURS
    (une petite avancée lente), jamais la caméra fixe par défaut."""
    from video_h3 import lire_camera   # le menu et ses contrôles sont ceux de la page
    t = str(reponse or "")
    debut, fin = t.find("{"), t.rfind("}")
    try:
        d = json.loads(t[debut:fin + 1]) if debut >= 0 else None
    except ValueError:
        d = None
    brutes = (d or {}).get("cameras") if isinstance(d, dict) else None
    brutes = brutes if isinstance(brutes, list) else []
    cameras = []
    for k in range(nombre):
        try:
            c = lire_camera(brutes[k] if k < len(brutes) and isinstance(brutes[k], dict) else None)
        except ValueError:
            c = None
        deux_fixes = c and c["mouvement"] == "fixe" and cameras and cameras[-1]["mouvement"] == "fixe"
        if k >= len(brutes) or not c or c["mouvement"] == "auto" or deux_fixes:
            c = dict(CAMERA_SECOURS)   # absent, illisible, au choix du modèle, ou fixe deux fois de suite
        cameras.append(c)
    return cameras


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
        existantes = self.route("GET", "/video-h3/fiches")
        existantes = existantes.get("fiches") if isinstance(existantes, dict) else None
        fiches = []
        for g in gens:
            deja = fiche_du_nom(existantes if isinstance(existantes, list) else [], g["nom"])
            if deja:
                fiches.append({"id": deja["id"], "nom": deja.get("nom") or g["nom"],
                               "description": deja.get("description") or g["description"], "reprise": True})
                continue
            f = self.route("POST", "/video-h3/fiches", g)
            self.route("POST", "/video-h3/fiches/%s/images/face" % f["id"], {})
            self.route("POST", "/video-h3/fiches/%s/planche" % f["id"], {})
            fiches.append({"id": f["id"], "nom": g["nom"], "description": g["description"]})
        self.etat["fiches"] = fiches
        self.noter("personnages", fiches=[f["id"] for f in fiches])

    def _decouper(self, texte: str, fiches: list) -> list:
        d = self.route("POST", "/video-h3/scenario/decouper", {"scenario": texte, "fiches": [f["id"] for f in fiches]})
        plans = d.get("plans") or []
        if not plans:
            raise Arret("Le découpage n'a rendu aucun plan.")
        r = self.etat["reglages"]
        if r["plans_max"] < PLANS_MAX:
            plans = plans[:r["plans_max"]]   # l'essai à blanc : les premiers plans seulement
        elif len(plans) > PLANS_MAX:
            raise Arret("Le découpage a rendu %d plans : %d au plus tiennent dans un clip maître de 15 s."
                        % (len(plans), PLANS_MAX))
        return self._avec_cameras(plans)

    def _avec_cameras(self, plans: list) -> list:
        from video_h3 import CAMERA_MOUVEMENTS
        permis = ", ".join('"%s"' % m for m in CAMERA_MOUVEMENTS if m not in ("auto", "tremble"))
        liste = "\n".join("%d. %s" % (k + 1, p.get("image_paroles") or "") for k, p in enumerate(plans))
        cameras = lire_cameras(self.chat(CONSIGNE_CAMERA % (permis, liste)), len(plans))
        return [dict(p, camera=c) for p, c in zip(plans, cameras)]

    def decoupage(self):
        if self.etat["reglages"].get("sequences", 1) > 1:
            self.etat["plans"] = self._avec_cameras([self._plan_de_sequence(k, s)
                                                     for k, s in enumerate(self.etat["sequences"])])
        else:
            self.etat["plans"] = self._decouper(self.etat["histoire"], self.etat["fiches"])
        self.noter("decoupage", plans=len(self.etat["plans"]))

    def _plan_de_sequence(self, k: int, s: dict) -> dict:
        """Une séquence = un plan du maître, déplié en un clip de 15 s. Le découpage du Studio la
        traduit et en retire la tenue ; ses plans sont joints en un seul texte, que le clip déplié
        joue à vitesse normale. Entre deux séquences, une coupe (« Le robot perdu », film 2 : une
        suite demandée, H3 coupe ou fond quand même, et le fondu dédouble Leila)."""
        texte = s["texte"]
        d = self.route("POST", "/video-h3/scenario/decouper",
                       {"scenario": texte, "fiches": [f["id"] for f in self._fiches_de(texte)]})
        plans = d.get("plans") or []
        if not plans:
            raise Arret("Le découpage de la séquence %d n'a rendu aucun plan." % (k + 1))
        joint = " ".join(" ".join(str(p.get("image_paroles") or "").split()) for p in plans).strip()
        part = TEXTES_MAITRE_MAX // self.etat["reglages"]["sequences"]
        for _ in range(2):
            if len(joint) <= part:
                break
            court = " ".join(str(self.chat(CONSIGNE_CONDENSER % (part, joint)) or "").split()).strip('"')
            if court:
                joint = court
        if len(joint) > part:
            raise Arret("Séquence %d : texte de %d caractères, %d au plus pour tenir dans le maître."
                        % (k + 1, len(joint), part))
        self.noter("sequence_texte", sequence=k + 1, caracteres=len(joint))
        return dict(plans[0], image_paroles=joint, enchainement="coupe",
                    longueur=self.etat["reglages"]["longueur_plan"])

    def musique_lancee(self):
        style = lire_style(self.chat(CONSIGNE_MUSIQUE % self.etat["histoire"]))
        # La chanson du Studio dure « jusqu'à 1, 2 ou 3 minutes » : la plus courte qui couvre le film.
        secondes = self.etat["reglages"].get("sequences", 1) * SEQUENCE_S
        duree = "1" if secondes <= 60 else "2" if secondes <= 120 else "3"
        job = self.route("POST", "/chanson/creer", {"style": style, "lora": True, "duree": duree, "ou": "modal",
                                                    "titre": self.etat["titre"] + " (musique)"})
        self.etat["musique"] = {"job": job["id"], "style": style}
        self.noter("musique_lancee", job=job["id"])

    def _commun(self, fiches: list = None) -> dict:
        ids = [f["id"] for f in (fiches or self.etat["fiches"])]
        return {"fiches": ids} if len(ids) > 1 else {"fiche": ids[0]}

    def _fiches_de(self, texte: str) -> list:
        """Les personnages qu'une séquence nomme ; tous si elle n'en nomme aucun. Une fiche donnée au
        maître sans que la séquence la montre ferait entrer le personnage dans l'image de départ."""
        bas = texte.casefold()
        nommes = [f for f in self.etat["fiches"] if f["nom"].casefold() in bas]
        return nommes or list(self.etat["fiches"])

    def maitre(self):
        self.etat["maitres"] = self._tourner_maitre(self.etat["plans"], self.etat["fiches"])
        self.etat["maitre"] = min(self.etat["maitres"], key=lambda e: (e["verdict"] != "ok", len(e["defauts"])))
        self.ecrire()

    def _tourner_maitre(self, plans: list, fiches: list, **marque) -> list:
        """Le clip en plans, jugé ; rejoué tant que le juge voit un défaut (essais_maitre au plus)."""
        essais, forcer = [], False
        r = self.etat["reglages"]
        for k in range(r["essais_maitre"]):
            corps = dict(self._commun(fiches), plans=plans, ou="maison",
                         definition=r.get("definition_maitre") or r["definition"],
                         longueur_maitre=r["longueur_maitre"], forcer=forcer)
            code, rendu = self.appel("POST", "/video-h3/maitre", corps)
            if code == 409 and not forcer:
                # Une règle d'avant tournage refusée : notée, puis « tourner quand même », comme la page
                # le propose ; la règle de la voix n'a jamais de passe-droit (le Studio refuse encore).
                self.noter("maitre_regles", refus=str((rendu or {}).get("detail"))[:1500], **marque)
                forcer = True
                code, rendu = self.appel("POST", "/video-h3/maitre", dict(corps, forcer=True))
            if code != 200:
                raise Arret("POST /video-h3/maitre : %s %s" % (code, str((rendu or {}).get("detail"))[:600]))
            self.reussi(rendu["id"], "Le clip maître")
            verdict = self.route("POST", "/video-h3/jobs/%s/juger" % rendu["id"], {})
            defauts = verdict.get("defauts") or []
            essais.append({"job": rendu["id"], "verdict": verdict.get("verdict"), "defauts": defauts})
            self.noter("maitre", essai=k + 1, job=rendu["id"], verdict=verdict.get("verdict"),
                       defauts=[d.get("quoi") for d in defauts], **marque)
            if verdict.get("verdict") == "ok":
                break
        return essais

    def sequences(self):
        n = self.etat["reglages"]["sequences"]
        erreur = ""
        for _ in range(2):   # le chat peut rendre une séquence de trop ou de moins : une seconde demande
            try:
                textes = lire_sequences(self.chat(CONSIGNE_SEQUENCES % (n, self.etat["histoire"])), n)
                break
            except ValueError as exc:
                erreur = str(exc)
        else:
            raise Arret(erreur)
        self.etat["sequences"] = [{"texte": t} for t in textes]
        self.noter("sequences", nombre=n)

    def deplier(self):
        # Film « Le phare », 03/10 : le maître le moins fautif n'avait pas fait deux coupes, et le
        # Studio refusait de le déplier ; les autres essais le pouvaient. Du moins fautif au plus
        # fautif, le premier qui se déplie.
        candidats = sorted(self.etat.get("maitres") or [self.etat["maitre"]],
                           key=lambda e: (e["verdict"] != "ok", len(e["defauts"])))
        refus = []
        for m in candidats:
            code, d = self.appel("POST", "/video-h3/maitre/%s/deplier" % m["job"],
                                 {"definition": self.etat["reglages"]["definition"], "ou": "maison",
                                  "forcer": m["verdict"] != "ok"})
            if code == 200:
                break
            detail = str((d or {}).get("detail") if isinstance(d, dict) else d)[:600]
            if code != 409:
                raise Arret("POST /video-h3/maitre/%s/deplier : %s %s" % (m["job"], code, detail))
            refus.append(detail)
            self.noter("maitre_non_depliable", job=m["job"], refus=detail)
        else:
            raise Arret("Aucun clip maître ne se déplie : " + " | ".join(refus))
        self.etat["maitre"] = m
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
    ETAPES_SEQUENCES = ("personnages", "sequences", "decoupage", "musique_lancee", "maitre", "deplier", "montage",
                        "agrandir", "musique")

    def etapes(self) -> tuple:
        return self.ETAPES_SEQUENCES if self.etat["reglages"].get("sequences", 1) > 1 else self.ETAPES

    def derouler(self):
        """Chaque étape une fois, dans l'ordre ; une étape déjà faite (reprise) est sautée."""
        try:
            for etape in self.etapes():
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


def nouvel_etat(histoire: str, titre: str = "", essai: bool = False, duree_s=0) -> dict:
    """`duree_s` au-delà de 15 s : le film en séquences de 15 s (2 min = 8 séquences, le plus long).
    À l'essai à blanc, deux séquences courtes en 480p."""
    histoire = str(histoire or "").strip()
    if not histoire:
        raise ValueError("Écrivez l'histoire du film.")
    if len(histoire) > HISTOIRE_MAX:
        raise ValueError("Histoire trop longue (%d caractères au plus)." % HISTOIRE_MAX)
    try:
        duree_s = float(duree_s or 0)
    except (TypeError, ValueError):
        raise ValueError("Durée du film illisible (en secondes).") from None
    if duree_s < 0 or duree_s > SEQUENCES_MAX * SEQUENCE_S:
        raise ValueError("Le film dure %d s au plus (%d séquences de %d s)."
                         % (SEQUENCES_MAX * SEQUENCE_S, SEQUENCES_MAX, SEQUENCE_S))
    titre = " ".join(str(titre or "").split())[:80] or re.split(r"[.!?\n]", histoire)[0][:60]
    reglages = dict(REGLAGES_ESSAI if essai else REGLAGES)
    sequences = -(-int(duree_s) // SEQUENCE_S) if duree_s > SEQUENCE_S else 1
    if sequences > 1:
        reglages["sequences"] = min(sequences, 2) if essai else sequences
        # Chaque séquence déplie en 15 s ; à l'essai à blanc, le clip court de la grille.
        reglages["longueur_plan"] = REGLAGES_ESSAI["longueur_maitre"] if essai else LONGUEUR_SEQUENCE
        if not essai:
            # Propriétaire, 04/10 : « on fait le maître à la définition maximale pour avoir des images
            # de qualité » — chaque clip part d'une image du maître. Les coupes y tiennent : « Le robot
            # perdu », films 1 et 2, maîtres 768p en mode Première image, 7 coupes franches sur 7.
            reglages["definition_maitre"] = DEFINITION
    return {"id": uuid.uuid4().hex, "cree_le": round(time.time()), "histoire": histoire, "titre": titre,
            "statut": "en cours", "etape": "", "faites": [], "journal": [], "erreur": "",
            "essai": bool(essai), "reglages": reglages}
