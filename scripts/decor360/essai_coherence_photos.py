"""Cohérence des pièces entre la photo de face et la vue à 180° (propriétaire, 06/10 : « you have to address the
consistency of the various pieces ») : un juge à vision (free-ai-max, comme le relecteur du Studio) reçoit les deux
photos, nomme chaque pièce de chacune, relève ce qui est en double (le même tapis devant ET derrière), le décor
recopié en miroir (cheminée du même côté du cadre dans les deux), et ce qui ne va pas ensemble (matière, lumière,
style) ; s'il y a un problème, il réécrit la consigne de la vue de dos, qu'on repeint (Gemini, la face jointe), puis
on rejuge. Au plus TOURS repeintes ; la dernière vue de dos est gardée (les précédentes en photo_dos_<k>.png), chaque
verdict écrit tel quel.

  python essai_coherence_photos.py <gemini> <sortie> [cas ...]   -> <sortie>/<cas>/photo.png, photo_dos.png,
                                                                  coherence.json (verdicts de chaque tour)
"""
import base64
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sandbox-manager"))
import plan_piece  # noqa: E402
import video_h3  # noqa: E402
from essai_image_gemini import image  # noqa: E402
from essai_plan_studio import chat  # noqa: E402
from essai_plans_texte import CAS  # noqa: E402
from essai_tour_texte import DOS  # noqa: E402

TOURS = 2
JUGE = (
    "A place is described by its owner as: « %s ». Image 1 is a photograph of it looking forward; image 2 must be "
    "the view from EXACTLY the same camera spot turned 180 degrees (so the left side of image 2 is the right-hand "
    "side of the room as seen in image 1's frame turned around). Check that the two images are two halves of ONE "
    "real place:\n"
    "1. duplicates: a distinctive piece (furniture, fireplace, rug, table, window, door, tree, boat…) that appears in "
    "both images although such a place has only one; a piece standing right next to the camera may legitimately "
    "show at the bottom edge of both only if it is very large (say so);\n"
    "2. mirror copy: image 2 repeats image 1's layout (same feature on the same side of the frame, same far wall "
    "composition) instead of showing the other end of the place;\n"
    "3. mismatch: materials, colours, light direction or time of day, ceiling, floor, style, scale that differ;\n"
    "4. missing: what the description names that neither image shows and that should stand behind the first camera.\n"
    "Answer with JSON only: {\"pieces_1\": [\"<short name>\"], \"pieces_2\": [\"<short name>\"], \"problemes\": "
    "[\"<one sentence each, naming the pieces>\"], \"coherent\": <true if no problem of kind 1, 2 or 3>, "
    "\"consigne_dos\": \"<if not coherent: the full prompt, at most 120 words in English, for an image model to "
    "repaint image 2 from image 1: what stands at the OTHER end of this place, piece by piece, left to right, same "
    "materials and light as image 1, none of the pieces of image 1; else empty>\"}")


def _url(p):
    return "data:image/png;base64," + base64.b64encode(Path(p).read_bytes()).decode()


def juger(d, nom):
    rep = chat(d, JUGE % CAS[nom], [_url(d / "photo.png"), _url(d / "photo_dos.png")], "free-ai-max")
    v = plan_piece._json_de(rep)
    return v if isinstance(v, dict) else {"coherent": False, "problemes": ["verdict illisible"], "brut": rep[:800]}


def main(src, sortie, noms):
    for nom in noms or list(CAS):
        d = sortie / nom
        d.mkdir(parents=True, exist_ok=True)
        for f in ("photo.png", "photo_dos.png"):
            if not (d / f).is_file():
                shutil.copyfile(src / nom / f, d / f)
        verdicts = []
        for k in range(TOURS + 1):
            v = juger(d, nom)
            verdicts.append(dict(v, tour=k))
            (d / "coherence.json").write_text(json.dumps(verdicts, indent=1, ensure_ascii=False), encoding="utf-8")
            print(json.dumps({"cas": nom, "tour": k, "coherent": v.get("coherent"), "problemes": v.get("problemes")},
                             ensure_ascii=False), flush=True)
            if v.get("coherent") or k == TOURS or not v.get("consigne_dos"):
                break
            shutil.copyfile(d / "photo_dos.png", d / ("photo_dos_%d.png" % k))
            texte = DOS.replace("<image2>", "the attached image") + v["consigne_dos"]
            (d / ("texte_dos_%d.txt" % (k + 1))).write_text(texte, encoding="utf-8")
            png = image(d, {"prompt": texte, "n": 1, "size": video_h3.TAILLE_IMAGE_DEMANDEE,
                            "image_reference": [_url(d / "photo.png")]})
            if not png:
                print(json.dumps({"cas": nom, "tour": k, "gemini": "echec"}), flush=True)
                break
            (d / "photo_dos.png").write_bytes(png)


if __name__ == "__main__":
    a = sys.argv[1:]
    if "--tours" in a:                      # --tours 0 : juger seulement
        i = a.index("--tours")
        TOURS = int(a[i + 1])
        del a[i:i + 2]
    main(Path(a[0]).resolve(), Path(a[1]).resolve(), a[2:])
