"""Telecharge UNE FOIS les poids du modele video de la maison.

Pourquoi ce fichier existe : le bac a sable qui fabrique les clips est sur un
reseau sans internet (`internal: true` dans docker-compose.yml, et c'est
volontaire -- du code quelconque y tourne). Il ne peut donc pas aller chercher
les 34 Go de poids lui-meme. Ce script les descend depuis un conteneur qui a le
droit d'aller sur le reseau, DANS LE MEME dossier que le bac a sable lira.

Il est lance par `scripts/telecharger-modele-video.ps1`, jamais tout seul :
c'est ce fichier-la qui sait ou est le cache et quelle image utiliser.

Mesure du 19/09/2026 sur cette machine : 34,20 Go annonces, 32 Go sur le disque,
et un blocage de treize minutes sans un octet ecrit tant que la couche de
transfert << Xet >> etait active -- d'ou HF_HUB_DISABLE_XET, pose par le .ps1.
"""
from __future__ import annotations

import os
import sys
import time

from huggingface_hub import snapshot_download

DEPOT = os.environ.get("VIDEO_MODELE_MAISON", "Wan-AI/Wan2.2-TI2V-5B-Diffusers")


def main() -> int:
    print("Telechargement de %s" % DEPOT, flush=True)
    print("Environ 34 Go. Une seule fois : les clips suivants repartent du disque.", flush=True)
    debut = time.time()
    try:
        chemin = snapshot_download(
            DEPOT,
            # Deux ouvriers, pas huit : mesure du 19/09, c'est la configuration
            # qui a fini quand la premiere s'etait bloquee.
            max_workers=2,
        )
    except Exception as exc:                      # noqa: BLE001 -- on rend le motif tel quel
        print("ECHEC : %s: %s" % (type(exc).__name__, exc), file=sys.stderr)
        return 1
    print("Fait en %.0f s. Les poids sont dans %s" % (time.time() - debut, chemin), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
