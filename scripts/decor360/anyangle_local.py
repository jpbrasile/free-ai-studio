"""AnyAngle sur la 4090 (propriétaire, 05/10 : « oui lance l'essai Blender + AnyAngle, on part d'une image et de son
contre plan » ; « la carte locale est à toi en priorité »).

Pour chaque caméra cible de scene.json : <image1> = la photo source la plus proche (la plaque si la caméra regarde vers
l'avant, sinon le contrechamp), <image2> = le rendu grossier de scene_blender.py sous cet angle ; consigne et réglages
de la fiche du LoRA (lilylilith/QI_2.1_AnyAngle, Apache-2.0) : « Change the camera angle from <image2> to <image1>. »,
force 1, CFG 3, 25 pas. Graphe = retouche_qwen.graphe du Studio + LoraLoaderModelOnly ; script = retouche_qwen._SCRIPT,
dans un conteneur jetable de l'image ComfyUI locale (free-ai-studio-comfy-maison). Une image par conteneur.
Témoin « sans » : même demande sans le LoRA, CFG 1 (réglage du Studio), sur la première cible.

  python anyangle_local.py <dossier de l'essai> [graine] [caméra,caméra]     (sans liste : toutes + le témoin)
  python anyangle_local.py --polir <dossier de l'essai> <caméra> [graine]     (vue à mur nu, voir polir())
Le dossier contient scene.json, les photos sources et rendus/rendu_<caméra>.png ; sortie dans <dossier>/anyangle/.
Lancer par la file (ressource gpu).
"""
import base64
import json
import math
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sandbox-manager"))
import retouche_qwen as rq  # noqa: E402
import video_h3  # noqa: E402

POIDS = Path.home() / ".cache" / "free-ai-studio" / "poids"
LORA = "QI2.1_AnyAngle.safetensors"
CONSIGNE = "Change the camera angle from <image2> to <image1>."
# les poids locaux sont rangés à plat ; le LoRA est dans loras/, que le script du Studio ne déclare pas
SCRIPT = rq._SCRIPT.replace(r'vae: vae\n")', r'vae: vae\n  loras: loras\n")')
assert SCRIPT != rq._SCRIPT


def demande(base, rendu, graine, lora):
    g = rq.graphe("base.png", ["ref_00.png"], CONSIGNE, graine)
    classes = list(rq.CLASSES)
    if lora:
        g["5"] = {"class_type": "LoraLoaderModelOnly",
                  "inputs": {"model": ["1", 0], "lora_name": LORA, "strength_model": 1.0}}
        g["41"]["inputs"].update({"model": ["5", 0], "cfg": 3.0})
        classes.append("LoraLoaderModelOnly")
    return {"base": base64.b64encode(base).decode(), "refs": {"ref_00.png": base64.b64encode(rendu).decode()},
            "graphe": g, "classes": classes, "comfy": video_h3.DOSSIER_COMFY, "base_poids": "/poids",
            "depot": rq.HF, "revision": rq.HF_REVISION, "fichiers": list(rq.FICHIERS), "delai_s": 1800}


def tourner(d, travail, sortie):
    travail.mkdir(parents=True, exist_ok=True)
    (travail / "script.py").write_text(video_h3._emballer(SCRIPT, d), encoding="utf-8")
    t = time.time()
    r = subprocess.run(["docker", "run", "--rm", "--gpus", "all", "--user", "0", "--name", "anyangle-local",
                        "-e", "FREE_AI_OUTPUT_DIR=/sortie", "-v", f"{POIDS}:/poids:ro", "-v", f"{travail}:/sortie",
                        "--entrypoint", "sh", "free-ai-studio-comfy-maison", "-c",
                        "python /sortie/script.py; rc=$?; cp /tmp/comfy.log /sortie/comfy.log 2>/dev/null; exit $rc"],
                       capture_output=True, text=True)
    (travail / "sortie.log").write_text(r.stdout + "\n--- stderr ---\n" + r.stderr, encoding="utf-8")
    if r.returncode == 0 and (travail / "retouche.png").is_file():
        (travail / "retouche.png").replace(sortie)
    return r.returncode, round(time.time() - t, 1)


def main(dossier, graine=11, cameras=None):
    dossier = Path(dossier).resolve()
    cfg = json.loads((dossier / "scene.json").read_text(encoding="utf-8"))
    # photos à plat (pas le panorama), par lacet : la plus proche de la caméra sert de base
    sources = {s["lacet"]: (dossier / s["image"]).read_bytes() for s in cfg["sources"] if s.get("type") != "pano"}
    out = dossier / "anyangle"
    out.mkdir(exist_ok=True)
    bilan = []
    cibles = [c for c in cfg["cameras"] if not c["nom"].startswith("verif")]
    if cameras:                       # caméras choisies : ni les autres, ni le témoin sans LoRA
        cibles = [c for c in cibles if c["nom"] in cameras]
        essais = [(c, True) for c in cibles]
    else:
        essais = [(c, True) for c in cibles] + [(cibles[0], False)]
    for cam, lora in essais:
        base = sources[max(sources, key=lambda la: math.cos(math.radians(cam["lacet"] - la)))]
        rendu = (dossier / "rendus" / ("rendu_%s.png" % cam["nom"])).read_bytes()
        nom = "%s_%s_g%d" % (cam["nom"], "aa" if lora else "sans", graine)
        rc, duree = tourner(demande(base, rendu, graine, lora), out / ("travail_" + nom), out / (nom + ".png"))
        bilan.append({"essai": nom, "rc": rc, "duree_s": duree})
        print("FAIT", nom, rc, duree, flush=True)
        (out / "bilan.json").write_text(json.dumps(bilan, indent=1), encoding="utf-8")


CONSIGNE_POLIR = ("Turn <image1> into a realistic photograph of the same living room as <image2>: same cream walls, "
                  "baseboards, beige carpet, daylight and colours. Keep the camera, the walls and the doorway of "
                  "<image1> exactly where they are.")


def polir(dossier, camera, graine=11):
    """Vue où le rendu n'a qu'un mur nu : AnyAngle y refait la vue de face. Retouche sans LoRA, le rendu en base
    (<image1>), la plaque pour la matière (<image2>) ; la géométrie du rendu est gardée."""
    dossier = Path(dossier).resolve()
    rendu = (dossier / "rendus" / ("rendu_%s.png" % camera)).read_bytes()
    d = demande(rendu, (dossier / "plaque.png").read_bytes(), graine, False)
    d["graphe"] = rq.graphe("base.png", ["ref_00.png"], CONSIGNE_POLIR, graine)
    nom = "%s_polir_g%d" % (camera, graine)
    out = dossier / "anyangle"
    print("FAIT", nom, *tourner(d, out / ("travail_" + nom), out / (nom + ".png")), flush=True)


if __name__ == "__main__":
    if sys.argv[1] == "--polir":       # python anyangle_local.py --polir <dossier> <caméra> [graine]
        polir(sys.argv[2], sys.argv[3], *(int(x) for x in sys.argv[4:5]))
    else:
        main(sys.argv[1], *(int(x) for x in sys.argv[2:3]), *(sys.argv[3].split(",") for _ in sys.argv[3:4]))
