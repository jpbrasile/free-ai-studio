"""Le plan au sol tiré par un agent Claude (propriétaire, 06/10 : « try to do it by a claude agent too ») : l'agent
regarde la photo de face et la vue à 180° (essai_tour_texte.py image / dos) et rend le plan au format de la consigne
sans photo (plan_piece.CONSIGNE_PLAN_TEXTE), lu comme le Studio le lit (lire_texte), avec les mêmes constats.

  python essai_plan_claude.py consignes <sortie> [cas ...]   -> <cas>/claude/consigne.txt (pour l'agent)
  python essai_plan_claude.py lire <sortie> [cas ...]        <cas>/claude/reponse.json -> plan.json, dessus.png,
                                                             defauts.json ; une ligne JSON par lieu
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sandbox-manager"))
import plan_piece  # noqa: E402
from essai_plans_texte import CAS, dessus  # noqa: E402

PHOTOS = (
    "You are given two photographs of this place, taken from the SAME camera spot at eye height 1.6 m with a level "
    "camera and about 80 degrees across: %s looks along +z (the front view), %s looks along -z (turned 180 degrees: "
    "its left side is +x, its right side is -x). Build the floor plan from what the two photographs SHOW: every "
    "visible thing at its place and real size (estimate distances from known sizes: a door is 2 m high, a chair "
    "seat 0.45 m, a table 0.75 m); the size of the place from where its walls or edges meet the floor; only then "
    "add what such a place plainly has in the parts no photograph shows (left and right of the camera). The camera "
    "stays at x = 0, z = 0. Each \"description\" is the element's ID card for the video model, which will also get "
    "its picture cut from the panorama: say exactly what the photograph shows of it (material, colour, shape, "
    "condition, what stands on it), nothing it does not show; an element no photograph shows is described so that "
    "it matches the materials and style of the photographs. ")


def consignes(sortie, noms):
    for nom in noms:
        d = sortie / nom
        if not (d / "photo.png").is_file() or not (d / "photo_dos.png").is_file():
            print(json.dumps({"cas": nom, "consigne": "sans les deux photos"}))
            continue
        (d / "claude").mkdir(exist_ok=True)
        texte = (PHOTOS % (d / "photo.png", d / "photo_dos.png")) + plan_piece.consigne_plan_texte(CAS[nom])
        (d / "claude" / "consigne.txt").write_text(texte, encoding="utf-8")
        print(json.dumps({"cas": nom, "consigne": str(d / "claude" / "consigne.txt")}))


def lire(sortie, noms):
    for nom in noms:
        d = sortie / nom / "claude"
        try:
            plan, geo, remarques = plan_piece.lire_texte((d / "reponse.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(json.dumps({"cas": nom, "erreur": str(exc)}, ensure_ascii=False))
            continue
        defauts = plan_piece.defauts(plan, geo)
        (d / "plan.json").write_text(json.dumps({"plan": plan, "geo": geo, "remarques": remarques}, ensure_ascii=False,
                                                indent=1), encoding="utf-8")
        (d / "defauts.json").write_text(json.dumps(defauts, ensure_ascii=False, indent=1), encoding="utf-8")
        dessus(plan, nom + " : Claude").save(d / "dessus.png")
        print(json.dumps({"cas": nom, "piece": plan["piece"], "elements": len(plan["elements"]),
                          "dehors": bool(plan.get("dehors")), "defauts": defauts, "remarques": remarques},
                         ensure_ascii=False))


if __name__ == "__main__":
    a = sys.argv[1:]
    (consignes if a[0] == "consignes" else lire)(Path(a[1]).resolve(), a[2:] or list(CAS))
