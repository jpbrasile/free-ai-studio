"""Un film à 60 images/s, à pas réguliers le long du mouvement (PLAN 21.6, étape 5 du tour 360°).

Propriétaire, 06/10 : « celui que tu as lancé est encore saccadé », puis « plus de saccades, tout est ok » sur
l'atelier (scripts/decor360/gimm_vfi.py). H3 perd une image à chaque seconde pile : une interpolation à temps égaux
garde ce pas double. Le chemin parcouru est mesuré (corrélation de phase, déplacement horizontal) et les images de
sortie y sont placées à pas égaux ; GIMM-VFI (modèle « arb », nœud de kijai) calcule chaque image intermédiaire.

Sur la carte d'ici seulement (la machine comfy-maison a le nœud et ses dépendances ; les poids sont lus sur
/poids/gimm-vfi). Licence de GIMM-VFI : S-Lab License 1.0, NON COMMERCIALE, comme Qwen-Image 2.1 et YuE2 dans la
même chaîne.

Le chemin se mesure sur `chemin` quand il est donné : une 4K agrandie efface la texture d'un mur nu, la mesure y lit
un pas nul et les images s'y tassent (06/10, saut à 17-18 s vu par le propriétaire). Mesurer sur le film d'avant
l'agrandissement (mêmes images). Le son du film est gardé tel quel (même durée).
"""
import base64

import video_h3

IPS = 60
NOEUD = "/comfy/custom_nodes/gimm_vfi"
DOSSIER_POIDS = "gimm-vfi"
FICHIERS = (DOSSIER_POIDS + "/gimmvfi_r_arb_lpips_fp32.safetensors", DOSSIER_POIDS + "/raft-things_fp32.safetensors")
MOTEUR = "GIMM-VFI (60 images/s)"
VIDEO_MAX_OCTETS = 1024 * 1024 * 1024
# Mesuré le 06/10 sur la 4090, tour de 30 s (720 images) : 761 s en 3780x2160, 294 s en 1344x768.
S_PAR_IMAGE = {2160: 761.2 / 720, 768: 294.0 / 720}


def estimation_s(images: int, hauteur: int) -> float:
    cle = 2160 if hauteur > 1080 else 768
    return images * S_PAR_IMAGE[cle] * max(1.0, hauteur / cle)


def tient(images: int, hauteur: int) -> bool:
    """Une passe tient dans le plafond de la machine de la carte, avec une marge."""
    return estimation_s(images, hauteur) <= video_h3.MAISON_DUREE_MAX_S * 0.8


def demande(video: bytes, chemin: bytes = b"", delai_s: int = video_h3.MAISON_DUREE_MAX_S) -> dict:
    if len(video) > VIDEO_MAX_OCTETS:
        raise ValueError("Film trop lourd pour être fluidifié ici.")
    return {"video": base64.b64encode(video).decode(), "chemin": base64.b64encode(chemin).decode() if chemin else "",
            "ips": IPS, "delai_s": delai_s, "noeud": NOEUD, "base_poids": video_h3.POINT_DE_MONTAGE,
            "fichiers": list(FICHIERS)}


def construire_script(video: bytes, chemin: bytes = b"", delai_s: int = video_h3.MAISON_DUREE_MAX_S) -> str:
    return video_h3._emballer(_SCRIPT, demande(video, chemin, delai_s))


def phrase_d_echec(stderr: str) -> str:
    s = stderr or ""
    for mot, phrase in (
            ("GIMM_ABSENT", "La machine de la carte d'ici n'a pas GIMM-VFI ou ses poids : relancez le Studio par "
                            "demarrer.cmd (ou ./start.sh) pour la reconstruire, poids dans gimm-vfi."),
            ("MEMOIRE_CARTE", "La carte d'ici a manqué de mémoire pendant la fluidification (un autre programme "
                              "s'en sert ?). Le détail est dans le journal."),
            ("CHEMIN_ECART", "Le film de mesure n'a pas le même nombre d'images que le film à fluidifier."),
            ("LECTURE_ECHOUEE", "Le film n'a pas pu être lu."),
            ("DELAI", "La fluidification n'était pas finie avant le délai. Rien n'a été rendu."),
            ("ECRITURE_ECHOUEE", "Le film à 60 images/s n'a pas pu être écrit.")):
        if mot in s:
            return phrase
    return ""


# --- Le script envoyé à la machine de la carte d'ici -----------------------------------

_SCRIPT = r'''
# Fluidification du Free AI Studio : 60 images/s à pas réguliers le long du mouvement, GIMM-VFI (nœud de kijai,
# S-Lab License 1.0, non commerciale) appelé directement, une image intermédiaire à la fois.
import base64, json, os, subprocess, sys, time
from pathlib import Path

D = json.loads(base64.b64decode("__DEMANDE_B64__").decode())
OUT = Path(os.environ.get("FREE_AI_OUTPUT_DIR", "/tmp/free_ai_output"))
OUT.mkdir(parents=True, exist_ok=True)
# 06/10 : le nœud tel quel déborde des 7,5 Gio laissés par llama-server. Avant le premier import de torch.
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
t0 = time.time()
limite = t0 + D["delai_s"] - 60
BASE = Path(D["base_poids"])


def echouer(code, mot, detail=""):
    print(mot + " " + str(detail)[-3000:], file=sys.stderr)
    sys.exit(code)


manque = [f for f in D["fichiers"] if not (BASE / f).is_file()] + ([] if Path(D["noeud"]).is_dir() else [D["noeud"]])
if manque:
    echouer(3, "GIMM_ABSENT", ", ".join(manque))

film = Path("/tmp/fluide_entree.mp4")
film.write_bytes(base64.b64decode(D["video"]))
mesure = film
if D["chemin"]:
    mesure = Path("/tmp/fluide_chemin.mp4")
    mesure.write_bytes(base64.b64decode(D["chemin"]))


def sonde(chemin, champ, compter=False):
    r = subprocess.run(["ffprobe", "-v", "error", *(["-count_frames"] if compter else []), "-select_streams", "v:0",
                        "-show_entries", "stream=" + champ, "-of", "csv=p=0", str(chemin)],
                       capture_output=True, text=True)
    if r.returncode or not r.stdout.strip():
        echouer(9, "LECTURE_ECHOUEE", r.stderr)
    return r.stdout.strip()


import numpy as np  # noqa: E402


def pas_mesures(chemin, l=336, h=192):
    """Déplacement horizontal entre images voisines (corrélation de phase, px à la taille réduite)."""
    brut = subprocess.run(["ffmpeg", "-v", "error", "-i", str(chemin), "-fps_mode", "passthrough", "-vf", "scale=%d:%d" % (l, h), "-f",
                           "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True).stdout
    im = np.frombuffer(brut, np.uint8).reshape(-1, h, l).astype(np.float32)
    fen = np.outer(np.hanning(h), np.hanning(l))
    pas = []
    for i in range(len(im) - 1):
        r = np.fft.fft2(im[i] * fen).conj() * np.fft.fft2(im[i + 1] * fen)
        c = np.fft.ifft2(r / (np.abs(r) + 1e-9)).real
        y, x = np.unravel_index(c.argmax(), c.shape)
        g, m, d = c[y, (x - 1) % l], c[y, x], c[y, (x + 1) % l]
        fx = x + 0.5 * (g - d) / (g - 2 * m + d + 1e-12)
        pas.append(abs(fx - l if fx > l / 2 else fx))
    return np.array(pas)


l, h = (int(x) for x in sonde(film, "width,height").split(","))
n_entree = int(sonde(film, "nb_read_frames", True))
num, _, den = sonde(film, "r_frame_rate").partition("/")
ips_src = int(num) / int(den or 1)
s = np.concatenate([[0.0], np.cumsum(pas_mesures(mesure))])
if len(s) != n_entree:
    echouer(9, "CHEMIN_ECART", "%d images mesurées, %d dans le film" % (len(s), n_entree))
if s[-1] <= 0:
    s = np.arange(n_entree, dtype=float)            # rien ne bouge : temps égaux
n_sortie = round((n_entree - 1) / ips_src * D["ips"]) + 1
cibles = np.linspace(0, s[-1], n_sortie)

import torch  # noqa: E402
sys.path.insert(0, "/comfy")
try:
    from custom_nodes.gimm_vfi.nodes import DownloadAndLoadGIMMVFIModel, InputPadder
    t = time.time()
    modele = DownloadAndLoadGIMMVFIModel().loadmodel("gimmvfi_r_arb_lpips_fp32.safetensors", "fp16")[0]
except torch.cuda.OutOfMemoryError as exc:
    echouer(6, "MEMOIRE_CARTE au chargement", exc)
except Exception as exc:
    echouer(3, "GIMM_ABSENT", repr(exc))
charge_s = round(time.time() - t, 1)
ds = 0.5 if h <= 1080 else 0.25                       # flux à demi-résolution, au quart au-delà de 1080p

lec = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(film), "-fps_mode", "passthrough", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                       stdout=subprocess.PIPE)
muet = Path("/tmp/fluide_muet.mp4")
ecr = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "%dx%d" % (l, h),
                        "-r", str(D["ips"]), "-i", "-", "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p",
                        str(muet)], stdin=subprocess.PIPE)


def lire():
    b = lec.stdout.read(l * h * 3)
    if len(b) < l * h * 3:
        return None
    return torch.from_numpy(np.frombuffer(b, np.uint8).reshape(h, l, 3).astype(np.float32) / 255)


def entre(a, b, t):
    x0, x2 = (im.permute(2, 0, 1).unsqueeze(0) for im in (a, b))
    pad = InputPadder(x0.shape, 32)
    x0, x2 = pad.pad(x0, x2)
    xs = torch.cat((x0.unsqueeze(2), x2.unsqueeze(2)), dim=2).cuda()
    coord = [(modele.sample_coord_input(1, xs.shape[-2:], [t], device=xs.device, upsample_ratio=ds), None)]
    with torch.no_grad(), torch.autocast("cuda", dtype=torch.float16):
        sortie = modele(xs, coord, t=[t * torch.ones(1, device=xs.device)], ds_factor=ds)
    return pad.unpad(sortie["imgt_pred"][0])[0].float().permute(1, 2, 0).cpu()


torch.cuda.reset_peak_memory_stats()
a, b, j, n, calcul = lire(), lire(), 0, 0, 0
try:
    for c in cibles:
        if time.time() > limite:
            echouer(8, "DELAI", "image %d sur %d" % (n, n_sortie))
        while b is not None and c > s[j + 1] + 1e-6:
            a, b, j = b, lire(), j + 1
        t = 0.0 if b is None else (c - s[j]) / max(s[j + 1] - s[j], 1e-6)
        if t < 0.02 or b is None:
            im = a
        elif t > 0.98:
            im = b
        else:
            im, calcul = entre(a, b, float(t)), calcul + 1
        ecr.stdin.write((im.clamp(0, 1) * 255).round().to(torch.uint8).numpy().tobytes())
        n += 1
except torch.cuda.OutOfMemoryError as exc:
    echouer(6, "MEMOIRE_CARTE image %d" % n, exc)
ecr.stdin.close()
if ecr.wait():
    echouer(9, "ECRITURE_ECHOUEE")
r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(muet), "-i", str(film), "-map", "0:v", "-map", "1:a?",
                    "-c:v", "copy", "-c:a", "copy", "-shortest", str(OUT / "video.mp4")], capture_output=True, text=True)
if r.returncode:
    echouer(9, "ECRITURE_ECHOUEE", r.stderr)
dif = np.diff(s)
resume = {"modele": "GIMM-VFI arb (fp16)", "ips": D["ips"], "images_entree": n_entree, "images_sortie": n,
          "calculees": calcul, "chemin_mesure_sur": "film de mesure" if D["chemin"] else "film",
          "pas_min_median_max_px": [round(float(x), 2) for x in np.percentile(dif, [0, 50, 100])] if len(dif) else [],
          "poids_s": charge_s, "total_s": round(time.time() - t0, 1),
          "pic_vram_go": round(torch.cuda.max_memory_reserved() / 2**30, 1)}
(OUT / "resume.json").write_text(json.dumps(resume))
print("FLUIDE " + json.dumps(resume), flush=True)
'''
