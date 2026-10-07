"""Repeindre une zone masquée d'une image exacte par Qwen-Image 2.1, avec des photos de fiche (propriétaire, 07/10 :
« qwen 2.1 image cannot help in repainting » ; usage courant : SetLatentNoiseMask + TextEncodeQwenImage21, et le
dehors du masque n'est pas garanti au pixel près, d'où le recollage).

Graphe = retouche_qwen.graphe du Studio (<image1> = l'image, <image2>… = les photos), dont le latent est l'image
encodée sous un masque de bruit (VAEEncode -> SetLatentNoiseMask) ; conteneur jetable de l'image ComfyUI locale,
comme anyangle_local.py. Puis seul le masque (adouci) est recollé sur l'image exacte.

  python repeindre_qwen.py <image.png> <masque.png> <consigne.txt> <sortie.png> [photo.png ...] [--graine n]
         [--force 0.75]
  -> <sortie.png> (recollée), <sortie>_qwen.png (sortie brute du modèle)          (par la file ou le porteur : gpu)
"""
import base64
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sandbox-manager"))
import retouche_qwen as rq  # noqa: E402
import video_h3  # noqa: E402
from anyangle_local import tourner  # noqa: E402

ELARGIR, ADOUCIR = 9, 6            # px : le masque grossi (bords repris par le modèle), puis fondu au recollage


def demande(image, masque, consigne, photos, graine, force=1.0):
    """`force` < 1 : le masque garde la mise en place de l'image (un élément déjà à sa place, flou, à nettoyer)."""
    noms = ["ref_%02d.png" % k for k in range(len(photos))]
    g = rq.graphe("base.png", noms, consigne, graine)
    g["41"]["inputs"]["denoise"] = force
    g["50"] = {"class_type": "LoadImage", "inputs": {"image": "masque.png"}}
    g["51"] = {"class_type": "ImageToMask", "inputs": {"image": ["50", 0], "channel": "red"}}
    g["52"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["10", 0], "vae": ["3", 0]}}
    g["53"] = {"class_type": "SetLatentNoiseMask", "inputs": {"samples": ["52", 0], "mask": ["51", 0]}}
    g["41"]["inputs"]["latent_image"] = ["53", 0]
    refs = {n: base64.b64encode(p).decode() for n, p in zip(noms, photos)}
    refs["masque.png"] = base64.b64encode(masque).decode()
    return {"base": base64.b64encode(image).decode(), "refs": refs, "graphe": g,
            "classes": list(rq.CLASSES) + ["ImageToMask", "VAEEncode", "SetLatentNoiseMask"],
            "comfy": video_h3.DOSSIER_COMFY, "base_poids": "/poids", "depot": rq.HF, "revision": rq.HF_REVISION,
            "fichiers": list(rq.FICHIERS), "delai_s": 1800}


def main(a):
    graine, force = 11, 1.0
    if "--graine" in a:
        i = a.index("--graine")
        graine = int(a[i + 1])
        a = a[:i] + a[i + 2:]
    if "--force" in a:
        i = a.index("--force")
        force = float(a[i + 1])
        a = a[:i] + a[i + 2:]
    image, masque, consigne, sortie, *photos = (Path(x).resolve() for x in a)
    m = Image.open(masque).convert("L").filter(ImageFilter.MaxFilter(2 * ELARGIR + 1))
    import io
    tampon = io.BytesIO()
    m.convert("RGB").save(tampon, "PNG")
    d = demande(image.read_bytes(), tampon.getvalue(), consigne.read_text(encoding="utf-8"),
                [p.read_bytes() for p in photos], graine, force)
    brut = sortie.with_name(sortie.stem + "_qwen.png")
    rc, duree = tourner(d, sortie.parent / ("travail_" + sortie.stem), brut)
    print("QWEN rc", rc, "en", duree, "s", flush=True)
    if rc != 0 or not brut.is_file():
        sys.exit(1)
    exact = Image.open(image).convert("RGB")
    q = Image.open(brut).convert("RGB").resize(exact.size, Image.LANCZOS)
    a_ = np.asarray(m.filter(ImageFilter.GaussianBlur(ADOUCIR)), np.float32)[..., None] / 255.0
    r = np.asarray(q, np.float32) * a_ + np.asarray(exact, np.float32) * (1 - a_)
    Image.fromarray(r.clip(0, 255).astype(np.uint8)).save(sortie)
    dehors = np.asarray(m) == 0
    ecart = np.abs(np.asarray(q, int) - np.asarray(exact, int))[dehors].mean()
    print("ok", sortie, "écart du modèle hors masque %.1f / 255 (effacé par le recollage)" % ecart, flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
