"""Combien de cartes un clip du tour verrait, par lieu (PLAN 21.6, expérience « cartes par clip ») : avant et après
le groupement des voisines (plan_piece.grouper), et les clips qui restent au-delà de ce que H3 prend.

  python mesure_cartes_clip.py <dossier des tours> -> une ligne JSON par lieu
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sandbox-manager"))
import plan_piece  # noqa: E402


def mesurer(etat):
    plan, geo = etat["plan"], etat["mesure"]
    fen = plan_piece.fenetre_clip(geo)
    groupees = plan_piece.cartes_du_plan(plan, geo)
    par_cap = [len([c for c in groupees if plan_piece._croise(c, k * 7.5, fen / 2)]) for k in range(48)]
    return {"elements": len(plan["elements"]), "fenetre": round(fen, 1), "cartes": len(groupees),
            "groupes": [[m["nom"] for m in c["membres"]] for c in groupees if c.get("membres")],
            "max_par_clip": max(par_cap), "clips_trop_pleins": sum(n > plan_piece.SUJETS_MAX for n in par_cap),
            "sans_groupement": _sans_groupement(plan, geo, fen)}


def _sans_groupement(plan, geo, fen):
    garde = plan_piece.grouper
    plan_piece.grouper = lambda cartes, fenetre: cartes
    try:
        cartes = plan_piece.cartes_du_plan(plan, geo)
    finally:
        plan_piece.grouper = garde
    n = [len([c for c in cartes if plan_piece._croise(c, k * 7.5, fen / 2)]) for k in range(48)]
    return {"cartes": len(cartes), "max_par_clip": max(n), "clips_trop_pleins": sum(x > plan_piece.SUJETS_MAX for x in n)}


if __name__ == "__main__":
    for t in sorted(Path(sys.argv[1]).glob("*/tour.json")):
        r = mesurer(json.loads(t.read_text(encoding="utf-8")))
        print(json.dumps(dict({"cas": t.parent.name}, **r), ensure_ascii=False))
