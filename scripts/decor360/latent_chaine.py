"""Essai : deux tronçons du tour 360° enchaînés par le LATENT, en un seul graphe sur Modal (propriétaire, 06/10 :
« do you include the latent syntax to have smooth changes between clips instead of the 22 last frames », puis
« prépare l'essai latent sur Modal en parallèle »).

Tronçon 1 : 60 -> 90°, Références, clés épinglées à l'image 0 et à la dernière (comme essai_epingles.py).
Tronçon 2 : 90 -> 120°, Références, son départ = les 22 dernières images du latent du tronçon 1, branché tel quel
(sortie de l'échantillonneur, `context_latent` de MiniMaxH3MotionContext : ni décodage ni ré-encodage), la clé 120°
épinglée à la dernière image (AddGuide, -1 ; le README du nœud dit que les deux tiennent ensemble).

Ce que le Studio fait aujourd'hui (voie « troncon », video_h3.brancher_troncon) est l'ancienne voie du nœud : les
22 images DÉCODÉES et leur son, ré-encodés (`context_frames`/`context_audio`) ; le latent gardé
(garder_latent -> /poids/chaines/<jid>.safetensors) n'est jamais relu. README : « it costs a lossy round trip per
link on both streams and it's where the visible seams came from. Use the latent unless you have a reason not to. »

  hôte       : python latent_chaine.py preparer <dossier essai> <sortie>        -> <sortie>/script.py, graphe.json
  conteneur  : python latent_chaine.py lancer <script.py> <sortie>              (client Modal, A100, ~0,3-0,5 $)
"""
import base64
import json
import math
import sys
from pathlib import Path

GPU = "A100-80GB"

try:      # dans le conteneur du routeur ET sur la machine louée, qui réimporte ce module sans arguments
    import modal
except ImportError:   # sur l'hôte : seulement preparer / local
    modal = None

if modal is not None:

    app = modal.App("essai-latent-chaine")
    poids = modal.Volume.from_name("free-ai-studio-h3")
    image = (modal.Image.debian_slim(python_version="3.12").apt_install("git", "ffmpeg")
             .run_commands("git clone --depth 1 --branch v0.37.0 https://github.com/Comfy-Org/ComfyUI /comfy",
                           "pip install -r /comfy/requirements.txt psutil",
                           "git clone https://github.com/NikoDemon80/ComfyUI-H3-Motion-Context "
                           "/comfy/custom_nodes/h3_motion_context",
                           "cd /comfy/custom_nodes/h3_motion_context && "
                           "git checkout 5335715abe54c1a9bfbe3494da29aae3e8635ce3"))

    @app.function(image=image, gpu=GPU, volumes={"/poids": poids}, timeout=2400, memory=65536, cpu=8)
    def tourner(script: str) -> dict:
        import os
        import subprocess
        import time
        Path("/tmp/script.py").write_text(script)
        t = time.time()
        r = subprocess.run(["python", "/tmp/script.py"], capture_output=True, text=True,
                           env=dict(os.environ, FREE_AI_OUTPUT_DIR="/tmp/out"))
        sortie = {"rc": r.returncode, "s": round(time.time() - t, 1), "stdout": r.stdout[-4000:],
                  "stderr": r.stderr[-6000:], "fichiers": {}}
        for p in list(Path("/tmp/out").glob("*")) + list(Path("/tmp/sortie/h3").glob("*")) + [Path("/tmp/comfy.log")]:
            if p.is_file():
                sortie["fichiers"][p.name] = p.read_bytes()
        return sortie


def cle_de(dossier, a):
    """Clé de l'angle a : la plaque à 0 / 360°, sinon le rendu Blender."""
    return Path(dossier) / ("plaque.png" if a % 360 == 0 else "rendus/rendu_r%03d.png" % a)


ECART_PIN = 7.5                # une vue exacte épinglée tous les 7,5°


def pins_1(pas):
    """1er tronçon (124 images, image f = f / 123 du chemin) : images des vues intermédiaires."""
    m = round(pas / ECART_PIN)
    return [round(123 * j / m) for j in range(1, m)]


def pins_suite(pas):
    """Tronçon enchaîné (141 images dont 22 de contexte ; rendue r = f - 22 -> (r + 1) / 119 du chemin)."""
    m = round(pas / ECART_PIN)
    return [22 + round(119 * j / m) - 1 for j in range(1, m)]


def preparer(dossier, sortie, graine=11, pas=30, cap0=60, n=2, arret_final=True, epingle_milieu=True, pano=None):
    """Un seul graphe de n tronçons de `pas` degrés à partir de cap0 : le 1er part de sa clé épinglée, chacun des
    suivants part du latent du précédent (MotionContext) ; chaque tronçon finit sur sa clé épinglée (-1). Seul le
    dernier tronçon « ralentit et s'arrête » (si arret_final), les autres passent par leur clé sans ralentir.
    `epingle_milieu=False` : seul le dernier tronçon a sa clé d'arrivée épinglée ; les autres la gardent en
    référence (<Picture>) sans épingle (essai du 06/10 : avec l'épingle, la caméra se pose sur chaque clé, une
    seconde quasi immobile à chaque jointure, malgré « without slowing »).
    `pano` : 3 vues exactes de plus par tronçon, tirées du panorama (7,5°, 15°, 22,5°), épinglées à leurs images :
    avec une clé tous les 30° seulement, H3 inventait le chemin (dérive jusqu'à 59, retour en arrière)."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sandbox-manager"))
    import io
    import numpy as np
    from PIL import Image
    import video_h3
    import essai_epingles
    import tour360_ref
    import vues_pano
    dossier, sortie = Path(dossier), Path(sortie)
    sortie.mkdir(parents=True, exist_ok=True)
    fiches = json.loads((dossier / "cartes" / "cartes_lieu.json").read_text(encoding="utf-8"))
    cfg = json.loads((dossier / "scene.json").read_text(encoding="utf-8"))
    cam = next(c for c in cfg["cameras"] if c["nom"] == "verif_plaque")
    demi = math.degrees(math.atan(cfg["taille"][0] / 2 / cam["f"]))
    cle = lambda a: cle_de(dossier, a)  # noqa: E731
    carte = lambda f: dossier / "cartes" / f["image"]  # noqa: E731
    arret = lambda i: arret_final and i == n - 1  # noqa: E731

    inv, suj = tour360_ref.invite(fiches, cam["lacet"] + cap0, pas, demi, arret=arret(0))
    (sortie / "invite_1.txt").write_text(inv, encoding="utf-8")
    d1, _ = essai_epingles.demande(inv, [cle(cap0), cle(cap0 + pas), *map(carte, suj)], graine, 124)
    g = d1["graphe"]
    g["18"]["inputs"]["filename_prefix"] = "h3/clip_1"
    images = dict(d1["images"])
    vues = np.asarray(Image.open(pano).convert("RGB")) if pano else None

    def intermediaires(prefixe, depart, angles):
        """Épingles des vues exactes du panorama {image: angle}, chaînées après `depart` ; rend le dernier nœud."""
        for j, (f, angle) in enumerate(sorted(angles.items()), 1):
            nom = "%spin_%d.png" % (prefixe, j)
            tampon = io.BytesIO()
            Image.fromarray(vues_pano.vue(vues, angle)).save(tampon, format="PNG")
            images[nom] = base64.b64encode(tampon.getvalue()).decode()
            g[prefixe + "7%d" % j] = {"class_type": "LoadImage", "inputs": {"image": nom}}
            g[prefixe + "2%d" % j] = {"class_type": "MiniMaxH3AddGuide", "inputs": {
                "positive": [depart, 0], "vae": ["4", 0], "latent": [(prefixe or "") + "10", 1],
                "image": [prefixe + "7%d" % j, 0], "frame_idx": f}}
            depart = prefixe + "2%d" % j
        return depart

    tete = "11"
    if vues is not None:                             # 124 images : image f = cap0 + pas * f / 123
        tete = intermediaires("", "11", {f: cap0 + pas * f / 123 for f in pins_1(pas)})
    if not epingle_milieu and n > 1:                 # clé d'arrivée du 1er tronçon : référence seulement
        del g["19"]
        g["13"]["inputs"]["conditioning"] = [tete, 0]
    else:
        g["19"]["inputs"]["positive"] = [tete, 0]
    classes = set(d1["classes"]) | {"MiniMaxH3MotionContext", "MiniMaxH3MotionContextTrim"}
    echantillon = "14"                               # sortie de l'échantillonneur du tronçon précédent

    for i in range(1, n):
        p = "bcdefgh"[i - 1]
        cap = cap0 + i * pas
        inv, suj = tour360_ref.invite(fiches, cam["lacet"] + cap, pas, demi, suite=True, arret=arret(i))
        (sortie / ("invite_%d.txt" % (i + 1))).write_text(inv, encoding="utf-8")
        b64 = [base64.b64encode(Path(x).read_bytes()).decode() for x in [cle(cap + pas), *map(carte, suj)]]
        d2 = video_h3.preparer({"mode": "references", "images": b64, "image_paroles": "placeholder",
                                "definition": "768p", "longueur": 141, "graine": graine})["demande"]
        g2 = d2["graphe"]
        g2["10"]["inputs"]["prompt"] = inv
        propres = {k for k in g2 if k in {"10", "12", "13", "14", "15", "16", "17", "18"} or k.startswith("6")}

        def renomme(v, p=p, propres=propres):
            return [p + v[0], v[1]] if isinstance(v, list) and len(v) == 2 and v[0] in propres else v
        for k in propres:
            nd = json.loads(json.dumps(g2[k]))
            nd["inputs"] = {a: renomme(v) for a, v in nd["inputs"].items()}
            if nd["class_type"] == "LoadImage":
                nd["inputs"]["image"] = p + "_" + nd["inputs"]["image"]
            g[p + k] = nd
        images.update({p + "_" + nom: v for nom, v in d2["images"].items()})
        epingle = epingle_milieu or i == n - 1
        tete = p + "10"
        if vues is not None:     # 141 images dont 22 de contexte ; rendue r = f - 22 : cap + pas * (r + 1) / 119
            tete = intermediaires(p, tete, {f: cap + pas * (f - 22 + 1) / 119 for f in pins_suite(pas)})
        if epingle:
            g[p + "19"] = {"class_type": "MiniMaxH3AddGuide", "inputs": {
                "positive": [tete, 0], "vae": ["4", 0], "latent": [p + "10", 1], "image": [p + "60", 0],
                "frame_idx": -1}}
            tete = p + "19"
        g[p + "31"] = {"class_type": "MiniMaxH3MotionContext", "inputs": {
            "conditioning": [tete, 0], "vae": ["4", 0], "latent": [p + "10", 1], "context_length": "22",
            "audio_context_length": 24, "context_latent": [echantillon, 0]}}
        g[p + "13"]["inputs"]["conditioning"] = [p + "31", 0]
        g[p + "32"] = {"class_type": "MiniMaxH3MotionContextTrim", "inputs": {
            "images": [p + "15", 0], "audio": [p + "16", 0], "trim_frames": [p + "31", 1], "fps": 24.0}}
        g[p + "17"]["inputs"].update({"images": [p + "32", 0], "audio": [p + "32", 1]})
        g[p + "18"]["inputs"]["filename_prefix"] = "h3/clip_%d" % (i + 1)
        classes |= set(d2["classes"])
        echantillon = p + "14"

    d = dict(d1, graphe=g, images=images, delai_s=900 * n, classes=sorted(classes))
    (sortie / "graphe.json").write_text(json.dumps(g, indent=1), encoding="utf-8")
    # le script du Studio ne garde que le dernier clip rendu : tous les tronçons sont copiés en plus
    tous = ("\nfor _p in sorted(Path('/tmp/sortie/h3').glob('clip_*')):\n"
            "    shutil.copyfile(_p, OUT / _p.name)\n")
    (sortie / "script.py").write_text(video_h3.construire_script(d) + tous, encoding="utf-8")
    print("PRET", sortie / "script.py", "noeuds", len(g), "images", len(images), flush=True)


def lancer(script, sortie):
    sortie = Path(sortie)
    sortie.mkdir(parents=True, exist_ok=True)
    with modal.enable_output(), app.run():
        r = tourner.remote(Path(script).read_text(encoding="utf-8"))
    for nom, octets in r.pop("fichiers").items():
        (sortie / nom).write_bytes(octets)
    (sortie / "resultat.json").write_text(json.dumps(r, indent=1, ensure_ascii=False), encoding="utf-8")
    print("FAIT rc", r["rc"], r["s"], "s", sorted(p.name for p in sortie.iterdir()), flush=True)
    return r["rc"]


NOEUD_LOCAL = Path.home() / ".cache" / "free-ai-studio" / "h3_motion_context"   # clone au commit 5335715


def local(dossier_travail):
    """Le même script sur la 4090 (propriétaire, 06/10 : « finalement on fait latent en local aussi ») : le nœud
    tiers monté en lecture seule dans le ComfyUI maison, rien d'installé dans l'image."""
    import subprocess
    import time
    travail = Path(dossier_travail).resolve()
    poids = Path.home() / ".cache" / "free-ai-studio" / "poids"
    t = time.time()
    r = subprocess.run(["docker", "run", "--rm", "--gpus", "all", "--user", "0", "--name", "essai-latent",
                        "-e", "FREE_AI_OUTPUT_DIR=/sortie", "-v", f"{poids}:/poids:ro", "-v", f"{travail}:/sortie",
                        "-v", f"{NOEUD_LOCAL}:/comfy/custom_nodes/h3_motion_context:ro",
                        "--entrypoint", "sh", "free-ai-studio-comfy-maison", "-c",
                        "python /sortie/script.py; rc=$?; cp /tmp/comfy.log /sortie/comfy.log 2>/dev/null; exit $rc"],
                       capture_output=True, text=True)
    (travail / "sortie.log").write_text(r.stdout + "\n--- stderr ---\n" + r.stderr, encoding="utf-8")
    print("FAIT rc", r.returncode, round(time.time() - t, 1), "s", sorted(p.name for p in travail.iterdir()),
          flush=True)
    return r.returncode


if __name__ == "__main__":
    if sys.argv[1] == "preparer":
        preparer(sys.argv[2], sys.argv[3])
    elif sys.argv[1] == "local":
        sys.exit(local(sys.argv[2]))
    else:
        sys.exit(lancer(sys.argv[2], sys.argv[3]))
