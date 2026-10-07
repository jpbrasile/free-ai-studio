"""Maquette, essai 4 (propriétaire, 05/10 : « oui fais les deux »).

Leçons de S11 : (1) panorama né à 1024 -> SeedVR2 x4 invente le détail (jardin peint, moquette ondulée) ;
(2) l'Union guidée par la seule profondeur ne connaît pas l'équirectangulaire -> droites courbes au plafond.
Ici :
  1. Union à 2048x1024 (QwenImage21UnionLatentFromImage, résolution 1440), hors plaque sous masque, contrôle = les
     ARÊTES de la maquette (blanc sur noir ; ce sont les droites exactes de la pièce en projection équirectangulaire).
     Variantes : L = arêtes seules (mode Lineart) ; DL = profondeur puis arêtes, deux Union enchaînées.
  2. Couture : demi-tour, bande de +-25° repeinte par la même Union, remis dans le sens.
  3. SeedVR2 x2 une seule fois -> 4096 (prolongé par l'autre bord).
  4. La plaque d'origine recollée à pleine résolution (fondu de 24 px), puis six vues (180 = contrechamp).
Chaque image part dès qu'elle est faite.

  python maquette4_modal.py /tmp/anyangle/maquette /tmp/anyangle/maq4 L11 L7 DL11
"""
import json
import sys
import time
from pathlib import Path

import modal

if modal.is_local():
    sys.path.insert(0, "/app")
    import agrandir  # noqa: E402
    import retouche_qwen as rq  # noqa: E402

VOLUME = "free-ai-studio-h3"
BASE = "/poids/qwen-image-21"
BASE_SEEDVR = "/poids/seedvr2"
T8 = ("https://github.com/T8mars/Comfyui-Qwen-Image-2.1-Fun-Controlnet-Union-T8",
      "01f084ccde2f2a262529b6e7b5504df9ea36a0b7")
UNION = ("Qwen-Image-2.1-Fun-Controlnet-Union-ComfyUI.safetensors", "t8star/Qwen-Image-2.1-Fun-Controlnet-Union-Comfy",
         "199bd863c41b5401e3c9bbc2b1bd4b62f468229c")
FX, PL_L, PL_H, MARGE = 904.0, 1344, 768, 12
TANGAGE = 0.0              # caméra devinée de maquette.py ; camera.json du dossier source (maquette_plan.py) la remplace
# La photo est recollée en retrait de ses bords, repeints par l'Union (comme tour360_pano.py du Studio, 2,5 %) : un
# objet coupé par le bord du cadre (chant d'un panneau au premier plan) devenait un poteau isolé dans le tour (06/10).
RETRAIT = 40
PANO_L, PANO_H = 2048, 1024
RESOLUTION = 1440          # -> latent 2048x1024 pour une image 2:1
BANDE = 25.0
ENROULE = 128
FONDU = 24
CONSIGNE = ("An equirectangular 360 panorama of the living room of <image1>, seen from the same spot, following the "
            "box layout exactly. On the left, the floor-to-ceiling glass wall with thin black frames continues up to "
            "beside the camera. On the right, the cream wall keeps its two open doorways to the hallway. Behind the "
            "camera the room is closed: a solid cream plastered wall with a tall wooden bookshelf with a solid back "
            "panel, full of books, a grey armchair and a floor lamp, a wooden door in the right wall, white ceiling, "
            "beige carpet, soft daylight from the room.")
LACETS = (0, 60, 120, 180, 240, 300)
CHAMP, VUE_L, VUE_H = 75.0, 1344, 768

app = modal.App("essai-maquette4-aretes")
poids = modal.Volume.from_name(VOLUME)
image = (modal.Image.debian_slim(python_version="3.12")
         .apt_install("git", "libgl1", "libglib2.0-0")
         .run_commands("git clone --depth 1 --branch v0.37.0 https://github.com/Comfy-Org/ComfyUI /comfy",
                       "pip install --no-cache-dir -r /comfy/requirements.txt psutil huggingface_hub pillow "
                       "opencv-python-headless",
                       "git clone %s /comfy/custom_nodes/union_t8 && cd /comfy/custom_nodes/union_t8 && "
                       "git checkout %s" % T8))


def union(voie, graine, entree, masque, controles):
    """Graphe Union : controles = [(mode, fichier)], enchaînés dans l'ordre."""
    g = rq.graphe("plaque.png", [], CONSIGNE, graine)
    g["4"] = {"class_type": "QwenImage21UnionLoader", "inputs": {"union_model": UNION[0]}}
    g["20"] = {"class_type": "LoadImage", "inputs": {"image": entree}}
    g["21"] = {"class_type": "LoadImageMask", "inputs": {"image": masque, "channel": "red"}}
    modele = ["1", 0]
    for k, (mode, fichier) in enumerate(controles):
        g[str(60 + k)] = {"class_type": "LoadImage", "inputs": {"image": fichier}}
        g[str(70 + k)] = {"class_type": "QwenImage21UnionApply",
                          "inputs": {"control_mode": mode, "strength": 1.0, "start_percent": 0.0, "end_percent": 1.0,
                                     "model": modele, "union_patch": ["4", 0], "vae": ["3", 0],
                                     "control_image": [str(60 + k), 0], "inpaint_image": ["20", 0],
                                     "mask": ["21", 0]}}
        modele = [str(70 + k), 0]
    g["13"] = {"class_type": "QwenImage21UnionLatentFromImage",
               "inputs": {"resolution": RESOLUTION, "image": ["20", 0]}}
    g["41"]["inputs"].update({"model": modele, "latent_image": ["13", 0]})
    return g


CONTROLES = {"L": [("Lineart", "aretes{s}.png")],
             "DL": [("Depth", "profondeur{s}.png"), ("Lineart", "aretes{s}.png")]}


def graphes_locaux(essais):
    out = {}
    for e in essais:
        voie, graine = e.rstrip("0123456789"), int(e[len(e.rstrip("0123456789")):])
        c1 = [(m, f.format(s="")) for m, f in CONTROLES[voie]]
        c2 = [(m, f.format(s="_tourne")) for m, f in CONTROLES[voie]]
        out[e] = (union(voie, graine, "maquette.png", "masque.png", c1),
                  union(voie, graine, "tourne.png", "bande.png", c2))
    s = agrandir.graphe("x.mp4", "x2", "agrandi")
    s["1"] = {"class_type": "LoadImage", "inputs": {"image": "a_agrandir.png"}}
    s["2"] = {"class_type": "RepeatImageBatch", "inputs": {"image": ["1", 0], "amount": agrandir.MULTIPLE}}
    s["3"]["inputs"]["input"] = ["2", 0]
    del s["14"], s["15"]
    s["16"] = {"class_type": "ImageFromBatch", "inputs": {"image": ["13", 0], "batch_index": 0, "length": 1}}
    s["43"] = {"class_type": "SaveImage", "inputs": {"images": ["16", 0], "filename_prefix": "agrandi"}}
    return out, s


def directions(l, h):
    import numpy as np
    lon = ((np.arange(l) + 0.5) / l - 0.5) * 2 * np.pi
    lat = (0.5 - (np.arange(h) + 0.5) / h) * np.pi
    lon, lat = np.meshgrid(lon, lat)
    return np.cos(lat) * np.sin(lon), -np.sin(lat), np.cos(lat) * np.cos(lon)


def coord_plaque(l, h):
    import numpy as np
    x, y, z = directions(l, h)
    t = -np.radians(TANGAGE)            # y vers le bas : plaque tournée vers le bas (< 0) = horizon au-dessus du milieu
    y, z = y * np.cos(t) - z * np.sin(t), z * np.cos(t) + y * np.sin(t)
    devant = z > 1e-3
    zs = np.where(devant, z, 1.0)
    return devant, FX * x / zs + PL_L / 2, FX * y / zs + PL_H / 2


def masque_hors_plaque():
    import cv2
    import numpy as np
    devant, u, v = coord_plaque(PANO_L, PANO_H)
    dedans = devant & (u >= RETRAIT) & (u < PL_L - RETRAIT) & (v >= RETRAIT) & (v < PL_H - RETRAIT)
    m = cv2.dilate((~dedans).astype(np.uint8) * 255, np.ones((2 * MARGE + 1, 2 * MARGE + 1), np.uint8))
    return cv2.GaussianBlur(m, (0, 0), 4)


def masque_bande():
    import cv2
    import numpy as np
    lon = ((np.arange(PANO_L) + 0.5) / PANO_L - 0.5) * 360.0
    m = np.repeat((np.abs(lon) <= BANDE).astype(np.float32)[None, :], PANO_H, axis=0)
    return (cv2.GaussianBlur(m, (0, 0), 10) * 255).astype(np.uint8)


def recoller_plaque(pano, plaque):
    """La plaque d'origine (1344x768) remise à pleine résolution, fondu doux de FONDU px sur son bord."""
    import cv2
    import numpy as np
    h, w = pano.shape[:2]
    devant, u, v = coord_plaque(w, h)
    bord = np.minimum.reduce([u, PL_L - u, v, PL_H - v]) - RETRAIT
    a = np.where(devant, np.clip(bord / FONDU, 0, 1), 0.0)
    a = (a * a * (3 - 2 * a))[..., None]
    echelle = (w / (2 * np.pi)) / FX
    petite = cv2.resize(plaque, (round(PL_L * echelle), round(PL_H * echelle)), interpolation=cv2.INTER_AREA)
    src = cv2.remap(petite, (u * echelle - 0.5).astype(np.float32), (v * echelle - 0.5).astype(np.float32),
                    cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    return (pano * (1 - a) + src * a).clip(0, 255).astype(np.uint8)


def reprojeter(pano, lacet):
    import cv2
    import numpy as np
    h_p, l_p = pano.shape[:2]
    f = (VUE_L / 2) / np.tan(np.radians(CHAMP / 2))
    x, y = np.meshgrid(np.arange(VUE_L) - VUE_L / 2 + 0.5, np.arange(VUE_H) - VUE_H / 2 + 0.5)
    d = np.stack([x / f, y / f, np.ones_like(x)], -1)
    c, s = np.cos(np.radians(lacet)), np.sin(np.radians(lacet))
    xr, zr = c * d[..., 0] + s * d[..., 2], -s * d[..., 0] + c * d[..., 2]
    lon = np.arctan2(xr, zr)
    lat = -np.arctan2(d[..., 1], np.hypot(xr, zr))
    u = ((lon / (2 * np.pi) + 0.5) * l_p - 0.5).astype(np.float32)
    v = ((0.5 - lat / np.pi) * h_p - 0.5).astype(np.float32)
    return cv2.remap(pano, u, v, cv2.INTER_CUBIC, borderMode=cv2.BORDER_WRAP)


@app.function(image=image, gpu="A100-80GB", volumes={"/poids": poids}, timeout=3600)
def carte(maquette: bytes, profondeur: bytes, aretes: bytes, plaque: bytes, essais: dict, seedvr: dict,
          qwen: dict, seedvr_poids: dict, camera: dict = None):
    global FX, TANGAGE
    if camera:                          # caméra mesurée de la plaque (maquette_plan.py : camera.json)
        FX, TANGAGE = camera["f"], camera["tangage"]
    import subprocess
    import urllib.request

    import cv2
    import numpy as np
    from huggingface_hub import hf_hub_download
    t0, temps = time.time(), {}
    for f in qwen["fichiers"]:
        if not Path(BASE, f).is_file():
            hf_hub_download(qwen["depot"], f, revision=qwen["revision"], local_dir=BASE)
    if not Path(BASE, "controlnet", UNION[0]).is_file():
        hf_hub_download(UNION[1], UNION[0], revision=UNION[2], local_dir=BASE + "/controlnet")
    for f in seedvr_poids["fichiers"]:
        if not Path(BASE_SEEDVR, f).is_file():
            hf_hub_download(seedvr_poids["depot"], f, revision=seedvr_poids["revision"], local_dir=BASE_SEEDVR)
    poids.commit()
    Path("/tmp/chemins.yaml").write_text(
        "q:\n  base_path: %s\n  diffusion_models: diffusion_models\n  text_encoders: text_encoders\n  vae: vae\n"
        "  loras: loras\n  controlnet: controlnet\ns:\n  base_path: %s\n  diffusion_models: diffusion_models\n"
        "  vae: vae\n" % (BASE, BASE_SEEDVR))
    entree = Path("/comfy/input")
    entree.mkdir(exist_ok=True)

    def png(img):
        return cv2.imencode(".png", img)[1].tobytes()

    def lire_img(octets):
        return cv2.imdecode(np.frombuffer(octets, np.uint8), cv2.IMREAD_COLOR)

    def taille(img):
        return cv2.resize(img, (PANO_L, PANO_H), interpolation=cv2.INTER_AREA)

    def demi(img, sens=1):
        return np.roll(img, sens * PANO_L // 2, 1)

    base = taille(lire_img(maquette))
    prof = taille(lire_img(profondeur))
    ar = cv2.resize(lire_img(aretes), (PANO_L, PANO_H), interpolation=cv2.INTER_NEAREST)
    pl = cv2.resize(lire_img(plaque), (PL_L, PL_H), interpolation=cv2.INTER_AREA)
    masque, bande = masque_hors_plaque(), masque_bande()
    m, mb = (masque.astype(np.float32) / 255)[..., None], (bande.astype(np.float32) / 255)[..., None]
    for nom, img in (("maquette.png", base), ("profondeur.png", prof), ("aretes.png", ar),
                     ("profondeur_tourne.png", demi(prof)), ("aretes_tourne.png", demi(ar)),
                     ("masque.png", masque), ("bande.png", bande), ("plaque.png", pl)):
        (entree / nom).write_bytes(png(img))
    yield "masque.png", png(masque)
    journal = open("/tmp/comfy.log", "w")
    proc = subprocess.Popen(["python", "main.py", "--listen", "127.0.0.1", "--port", "8188",
                             "--extra-model-paths-config", "/tmp/chemins.yaml", "--output-directory", "/tmp/sortie"],
                            cwd="/comfy", stdout=journal, stderr=subprocess.STDOUT)

    def lire(chemin, corps=None):
        req = urllib.request.Request("http://127.0.0.1:8188" + chemin, data=corps,
                                     headers={"Content-Type": "application/json"} if corps else {})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())

    def tourner(nom, g):
        t1 = time.time()
        try:
            pid = lire("/prompt", json.dumps({"prompt": g}).encode())["prompt_id"]
        except Exception as e:
            return None, getattr(e, "read", lambda: str(e).encode())()
        while True:
            hist = lire("/history/" + pid)
            if pid in hist and hist[pid].get("status", {}).get("completed") is not None:
                break
            if proc.poll() is not None:
                break
            time.sleep(1)
        temps[nom] = round(time.time() - t1, 1)
        images = hist.get(pid, {}).get("outputs", {}).get("43", {}).get("images", [])
        if not images:
            return None, json.dumps(hist.get(pid, {}).get("status")).encode()
        return Path("/tmp/sortie", images[0].get("subfolder", ""), images[0]["filename"]).read_bytes(), None

    for _ in range(300):
        try:
            lire("/system_stats")
            break
        except Exception:
            time.sleep(1)
    for nom, (g1, g2) in essais.items():
        octets, err = tourner("pano_" + nom, g1)
        if err:
            yield "pano_%s.erreur.txt" % nom, err
            continue
        pano = (base * (1 - m) + taille(lire_img(octets)) * m).astype(np.uint8)
        yield "pano_%s_2048_couture.png" % nom, png(pano)
        tourne = demi(pano)
        (entree / "tourne.png").write_bytes(png(tourne))
        octets, err = tourner("couture_" + nom, g2)
        if err:
            yield "couture_%s.erreur.txt" % nom, err
            continue
        pano = demi((tourne * (1 - mb) + taille(lire_img(octets)) * mb).astype(np.uint8), -1)
        yield "pano_%s_2048.png" % nom, png(pano)
        (entree / "a_agrandir.png").write_bytes(png(np.concatenate([pano[:, -ENROULE:], pano, pano[:, :ENROULE]], 1)))
        octets, err = tourner("seedvr_" + nom, seedvr)
        if err:
            yield "seedvr_%s.erreur.txt" % nom, err
            continue
        g = lire_img(octets)
        e = round(ENROULE * g.shape[1] / (PANO_L + 2 * ENROULE))
        grand = cv2.resize(g[:, e:g.shape[1] - e], (2 * PANO_L, 2 * PANO_H), interpolation=cv2.INTER_AREA)
        grand = recoller_plaque(grand, pl)
        yield "pano_%s_4096.png" % nom, png(grand)
        for lacet in LACETS:
            yield "vue_%s_%03d.png" % (nom, lacet), png(reprojeter(grand, lacet))
    proc.kill()
    temps["total_s"] = round(time.time() - t0, 1)
    yield "comfy.log", Path("/tmp/comfy.log").read_bytes()[-20000:]
    yield "temps.json", json.dumps(temps).encode()


if __name__ == "__main__":
    src, dossier = Path(sys.argv[1]), Path(sys.argv[2])
    essais = sys.argv[3:] or ["L11"]
    dossier.mkdir(parents=True, exist_ok=True)
    graphes, seedvr = graphes_locaux(essais)
    with modal.enable_output(), app.run():
        for nom, octets in carte.remote_gen((src / "maquette_plaque.png").read_bytes(),
                                            (src / "maquette_profondeur.png").read_bytes(),
                                            (src / "maquette_aretes.png").read_bytes(),
                                            (src / "plaque.png").read_bytes(), graphes, seedvr,
                                            {"fichiers": list(rq.FICHIERS), "depot": rq.HF,
                                             "revision": rq.HF_REVISION},
                                            {"fichiers": list(agrandir.FICHIERS), "depot": agrandir.HF,
                                             "revision": agrandir.HF_REVISION},
                                            json.loads((src / "camera.json").read_text(encoding="utf-8"))
                                            if (src / "camera.json").is_file() else None):
            (dossier / nom).write_bytes(octets)
            print("SORTI", nom, len(octets), round(time.time()), flush=True)
