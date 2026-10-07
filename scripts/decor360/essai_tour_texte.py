"""Le tour 360° d'un lieu SANS photo (PLAN 21.6 étape 6), étape par étape comme le Studio (propriétaire, 06/10 :
« do it step by step as in studio with these 8 examples » ; « do it locally ») : le vrai `tour360.Tour`, le chat du
Studio (essai_plan_studio.chat : propose sur free-ai-auto, relit sur free-ai-max comme app._tour360_relecteur), le
panorama sur la 4090 dans un conteneur jetable de l'image ComfyUI locale (free-ai-studio-comfy-maison), le script
étant celui que le Studio envoie chez Modal (tour360.construire_script). Le nœud Union de T8 (commit de tour360.T8)
est monté en lecture seule ; les poids manquants (Union, SeedVR2) se posent une fois dans le cache local.

  python essai_tour_texte.py image <sortie> [cas ...]             le chat écrit une photo, Qwen-Image 2.1 la peint
                                                                  (GPU) ; le plan part ensuite de cette photo
  python essai_tour_texte.py dos <sortie> [cas ...]               la vue à 180° (photo_dos.png), la photo de face
                                                                  en référence (GPU)
  python essai_tour_texte.py plan <sortie> [cas ...]              consigne + plan proposé + relu ; s'arrête à valider
  python essai_tour_texte.py retouche <sortie> <cas> "<message>"  le client écrit, le chat rend le plan modifié
  python essai_tour_texte.py panorama <sortie> [cas ...]          valide, peint (GPU : par la file), cartes
  --union force,fin : contrôle Lineart du dessin réglé (essai ; défaut du Studio 1.0, 1.0)
  -> <sortie>/<cas>/tour.json, dessus.png, pano.png, maquette.png, cles/, cartes/, pano/{script.py,sortie.log}
Les cas et descriptions sont ceux d'essai_plans_texte.CAS.
"""
import base64
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sandbox-manager"))
import essai_mesure_studio  # noqa: E402
import retouche_qwen as rq  # noqa: E402
import tour360  # noqa: E402
import video_h3  # noqa: E402
from essai_plan_studio import chat  # noqa: E402
from essai_plans_texte import CAS, dessus  # noqa: E402

POIDS = Path.home() / ".cache" / "free-ai-studio" / "poids"
UNION_T8 = Path.home() / ".cache" / "free-ai-studio" / "union_t8"
IMAGE = "free-ai-studio-comfy-maison"


def regler_union(force, fin):
    """Essai (06/10, panoramas sans photo : la maquette coloriée telle quelle, arbres en boîtes grises) : le contrôle
    Lineart du dessin à `force` jusqu'à `fin` du débruitage, au lieu de 1.0 jusqu'au bout."""
    union = tour360.graphe_union

    def regle(*a, **k):
        g = union(*a, **k)
        g["70"]["inputs"].update(strength=force, end_percent=fin)
        return g
    tour360.graphe_union = regle


def _tour(dossier, nom):
    """Le tour du lieu ; avec une photo.png dans son dossier (commande `image`), le tour d'une photo (mesure MoGe
    sur la carte d'ici, plan proposé et relu sur la photo), sinon le tour sans photo (étape 6)."""
    dossier.mkdir(parents=True, exist_ok=True)
    chemin = dossier / "tour.json"
    photo = (dossier / "photo.png").is_file()
    if chemin.is_file():
        etat = json.loads(chemin.read_text(encoding="utf-8"))
    else:
        etat = tour360.nouvel_etat({"id": nom, "nom": nom, "genre": "decor", "description": CAS[nom]}, "maison",
                                   texte=not photo)
    return tour360.Tour(etat, dossier, None, lambda c, i: chat(dossier, c, i),
                        panorama_local(dossier, "essai-tour-texte-" + nom),
                        mesure=mesure_locale(dossier) if photo else None,
                        relecteur=lambda c, i: chat(dossier, c, i, "free-ai-max"))


def mesure_locale(dossier):
    def mesurer(photo):
        sortie = dossier / "mesure"
        sortie.mkdir(parents=True, exist_ok=True)
        (sortie / "photo.png").write_bytes(photo)
        if essai_mesure_studio.main(sortie / "photo.png", sortie):
            raise tour360.Arret("La mesure MoGe a échoué : voir %s." % (sortie / "sortie.log"))
        return {n: (sortie / n).read_bytes() for n in ("geometrie.json", "grille.json")}
    return mesurer


# --- L'image d'abord (propriétaire, 06/10 : « start with a llm with vision, use qwen2.1 image to create an image
# then do the 2d plane footprint ») : le chat écrit la photo, Qwen-Image 2.1 la peint, le tour part de la photo ---
CONSIGNE_PHOTO = (
    "A place is described by its owner as: « %s ». Write the prompt for an image model that must produce ONE real "
    "photograph of this place: eye level (1.6 m), level camera, wide angle (about 80 degrees across), taken from "
    "near the middle of the place towards its most important side; the floor in the lower part and, indoors, the "
    "ceiling at the top, so that the size of the place reads; what the description names that would stand in that "
    "view, at real sizes, with what such a place plainly has; daylight or the place's own light; no people, no "
    "text, not a film set. Answer with the prompt only, in English, at most 120 words.")


CONSIGNE_DOS = (
    "A place is described by its owner as: « %s ». A photograph of it was made from this prompt: « %s ». Write the "
    "prompt for the OPPOSITE view: the same place from the same camera spot, turned 180 degrees, same eye level, "
    "lens, light and materials; what stands behind the first camera (the entrance, the other walls or the other "
    "side of the open place), with what such a place plainly has there; nothing seen in the first view. Answer "
    "with the prompt only, in English, at most 120 words.")
DOS = ("<image2> is a photograph of this place. Paint the view from exactly the same spot turned 180 degrees: same "
       "place, same eye level and lens, same light, same materials and colours as <image2>; none of what <image2> "
       "shows is in front now. ")


def _qwen(dossier, nom, sous, texte, refs=()):
    """Qwen-Image 2.1 sur la carte d'ici : une toile au format du Studio en <image1>, `refs` en <image2>… ->
    les octets du PNG, ou None (la sortie dit pourquoi)."""
    run = dossier / sous
    run.mkdir(parents=True, exist_ok=True)
    (run / "texte.txt").write_text(texte, encoding="utf-8")
    largeur, hauteur = (int(x) for x in video_h3.TAILLE_IMAGE_DEMANDEE.split("x"))
    noms = ["ref_%02d.png" % k for k in range(len(refs))]
    d = {"base": base64.b64encode(rq._png_uni(largeur, hauteur)).decode(),
         "refs": {n: base64.b64encode(r).decode() for n, r in zip(noms, refs)},
         "graphe": rq.graphe("base.png", noms, texte), "classes": list(rq.CLASSES),
         "comfy": video_h3.DOSSIER_COMFY, "base_poids": rq.DOSSIER_POIDS, "depot": rq.HF,
         "revision": rq.HF_REVISION, "fichiers": list(rq.FICHIERS), "delai_s": rq.DUREE_MAX_S}
    (run / "script.py").write_text(video_h3._emballer(rq._SCRIPT, d), encoding="utf-8")
    t = time.time()
    r = subprocess.run(
        ["docker", "run", "--rm", "--gpus", "all", "--user", "0", "--name", "essai-tour-texte-" + nom,
         "-e", "FREE_AI_OUTPUT_DIR=/sortie", "-e", "HF_HUB_DISABLE_PROGRESS_BARS=1",
         "-v", f"{POIDS}:{rq.DOSSIER_POIDS}", "-v", f"{run.resolve()}:/sortie", "--entrypoint", "sh", IMAGE,
         "-c", "python /sortie/script.py; rc=$?; cp /tmp/comfy.log /sortie/comfy.log 2>/dev/null; exit $rc"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    (run / "sortie.log").write_text(r.stdout + "\n--- stderr ---\n" + r.stderr, encoding="utf-8")
    if r.returncode or not (run / "retouche.png").is_file():
        print(json.dumps({"cas": nom, sous: "echec", "rc": r.returncode, "stderr": r.stderr[-600:]}), flush=True)
        return None
    print(json.dumps({"cas": nom, sous: "faite", "s": round(time.time() - t, 1), "texte": texte},
                     ensure_ascii=False), flush=True)
    return (run / "retouche.png").read_bytes()


def image(sortie, noms):
    for nom in noms or list(CAS):
        dossier = sortie / nom
        dossier.mkdir(parents=True, exist_ok=True)
        if (dossier / "photo.png").is_file():
            continue
        texte = chat(dossier, CONSIGNE_PHOTO % CAS[nom], []).strip().strip('"')
        png = _qwen(dossier, nom, "image", rq.TOILE + texte)
        if png:
            (dossier / "photo.png").write_bytes(png)


def dos(sortie, noms):
    """La vue à 180° (propriétaire, 06/10 : « 2 image at 180° may be better ») : la photo de face en <image2>, pour
    que la matière, la lumière et le style suivent."""
    for nom in noms or list(CAS):
        dossier = sortie / nom
        if (dossier / "photo_dos.png").is_file() or not (dossier / "photo.png").is_file():
            continue
        face = (dossier / "image" / "texte.txt").read_text(encoding="utf-8")[len(rq.TOILE):]
        texte = chat(dossier, CONSIGNE_DOS % (CAS[nom], face), []).strip().strip('"')
        png = _qwen(dossier, nom, "image_dos", rq.TOILE + DOS + texte, [(dossier / "photo.png").read_bytes()])
        if png:
            (dossier / "photo_dos.png").write_bytes(png)


def panorama_local(dossier, conteneur):
    def peindre(photo, texte, graine, pas, geo=None, scene=None, cartes=None):
        run = dossier / "pano"
        run.mkdir(parents=True, exist_ok=True)
        (run / "texte.txt").write_text(texte, encoding="utf-8")
        (run / "script.py").write_text(tour360.construire_script(photo, texte, graine, pas, geo, scene, cartes),
                                       encoding="utf-8")
        t = time.time()
        r = subprocess.run(
            ["docker", "run", "--rm", "--gpus", "all", "--user", "0", "--name", conteneur,
             "-e", "FREE_AI_OUTPUT_DIR=/sortie", "-e", "HF_HUB_DISABLE_PROGRESS_BARS=1",
             "-v", f"{POIDS}:/poids/qwen-image-21", "-v", f"{POIDS}:/poids/seedvr2",
             "-v", f"{UNION_T8}:/comfy/custom_nodes/union_t8:ro", "-v", f"{run.resolve()}:/sortie",
             "--entrypoint", "sh", IMAGE, "-c",
             "python /sortie/script.py; rc=$?; cp /tmp/comfy.log /sortie/comfy.log 2>/dev/null; exit $rc"],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        (run / "sortie.log").write_text(r.stdout + "\n--- stderr ---\n" + r.stderr, encoding="utf-8")
        print("PANORAMA rc", r.returncode, round(time.time() - t, 1), "s", r.stdout.strip()[-400:], flush=True)
        if r.returncode:
            raise tour360.Arret(tour360.phrase_d_echec(r.stderr) or r.stderr.strip()[-600:])
        return {p.name: p.read_bytes() for p in run.iterdir()
                if p.is_file() and p.name not in ("script.py", "texte.txt", "sortie.log", "comfy.log")}
    return peindre


def plan(sortie, noms):
    for nom in noms or list(CAS):
        tour = _tour(sortie / nom, nom)
        for etape in ("consigne", "mesure", "plan"):
            if etape in tour.etat["faites"]:
                continue
            try:
                getattr(tour, etape)()
            except tour360.Attente:
                tour.etat["statut"] = tour360.A_VALIDER
                break
            tour.etat["faites"].append(etape)
        tour.ecrire()
        _dessus(tour)
        r = tour.etat.get("plan_relecture") or {}
        print(json.dumps({"cas": nom, "statut": tour.etat["statut"], "piece": tour.etat["consigne"]["piece"],
                          "elements": len(tour.etat["plan"]["elements"]), "dehors": bool(tour.etat["plan"].get("dehors")),
                          "relu": r}, ensure_ascii=False), flush=True)


def _dessus(tour):
    plan = tour.etat["plan"]
    dessus(plan, "%s : %s" % (tour.etat["nom"], tour.etat["consigne"]["piece"])).save(tour.dossier / "dessus.png")
    if tour.etat.get("plan_propose"):
        dessus(tour.etat["plan_propose"], tour.etat["nom"] + " : propose").save(tour.dossier / "dessus_propose.png")


def retouche(sortie, nom, message):
    tour = _tour(sortie / nom, nom)
    tour360.retoucher_plan(tour.etat, message, tour.chat, None)
    tour.ecrire()
    _dessus(tour)
    print("RETOUCHE", nom, len(tour.etat["plan"]["elements"]), "elements", tour.etat.get("plan_remarques"))


def panorama(sortie, noms):
    for nom in noms or list(CAS):
        tour = _tour(sortie / nom, nom)
        if not tour.etat.get("plan_valide"):
            tour360.valider_plan(tour.etat)
        try:
            for etape in ("panorama", "cartes"):
                if etape not in tour.etat["faites"]:
                    getattr(tour, etape + "_" if etape == "panorama" else etape)()
                    tour.etat["faites"].append(etape)
                    tour.ecrire()
            tour.etat["statut"] = "panorama_fait"
        except tour360.Arret as exc:
            tour.etat.update(statut="arrete", erreur=str(exc))
        tour.ecrire()
        print(json.dumps({"cas": nom, "statut": tour.etat["statut"], "erreur": tour.etat.get("erreur", ""),
                          "temps": tour.etat.get("temps_panorama"), "cartes": len(tour.etat.get("cartes") or [])},
                         ensure_ascii=False), flush=True)


if __name__ == "__main__":
    a = sys.argv[1:]
    if "--union" in a:                       # --union force,fin
        i = a.index("--union")
        regler_union(*(float(v) for v in a[i + 1].split(",")))
        del a[i:i + 2]
    sortie = Path(a[1]).resolve()
    if a[0] == "image":
        image(sortie, a[2:])
    elif a[0] == "dos":
        dos(sortie, a[2:])
    elif a[0] == "plan":
        plan(sortie, a[2:])
    elif a[0] == "retouche":
        retouche(sortie, a[2], a[3])
    elif a[0] == "panorama":
        panorama(sortie, a[2:])
    else:
        sys.exit("image | dos | plan | retouche | panorama")
