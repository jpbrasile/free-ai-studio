"""Essai GIMM-VFI (propriétaire, 06/10 : « oui essaie gimm-vfi ») : un clip H3 à 24 i/s passé à 60 i/s par
interpolation de mouvement, pour ôter la saccade du panoramique. Le nœud de kijai (ComfyUI-GIMM-VFI, commit 4c9a312)
est monté en lecture seule dans le ComfyUI maison et appelé directement, sans graphe ; ses dépendances (cupy, timm,
omegaconf, yacs, easydict) s'installent au lancement du conteneur jetable, rien dans l'image.

Les images de sortie sont placées à pas égaux le long du chemin mesuré (pas à temps égaux) : H3 perd une image par
seconde, et une interpolation à temps égaux garderait ce pas double. GIMM (modèle « arb ») interpole à tout instant
t entre deux images ; une seule image intermédiaire à la fois, envoyée aussitôt à ffmpeg.
Pour une caméra qui tourne (déplacement horizontal) ; un autre mouvement demanderait une autre mesure du chemin.

  python gimm_vfi.py <entree.mp4> <sortie.mp4> [chemin.mp4]   (lance le conteneur sur la 4090 ; par la file, gpu)

`chemin` : le chemin se mesure sur ce clip (mêmes images, autre définition). Sur une 4K agrandie, un mur nu a perdu
sa texture : la mesure y lit un pas nul (06/10, 16-20 s du tour : 0,0 px au lieu de 2 px) et les images de sortie s'y
tassent. Mesurer sur le clip d'avant l'agrandissement.
"""
import subprocess
import sys
import time
from pathlib import Path

NOEUD = Path.home() / ".cache" / "free-ai-studio" / "noeuds" / "ComfyUI-GIMM-VFI"
POIDS = Path.home() / ".cache" / "free-ai-studio" / "poids" / "gimm-vfi"
DEPS = "cupy-cuda13x[ctk] timm omegaconf yacs easydict"
IPS = 60
DS, PRECISION = 0.5, "fp16"            # flux estimé à demi-résolution (768p), au quart en 4K (ds plus bas)


def dedans(entree, sortie, chemin=None):
    """Dans le conteneur : lit, interpole paire par paire, écrit."""
    import numpy as np
    import torch
    sys.path.insert(0, "/comfy")
    from custom_nodes.gimm_vfi.nodes import DownloadAndLoadGIMMVFIModel
    sonde = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=width,height", "-of", "csv=p=0", entree], capture_output=True, text=True)
    l, h = (int(x) for x in sonde.stdout.strip().split(","))
    lec = subprocess.Popen(["ffmpeg", "-v", "error", "-i", entree, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                           stdout=subprocess.PIPE)
    ecr = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "%dx%d" % (l, h),
                            "-r", str(IPS), "-i", "-", "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", sortie],
                           stdin=subprocess.PIPE)
    from custom_nodes.gimm_vfi.nodes import InputPadder
    ds = DS if h <= 1080 else DS / 2
    modele = DownloadAndLoadGIMMVFIModel().loadmodel("gimmvfi_r_arb_lpips_fp32.safetensors", PRECISION)[0]

    def entre(a, b, t):
        """Une seule image au temps t entre a et b : le nœud les calcule toutes d'un coup et déborde des 7,5 Gio
        laissés par llama-server (06/10, OOM à la première paire en fp32, x5, pleine résolution)."""
        x0, x2 = (im.permute(2, 0, 1).unsqueeze(0) for im in (a, b))
        pad = InputPadder(x0.shape, 32)
        x0, x2 = pad.pad(x0, x2)
        xs = torch.cat((x0.unsqueeze(2), x2.unsqueeze(2)), dim=2).cuda()
        coord = [(modele.sample_coord_input(1, xs.shape[-2:], [t], device=xs.device, upsample_ratio=ds), None)]
        with torch.no_grad(), torch.autocast("cuda", dtype=torch.float16):
            sortie = modele(xs, coord, t=[t * torch.ones(1, device=xs.device)], ds_factor=ds)
        return pad.unpad(sortie["imgt_pred"][0])[0].float().permute(1, 2, 0).cpu()

    def lire():
        b = lec.stdout.read(l * h * 3)
        if len(b) < l * h * 3:
            return None
        return torch.from_numpy(np.frombuffer(b, np.uint8).reshape(h, l, 3).astype(np.float32) / 255)

    def ecrire(t):
        ecr.stdin.write((t.clamp(0, 1) * 255).round().to(torch.uint8).numpy().tobytes())

    t0 = time.time()
    s = np.concatenate([[0.0], np.cumsum(pas_mesures(chemin or entree))])    # chemin parcouru à chaque image source
    ips_src = eval(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                   "stream=r_frame_rate", "-of", "csv=p=0", entree],
                                  capture_output=True, text=True).stdout.strip())
    n_sortie = round((len(s) - 1) / ips_src * IPS) + 1                # même durée
    cibles = np.linspace(0, s[-1], n_sortie)                         # pas égaux le long du chemin
    a, b, j, n = lire(), lire(), 0, 0
    for c in cibles:
        while b is not None and c > s[j + 1] + 1e-6:
            a, b, j = b, lire(), j + 1
        t = 0.0 if b is None else (c - s[j]) / max(s[j + 1] - s[j], 1e-6)
        ecrire(a if t < 0.02 or b is None else b if t > 0.98 else entre(a, b, float(t)))
        n += 1
    ecr.stdin.close()
    print("FAIT", len(s), "images lues,", n, "écrites à", IPS, "i/s, pas source min/médian/max %.2f/%.2f/%.2f px,"
          % tuple(np.percentile(np.diff(s), [0, 50, 100])), round(time.time() - t0, 1), "s", flush=True)
    return ecr.wait()


def pas_mesures(entree, l=336, h=192):
    """Déplacement horizontal entre images voisines (corrélation de phase, px à la taille réduite). H3 perd une
    image à chaque seconde pile (06/10 : pas double à 1,00 s, 2,00 s… dans le clip brut, avec ou sans épingles) ;
    rééchantillonner à pas égaux le long du chemin bouche ces trous au lieu de les interpoler fidèlement."""
    import numpy as np
    brut = subprocess.run(["ffmpeg", "-v", "error", "-i", entree, "-vf", "scale=%d:%d" % (l, h), "-f", "rawvideo",
                           "-pix_fmt", "gray", "-"], capture_output=True).stdout
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


def lancer(entree, sortie, chemin=None):
    entree, sortie = Path(entree).resolve(), Path(sortie).resolve()
    monte = ["-v", f"{Path(chemin).resolve().parent}:/chemin:ro"] if chemin else []
    arg = f" /chemin/{Path(chemin).name}" if chemin else ""
    POIDS.mkdir(parents=True, exist_ok=True)
    ici = Path(__file__).resolve().parent
    cmd = (f"pip install -q {DEPS} && python /code/gimm_vfi.py --dedans /entree/{entree.name} /sortie/{sortie.name}{arg}")
    t = time.time()
    r = subprocess.run(["docker", "run", "--rm", "--gpus", "all", "--user", "0", "--name", "essai-gimm-vfi",
                        "-v", f"{NOEUD}:/comfy/custom_nodes/gimm_vfi:ro", "-v", f"{POIDS}:/comfy/models/interpolation/gimm-vfi",
                        *monte, "-v", f"{ici}:/code:ro", "-v", f"{entree.parent}:/entree:ro", "-v", f"{sortie.parent}:/sortie",
                        "-e", "PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True", "--entrypoint", "sh", "free-ai-studio-comfy-maison", "-c", cmd])
    print("rc", r.returncode, round(time.time() - t, 1), "s", flush=True)
    return r.returncode


if __name__ == "__main__":
    a = sys.argv[1:]
    sys.exit(dedans(*a[1:4]) if a[0] == "--dedans" else lancer(*a[0:3]))
