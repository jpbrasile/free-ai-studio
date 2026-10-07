"""Un tour 360° déjà peint (panorama + cartes d'un essai de l'atelier) devient un tour du Studio, prêt à tourner ses
clips depuis la route « reprendre » (07/10, propriétaire : « add Leila in all the scene … ajust studio for that ») :
le panorama et les cartes sont repris tels quels, le Studio fait le reste (personnage, groupes H3, montage, 4K,
60 i/s, musique). S'exécute DANS le conteneur sandbox-manager (clé du Studio lue dans son environnement ; jamais
`import app`) ; n'écrit que des données : une fiche décor par la route du Studio, puis le dossier du tour.

  python importer_tour.py <dossier>      (<dossier> : meta.json, pano.png, face.png, cartes/<nom>.png)
  meta.json : {nom, description, piece, ambiance, lacet, cartes: [{nom, description, azimut: [a0, a1]}],
               personnage: {fiche, ...} | null, ou, musique?}
  -> imprime {"fiche": ..., "tour": ...}
"""
import base64
import json
import os
import shutil
import sys
import time
import uuid
from pathlib import Path

import httpx

U = "http://127.0.0.1:8000"
H = {"Authorization": "Bearer " + os.environ["SANDBOX_MANAGER_KEY"]}
FICHES = Path("/config/h3-fiches")
FX_VUE = 904.0
FINITION = {"4k": True, "musique": "instrumental ambient, soft piano and warm strings, slow tempo", "fluide": True,
            "compresser": True}


def appel(m, chemin, corps=None):
    r = httpx.request(m, U + chemin, headers=H, json=corps, timeout=300)
    if r.status_code != 200:
        sys.exit("HTTP %d %s %s" % (r.status_code, chemin, r.text[:600]))
    return r.json()


def main(dossier):
    d = Path(dossier)
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    fiche = appel("POST", "/video-h3/fiches", {"nom": meta["nom"], "description": meta["description"],
                                              "genre": "decor"})
    appel("POST", "/video-h3/fiches/%s/images/face" % fiche["id"],
          {"image": "data:image/png;base64," + base64.b64encode((d / "face.png").read_bytes()).decode()})
    tid = uuid.uuid4().hex
    tour = FICHES / fiche["id"] / "tour360" / tid
    (tour / "cartes").mkdir(parents=True)
    shutil.copyfile(d / "pano.png", tour / "pano.png")
    cartes = []
    for c in meta["cartes"]:
        src = d / "cartes" / (c["nom"] + ".png")
        if not src.is_file():
            continue
        shutil.copyfile(src, tour / "cartes" / src.name)
        # les azimuts de l'atelier sont dans le repère de la pièce ; le Studio compte ses caps dans le panorama
        a0, a1 = c["azimut"][0] - meta["lacet"], c["azimut"][1] - meta["lacet"]
        cartes.append({"nom": c["nom"], "description": c["description"], "a0": round(a0, 1), "a1": round(a1, 1)})
    finition = dict(FINITION, **({"musique": meta["musique"]} if meta.get("musique") else {}))
    etat = {"id": tid, "fiche": fiche["id"], "nom": meta["nom"], "description": meta["description"],
            "cree_le": round(time.time()), "ou": meta.get("ou", "maison"), "graine": 11, "pas": 45,
            "reglages_camera": {"camera": "tour_droite", "duree_s": 30, "cap_depart": 0.0, "angle": 90.0},
            "reglages_finition": finition, "plan_valide": True, "statut": "arrete", "etape": "cartes", "texte": False,
            "personnage": meta.get("personnage"), "ref_image_size": meta.get("ref_image_size") or "match",
            "faites": ["consigne", "mesure", "plan", "panorama", "cartes"],
            "journal": [{"le": round(time.time()), "etape": "importe", "depuis": meta.get("source", "")}],
            "erreur": "Importé : à reprendre.",
            "consigne": {"piece": meta["piece"], "panorama": meta["description"], "ambiance": meta["ambiance"]},
            "geometrie": {"fx_vue": FX_VUE}, "cartes": cartes}
    (tour / "tour.json").write_text(json.dumps(etat, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"fiche": fiche["id"], "tour": tid, "cartes": len(cartes)}))


if __name__ == "__main__":
    main(sys.argv[1])
