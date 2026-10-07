"""Le panoramique EXACT du tour 360°, image par image, tiré du panorama (propriétaire, 06/10 : « le raccordement ne
se fait pas alors que l'on part d'une modélisation 3d!!!! »). La caméra tourne sur place : chaque image du chemin est
une vue du panorama (vues_pano.vue), aucune n'est à inventer. Sert de vérité pour mesurer un tour H3, et de source
d'épingles intermédiaires (une vue exacte tous les quelques degrés au lieu d'une clé tous les 30°).

Saccades (propriétaire, 06/10 : « comment éviter l'effet saccadé des frames ») : 360° en 30 s à 24 i/s, c'est 0,5°
(~8 px) par image sans flou, le « judder » des panoramiques. `--ips 60` rend 60 images par seconde ; `--flou k`
moyenne k sous-vues sur une obturation de 180° (la moitié de l'intervalle entre deux images), comme une caméra.

  python pano_pan.py <pano.png> <sortie.mp4> [durée du tour en s, 60] [--ips 24] [--flou 1] [--fx 904]
"""
import subprocess
import sys

import numpy as np
from PIL import Image

import vues_pano


def main(pano, sortie, duree=60.0, ips=24, flou=1, fx=vues_pano.FX):
    p = np.asarray(Image.open(pano).convert("RGB"))
    n = round(duree * ips)
    ff = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s",
                           "%dx%d" % (vues_pano.L, vues_pano.H), "-r", str(ips), "-i", "-", "-c:v", "libx264",
                           "-crf", "16", "-pix_fmt", "yuv420p", str(sortie)], stdin=subprocess.PIPE)
    pas = 360.0 / n
    for i in range(n + 1):                      # la dernière image = la première : le tour se referme
        caps = [pas * (i + 0.5 * (k / (flou - 1) - 0.5)) for k in range(flou)] if flou > 1 else [pas * i]
        img = np.mean([vues_pano.vue(p, c, fx).astype(np.float32) for c in caps], axis=0)
        ff.stdin.write(img.round().astype(np.uint8).tobytes())
        if i % (10 * ips) == 0:
            print(i, "/", n, flush=True)
    ff.stdin.close()
    return ff.wait()


if __name__ == "__main__":
    a = sys.argv[1:]
    opts = {}
    for cle, typ in (("--ips", int), ("--flou", int), ("--fx", float)):
        if cle in a:
            i = a.index(cle)
            opts[cle[2:]] = typ(a[i + 1])
            del a[i:i + 2]
    sys.exit(main(a[0], a[1], *(float(x) for x in a[2:3]), **opts))
