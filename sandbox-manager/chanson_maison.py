"""La chanson sur la carte de cet ordinateur -- ou pas. Ecrit le 26/09/2026.

Meme patron que la video (docs/GPU-LOCAL.md, phase 3) : la carte est sondee A
LA SECONDE du lancement ; libre et prete, la chanson se fait ici pour zero ;
sinon elle part chez le loueur choisi sur la page, exactement comme avant. On
ne reserve jamais la carte, on n'arrete jamais celui qui la tient.

Ce module ne fait que raisonner : aucun reseau, aucune carte. `app.py` lui
passe la sonde et l'etat du bac a sable, ce qui le rend jugeable a la table.

TROIS GARDES, et c'est pourquoi la route est INERTE aujourd'hui :
  1. la memoire -- mesuree le 23/09/2026 sur la 4090 (PLAN.md, point 16.1) ;
  2. les bibliotheques de YuE2 dans le bac a sable de la carte -- l'image
     `sandbox-worker-gpu` ne les a PAS (elle porte torch 2.6 et diffusers pour
     la video) ; son /health dit `yue2` depuis le 26/09, faux ou absent = pas
     ici ;
  3. les poids, epingles a leur revision, deja dans le cache partage -- ce
     bac a sable n'a pas Internet et ne les trouvera jamais seul.
Tant que 2 ou 3 manque, chaque chanson part chez le loueur, comme hier.

Le dialogue n'a PAS de route ici, expres : son pic (13 012 Mio court, 13 752
Mio puis echec en long) a ete mesure sous torch 2.7.1, et le torchao epingle
refuse le torch 2.6 de l'image (`register_constant` absent). Voir PLAN.md.
"""
from __future__ import annotations

import os
from pathlib import Path

import chanson
import ou_calculer

MAISON = "maison"
LOUEUR = "loueur"

# Pic releve par `nvidia-smi` toutes les 500 ms, carte vide avant chaque essai,
# RTX 4090, chemin officiel bfloat16, SANS LoRA (PLAN.md, point 16.1) :
#   7 942 Mio -- 46 s de son, une partie ;
#   8 472 Mio -- 47 s, trois parties ;
#   8 622 Mio -- 180 s, trois parties, arretee par la borne de 4 500 jetons,
#               c'est-a-dire exactement la duree "3" de chanson.DUREES.
# Le plus haut sert de MAJORANT aux trois durees de la page. Pour "1" et "2"
# c'est une SUPPOSITION -- que le pic croit avec le nombre de jetons, ce que
# les trois releves montrent (7 942 -> 8 472 -> 8 622) sans le prouver --
# et elle ne peut que surestimer. La marge de gpu_local (1 Gio) s'y ajoute.
BESOIN_MO = {"1": 8622, "2": 8622, "3": 8622}
# Ce qui est un releve et non un majorant : la page ne doit dire << mesure >>
# que la.
DUREES_MESUREES = ("3",)

# Le cache vu par le GESTIONNAIRE (qui telecharge, surcouche GPU) et, au meme
# endroit, par le bac a sable de la carte (en lecture seule).
POIDS_DIR = Path(os.getenv("POIDS_VIDEO_DIR", chanson.CACHE_MAISON))


def _depot(dossier: Path, hf: str) -> Path:
    return dossier / "hub" / ("models--" + hf.replace("/", "--"))


def poids_presents(dossier: Path | None = None) -> tuple[bool, str]:
    """Les deux depots (modele et decodeur) sont-ils la, a LEUR revision epinglee ?

    Trois marques par depot : le dossier de la revision existe, il porte un
    `config.json` et au moins un `.safetensors`, et aucun fichier `.incomplete`
    ne traine (huggingface_hub les nomme ainsi pendant qu'il ecrit). NON
    MESURE sur un vrai telechargement : la liste exacte des fichiers qu'il faut
    au pipeline n'a pas ete relevee ; ces marques refusent un dossier vide ou
    en cours, pas un depot auquel manquerait un fichier secondaire."""
    dossier = POIDS_DIR if dossier is None else dossier
    for hf, rev in ((chanson.MODELE["hf"], chanson.MODELE["revision"]),
                    (chanson.MODELE["vae"], chanson.MODELE["vae_revision"])):
        depot = _depot(dossier, hf)
        instant = depot / "snapshots" / rev
        if not instant.is_dir():
            return False, "%s n'est pas téléchargé sur cet ordinateur." % hf
        if not (instant / "config.json").exists() or not any(instant.rglob("*.safetensors")):
            return False, "%s est incomplet sur cet ordinateur." % hf
        blobs = depot / "blobs"
        if blobs.is_dir() and any(blobs.glob("*.incomplete")):
            return False, "%s est en cours de téléchargement." % hf
    return True, ""


def lora_presente(dossier: Path | None = None) -> tuple[bool, str]:
    """La LoRA instrumentale, a SA revision epinglee, dans le cache partage : le bac a
    sable de la carte n'a pas Internet et ne la telechargera jamais seul."""
    L = chanson.LORA
    depot = _depot(dossier or POIDS_DIR, L["hf"])
    if not (depot / "snapshots" / str(L["revision"]) / L["fichier"]).is_file():
        return False, ("La version instrumentale (%s) n'est pas téléchargée sur cet ordinateur."
                       % L["hf"])
    blobs = depot / "blobs"
    if blobs.is_dir() and any(blobs.glob("*.incomplete")):
        return False, "La version instrumentale est en cours de téléchargement."
    return True, ""


def pas_ici(duree: str, lora: bool, prete, dossier: Path | None = None) -> str:
    """« Ici, sans urgence » (01/10/2026) : pourquoi la chanson ne peut PAS attendre la
    carte d'ici ; "" si elle le peut. La carte n'est pas sondée : la file l'attendra.
    La version instrumentale y passe depuis le soir même (demande du propriétaire :
    la musique du film, instrumentale comme celle avec laquelle le Studio a été
    validé), pourvu que sa LoRA épinglée soit dans le cache."""
    if lora:
        ok, motif = lora_presente(dossier)
        if not ok:
            return motif
    if duree not in BESOIN_MO:
        return "Cette durée n'a pas été mesurée sur la carte d'ici."
    ok, motif = prete()
    return "" if ok else (motif.rstrip() or "La carte d'ici n'est pas prête.")


def decider(duree: str, lora: bool, reglage: str, prete,
            sonde, loueur: str = "Modal") -> dict:
    """Ou faire cette chanson : ici ou chez le loueur. Jamais de question.

    `prete` : fonction sans argument qui rend (le bac a sable de la carte
    peut-il faire tourner YuE2, pourquoi pas) -- appelee seulement si les
    gardes gratuites sont passees. `sonde` : `gpu_local.utilisable`, ou un faux
    dans les tests ; appelee en dernier, a la seconde du lancement.

    Rend `ou` (MAISON ou LOUEUR), `pourquoi` (montrable tel quel), `besoin_mo`,
    `besoin_est_mesure` et `carte`.

    << Toujours a la maison >> n'est PAS etendu a la chanson (decision du
    26/09/2026, prise seul) : ce reglage promet que rien ne part sans accord,
    et la page /chanson ne sait pas encore poser la question ni attendre. Le
    lire ici aurait refuse TOUTES les chansons de qui l'a regle, tant que
    l'image n'a pas YuE2 -- pire qu'hier. Il se lit donc comme << maison si
    libre >> ; seul << toujours sur une machine louee >> change la route."""
    def reponse(ou, pourquoi, besoin=None, carte=None):
        return {
            "ou": ou,
            "pourquoi": pourquoi,
            "besoin_mo": besoin,
            "besoin_est_mesure": besoin is not None and duree in DUREES_MESUREES,
            "carte": carte or {"vue": False, "motif": "carte non sondée"},
        }

    if reglage == ou_calculer.TOUJOURS_MODAL:
        return reponse(LOUEUR, "Vous avez réglé « toujours sur une machine louée » (%s)." % loueur)
    if lora:
        return reponse(LOUEUR, "La version instrumentale n'est vérifiée que sur la carte L4 de "
                               "Modal ; sur la carte d'ici, ni sa mémoire ni son résultat n'ont "
                               "été mesurés. Elle part chez %s." % loueur)
    besoin = BESOIN_MO.get(duree)
    if besoin is None:
        return reponse(LOUEUR, "Cette durée n'a pas été mesurée sur la carte d'ici : on ne lance "
                               "pas un travail sur un chiffre supposé. Elle part chez %s." % loueur)
    ok, motif = prete()
    if not ok:
        return reponse(LOUEUR, "%s La chanson part chez %s." % (motif.rstrip() or
                               "La carte d'ici n'est pas prête.", loueur), besoin=besoin)
    libre, phrase, carte = sonde(besoin)
    if libre:
        return reponse(MAISON, "Faite ici, gratuitement. " + phrase, besoin=besoin, carte=carte)
    return reponse(LOUEUR, "La carte d'ici n'est pas disponible : %s La chanson part chez %s."
                   % (phrase.rstrip(), loueur), besoin=besoin, carte=dict(carte, raison=phrase))
