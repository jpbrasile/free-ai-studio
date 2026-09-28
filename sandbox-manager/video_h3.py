"""Vidéo H3 : MiniMax H3 par ComfyUI, sur une machine louée chez Modal.

Décision du propriétaire, 27/09/2026 (« go H3, budget 2 $ ») ; découpage au
point 18.9 de PLAN.md, page décrite au point 18.7.

POURQUOI CE MODULE NE TOUCHE PAS À COMFYUI. ComfyUI est sous GPL-3.0 et le
Studio sous MIT. Rien ici n'importe ComfyUI : le script envoyé sur la machine
louée clone ComfyUI dans l'image Modal, le lance comme un service à part, et
lui parle par HTTP (/object_info, /prompt, /history). Le graphe est un
dictionnaire JSON fabriqué ici. Même règle que pour Piper (PLAN.md:803).

CE QUI A TOURNÉ, ET SEULEMENT CELA (27/09/2026, A100 40 Go, 832x480, 124
images, LoRA Turbo 4 étapes, hors du Studio, en fonction Modal) :
  - texte seul : 48,1 s de calcul, 72,4 s en tout ;
  - première image : 26,4 s de calcul ;
  - première et dernière, et références : 111 s de calcul pour les deux.
Les quatre modes sont donc proposés. Aucune autre taille, aucune autre durée
n'a tourné : la page le dit à côté de chaque durée.

LICENCE. Les poids de MiniMax H3 excluent par défaut l'UE, le Royaume-Uni et la
Corée. Chaque Studio doit porter la copie de SA propre autorisation écrite de
MiniMax (PLAN.md, 18.0) : sans elle, /video-h3/creer refuse avant de louer.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import random
import re
import time
import unicodedata
from pathlib import Path
from typing import Optional

import budget_modal

# --- Moteur et poids ------------------------------------------------------------

COMFY_DEPOT = "https://github.com/Comfy-Org/ComfyUI"
COMFY_VERSION = "v0.37.0"   # dernière publiée au 27/09/2026 ; celle des essais
DOSSIER_COMFY = "/comfy"
HF = "Comfy-Org/MiniMax-H3"
HF_REVISION = "bf92c4091e333e69b8ca1998e0a669f15cb0832b"   # relevée le 27/09/2026
FICHIERS = (
    "diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors",
    # INT8 et pas NVFP4 : l'A100 est une Ampere.
    "text_encoders/qwen3vl_32b_minimax_h3_int8_convrot.safetensors",
    "vae/minimax_h3_video_vae_int8_convrot.safetensors",
    "vae/minimax_h3_audio_vae_fp32.safetensors",
    "loras/minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors",
)
POIDS_GO = 52   # total téléchargé le 27/09/2026 (essai hors du Studio)


def actif() -> bool:
    """H3 est un outil du poste administrateur (PLAN 20.1) : la licence de
    MiniMax est accordée à une personne, pas aux clients du Studio. Éteint par
    défaut ; VIDEO_H3_ACTIF=true dans le .env de l'administrateur l'allume.
    Lu à chaque appel, pour que les tests puissent le basculer."""
    return os.getenv("VIDEO_H3_ACTIF", "false").strip().lower() == "true"

# Le disque Modal où les poids restent d'un clip à l'autre. Un disque à part
# de celui de la vidéo « Rapide » : 52 Go qu'on veut pouvoir effacer seuls.
VOLUME = os.getenv("H3_MODAL_VOLUME", "free-ai-studio-h3")
POINT_DE_MONTAGE = "/poids"

# La machine des essais du 27/09. « A100 » est le nom que Modal facture au
# tarif de la table (budget_modal.PRIX_GPU_USD_S) ; « A100-40GB » y serait une
# carte inconnue, comptée au prix de la plus chère.
GPU = os.getenv("H3_GPU", "A100")
# Pic mesuré le 27/09 : 56,7 Gio de mémoire vive avec --disable-pinned-memory ;
# les deux modes du même jour ont réussi avec 48 Gio demandés. Modal traite la
# demande comme un minimum, pas comme une limite.
MEMOIRE_MB = int(os.getenv("H3_MEMOIRE_MB", "49152"))
COEURS = float(os.getenv("H3_COEURS", "4"))
# Garde-fou dur : au-delà, la machine est arrêtée. Le pire cas du compteur se
# calcule sur ce délai.
DUREE_MAX_S = int(os.getenv("H3_TIMEOUT_SECONDS", "900"))
APT = ("git", "ffmpeg")
COMMANDES = (
    f"git clone --depth 1 --branch {COMFY_VERSION} {COMFY_DEPOT} {DOSSIER_COMFY}",
    f"pip install -r {DOSSIER_COMFY}/requirements.txt psutil",
)
PAQUETS_POIDS = ("huggingface_hub==1.9.2",)

# --- Ce que la page propose ------------------------------------------------------

LARGEUR, HAUTEUR, IMAGES_PAR_SECONDE = 832, 480, 24
# La définition de l'image. 480p est celle des essais du 27/09 ; le LoRA Turbo
# chargé (FICHIERS[4], « 768p ») a été entraîné en 1344 × 768 selon ses auteurs
# (lightx2v, 11/08/2026) : 768p est proposé depuis le 28/09. Tous les plans d'un
# scénario ont la même, pour que le montage les recolle.
DEFINITIONS = {"480p": (LARGEUR, HAUTEUR), "768p": (1344, 768)}
DEFINITION_PAR_DEFAUT = "480p"
# Grille du modèle : 17k+5 images à 24 images/s. 124 = 5,2 s ; le modèle a été
# entraîné de 124 à 362 (15,1 s) ; au-delà, « non essayé » selon ComfyUI.
LONGUEURS = tuple(124 + 17 * k for k in range(15))
LONGUEUR_PAR_DEFAUT = 124

MODES = {
    "texte": {"titre": "Texte seul", "noeud": "MiniMaxH3ImageToVideo", "images_min": 0,
              "images_max": 0, "essaye_le": "2026-09-27",
              "note": "Le début du clip peut être déformé : donner une première image l'évite."},
    "premiere": {"titre": "Première image", "noeud": "MiniMaxH3ImageToVideo", "images_min": 1,
                 "images_max": 1, "essaye_le": "2026-09-27",
                 "note": "Le clip part exactement de votre image."},
    "premiere_derniere": {"titre": "Première et dernière image", "noeud": "MiniMaxH3ImageToVideo",
                          "images_min": 2, "images_max": 2, "essaye_le": "2026-09-27",
                          "note": "Le clip part de la première image et finit sur la seconde."},
    "references": {"titre": "Références (garder un personnage)", "noeud": "MiniMaxH3ReferenceToVideo",
                   "images_min": 1, "images_max": 9, "essaye_le": "2026-09-27",
                   "note": "Une nouvelle scène avec le même personnage. Essayé avec une seule "
                           "image de référence ; jusqu'à 9 acceptées par le modèle."},
}
# --- Prolonger un clip ---------------------------------------------------------------
# Par défaut, le plan suivant part de la DERNIÈRE IMAGE du précédent (mode
# « première image »), puis le Studio recolle les deux, son compris, en retirant
# l'image qui se montrerait deux fois. Rien de plus n'est installé.
#
# En option (H3_MOTION_CONTEXT=true, décision du propriétaire le 27/09 :
# « autoriser en option sinon dernière image ») : « par tronçon ». Le plan suivant
# reprend 22 images et 1 s de son du précédent, pris dans son latent gardé sur le
# disque Modal, par le nœud ComfyUI-H3-Motion-Context (NikoDemon80, GPL-3.0,
# essayé hors du Studio le 27/09). Cloné dans la machine louée au commit relu,
# appelé par le graphe, jamais importé ici.
MC_DEPOT = "https://github.com/NikoDemon80/ComfyUI-H3-Motion-Context"
MC_COMMIT = "5335715abe54c1a9bfbe3494da29aae3e8635ce3"   # relu le 27/09/2026
COMMANDES_MC = (
    f"git clone {MC_DEPOT} {DOSSIER_COMFY}/custom_nodes/h3_motion_context",
    f"cd {DOSSIER_COMFY}/custom_nodes/h3_motion_context && git checkout {MC_COMMIT}",
)
CONTEXTE_IMAGES, CONTEXTE_SON = "22", 24   # réglage recommandé par le nœud, celui de l'essai
# Au-delà de ~4 raccords la texture se dégrade (limite connue, PLAN 18.x) :
# 4 plans au plus par chaîne, puis on repart d'une image.
PLANS_MAX = 4
DOSSIER_CHAINES = POINT_DE_MONTAGE + "/chaines"


def motion_context_actif() -> bool:
    return os.getenv("H3_MOTION_CONTEXT", "false").strip().lower() == "true"


def commandes() -> tuple:
    """Ce qui construit la machine louée ; le nœud tiers seulement si l'option est mise."""
    return COMMANDES + (COMMANDES_MC if motion_context_actif() else ())


COUPES = (0.0, 0.25, 0.5)   # secondes retirées au début, par ffmpeg
IMAGE_MAX_OCTETS = 8 * 1024 * 1024
IMAGES_MAX_OCTETS = 24 * 1024 * 1024

# Temps de location MESURÉ PAR LE STUDIO, par longueur : le second clip passé par
# /video-h3 le 27/09 (première image, disque déjà lu) a été compté 109 s,
# création de la machine comprise ; Modal en a facturé 0,107 $. L'essai du matin
# hors du Studio (72,4 s) sous-estimait : il ne comptait ni la création de la
# machine ni le tarif du bac à sable. Le tout premier clip coûte plus (lecture
# des 52 Go sur un disque neuf : 0,21 $ avec le téléchargement). Une seule
# longueur a été chronométrée ; les autres n'ont pas d'estimation, seulement le
# pire cas.
SECONDES_MESUREES = {124: 109.1}
MESURE_LE = "2026-09-27"


def secondes_de(longueur: int) -> float:
    return round(longueur / IMAGES_PAR_SECONDE, 2)


def prix_estime(longueur: int) -> Optional[float]:
    """Le temps mesuré au tarif du bac à sable ; None si jamais mesuré."""
    s = SECONDES_MESUREES.get(int(longueur))
    if s is None:
        return None
    return round(budget_modal.prix_seconde(GPU, MEMOIRE_MB, COEURS) * s, 4)


def pire_cas() -> float:
    """Le clip qui va jusqu'au bout de son délai sans rien rendre."""
    return round(budget_modal.prix_seconde(GPU, MEMOIRE_MB, COEURS) * DUREE_MAX_S, 3)


def durees() -> list:
    return [{"images": n, "secondes": secondes_de(n), "prix_estime_usd": prix_estime(n)}
            for n in LONGUEURS]


# --- L'invite en trois cases -----------------------------------------------------

# Les paroles au format des poids : `(S1) <d>[French] …</d>` (fiche du modèle,
# MiniMaxAI/MiniMax-H3). Sans balise ni langue, la réécriture d'invite de MiniMax
# (H3-Context-IR, non publiée) manque et la parole sort au hasard : le 27/09, un
# « Enfin au sec » entre guillemets est sorti en charabia (PLAN 18.9).
LANGUE_PAROLES = "French"
# Les 11 langues que la fiche dit « stables », sous leur nom anglais attendu dans la balise.
LANGUES_PAROLES = {
    "French": "français", "English": "anglais", "Spanish": "espagnol", "German": "allemand",
    "Italian": "italien", "Portuguese": "portugais", "Arabic": "arabe", "Chinese": "chinois",
    "Japanese": "japonais", "Korean": "coréen", "Russian": "russe",
}
_PAROLES = re.compile(r"«\s*([^«»]+?)\s*»|“\s*([^“”]+?)\s*”|\"\s*([^\"]+?)\s*\"")


def balises_paroles(texte: str, langue: str = LANGUE_PAROLES, locuteur: str = "(S1)") -> str:
    """Chaque réplique entre guillemets devient `(S1) <d>[langue] …</d>`.
    Un texte qui porte déjà ses balises `<d>` est laissé tel quel."""
    if "<d>" in texte:
        return texte

    def balise(m):
        return f"{locuteur} <d>[{langue}] {next(g for g in m.groups() if g)}</d>"
    return _PAROLES.sub(balise, texte)


def _motif_nom(nom: str) -> str:
    """Le nom d'un personnage, accents facultatifs : la traduction en anglais peut
    rendre « Lea » pour « Léa »."""
    morceaux = []
    for c in nom.strip():
        base = unicodedata.normalize("NFD", c)[0]
        morceaux.append(re.escape(c) if base == c else "[%s%s]" % (re.escape(c), re.escape(base)))
    return r"(?<!\w)" + "".join(morceaux) + r"(?!\w)"


def attribuer_repliques(texte: str, sujets: list) -> str:
    """Plusieurs personnages (guide de MiniMax, ref-en.txt, 5.4) : `sujets` est la
    liste des (nom, langue) dans l'ordre des <Subject N>.

    Chaque nom devient `<Subject N>` : dit tel quel, un nom a été récité (28/09).
    Chaque réplique va au PREMIER personnage nommé dans sa phrase (« Léa dit à
    Tom : « … » » : Léa), sinon au dernier nommé avant, sinon au premier ; elle
    part dans SA langue, les (Sx) numérotés dans l'ordre où l'on parle.

    Forme du guide (5.4) : `<Subject 2> (S1) turns … and says, <d>[English] …</d>`.
    Quand le locuteur est nommé dans la phrase, (Sx) suit ce nom et la réplique
    n'a que sa balise `<d>` ; le 28/09, « James demande <Subject 2> (S1) … »
    faisait parler James à lui-même, et le juge a vu une personne de trop.
    Sinon, la réplique porte `<Subject N> (Sx) <d>[langue] …</d>`."""
    texte = str(texte or "")
    repliques_vues = list(_PAROLES.finditer(texte))
    dans_une_replique = [(m.start(), m.end()) for m in repliques_vues]
    noms = sorted((m.start(), m.end(), k) for k, (nom, _langue) in enumerate(sujets) if nom.strip()
                  for m in re.finditer(_motif_nom(nom), texte, re.I)
                  if not any(a <= m.start() < b for a, b in dans_une_replique))
    locuteurs, parleur, fin_precedente = {}, {}, 0
    nom_du_locuteur = {}   # début du nom qui porte (Sx) -> personnage
    dit_par_son_nom = set()   # répliques dont le locuteur est nommé dans la phrase
    for m in repliques_vues:
        avant = texte[fin_precedente:m.start()]
        coupure = max(avant.rfind(c) for c in ".!?;\n")
        debut_phrase = fin_precedente + coupure + 1
        dans_la_phrase = [n for n in noms if debut_phrase <= n[0] < m.start()]
        plus_tot = [n for n in noms if n[0] < debut_phrase]
        k = dans_la_phrase[0][2] if dans_la_phrase else plus_tot[-1][2] if plus_tot else 0
        parleur[m.start()] = k
        if dans_la_phrase:
            nom_du_locuteur[dans_la_phrase[0][0]] = k
            dit_par_son_nom.add(m.start())
        locuteurs.setdefault(k, len(locuteurs) + 1)
        fin_precedente = m.end()
    evenements = sorted([(a, b, "nom", k) for a, b, k in noms]
                        + [(m.start(), m.end(), "replique", m) for m in repliques_vues], key=lambda e: e[0])
    sortie, pos = [], 0
    for debut, fin, genre, valeur in evenements:
        sortie.append(texte[pos:debut])
        pos = fin
        if genre == "nom":
            marque = f" (S{locuteurs[valeur]})" if nom_du_locuteur.get(debut) == valeur else ""
            sortie.append(f"<Subject {valeur + 1}>{marque}")
        else:
            k = parleur[debut]
            dite = next(g for g in valeur.groups() if g)
            qui = "" if debut in dit_par_son_nom else f"<Subject {k + 1}> (S{locuteurs[k]}) "
            sortie.append(f"{qui}<d>[{sujets[k][1]}] {dite}</d>")
    sortie.append(texte[pos:])
    return "".join(sortie)


def invite(image_paroles: str, ambiance: str = "", musique: str = "",
           langue: str = LANGUE_PAROLES, locuteur: str = "(S1)", son: str = "Sound: ") -> str:
    """Une seule invite pour le modèle, à partir des trois cases de la page.

    H3 fabrique l'image ET le son à partir du même texte : la case « image et
    paroles » décrit ce qu'on voit et ce qui est dit (les paroles entre
    guillemets, balisées ici pour le modèle), les deux autres le reste de la
    bande son.

    La musique va dans le champ `non_diegetic_music` du guide de MiniMax
    (docs/VIDEO_PROMPT_WRITING_GUIDE_ref_en.md) ; case vide, il vaut `N/A` :
    sans rien dire, H3 ajoute une musique (entendue le 27/09, PLAN 18.9).
    """
    morceaux = []
    for texte, prefixe in ((balises_paroles(image_paroles, langue, locuteur), ""), (ambiance, son),
                           (musique, "non_diegetic_music: ")):
        t = " ".join(str(texte or "").split())
        if t:
            if t[-1] not in ".!?\"»>":
                t += "."
            morceaux.append(prefixe + t)
    if morceaux and not " ".join(str(musique or "").split()):
        morceaux.append("non_diegetic_music: N/A")
    return " ".join(morceaux)


# --- La première et la dernière image, par l'image du Studio ------------------------

# Une taille paysage : le routeur la traduit en 16:9 pour Google (aspect_ratio
# de free-tier-manager). La page recadre ensuite en 832 x 480 sans déformer.
TAILLE_IMAGE_DEMANDEE = "1664x960"


def texte_image(texte: str) -> str:
    t = " ".join(str(texte or "").split())
    if not t:
        raise ValueError("Décrivez l'image à créer.")
    if len(t) > 2000:
        raise ValueError("Description d'image trop longue (2 000 caractères au plus).")
    return t


# --- Les fiches de casting (PLAN 18.9, V2) ----------------------------------------
# Un personnage décrit une fois, et ses images, rejouées à chaque plan en mode
# « Références ». Demande du propriétaire, 28/09 : « tu automatises la création
# des images du casting à partir du texte, possibilité de rejouer ou supprimer
# certaines ». Le portrait de face part du texte ; les autres angles partent du
# portrait (image de départ envoyée à Google), pour garder le même visage.
# Le prompt suit le guide de MiniMax (docs/VIDEO_PROMPT_WRITING_GUIDE_ref_en.md) :
# `<Subject 1>` défini une fois par ses `<Picture N>`, `<Subject 1> (S1)` quand il parle.

DOSSIER_FICHES = budget_modal.CONFIG_DIR / "h3-fiches"
ANGLES = {   # l'ordre est celui des <Picture N>
    "face": ("De face", "portrait de face, cadré aux épaules, regard vers l'objectif"),
    "trois_quarts": ("Trois-quarts", "portrait de trois-quarts, cadré à la taille"),
    "pied": ("En pied", "en pied, de face, debout, tout le corps visible"),
    "profil": ("Profil", "de profil, cadré à la taille"),
}
ANGLE_DEPART = "face"
FICHE_NOM_MAX, FICHE_DESCRIPTION_MAX = 60, 800
TAILLE_IMAGE_FICHE = "1024x1024"
_ID_FICHE = re.compile(r"[0-9a-f]{12}")
_EXTENSIONS = {b"\x89PNG": ".png", b"\xff\xd8\xff": ".jpg", b"RIFF": ".webp"}
_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp"}


def _dossier_fiche(fid) -> Path:
    if not _ID_FICHE.fullmatch(str(fid or "")):
        raise ValueError("Fiche inconnue.")
    return DOSSIER_FICHES / str(fid)


def fiche_lire(fid) -> dict:
    try:
        return json.loads((_dossier_fiche(fid) / "fiche.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("Fiche inconnue.") from exc


def _fiche_ecrire(fiche: dict) -> None:
    dossier = _dossier_fiche(fiche["id"])
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / "fiche.json").write_text(json.dumps(fiche, ensure_ascii=False, indent=1), encoding="utf-8")


def fiches_liste() -> list:
    fiches = []
    for f in sorted(DOSSIER_FICHES.glob("*/fiche.json")) if DOSSIER_FICHES.is_dir() else []:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        fiches.append({"id": d["id"], "nom": d["nom"], "description": d["description"],
                       "angles": [a for a in ANGLES if a in d.get("images", {})], "cree_le": d["cree_le"]})
    return sorted(fiches, key=lambda d: d["cree_le"])


def fiche_creer(nom: str, description: str) -> dict:
    nom, description = " ".join(str(nom or "").split()), " ".join(str(description or "").split())
    if not nom or len(nom) > FICHE_NOM_MAX:
        raise ValueError(f"Donnez un nom au personnage ({FICHE_NOM_MAX} caractères au plus).")
    if not description or len(description) > FICHE_DESCRIPTION_MAX:
        raise ValueError(f"Décrivez le personnage ({FICHE_DESCRIPTION_MAX} caractères au plus) : "
                         "âge, visage, coiffure, tenue.")
    fiche = {"id": os.urandom(6).hex(), "nom": nom, "description": description,
             "cree_le": time.strftime("%Y-%m-%d %H:%M:%S"), "images": {}}  # date-machine
    _fiche_ecrire(fiche)
    return fiche


def fiche_supprimer(fid) -> None:
    dossier = _dossier_fiche(fid)
    fiche_lire(fid)
    for f in dossier.iterdir():
        f.unlink()
    dossier.rmdir()


def _angle(angle: str) -> str:
    if angle not in ANGLES:
        raise ValueError("Angle inconnu.")
    return angle


def fiche_demande_image(fiche: dict, angle: str) -> dict:
    """Ce qu'on demande à l'image du Studio pour un angle : le texte, la taille,
    et le portrait de face comme image de départ pour les autres angles."""
    detail = ANGLES[_angle(angle)][1]
    fin = "fond neutre gris clair, lumière douce, photographie réaliste, une seule personne."
    if angle == ANGLE_DEPART:
        return {"prompt": f"{fiche['description']}. {detail}, {fin}", "n": 1, "size": TAILLE_IMAGE_FICHE}
    if ANGLE_DEPART not in fiche.get("images", {}):
        raise ValueError("Créez d'abord le portrait de face : les autres angles partent de lui.")
    return {"prompt": (f"La même personne que sur l'image jointe, mêmes visage, coiffure et tenue : "
                       f"{fiche['description']}. {detail}, {fin}"),
            "n": 1, "size": TAILLE_IMAGE_FICHE,
            "image_reference": fiche_image_data_url(fiche["id"], ANGLE_DEPART)}


def fiche_poser_image(fid, angle: str, image: str) -> dict:
    fiche = fiche_lire(fid)
    octets = base64.b64decode(_image(image, ANGLES[_angle(angle)][0]))
    ext = next(e for debut, e in _EXTENSIONS.items() if octets.startswith(debut))
    dossier = _dossier_fiche(fid)
    ancien = fiche["images"].get(angle)
    if ancien:
        (dossier / ancien).unlink(missing_ok=True)
    fiche["images"][angle] = angle + ext
    (dossier / (angle + ext)).write_bytes(octets)
    _fiche_ecrire(fiche)
    return fiche


def fiche_retirer_image(fid, angle: str) -> dict:
    fiche = fiche_lire(fid)
    nom = fiche["images"].pop(_angle(angle), None)
    if nom:
        (_dossier_fiche(fid) / nom).unlink(missing_ok=True)
    _fiche_ecrire(fiche)
    return fiche


def fiche_image_data_url(fid, angle: str) -> str:
    nom = fiche_lire(fid)["images"].get(_angle(angle))
    if not nom:
        raise ValueError("Cette image n'existe pas.")
    octets = (_dossier_fiche(fid) / nom).read_bytes()
    return f"data:{_TYPES[Path(nom).suffix]};base64," + base64.b64encode(octets).decode()


def fiche_images(fid) -> list:
    """Les images de la fiche, dans l'ordre des angles, en base64 nu."""
    fiche = fiche_lire(fid)
    return [fiche_image_data_url(fid, a).split(",", 1)[1] for a in ANGLES if a in fiche["images"]]


def sujets_des_fiches(nombres: list) -> str:
    """Les personnages, désignés par leurs images seulement : `nombres` dit
    combien d'images a chaque fiche, dans l'ordre des <Subject N>. La
    description d'une fiche ne sert qu'à fabriquer ses images : mise dans
    l'invite, elle a été DITE par le personnage (essai du 28/09, « Femme de 35
    ans, cheveux bruns… »)."""
    definitions, garde, premiere = [], [], 1
    for k, nombre in enumerate(nombres):
        images = ", ".join(f"<Picture {premiere + i}>" for i in range(nombre))
        premiere += nombre
        definitions.append(f"<Subject {k + 1}> is the person in {images}.")
        garde.append(f"<Subject {k + 1}> keeps the face, hair and clothing of the reference pictures.")
    return "subject_definitions: " + " ".join(definitions) + " retention_analysis: " + " ".join(garde)


def premier_plan(texte: str) -> str:
    """Qui est au premier plan, compté par le Studio sur les <Subject N> du plan
    (règle 1, 28/09/2026) : quatre fois ce jour-là, H3 a ajouté un personnage ou
    en a montré un deux fois. Rien si le plan ne nomme personne. Le fond n'est
    pas mentionné : « anyone else stays in the background » a peuplé une
    terrasse que le texte voulait vide (trois plans refusés par le juge, 28/09)."""
    presents = sorted({int(n) for n in re.findall(r"<Subject (\d+)>", str(texte or ""))})
    if not presents:
        return ""
    noms = [f"<Subject {n}>" for n in presents]
    qui = noms[0] if len(noms) == 1 else ", ".join(noms[:-1]) + " and " + noms[-1]
    return "In the foreground: only %s, each of them one single person shown once." % qui


# --- La traduction en anglais, en mode « Références » -----------------------------
# Essai du 28/09 (PLAN 18.9) : en mode « Références », le texte français hors
# guillemets est DIT par le personnage (la scène, l'ambiance), la réplique se
# perd. Décision du propriétaire, même jour : « oui traduis en anglais ». Tout ce
# qui n'est pas réplique part en anglais ; les répliques restent mot pour mot.
# Les autres modes ont été validés en français : ils n'y passent pas.

CASES_TRADUITES = ("image_paroles", "ambiance", "musique")


def a_traduire(payload: dict) -> bool:
    return str(payload.get("mode") or "") == "references" and any(
        str(payload.get(k) or "").strip() for k in CASES_TRADUITES)


def repliques(texte: str) -> list:
    return [next(g for g in m.groups() if g) for m in _PAROLES.finditer(str(texte or ""))]


def consigne_traduction(payload: dict) -> str:
    cases = {k: " ".join(str(payload.get(k) or "").split()) for k in CASES_TRADUITES}
    return ("Translate the values of this JSON object into English, for a video-generation prompt. "
            "Text between quotation marks (« », “ ” or \" \") is spoken dialogue: copy it EXACTLY, "
            "untranslated, with its quotation marks. Empty values stay empty. Answer with the JSON "
            "object only, same keys, nothing else.\n" + json.dumps(cases, ensure_ascii=False))


def lire_traduction(reponse: str, payload: dict) -> dict:
    """Le JSON du modèle, contrôlé : mêmes cases, et les répliques intactes."""
    t = str(reponse or "").strip()
    if t.startswith("```"):
        t = t.strip("`").split("\n", 1)[-1] if "\n" in t else t.strip("`")
    debut, fin = t.find("{"), t.rfind("}")
    try:
        d = json.loads(t[debut:fin + 1]) if debut >= 0 else None
    except ValueError:
        d = None
    if not isinstance(d, dict) or not all(isinstance(d.get(k, ""), str) for k in CASES_TRADUITES):
        raise ValueError("La traduction en anglais n'a pas pu être lue.")
    for k in CASES_TRADUITES:
        if repliques(d.get(k, "")) != repliques(payload.get(k, "")):
            raise ValueError("La traduction en anglais a changé une réplique : rien n'est lancé.")
    return dict(payload, **{k: d.get(k, "") for k in CASES_TRADUITES})


# --- Le scénario, monté après coup (PLAN 18.9) --------------------------------------
# Demande du propriétaire, 28/09 : « les clips générés devraient pouvoir se coller
# les uns aux autres suivant le scénario initial », puis « pas besoin de rejouer
# les clips de base, reconstruit le scénario a posteriori ». Rien n'est tourné ici :
# le Studio recolle, son compris, des clips H3 déjà réussis, dans l'ordre choisi.
# Le chat du Studio peut proposer cet ordre à partir du scénario ; gratuit.

SCENARIO_MAX = 2000
MONTAGE_CLIPS_MAX = 12


def verifier_ordre(ids) -> list:
    """Des numéros de clips, sans doublon, de 2 à MONTAGE_CLIPS_MAX."""
    if not isinstance(ids, list) or not all(isinstance(i, str) and re.fullmatch(r"[0-9a-f]{32}", i)
                                            for i in ids):
        raise ValueError("Liste de clips illisible.")
    if len(set(ids)) != len(ids):
        raise ValueError("Un même clip apparaît deux fois.")
    if not 2 <= len(ids) <= MONTAGE_CLIPS_MAX:
        raise ValueError(f"Choisissez de 2 à {MONTAGE_CLIPS_MAX} clips.")
    return ids


def consigne_ordre(scenario: str, clips: dict) -> str:
    """`clips` : numéro -> invite du clip. Le chat rend les numéros dans l'ordre du récit."""
    return ("Here is a film script, then video clips already made, each with the prompt that made it. "
            "Choose the clips that tell the script and put them in the order of the story. Leave out "
            "clips that do not belong. Answer with a JSON array of clip ids only.\n\nScript:\n"
            + scenario + "\n\nClips:\n" + json.dumps(clips, ensure_ascii=False))


def lire_ordre(reponse: str, permis) -> list:
    """L'ordre du chat, contrôlé : seulement des clips proposés, chacun une fois."""
    t = str(reponse or "")
    debut, fin = t.find("["), t.rfind("]")
    try:
        ids = json.loads(t[debut:fin + 1]) if debut >= 0 else None
    except ValueError:
        ids = None
    try:
        ids = verifier_ordre(ids)
    except ValueError as exc:
        raise ValueError("L'ordre proposé par le chat n'a pas pu être lu (" + str(exc) + ") : "
                         "réessayez, ou rangez les clips vous-même.") from exc
    if any(i not in permis for i in ids):
        raise ValueError("Le chat a proposé un clip qui n'est pas dans la liste : réessayez.")
    return ids


# --- Le scénario tourné plan par plan (PLAN 18.9) -----------------------------------
# Pour les scénarios neufs (« la partie tourner est à conserver pour les futurs
# scénarios », 28/09) : le chat du Studio découpe l'histoire en plans, le
# propriétaire les relit, puis le Studio les tourne l'un après l'autre et recolle
# chacun au film déjà tourné.

SCENARIO_PLANS_MAX = PLANS_MAX
ENCHAINEMENTS = {
    "coupe": "Nouveau plan (la fiche garde le personnage)",
    "suite": "Suite directe (repart de la dernière image du plan précédent)",
}
DOSSIER_SCENARIOS = budget_modal.CONFIG_DIR / "h3-scenarios"


# Règle 2 (28/09/2026) : les doublons de personnages sont venus de plans où
# l'un d'eux n'était qu'à moitié dans le cadre (gros plan à deux, plan par-dessus l'épaule).
CADRAGE = ("Framing: a close-up shows one character only; when two or more characters are in a shot, choose a "
           "medium or wide shot that shows each of them entirely, and never describe a character as only partly "
           "in frame or seen from behind. If a shot's framing breaks this rule, change the framing, never the "
           # Le 28/09, pour tenir la règle, une correction a retiré un personnage et son action.
           "characters in it or what they do. ")


def consigne_decoupage(scenario: str) -> str:
    # Une action et une réplique courte par plan : l'essai du 27/09 (clip 2) a
    # montré qu'un plan chargé rend un son incompréhensible.
    return ("Split this short film script into at most %d shots of about 5 seconds each. "
            "Each shot shows ONE simple action and has at most ONE short line of dialogue. %s"
            "Write in the language of the script. Dialogue must be copied EXACTLY from the script, "
            "between « »; never invent dialogue. For each shot give \"image_paroles\" (what we see, "
            "then the line if any), \"ambiance\" (the sounds, a few words) and \"enchainement\": "
            "\"coupe\" for a new camera shot or place, \"suite\" when it continues the previous shot "
            "without a cut. The first shot is \"coupe\". Answer with the JSON array only.\n\n%s"
            % (SCENARIO_PLANS_MAX, CADRAGE, scenario))


def verifier_plans(plans) -> list:
    """Les plans relus par le propriétaire : de 1 à SCENARIO_PLANS_MAX, le premier
    en « coupe » (il n'a pas de plan avant lui)."""
    if not isinstance(plans, list) or not plans:
        raise ValueError("Le scénario n'a aucun plan.")
    if len(plans) > SCENARIO_PLANS_MAX:
        raise ValueError(f"{SCENARIO_PLANS_MAX} plans au plus par scénario.")
    propres = []
    for i, p in enumerate(plans):
        if not isinstance(p, dict) or not all(isinstance(p.get(k, ""), str)
                                              for k in ("image_paroles", "ambiance", "enchainement")):
            raise ValueError(f"Plan {i + 1} illisible.")
        if not p.get("image_paroles", "").strip():
            raise ValueError(f"Plan {i + 1} : décrivez ce qu'on voit.")
        enchainement = p.get("enchainement") or "coupe"
        if enchainement not in ENCHAINEMENTS:
            raise ValueError(f"Plan {i + 1} : enchaînement inconnu.")
        propres.append({"image_paroles": p["image_paroles"].strip(), "ambiance": p.get("ambiance", "").strip(),
                        "enchainement": "coupe" if i == 0 else enchainement})
    return propres


def lire_decoupage(reponse: str, scenario: str) -> list:
    """Le découpage du chat, contrôlé : aucune réplique qui ne soit dans le scénario."""
    t = str(reponse or "")
    debut, fin = t.find("["), t.rfind("]")
    try:
        plans = json.loads(t[debut:fin + 1]) if debut >= 0 else None
    except ValueError:
        plans = None
    try:
        plans = verifier_plans(plans)
    except ValueError as exc:
        raise ValueError("Le découpage du chat n'a pas pu être lu (" + str(exc) + ") : réessayez.") from exc
    permises = set(repliques(scenario))
    for i, p in enumerate(plans):
        if any(r not in permises for r in repliques(p["image_paroles"] + " " + p["ambiance"])):
            raise ValueError(f"Le découpage a inventé ou changé une réplique (plan {i + 1}) : réessayez.")
    return plans


def _chemin_scenario(sid) -> Path:
    if not isinstance(sid, str) or not re.fullmatch(r"[0-9a-f]{32}", sid):
        raise ValueError("Scénario inconnu.")
    return DOSSIER_SCENARIOS / (sid + ".json")


def scenario_lire(sid) -> dict:
    chemin = _chemin_scenario(sid)
    if not chemin.is_file():
        raise ValueError("Scénario inconnu.")
    return json.loads(chemin.read_text(encoding="utf-8"))


def scenario_ecrire(sc: dict) -> dict:
    chemin = _chemin_scenario(sc["id"])
    chemin.parent.mkdir(parents=True, exist_ok=True)
    provisoire = chemin.with_suffix(".tmp")
    provisoire.write_text(json.dumps(sc, ensure_ascii=False), encoding="utf-8")
    provisoire.replace(chemin)
    return sc


def scenario_noter(sid: str, **champs) -> dict:
    sc = scenario_lire(sid)
    sc.update(champs)
    return scenario_ecrire(sc)


# --- Juger, corriger, rejouer un scénario tourné (28/09) ------------------------
# Demande du propriétaire : un bouton pour faire juger les plans, le scénario
# remis à jour d'après les retours (les changements en gras), un bouton pour
# rejouer. Essai du 28/09 : Gemini, par le routeur, a vu sur la planche du plan 2
# « Léa porte une veste grise au lieu de sa veste rouge » ; il n'a pas vu la
# silhouette de dos vers 6,5 s. Une aide, pas une garantie.

MODELE_JUGE = "free-ai-max"   # le modèle plus fort du routeur, gratuit, son propre quota


def consigne_jugement(noms: list, texte: str = "") -> str:
    refs = " ".join(f"Image {k + 1} shows {nom}, a reference picture." for k, nom in enumerate(noms))
    # Le texte du plan : la vidéo doit faire ce qu'il dit, dans le même ordre (28/09).
    voulu = (" The shot is meant to show: «%s». Also say if the video does not show these actions, or not in "
             "this order." % " ".join(texte.split())) if texte.strip() else ""
    # Le modèle rend le NUMÉRO de l'image, le Studio en fait l'heure : le 28/09,
    # un départ mal annoncé dans la consigne a décalé sa réponse d'une seconde.
    return (refs + f" Image {len(noms) + 1} is a contact sheet of ONE video shot: frames numbered from 1, "
            "one every 0.5 s, read left to right then top to bottom; black cells after the end are empty. "
            # Neutre, sans questions qui cherchent la faute : le 28/09, la consigne
            # d'avant faisait trouver un défaut même au plan repris tel quel.
            "Say whether the characters stay consistent with their reference pictures throughout the shot." + voulu
            + " "
            "Many shots have no problem: then answer ok with an empty list. Report only what you clearly see, "
            "each problem once, at the first frame where it appears, in one short sentence. "
            "Answer in French, JSON only: {\"verdict\": \"ok\" or \"defaut\", "
            "\"defauts\": [{\"image\": frame number, \"quoi\": \"what is wrong\"}]}.")


def lire_jugement(reponse: str, debut_s: float, nombre: int) -> dict:
    t = str(reponse or "")
    debut, fin = t.find("{"), t.rfind("}")
    try:
        d = json.loads(t[debut:fin + 1]) if debut >= 0 else None
    except ValueError:
        d = None
    if not isinstance(d, dict) or d.get("verdict") not in ("ok", "defaut"):
        raise ValueError("Le jugement du chat n'a pas pu être lu : réessayez.")
    defauts = []
    for x in d.get("defauts") or []:
        try:
            i = int(x.get("image"))
        except (AttributeError, TypeError, ValueError):
            continue
        quoi = " ".join(str(x.get("quoi") or "").split())[:300]
        if 1 <= i <= nombre and quoi:   # une image qui n'existe pas n'a rien montré
            defauts.append({"t_s": round(debut_s + (i - 1) * 0.5, 1), "quoi": quoi})
    return {"verdict": d["verdict"], "defauts": defauts}


def consigne_correction(plans: list, retours: str, histoire: str = "") -> str:
    # L'histoire vient du scénario initial : des plans déjà réécrits peuvent l'avoir
    # abîmée, et la correction ne voyait qu'eux (28/09/2026).
    reference = ("The story the shots must tell (what happens, in order; it must stay true, even where the shots "
                 "given have drifted from it): %s\n\n" % histoire) if histoire else ""
    return (reference + "Here are the shots of a short film (JSON) and the feedback after shooting them. Rewrite the shots "
            "so that the feedback is fixed: be explicit about who is in the frame and what they wear. Keep the "
            "same number of shots in the same order, keep each \"enchainement\", and copy every line of "
            "dialogue between « » EXACTLY in its own shot; never add, move or remove dialogue. Change only what "
            "the feedback requires; write in the language of the shots. "
            # Le 28/09, pour effacer un défaut d'image, la correction a fait asseoir un
            # personnage avant qu'on l'y invite : on change la façon de montrer, pas l'histoire.
            "Change how the scene is shown (framing, clothing, who else is in the frame), never what happens: "
            "keep every action of the characters, and their order, as in the story. Write each shot in the order "
            "things happen, lines of dialogue included: an action caused by a line comes after that line. "
            "If a problem cannot be "
            "fixed without changing what happens, leave that shot unchanged: it will be shot again. " + CADRAGE +
            "Answer with the JSON array only.\n\n"
            "Shots: %s\n\nFeedback: %s" % (json.dumps(plans, ensure_ascii=False), retours))


def consigne_continuite(plans: list, histoire: str) -> str:
    """Le texte des plans se tient-il ? Un état au début et à la fin de chaque
    plan (28/09/2026) : un plan part de l'état où le précédent s'arrête, et
    aucune action ne vient avant ce qui la cause. Rien n'est loué."""
    return ("Here are the shots of a short film (JSON), in order, and the story they tell. For each shot, write "
            "the state at its start and at its end: who is there, where, standing or sitting, what they wear. "
            "Then check the continuity: does each shot start in the state where the previous one ends (a cut may "
            "move on in time or place, but nothing may be undone without being shown), does every action come "
            "after what causes it, as in the story, and is every action of the story still shown in some shot, "
            "none missing? Answer in French, JSON only: {\"etats\": [{\"plan\": number, "
            "\"debut\": \"...\", \"fin\": \"...\"}], \"problemes\": [{\"plan\": number, \"quoi\": \"...\"}]}; "
            "an empty \"problemes\" list if the shots hold together.\n\nStory: %s\n\nShots: %s"
            % (histoire, json.dumps([{k: p[k] for k in ("image_paroles", "enchainement")} for p in plans],
                                    ensure_ascii=False)))


def lire_continuite(reponse: str, nombre: int) -> dict:
    t = str(reponse or "")
    debut, fin = t.find("{"), t.rfind("}")
    try:
        d = json.loads(t[debut:fin + 1]) if debut >= 0 else None
    except ValueError:
        d = None
    if not isinstance(d, dict) or not isinstance(d.get("problemes"), list):
        raise ValueError("Le contrôle de continuité n'a pas pu être lu : réessayez.")
    problemes = []
    for x in d["problemes"]:
        try:
            plan = int(x["plan"])
        except (KeyError, TypeError, ValueError):
            continue
        if 1 <= plan <= nombre and str(x.get("quoi") or "").strip():
            problemes.append({"plan": plan, "quoi": " ".join(str(x["quoi"]).split())[:300]})
    etats = [e for e in d.get("etats") or [] if isinstance(e, dict)][:nombre]
    return {"ok": not problemes, "problemes": problemes, "etats": etats}


def lire_correction(reponse: str, plans: list) -> list:
    """La correction du chat, contrôlée : mêmes plans, mêmes répliques à la même place."""
    nouveaux = lire_decoupage(reponse, " ".join(p["image_paroles"] + " " + p["ambiance"] for p in plans))
    if len(nouveaux) != len(plans):
        raise ValueError("La correction a changé le nombre de plans : réessayez.")
    for i, (n, p) in enumerate(zip(nouveaux, plans)):
        if repliques(n["image_paroles"] + " " + n["ambiance"]) != repliques(p["image_paroles"] + " " + p["ambiance"]):
            raise ValueError(f"La correction a déplacé ou retiré une réplique (plan {i + 1}) : réessayez.")
    return [dict(n, enchainement=p["enchainement"]) for n, p in zip(nouveaux, plans)]


def plans_a_reprendre(anciens: list, nouveaux: list, retourner=()) -> list:
    """Les numéros (0…) des plans repris tels quels au lieu d'être retournés :
    inchangés, non demandés, et, pour une « suite », après un plan repris
    (elle part de sa dernière image)."""
    repris = []
    for i, p in enumerate(nouveaux):
        pareil = i < len(anciens) and all(p[k] == anciens[i].get(k) for k in ("image_paroles", "ambiance",
                                                                              "enchainement"))
        if pareil and (i + 1) not in retourner and (p["enchainement"] == "coupe" or (i - 1) in repris):
            repris.append(i)
    return repris


# --- Le graphe ComfyUI -------------------------------------------------------------

def _n(classe: str, entrees: dict) -> dict:
    return {"class_type": classe, "inputs": entrees}


def noms_images(mode: str, nombre: int) -> list:
    if mode == "premiere":
        return ["premiere.png"]
    if mode == "premiere_derniere":
        return ["premiere.png", "derniere.png"]
    if mode == "references":
        return [f"ref_{i}.png" for i in range(nombre)]
    return []


def graphe(mode: str, texte: str, longueur: int, graine: int, nb_images: int = 0,
           definition: str = DEFINITION_PAR_DEFAUT) -> dict:
    """Le graphe des essais du 27/09, pour un clip.

    Chargeurs, LoRA Turbo 4 étapes, échantillonneur `res_multistep`, ordonnanceur
    `simple`, puis image et son décodés et réunis en un MP4.
    """
    nom = lambda chemin: chemin.split("/")[1]  # noqa: E731
    g = {
        "1": _n("UNETLoader", {"unet_name": nom(FICHIERS[0]), "weight_dtype": "default"}),
        "2": _n("LoraLoaderModelOnly", {"model": ["1", 0], "lora_name": nom(FICHIERS[4]),
                                         "strength_model": 1.0}),
        "3": _n("CLIPLoader", {"clip_name": nom(FICHIERS[1]), "type": "minimax"}),
        "4": _n("VAELoader", {"vae_name": nom(FICHIERS[2])}),
        "5": _n("VAELoader", {"vae_name": nom(FICHIERS[3])}),
        "8": _n("KSamplerSelect", {"sampler_name": "res_multistep"}),
        "9": _n("BasicScheduler", {"model": ["2", 0], "scheduler": "simple", "steps": 4, "denoise": 1.0}),
    }
    largeur, hauteur = DEFINITIONS[definition]
    taille = {"width": largeur, "height": hauteur, "length": int(longueur)}
    images = noms_images(mode, nb_images)
    for i, fichier in enumerate(images):
        g[f"6{i}"] = _n("LoadImage", {"image": fichier})
    if mode == "references":
        entrees = {"clip": ["3", 0], "vae": ["4", 0], "audio_vae": ["5", 0], "prompt": texte,
                   "ref_image_size": "match", **taille}
        for i in range(len(images)):
            entrees[f"ref_images.ref_image_{i}"] = [f"6{i}", 0]
        g["10"] = _n("MiniMaxH3ReferenceToVideo", entrees)
    else:
        entrees = {"clip": ["3", 0], "vae": ["4", 0], "prompt": texte, **taille}
        if images:
            entrees["first_frame"] = ["60", 0]
        if len(images) == 2:
            entrees["last_frame"] = ["61", 0]
        g["10"] = _n("MiniMaxH3ImageToVideo", entrees)
    g["12"] = _n("RandomNoise", {"noise_seed": int(graine)})
    g["13"] = _n("BasicGuider", {"model": ["2", 0], "conditioning": ["10", 0]})
    g["14"] = _n("SamplerCustomAdvanced", {"noise": ["12", 0], "guider": ["13", 0], "sampler": ["8", 0],
                                            "sigmas": ["9", 0], "latent_image": ["10", 1]})
    g["15"] = _n("VAEDecode", {"samples": ["14", 0], "vae": ["4", 0]})
    g["16"] = _n("VAEDecodeAudio", {"samples": ["14", 0], "vae": ["5", 0]})
    g["17"] = _n("CreateVideo", {"images": ["15", 0], "audio": ["16", 0], "fps": IMAGES_PAR_SECONDE})
    g["18"] = _n("SaveVideo", {"video": ["17", 0], "filename_prefix": "h3/clip",
                               "format": "auto", "format.codec": "auto"})
    return g


NOEUDS_TRONCON = ("MiniMaxH3MotionContextLoadLatent", "MiniMaxH3MotionContext",
                  "MiniMaxH3MotionContextTrim")


def graphe_troncon(texte: str, longueur: int, graine: int, contexte: str) -> dict:
    """Le plan suivant par tronçon : le graphe de l'essai du 27/09 (branche b).

    Le latent du plan précédent est relu sur le disque Modal ; le nœud en épingle
    la fin (22 images, 1 s de son) au début du nouveau plan, puis Trim retire ces
    images reprises, et le son qui va avec, du plan livré.
    """
    g = graphe("texte", texte, longueur, graine)
    g["30"] = _n("MiniMaxH3MotionContextLoadLatent", {"latent_path": contexte, "clip_index": 1})
    g["31"] = _n("MiniMaxH3MotionContext", {
        "conditioning": ["10", 0], "vae": ["4", 0], "latent": ["10", 1], "context_latent": ["30", 0],
        "audio_vae": ["5", 0], "context_length": CONTEXTE_IMAGES, "audio_context_length": CONTEXTE_SON})
    g["13"]["inputs"]["conditioning"] = ["31", 0]
    g["32"] = _n("MiniMaxH3MotionContextTrim", {"images": ["15", 0], "audio": ["16", 0],
                                                 "trim_frames": ["31", 1], "fps": float(IMAGES_PAR_SECONDE)})
    g["17"]["inputs"].update({"images": ["32", 0], "audio": ["32", 1]})
    return g


def garder_latent(demande: dict, jid: str) -> dict:
    """Option tronçon : le latent de ce clip reste sur le disque Modal, pour le
    plan qui le prolongera. Sans l'option, rien n'est ajouté au graphe."""
    if not motion_context_actif():
        return demande
    demande["graphe"]["19"] = _n("MiniMaxH3MotionContextSaveLatent", {
        "latent": ["14", 0], "filename_prefix": "h3_context/clip", "clip_index": 1})
    demande["classes"] = list(demande["classes"]) + ["MiniMaxH3MotionContextSaveLatent"]
    demande["latent_vers"] = f"{DOSSIER_CHAINES}/{jid}.safetensors"
    return demande


# --- La demande ------------------------------------------------------------------

def _image(b64: str, quoi: str) -> str:
    """Contrôle une image venue de la page (base64, sans l'en-tête data:)."""
    b64 = str(b64 or "")
    if "," in b64[:100] and b64.startswith("data:"):
        b64 = b64.split(",", 1)[1]
    try:
        octets = base64.b64decode(b64, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{quoi} : fichier illisible.") from exc
    if not octets:
        raise ValueError(f"{quoi} : fichier vide.")
    if len(octets) > IMAGE_MAX_OCTETS:
        raise ValueError(f"{quoi} : plus de 8 Mo, réduisez l'image.")
    if not (octets[:8] == b"\x89PNG\r\n\x1a\n" or octets[:3] == b"\xff\xd8\xff"
            or (octets[:4] == b"RIFF" and octets[8:12] == b"WEBP")):
        raise ValueError(f"{quoi} : seules les images PNG, JPEG et WebP sont acceptées.")
    return base64.b64encode(octets).decode()


def preparer(payload: dict, graine_hasard=None) -> dict:
    """Vérifie la demande de la page et fabrique ce qui part sur la machine.

    Rend {"demande", "resume_public"} ou lève ValueError avec une phrase pour
    la page. Rien n'est loué ici.
    """
    mode = str(payload.get("mode") or "texte")
    if mode not in MODES:
        raise ValueError("Mode inconnu.")
    langue = str(payload.get("langue") or LANGUE_PAROLES)
    if langue not in LANGUES_PAROLES:
        raise ValueError("Langue des paroles inconnue.")
    # Une fiche (`fiche`) ou plusieurs (`fiches`, une par personnage, dans
    # l'ordre des <Subject N>) ; chacune peut parler sa langue (`langues`).
    ids = payload.get("fiches") or ([payload["fiche"]] if payload.get("fiche") else [])
    if not isinstance(ids, list) or len(set(map(str, ids))) != len(ids):
        raise ValueError("Liste de fiches illisible.")
    langues = payload.get("langues") or {}
    if not isinstance(langues, dict) or any(v not in LANGUES_PAROLES for v in langues.values()):
        raise ValueError("Langue d'un personnage inconnue.")
    fiches, de_la_fiche, nombres = [], [], []
    for fid in ids:
        if mode != "references":
            raise ValueError("Une fiche de casting se joue en mode « Références ».")
        fiche = fiche_lire(fid)
        images_fiche = fiche_images(fiche["id"])
        if not images_fiche:
            raise ValueError(f"La fiche « {fiche['nom']} » n'a encore aucune image : créez-les d'abord.")
        fiches.append(fiche)
        de_la_fiche += images_fiche
        nombres.append(len(images_fiche))
    image_paroles, ambiance = payload.get("image_paroles", ""), payload.get("ambiance", "")
    if fiches:
        sujets = [(f["nom"], langues.get(f["id"], langue)) for f in fiches]
        image_paroles = attribuer_repliques(image_paroles, sujets)
        ambiance = attribuer_repliques(ambiance, sujets)
    texte = invite(image_paroles, ambiance, payload.get("musique", ""), langue, "(S1)",
                   # Rubriques du mode références, dans l'ordre de la consigne de MiniMax
                   # (skills/h3-prompt-writing/SKILL.md) ; `summary` n'est pas écrit.
                   "overall_soundscape: " if fiches else "Sound: ")
    if not texte:
        raise ValueError("Décrivez au moins ce qu'on voit (première case).")
    if fiches:
        devant = premier_plan(image_paroles)
        texte = sujets_des_fiches(nombres) + " detailed_description: " + (devant + " " if devant else "") + texte
    if len(texte) > 4000:
        raise ValueError("Invite trop longue (4 000 caractères au plus).")
    try:
        longueur = int(payload.get("longueur") or LONGUEUR_PAR_DEFAUT)
    except (TypeError, ValueError) as exc:
        raise ValueError("Durée illisible.") from exc
    if longueur not in LONGUEURS:
        raise ValueError("Durée hors de la grille du modèle.")
    try:
        coupe = float(payload.get("coupe_s") or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("Coupe du début illisible.") from exc
    if coupe not in COUPES:
        raise ValueError("Coupe du début non proposée.")
    definition = str(payload.get("definition") or DEFINITION_PAR_DEFAUT)
    if definition not in DEFINITIONS:
        raise ValueError("Définition non proposée.")
    graine = payload.get("graine")
    if graine in (None, ""):
        graine = (graine_hasard or random.randint)(0, 2**31 - 1)
    try:
        graine = int(graine)
    except (TypeError, ValueError) as exc:
        raise ValueError("Graine illisible : un nombre entier.") from exc
    if not 0 <= graine < 2**63:
        raise ValueError("Graine hors bornes.")

    brutes = payload.get("images") or []
    if not isinstance(brutes, list):
        raise ValueError("Images illisibles.")
    brutes = de_la_fiche + brutes
    m = MODES[mode]
    if not m["images_min"] <= len(brutes) <= m["images_max"]:
        if m["images_max"] == 0:
            raise ValueError("Le mode « Texte seul » ne prend pas d'image.")
        if m["images_min"] == m["images_max"]:
            raise ValueError(f"Le mode « {m['titre']} » demande {m['images_min']} image(s).")
        raise ValueError(f"Le mode « {m['titre']} » demande de {m['images_min']} à "
                         f"{m['images_max']} images.")
    noms = noms_images(mode, len(brutes))
    images = {nom: _image(b, f"Image {i + 1}") for i, (nom, b) in enumerate(zip(noms, brutes))}
    if sum(len(v) * 3 // 4 for v in images.values()) > IMAGES_MAX_OCTETS:
        raise ValueError("Images trop lourdes ensemble (24 Mo au plus).")

    demande = {
        "mode": mode,
        "graphe": graphe(mode, texte, longueur, graine, len(brutes), definition),
        "classes": [m["noeud"]],
        "images": images,
        "fichiers": list(FICHIERS),
        "base_poids": POINT_DE_MONTAGE,
        "comfy": DOSSIER_COMFY,
        "comfy_version": COMFY_VERSION,
        "coupe_s": coupe,
        "delai_s": max(60, DUREE_MAX_S - 120),
        "longueur": longueur,
        "graine": graine,
    }
    return {
        "demande": demande,
        "resume_public": {
            "moteur": "MiniMax H3 (ComfyUI " + COMFY_VERSION + ")",
            "mode": mode,
            "mode_titre": m["titre"],
            "invite": texte,
            "langue": langue,
            "fiche": {"id": fiches[0]["id"], "nom": fiches[0]["nom"]} if fiches else None,
            "fiches": [{"id": f["id"], "nom": f["nom"]} for f in fiches],
            "images": longueur,
            "secondes": secondes_de(longueur),
            "coupe_s": coupe,
            "graine": graine,
            "taille": "%dx%d" % DEFINITIONS[definition],
            "carte": GPU,
            # Les durées ont été mesurées en 480p seulement.
            "prix_estime_usd": prix_estime(longueur) if definition == DEFINITION_PAR_DEFAUT else None,
            "cout_max_usd": pire_cas(),
        },
    }


def voie_prolonger(precedent: dict) -> str:
    """« troncon » si l'option est mise ET que le clip a gardé son latent ; sinon « image »."""
    v = precedent.get("video") or {}
    return "troncon" if motion_context_actif() and v.get("latent_vers") else "image"


def preparer_prolonger(payload: dict, precedent: dict, derniere_b64: Optional[str] = None,
                       graine_hasard=None) -> dict:
    """Le plan qui suit un clip H3 réussi. Mêmes contrôles que `preparer` ;
    la page envoie les trois cases de la suite, la durée et la graine."""
    v = precedent.get("video") or {}
    if not str(v.get("moteur", "")).startswith("MiniMax H3"):
        raise ValueError("Seul un clip H3 se prolonge ici.")
    if precedent.get("status") != "succeeded":
        raise ValueError("Ce clip n'est pas réussi : rien à prolonger.")
    plans = int(v.get("plans") or 1)
    if plans >= PLANS_MAX:
        raise ValueError(f"Cette chaîne a déjà {PLANS_MAX} plans : au-delà, l'image se dégrade. "
                         "Repartez d'une image.")
    voie = voie_prolonger(precedent)
    base = dict(payload, coupe_s=0)
    if voie == "troncon":
        plan = preparer(dict(base, mode="texte", images=[]), graine_hasard)
        d = plan["demande"]
        d["graphe"] = graphe_troncon(plan["resume_public"]["invite"], d["longueur"], d["graine"],
                                     v["latent_vers"])
        d["classes"] = [MODES["texte"]["noeud"], *NOEUDS_TRONCON]
        d["contexte"] = v["latent_vers"]
    else:
        if not derniere_b64:
            raise ValueError("La dernière image du clip est illisible.")
        plan = preparer(dict(base, mode="premiere", images=[derniere_b64]), graine_hasard)
    plan["demande"]["mode"] = "prolonger"
    plan["resume_public"].update({
        "mode": "prolonger",
        "mode_titre": "Prolonger " + ("par tronçon" if voie == "troncon" else "par la dernière image"),
        "voie": voie, "precedent": str(precedent.get("id", "")), "plans": plans + 1,
    })
    return plan


# --- La garde de licence ---------------------------------------------------------

DOSSIER_AUTORISATION = budget_modal.CONFIG_DIR / "h3-autorisation"
FICHE_AUTORISATION = DOSSIER_AUTORISATION / "fiche.json"
AUTORISATION_MAX_OCTETS = 10 * 1024 * 1024
TYPES_AUTORISATION = {b"\x89PNG": ".png", b"\xff\xd8\xff": ".jpg", b"%PDF": ".pdf"}


def autorisation_etat() -> dict:
    """La copie de l'autorisation MiniMax de CE Studio, sans son contenu."""
    try:
        fiche = json.loads(FICHE_AUTORISATION.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"presente": False}
    copie = DOSSIER_AUTORISATION / str(fiche.get("fichier", ""))
    if not copie.is_file() or copie.is_symlink():
        return {"presente": False}
    return {"presente": True, "date_autorisation": fiche.get("date_autorisation", ""),
            "deposee_le": fiche.get("deposee_le", ""), "octets": fiche.get("octets", 0),
            "empreinte": fiche.get("empreinte", "")}


def autorisation_poser(b64: str, date_autorisation: str) -> dict:
    """Range la copie déposée par le client. Elle ne quitte jamais cette machine."""
    date_autorisation = str(date_autorisation or "").strip()
    if not (len(date_autorisation) == 10 and date_autorisation[4] == "-" and date_autorisation[7] == "-"
            and date_autorisation.replace("-", "").isdigit()):
        raise ValueError("Date de l'autorisation illisible (jour/mois/année).")
    b64 = str(b64 or "")
    if b64.startswith("data:") and "," in b64[:100]:
        b64 = b64.split(",", 1)[1]
    try:
        octets = base64.b64decode(b64, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("Copie illisible.") from exc
    if not octets or len(octets) > AUTORISATION_MAX_OCTETS:
        raise ValueError("Copie vide ou de plus de 10 Mo.")
    ext = next((e for debut, e in TYPES_AUTORISATION.items() if octets.startswith(debut)), None)
    if not ext:
        raise ValueError("La copie doit être une image PNG, JPEG, ou un PDF.")
    DOSSIER_AUTORISATION.mkdir(parents=True, exist_ok=True)
    for ancien in DOSSIER_AUTORISATION.glob("copie.*"):
        ancien.unlink()
    (DOSSIER_AUTORISATION / ("copie" + ext)).write_bytes(octets)
    FICHE_AUTORISATION.write_text(json.dumps({
        "fichier": "copie" + ext,
        "date_autorisation": date_autorisation,
        "deposee_le": time.strftime("%Y-%m-%d %H:%M:%S"),  # date-machine
        "octets": len(octets),
        "empreinte": hashlib.sha256(octets).hexdigest()[:16],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return autorisation_etat()


# --- Les poids, préparés une fois --------------------------------------------------

FICHE_POIDS = budget_modal.CONFIG_DIR / "h3-poids.json"


def poids_etat() -> dict:
    try:
        fiche = json.loads(FICHE_POIDS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"prets": False, "volume": VOLUME}
    fiche["volume"] = VOLUME
    fiche["prets"] = bool(fiche.get("prets")) and fiche.get("revision") == HF_REVISION
    return fiche


def poids_noter(prets: bool, detail: str = "") -> dict:
    FICHE_POIDS.parent.mkdir(parents=True, exist_ok=True)
    FICHE_POIDS.write_text(json.dumps({
        "prets": bool(prets), "revision": HF_REVISION, "volume": VOLUME,
        "le": time.strftime("%Y-%m-%d %H:%M:%S"),  # date-machine
        "detail": detail[:500]}, ensure_ascii=False, indent=2), encoding="utf-8")
    return poids_etat()


# --- Messages d'échec --------------------------------------------------------------

def phrase_d_echec(stderr: str) -> str:
    s = str(stderr or "")
    if "POIDS_ABSENTS" in s:
        return ("Les poids de H3 ne sont pas sur le disque Modal « " + VOLUME + " ». "
                "Cliquez « Préparer les poids » (une fois), puis relancez.")
    if "NOEUD_ABSENT" in s:
        return ("Ce ComfyUI n'a pas le nœud de ce mode : le mode n'est pas proposé tant "
                "que la version épinglée ne l'a pas.")
    if "GRAPHE_REFUSE" in s:
        return "ComfyUI a refusé le graphe avant tout calcul. Le détail est dans le journal."
    if "COMFY_ARRETE" in s:
        return "ComfyUI s'est arrêté pendant le calcul (mémoire ?). Le détail est dans le journal."
    if "DELAI" in s:
        return "Le clip n'était pas fini avant le délai. Rien n'a été rendu."
    if "CONTEXTE_ABSENT" in s:
        return ("La fin du clip précédent n'est plus sur le disque Modal : prolongez-le par "
                "la dernière image (option « tronçon » éteinte), ou repartez d'une image.")
    return ""


# --- Les scripts envoyés sur la machine louée ---------------------------------------

_SCRIPT = r'''
# Vidéo H3 du Free AI Studio : lance ComfyUI (service à part, GPL-3.0) et lui
# envoie un graphe par HTTP. Rien de ComfyUI n'est importé ici.
import base64, json, os, shutil, subprocess, sys, time, urllib.error, urllib.request
from pathlib import Path

D = json.loads(base64.b64decode("__DEMANDE_B64__").decode())
OUT = Path(os.environ.get("FREE_AI_OUTPUT_DIR", "/tmp/free_ai_output"))
OUT.mkdir(parents=True, exist_ok=True)
BASE = Path(D["base_poids"])
COMFY = Path(D["comfy"])
t0 = time.time()

manque = [f for f in D["fichiers"] if not (BASE / f).is_file()]
if manque:
    print("POIDS_ABSENTS " + ", ".join(manque), file=sys.stderr)
    sys.exit(3)
if D.get("contexte") and not Path(D["contexte"]).is_file():
    print("CONTEXTE_ABSENT " + D["contexte"], file=sys.stderr)
    sys.exit(10)

Path("/tmp/chemins.yaml").write_text(
    "h3:\n  base_path: " + str(BASE) + "\n  diffusion_models: diffusion_models\n"
    "  text_encoders: text_encoders\n  vae: vae\n  loras: loras\n")
(COMFY / "input").mkdir(exist_ok=True)
for nom, b64 in D["images"].items():
    (COMFY / "input" / nom).write_bytes(base64.b64decode(b64))

journal = open("/tmp/comfy.log", "w")
proc = subprocess.Popen(
    [sys.executable, "main.py", "--listen", "127.0.0.1", "--port", "8188", "--disable-pinned-memory",
     "--extra-model-paths-config", "/tmp/chemins.yaml", "--output-directory", "/tmp/sortie"],
    cwd=str(COMFY), stdout=journal, stderr=subprocess.STDOUT)
BASE_URL = "http://127.0.0.1:8188"


def lire(chemin):
    with urllib.request.urlopen(BASE_URL + chemin, timeout=30) as r:
        return json.loads(r.read())


def fin_du_journal():
    journal.flush()
    return Path("/tmp/comfy.log").read_text(errors="replace")[-4000:]


def echouer(code, mot, detail=""):
    print(mot + " " + str(detail)[:3000], file=sys.stderr)
    print("--- journal ComfyUI ---\n" + fin_du_journal(), file=sys.stderr)
    proc.kill()
    sys.exit(code)


for _ in range(300):
    try:
        lire("/system_stats")
        break
    except Exception:
        if proc.poll() is not None:
            echouer(7, "COMFY_ARRETE", "au démarrage")
        time.sleep(1)
else:
    echouer(7, "COMFY_ARRETE", "pas de réponse en 300 s")
t_pret = time.time()

info = lire("/object_info")
absents = [c for c in D["classes"] if c not in info]
if absents:
    echouer(4, "NOEUD_ABSENT", absents)

corps = json.dumps({"prompt": D["graphe"], "client_id": "free-ai-studio"}).encode()
req = urllib.request.Request(BASE_URL + "/prompt", data=corps, headers={"Content-Type": "application/json"})
try:
    with urllib.request.urlopen(req, timeout=60) as r:
        rep = json.loads(r.read())
except urllib.error.HTTPError as e:
    echouer(5, "GRAPHE_REFUSE", e.read().decode(errors="replace"))
if rep.get("node_errors") or "prompt_id" not in rep:
    echouer(5, "GRAPHE_REFUSE", json.dumps(rep))

pid, etat, limite = rep["prompt_id"], None, time.time() + D["delai_s"]
while time.time() < limite:
    h = lire("/history/" + pid)
    if pid in h:
        etat = h[pid]
        break
    if proc.poll() is not None:
        echouer(7, "COMFY_ARRETE", "pendant le calcul")
    time.sleep(2)
if etat is None:
    echouer(8, "DELAI", "%d s" % D["delai_s"])
statut = etat.get("status", {}).get("status_str")
if statut != "success":
    echouer(6, "CALCUL_ECHOUE", json.dumps(etat.get("status", {}).get("messages", []))[-3000:])
calcul_s = round(time.time() - t_pret, 1)

clips = sorted(Path("/tmp/sortie/h3").glob("clip_*"))
if not clips:
    echouer(6, "CALCUL_ECHOUE", "aucun fichier rendu")
if D["coupe_s"] > 0:
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(D["coupe_s"]), "-i", str(clips[-1]),
                        "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac",
                        str(OUT / "video.mp4")], capture_output=True, text=True)
    if r.returncode:
        echouer(9, "COUPE_ECHOUEE", r.stderr)
else:
    shutil.copyfile(clips[-1], OUT / "video.mp4")
proc.kill()
latent_garde = False
if D.get("latent_vers"):
    # Le latent reste sur le disque Modal pour le plan suivant. Son absence
    # n'annule pas le clip : on ne pourra le prolonger que par la dernière image.
    latents = sorted(Path("/tmp/sortie/h3_context").glob("clip_*.safetensors"))
    if latents:
        Path(D["latent_vers"]).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(latents[-1], D["latent_vers"])
        subprocess.run(["sync"], check=False)
        latent_garde = True
    else:
        print("LATENT_NON_GARDE", file=sys.stderr)
(OUT / "resume.json").write_text(json.dumps({
    "moteur": "MiniMax H3, ComfyUI " + D["comfy_version"], "mode": D["mode"],
    "images": D["longueur"], "graine": D["graine"], "coupe_s": D["coupe_s"],
    "latent_garde": latent_garde,
    "demarrage_comfy_s": round(t_pret - t0, 1), "calcul_s": calcul_s,
    "total_s": round(time.time() - t0, 1)}, ensure_ascii=False))
print("ok", calcul_s, "s de calcul")
'''

_SCRIPT_POIDS = r'''
# Poids de MiniMax H3 (Comfy-Org, révision épinglée) vers le disque Modal.
# Sur processeur : aucune carte n'est louée pendant le téléchargement.
import base64, json, os, subprocess, sys, time
from pathlib import Path
from huggingface_hub import hf_hub_download

D = json.loads(base64.b64decode("__DEMANDE_B64__").decode())
OUT = Path(os.environ.get("FREE_AI_OUTPUT_DIR", "/tmp/free_ai_output"))
OUT.mkdir(parents=True, exist_ok=True)
t0 = time.time()
tailles = {}
for f in D["fichiers"]:
    p = hf_hub_download(D["depot"], f, revision=D["revision"], local_dir=D["base_poids"])
    tailles[f] = os.path.getsize(p)
    print("ok %6.2f Gio  %s  (%d s)" % (tailles[f] / 2**30, f, time.time() - t0), flush=True)
subprocess.run(["sync"], check=False)
(OUT / "poids.json").write_text(json.dumps({"secondes": round(time.time() - t0, 1),
                                           "gio": round(sum(tailles.values()) / 2**30, 2)}))
'''


def _emballer(gabarit: str, demande: dict) -> str:
    b64 = base64.b64encode(json.dumps(demande, ensure_ascii=False).encode()).decode()
    return gabarit.replace("__DEMANDE_B64__", b64)


def construire_script(demande: dict) -> str:
    return _emballer(_SCRIPT, demande)


def construire_script_poids() -> str:
    return _emballer(_SCRIPT_POIDS, {"fichiers": list(FICHIERS), "depot": HF, "revision": HF_REVISION,
                                     "base_poids": POINT_DE_MONTAGE})


# Le téléchargement : 52 Go sur processeur. Délai large, carte aucune.
POIDS_DUREE_MAX_S = int(os.getenv("H3_POIDS_TIMEOUT_SECONDS", "3600"))
POIDS_MEMOIRE_MB = 4096
POIDS_COEURS = 2.0


def pire_cas_poids() -> float:
    return round(budget_modal.prix_seconde(None, POIDS_MEMOIRE_MB, POIDS_COEURS) * POIDS_DUREE_MAX_S, 3)


# --- La page -----------------------------------------------------------------------

PAGE_HTML = r"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Vidéo H3 — Free AI Studio</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: 860px; margin: 0 auto; padding: 16px; background: #fafafa; color: #222; }
  h1 { font-size: 1.5rem; margin-bottom: 4px; }
  .bloc { background: #fff; border: 1px solid #ddd; border-radius: 8px; padding: 12px 14px; margin: 12px 0; }
  label { display: block; font-weight: 600; margin-top: 10px; }
  textarea, select, input[type=text], input[type=number], input[type=date] { width: 100%; box-sizing: border-box; font: inherit; padding: 6px; }
  textarea { min-height: 70px; }
  .note { color: #555; font-size: .92rem; }
  .avert { color: #8a4b00; }
  .refus { color: #a40000; font-weight: 600; }
  .occupe { background: #eef4ff; border-left: 4px solid #2b5fd9; padding: .5rem .7rem; font-weight: 600; }
  .rond { display: inline-block; width: .8rem; height: .8rem; border: 2px solid #2b5fd9; border-top-color: transparent;
          border-radius: 50%; animation: tourne 1s linear infinite; vertical-align: -1px; }
  @keyframes tourne { to { transform: rotate(360deg); } }
  button { font: inherit; padding: 8px 16px; margin-top: 12px; cursor: pointer; }
  video { width: 100%; margin-top: 10px; background: #000; }
  .image_bord { border-top: 1px solid #eee; margin-top: 12px; padding-top: 8px; }
  .image_bord label { font-weight: normal; }
  .apercu { display: block; max-width: 100%; margin-top: 8px; border: 1px solid #ccc; }
  .grille { display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 10px; margin-top: 8px; }
  .grille img { display: block; width: 100%; border: 1px solid #ccc; margin: 4px 0; }
  .grille button { margin: 4px 4px 0 0; padding: 4px 10px; }
  .clip { display: flex; gap: 10px; align-items: flex-start; border-top: 1px solid #eee; padding: 8px 0; }
  .clip video { width: 200px; flex: none; margin: 0; }
  .clip button { margin: 0 4px 0 0; padding: 2px 10px; }
  .clip .note { flex: 1; overflow-wrap: anywhere; }
  pre { white-space: pre-wrap; font-size: .8rem; max-height: 240px; overflow: auto; background: #f3f3f3; padding: 8px; }
</style>
</head>
<body>
<h1>🎞️ Vidéo H3 <span class="note">expérimental</span></h1>
<p class="note">MiniMax H3 fabrique l'image <b>et</b> le son d'un clip, sur une machine louée chez Modal
(A100). Moteur : ComfyUI, lancé à part sur la machine louée.</p>

<div class="bloc" id="banniere">Lecture du budget…</div>

<div class="bloc" id="licence">
  <b>Licence de MiniMax H3.</b> Elle exclut par défaut l'Union européenne, le Royaume-Uni et la Corée :
  il faut l'autorisation écrite de MiniMax.
  <div id="licence_etat">Lecture…</div>
  <div id="licence_depot" hidden>
    <label for="licence_fichier">Copie de votre autorisation (image PNG ou JPEG, ou PDF)</label>
    <input type="file" id="licence_fichier" accept="image/png,image/jpeg,application/pdf">
    <label for="licence_date">Date de l'autorisation</label>
    <input type="date" id="licence_date">
    <button id="licence_envoyer">Enregistrer ma copie</button>
    <p class="note">La copie reste sur cet ordinateur (dossier de configuration du Studio). Elle ne part chez personne.</p>
  </div>
</div>

<div class="bloc" id="poids">
  <b>Poids du modèle.</b> <span id="poids_etat">Lecture…</span>
  <button id="poids_preparer" hidden>Préparer les poids</button>
</div>

<div class="bloc" id="casting">
  <b>Fiches de casting</b>
  <span class="note">un personnage décrit une fois, retrouvé d'un plan à l'autre (mode « Références »).</span>
  <label for="fiche_choix">Fiche</label>
  <select id="fiche_choix"><option value="">Nouvelle fiche…</option></select>
  <label for="fiche_nom">Nom du personnage</label>
  <input type="text" id="fiche_nom" maxlength="60">
  <label for="fiche_description">Description (âge, visage, coiffure, tenue)</label>
  <textarea id="fiche_description" maxlength="800"></textarea>
  <button id="fiche_creer">Créer la fiche et ses images</button>
  <button id="fiche_supprimer" hidden>Supprimer la fiche</button>
  <p class="note" id="fiche_etat"></p>
  <div id="fiche_images" class="grille"></div>
  <p class="note">Les images sont faites par l'image du Studio (clé Google, gratuite) : d'abord le
  portrait de face, d'après la description, puis les autres angles à partir de lui, pour garder le même
  visage. Rejouez ou supprimez celles qui ne vont pas.</p>
</div>

<div class="bloc">
  <label for="mode">Mode</label>
  <select id="mode"></select>
  <p class="note" id="mode_note"></p>
  <label for="image_paroles">1. Image et paroles (les paroles entre « guillemets »)</label>
  <textarea id="image_paroles">Une femme en manteau rouge marche sous la pluie à Paris, la nuit ; elle se retourne et dit : « On y est presque. »</textarea>
  <label for="langue">Langue des paroles</label>
  <select id="langue">__LANGUES__</select>
  <label for="ambiance">2. Ambiance sonore</label>
  <textarea id="ambiance">Pluie, circulation au loin.</textarea>
  <label for="musique">3. Musique (vide : aucune musique)</label>
  <textarea id="musique"></textarea>
  <p class="note">Les trois textes sont des exemples : modifiez-les librement.
  Pour des paroles nettes : une seule personne parle, visage vers la caméra, une seule action par plan,
  et pas plus de 2 mots par seconde (une dizaine pour 5 s). Case musique vide, le Studio demande au modèle
  de n'en mettre aucune : sinon il en ajoute une de lui-même.</p>

  <div class="image_bord" id="bord_premiere" hidden>
    <b>Première image</b>
    <label><input type="radio" name="source_premiere" value="creer" checked> La créer avec l'image du Studio (clé Google, gratuite)</label>
    <label><input type="radio" name="source_premiere" value="televerser"> La téléverser</label>
    <div class="creer">
      <label for="invite_premiere">Description de l'image (préremplie d'après la case 1, modifiable)</label>
      <textarea id="invite_premiere"></textarea>
      <button id="creer_premiere">Créer l'image</button>
    </div>
    <div class="televerser" hidden><input type="file" id="fichier_premiere" accept="image/png,image/jpeg,image/webp"></div>
    <img id="apercu_premiere" class="apercu" alt="" hidden>
    <p class="note" id="etat_premiere"></p>
  </div>
  <div class="image_bord" id="bord_derniere" hidden>
    <b>Dernière image</b>
    <label><input type="radio" name="source_derniere" value="creer" checked> La créer avec l'image du Studio (clé Google, gratuite)</label>
    <label><input type="radio" name="source_derniere" value="televerser"> La téléverser</label>
    <div class="creer">
      <label for="invite_derniere">Description de l'image (préremplie d'après la case 1, modifiable)</label>
      <textarea id="invite_derniere"></textarea>
      <button id="creer_derniere">Créer l'image</button>
    </div>
    <div class="televerser" hidden><input type="file" id="fichier_derniere" accept="image/png,image/jpeg,image/webp"></div>
    <img id="apercu_derniere" class="apercu" alt="" hidden>
    <p class="note" id="etat_derniere"></p>
  </div>
  <div id="references_bloc" hidden>
    <label for="fiche_ref">Personnage (fiche de casting)</label>
    <select id="fiche_ref"><option value="">Aucun : images téléversées seulement</option></select>
    <label for="images">Images de référence (en plus de la fiche, facultatif ; 9 au plus en tout)</label>
    <input type="file" id="images" accept="image/png,image/jpeg,image/webp" multiple>
  </div>

  <label for="longueur">Durée</label>
  <select id="longueur"></select>
  <p class="note" id="prix"></p>

  <label for="definition">Définition de l'image</label>
  <select id="definition">
    <option value="480p">480p (832 × 480), celle des prix mesurés</option>
    <option value="768p">768p (1344 × 768), plus nette, plus longue à calculer, prix non mesuré</option>
  </select>

  <label for="coupe">Couper le début</label>
  <select id="coupe">
    <option value="0">Ne rien couper</option>
    <option value="0.25">0,25 s</option>
    <option value="0.5">0,5 s</option>
  </select>
  <label for="graine">Graine (vide = au hasard ; la même graine refait le même tirage)</label>
  <input type="number" id="graine" min="0" step="1">

  <button id="lancer">Fabriquer le clip</button>
  <p id="statut" class="note"></p>
  <div id="resultat" hidden>
    <video id="lecteur" controls playsinline></video>
    <p><a id="telecharger" href="#">Enregistrer le clip</a></p>
    <p class="note" id="fiche"></p>
    <div id="prolonger_bloc" hidden>
      <p class="note" id="prolonger_note"></p>
      <button id="prolonger">Prolonger ce clip</button>
    </div>
  </div>
  <pre id="journal" hidden></pre>
</div>

<div class="bloc" id="montage_bloc">
  <b>Monter un scénario</b>
  <span class="note">avec les clips déjà faits : rien n'est tourné de nouveau, rien n'est loué.</span>
  <label for="scenario">Scénario (sert à ranger les clips dans l'ordre du récit)</label>
  <textarea id="scenario" maxlength="2000"></textarea>
  <p class="note">Cochez les clips du film. Rangez-les avec ↑ ↓, ou demandez l'ordre au chat du Studio
  d'après le scénario ; puis assemblez. Les clips sont recollés bout à bout, son compris, sans rien couper.</p>
  <div id="clips_liste"></div>
  <button id="scenario_ordonner">Ranger selon le scénario</button>
  <button id="montage_lancer">Assembler le film</button>
  <p class="note" id="montage_etat"></p>
  <div id="montage_resultat" hidden>
    <video id="montage_lecteur" controls playsinline></video>
    <p><a id="montage_telecharger" href="#">Enregistrer le film</a></p>
  </div>
  <div class="image_bord">
    <b>Ou tourner un scénario neuf</b>
    <span class="note">le même scénario, découpé en plans par le chat du Studio, puis tourné plan par plan
    (chaque plan se paie comme un clip : durée, graine, langue et musique sont celles du formulaire du clip).</span>
    <label for="scenario_fiche">Personnage (fiche de casting) et sa langue</label>
    <select id="scenario_fiche"><option value="">Choisissez une fiche…</option></select>
    <select id="scenario_langue1">__LANGUES__</select>
    <label for="scenario_fiche2">Second personnage (facultatif) et sa langue</label>
    <select id="scenario_fiche2"><option value="">Aucun</option></select>
    <select id="scenario_langue2">__LANGUES__</select>
    <span class="note">Nommez le personnage qui parle dans la phrase de sa réplique : le Studio lui attribue
    la réplique et sa langue.</span>
    <label for="scenario_chanson">Musique de fond (une chanson du Studio, posée après le tournage)</label>
    <select id="scenario_chanson"><option value="">Aucune (musique décrite au clip)</option></select>
    <label for="scenario_musique_plan">à partir du plan</label>
    <input id="scenario_musique_plan" type="number" min="1" max="4" value="1">
    <button id="scenario_decouper">Découper en plans</button>
    <div id="plans_liste"></div>
    <button id="plan_ajouter" hidden>Ajouter un plan</button>
    <p class="note" id="scenario_prix"></p>
    <button id="scenario_tourner" hidden>Tourner le scénario</button>
    <button id="scenario_arreter" hidden>Arrêter le tournage</button>
    <p id="scenario_occupe" class="occupe" hidden><span class="rond"></span> <span id="scenario_occupe_texte"></span>
      <span id="scenario_chrono"></span></p>
    <p class="note" id="scenario_etat"></p>
    <label for="scenario_choix">Reprendre un scénario déjà tourné</label>
    <select id="scenario_choix"><option value="">Choisissez un scénario…</option></select>
    <div id="scenario_suite" hidden>
      <label for="suite_action">Que faire ?</label>
      <select id="suite_action">
        <option value="auto">Corriger tout seul, avec pause avant de payer</option>
        <option value="juger">Faire juger les plans (gratuit)</option>
        <option value="corriger">Corriger le texte d'après mes remarques (gratuit)</option>
        <option value="rejouer">Rejouer les plans changés ou cochés (payant)</option>
      </select>
      <div id="suite_auto_options">
        <select id="auto_tours"><option value="1">1 tour</option><option value="2" selected>2 tours au plus</option>
          <option value="3">3 tours au plus</option></select>
        <label><input type="checkbox" id="auto_sans_arret"> sans pause (chaque fausse alerte fait payer un plan)</label>
      </div>
      <div id="suite_corriger_options" hidden>
        <label for="retours">Vos remarques</label>
        <textarea id="retours" maxlength="2000"></textarea>
      </div>
      <button id="suite_lancer">Lancer</button>
      <div id="jugement"></div>
      <div id="suite_pause" hidden>
        <p class="refus">Pause avant de payer : décochez les fausses alertes et relisez le texte en gras.</p>
        <button id="scenario_auto_payer">Rejouer les plans aux défauts cochés (payant)</button>
        <button id="scenario_auto_arreter">Arrêter ici</button>
      </div>
      <details class="note"><summary>Comment ça marche</summary>
        Le juge (Free AI Max, gratuit) compare chaque plan aux fiches et à l'histoire, sur une image toutes les
        0,5 s ; il se trompe parfois. La correction change la façon de montrer, pas l'histoire, et sa continuité est
        contrôlée. Le texte en <b>gras</b> a changé depuis le scénario initial (<s>barré</s> : retiré). Au rejeu,
        seuls les plans changés ou cochés sont tournés et payés, les autres sont repris, la musique est reposée.
      </details>
    </div>
  </div>
  <div class="image_bord">
    <b>Poser une musique sous un film</b>
    <span class="note">une chanson du Studio (page Chanson) sous le son du film, du début choisi à la fin, avec
    un decrescendo final ; rien n'est loué.</span>
    <label for="musique_film">Film</label>
    <select id="musique_film"></select>
    <label for="musique_chanson">Musique</label>
    <select id="musique_chanson"></select>
    <label for="musique_debut">Début de la musique (secondes)</label>
    <input id="musique_debut" type="number" min="0" step="0.01" value="0">
    <label for="musique_volume">Volume (de 0,05 à 1)</label>
    <input id="musique_volume" type="number" min="0.05" max="1" step="0.05" value="0.3">
    <button id="musique_poser">Poser la musique</button>
    <p class="note" id="musique_etat"></p>
  </div>
</div>

<script>
const CLE = "__CLE__";
const H = {"Authorization": "Bearer " + CLE, "Content-Type": "application/json"};
let ETAT = null;

function lireFichier(f){
  return new Promise((ok, ko) => {
    const r = new FileReader();
    r.onload = () => ok(String(r.result));
    r.onerror = () => ko(r.error);
    r.readAsDataURL(f);
  });
}

// Première et dernière image : créées par l'image du Studio ou téléversées,
// puis recadrées à la taille du clip (sans déformation), ici, dans la page.
const IMAGES = {premiere: null, derniere: null};
const RETOUCHEE = {premiere: false, derniere: false};
const PREFIXE = {
  premiere: "Photo réaliste, cadrage paysage 16:9, image nette, début de la scène : ",
  derniere: "Photo réaliste, cadrage paysage 16:9, image nette, même personnage et même décor, fin de la scène : "};

function sansParoles(t){
  // La description de l'image n'a que faire des répliques entre guillemets.
  // Le verbe qui annonçait la réplique part avec elle (« … et dit : »).
  return t.replace(/«[^»]*»/g, "").replace(/"[^"]*"/g, "")
    .replace(/\s*(?:,\s*)?(?:\bet\s+)?\b(?:dit|demande|crie|murmure|chuchote|répond)\s*:\s*/gi, " ")
    .replace(/\s+/g, " ").replace(/\s+([,.])/g, "$1").replace(/[\s,;:]+$/, "").trim();
}

function majInvitesImages(){
  const base = sansParoles(document.getElementById("image_paroles").value);
  for (const nom of ["premiere", "derniere"]){
    if (!RETOUCHEE[nom]) document.getElementById("invite_" + nom).value = PREFIXE[nom] + base;
  }
}

function tailleChoisie(){
  const t = ETAT.definitions[document.getElementById("definition").value];
  return [t.largeur, t.hauteur];
}

function recadrer(src){
  return new Promise((ok, ko) => {
    const im = new Image();
    im.onload = () => {
      const [L, Ht] = tailleChoisie();
      const c = document.createElement("canvas");
      c.width = L; c.height = Ht;
      const s = Math.max(L / im.width, Ht / im.height);
      const w = im.width * s, h = im.height * s;
      c.getContext("2d").drawImage(im, (L - w) / 2, (Ht - h) / 2, w, h);
      ok(c.toDataURL("image/png"));
    };
    im.onerror = () => ko(new Error("image illisible"));
    im.src = src;
  });
}

function poserImage(nom, src){
  return recadrer(src).then(png => {
    IMAGES[nom] = png;
    const a = document.getElementById("apercu_" + nom);
    a.src = png;
    a.hidden = false;
    const [L, Ht] = tailleChoisie();
    document.getElementById("etat_" + nom).textContent = "Image prête, recadrée en " + L + " × " + Ht + ".";
  });
}

function brancherBord(nom){
  for (const r of document.querySelectorAll('input[name="source_' + nom + '"]')){
    r.addEventListener("change", () => {
      const creer = document.querySelector('input[name="source_' + nom + '"]:checked').value === "creer";
      const bord = document.getElementById("bord_" + nom);
      bord.querySelector(".creer").hidden = !creer;
      bord.querySelector(".televerser").hidden = creer;
    });
  }
  document.getElementById("invite_" + nom).addEventListener("input", () => { RETOUCHEE[nom] = true; });
  document.getElementById("fichier_" + nom).addEventListener("change", async (e) => {
    const f = e.target.files[0];
    if (f) await poserImage(nom, await lireFichier(f));
  });
  document.getElementById("creer_" + nom).addEventListener("click", async () => {
    const etat = document.getElementById("etat_" + nom);
    etat.className = "note";
    etat.textContent = "Création de l'image (quelques secondes)…";
    const r = await fetch("/video-h3/image", {method: "POST", headers: H,
      body: JSON.stringify({texte: document.getElementById("invite_" + nom).value})});
    const d = await r.json();
    if (!r.ok){ etat.className = "refus"; etat.textContent = d.detail || "Refusé."; return; }
    await poserImage(nom, d.image);
  });
}

function majMode(){
  const cle = document.getElementById("mode").value;
  const m = ETAT.modes[cle];
  document.getElementById("mode_note").textContent = m.note + " Essayé le " + dateFr(m.essaye_le) + ".";
  document.getElementById("bord_premiere").hidden = !(cle === "premiere" || cle === "premiere_derniere");
  document.getElementById("bord_derniere").hidden = cle !== "premiere_derniere";
  document.getElementById("references_bloc").hidden = cle !== "references";
}

function majPrix(){
  const n = Number(document.getElementById("longueur").value);
  const d = ETAT.durees.find(x => x.images === n);
  const pire = "Au pire (la machine va jusqu'au bout de son délai) : " + fr(ETAT.pire_cas_usd, 2) + " $.";
  document.getElementById("prix").textContent = (d && d.prix_estime_usd !== null)
    ? "Estimé : " + fr(d.prix_estime_usd, 3) + " $, d'après " + fr(ETAT.secondes_mesurees, 0)
      + " s de location mesurées par le Studio le " + dateFr(ETAT.mesure_le)
      + ". Le tout premier clip coûte davantage : il lit les 52 Go de poids sur un disque neuf. " + pire
    : "Durée jamais essayée : pas d'estimation mesurée. " + pire;
}

function afficherLicence(a){
  const e = document.getElementById("licence_etat");
  document.getElementById("licence_depot").hidden = a.presente;
  e.className = a.presente ? "" : "refus";
  e.textContent = a.presente
    ? "Copie de l'autorisation déposée le " + dateFr(a.deposee_le) + " (autorisation du "
      + dateFr(a.date_autorisation) + "). Les clips sont permis."
    : "Aucune copie d'autorisation sur ce Studio : les clips sont refusés tant qu'elle n'est pas déposée.";
}

function afficherPoids(p){
  document.getElementById("poids_etat").textContent = p.prets
    ? "Prêts sur le disque Modal « " + p.volume + " » (depuis le " + dateFr(p.le) + ")."
    : "Pas encore sur le disque Modal « " + p.volume + " ». Une fois pour toutes : environ "
      + ETAT.poids_go + " Go, téléchargés sur processeur (sans carte). Au pire " + fr(ETAT.pire_cas_poids_usd, 2) + " $.";
  document.getElementById("poids_preparer").hidden = p.prets;
}

function rafraichir(){
  return fetch("/video-h3/etat", {headers: H}).then(r => r.json()).then(d => {
    ETAT = d;
    document.getElementById("banniere").textContent = "Budget Modal : " + fr(d.budget.usd, 2) + " $ dépensés sur "
      + fr(d.budget.plafond_usd, 2) + " $ ouverts aux demandes. " + renouvellementTexte(d.budget);
    const sm = document.getElementById("mode");
    if (!sm.options.length){
      for (const [k, m] of Object.entries(d.modes)){ sm.add(new Option(m.titre, k)); }
      const sl = document.getElementById("longueur");
      for (const x of d.durees){
        sl.add(new Option(fr(x.secondes, 1) + " s (" + x.images + " images)"
          + (x.prix_estime_usd !== null ? " — mesurée" : " — jamais essayée"), x.images));
      }
    }
    afficherLicence(d.autorisation);
    afficherPoids(d.poids);
    majMode();
    majPrix();
  });
}

function suivre(jid){
  fetch("/video/jobs/" + jid, {headers: H}).then(r => r.json()).then(j => {
    const st = document.getElementById("statut");
    if (j.status === "succeeded" && j.video_url){
      st.textContent = "Clip prêt.";
      document.getElementById("resultat").hidden = false;
      document.getElementById("lecteur").src = j.video_url;
      document.getElementById("telecharger").href = j.video_url + "&telecharger=1&nom=clip-h3";
      const r = j.resume || {};
      const v = j.video || {};
      document.getElementById("fiche").textContent = "Graine " + r.graine + " ; " + fr(r.calcul_s, 0)
        + " s de calcul, " + fr(r.total_s, 0) + " s de location."
        + (v.plans ? " Chaîne de " + v.plans + " plans, " + fr(v.secondes, 1) + " s en tout." : "");
      majProlonger(jid, v, r);
      rafraichir();
      chargerClips();
      return;
    }
    if (j.etape === "recollage"){
      st.textContent = "Plan rendu ; le Studio le recolle au clip précédent…";
      setTimeout(() => suivre(jid), 3000);
      return;
    }
    if (j.status === "failed"){
      st.className = "refus";
      st.textContent = "Échec : " + (j.message || "voir le journal.");
      const jr = document.getElementById("journal");
      jr.hidden = false;
      jr.textContent = (j.stderr || "") + "\n" + (j.stdout || "");
      rafraichir();
      return;
    }
    st.textContent = "En cours (" + j.status + ")… Le premier clip construit aussi la machine : plusieurs minutes.";
    setTimeout(() => suivre(jid), 4000);
  });
}

document.getElementById("mode").addEventListener("change", majMode);
document.getElementById("longueur").addEventListener("change", majPrix);

document.getElementById("licence_envoyer").addEventListener("click", async () => {
  const f = document.getElementById("licence_fichier").files[0];
  const date = document.getElementById("licence_date").value;
  if (!f || !date){ alerteTexte("Choisissez le fichier et la date."); return; }
  const r = await fetch("/video-h3/autorisation", {method: "POST", headers: H,
    body: JSON.stringify({copie: await lireFichier(f), date_autorisation: date})});
  const d = await r.json();
  if (!r.ok){ alerteTexte(d.detail || "Refusé."); return; }
  afficherLicence(d);
});

document.getElementById("poids_preparer").addEventListener("click", async () => {
  const r = await fetch("/video-h3/poids/preparer", {method: "POST", headers: H, body: "{}"});
  const d = await r.json();
  if (!r.ok){ alerteTexte(d.detail || "Refusé."); return; }
  document.getElementById("poids_etat").textContent = "Téléchargement lancé (plusieurs minutes)…";
  document.getElementById("poids_preparer").hidden = true;
  const attendre = () => fetch("/video/jobs/" + d.id, {headers: H}).then(x => x.json()).then(j => {
    if (j.status === "succeeded" || j.status === "failed"){ rafraichir(); return; }
    setTimeout(attendre, 10000);
  });
  attendre();
});

// Prolonger : le clip affiché devient le début de la chaîne. Les trois cases,
// la durée et la graine décrivent le plan suivant.
let PRECEDENT = null;

function majProlonger(jid, v, r){
  const bloc = document.getElementById("prolonger_bloc");
  const plans = v.plans || 1, max = ETAT.prolonger.plans_max;
  PRECEDENT = jid;
  bloc.hidden = false;
  const btn = document.getElementById("prolonger");
  btn.disabled = plans >= max;
  const troncon = ETAT.prolonger.par_troncon && v.latent_vers && r.latent_garde;
  document.getElementById("prolonger_note").textContent = plans >= max
    ? "Cette chaîne a " + plans + " plans, le maximum : au-delà, l'image se dégrade. Repartez d'une image."
    : "Plan " + plans + " sur " + max + ". Réécrivez les trois cases pour la suite, puis prolongez. "
      + (troncon
        ? "Par tronçon : le plan suivant reprend 22 images et 1 s de son de celui-ci."
        : "Par la dernière image : le plan suivant part de la dernière image de celui-ci ; "
          + "le mouvement et le son ne sont pas repris à la jointure.")
      + " Même prix qu'un clip.";
}

document.getElementById("prolonger").addEventListener("click", async () => {
  const st = document.getElementById("statut");
  st.className = "note";
  document.getElementById("journal").hidden = true;
  const graine = document.getElementById("graine").value;
  const r = await fetch("/video-h3/prolonger", {method: "POST", headers: H, body: JSON.stringify({
    precedent: PRECEDENT,
    image_paroles: document.getElementById("image_paroles").value,
    ambiance: document.getElementById("ambiance").value,
    musique: document.getElementById("musique").value,
    langue: document.getElementById("langue").value,
    longueur: Number(document.getElementById("longueur").value),
    definition: document.getElementById("definition").value,
    graine: graine === "" ? null : Number(graine)})});
  const d = await r.json();
  if (!r.ok){ alerteTexte(typeof d.detail === "string" ? d.detail : "Refusé."); return; }
  document.getElementById("resultat").hidden = true;
  st.textContent = "Plan suivant lancé.";
  suivre(d.id);
});

function alerteTexte(t){
  const st = document.getElementById("statut");
  st.className = "refus";
  st.textContent = t;
}

document.getElementById("lancer").addEventListener("click", async () => {
  const st = document.getElementById("statut");
  st.className = "note";
  document.getElementById("resultat").hidden = true;
  document.getElementById("journal").hidden = true;
  const m = document.getElementById("mode").value;
  const images = [];
  if (m === "references"){
    for (const f of Array.from(document.getElementById("images").files)){ images.push(await lireFichier(f)); }
  } else {
    const noms = m === "premiere" ? ["premiere"] : m === "premiere_derniere" ? ["premiere", "derniere"] : [];
    for (const nom of noms){
      if (!IMAGES[nom]){
        alerteTexte("Il manque la " + (nom === "premiere" ? "première" : "dernière")
          + " image : créez-la ou téléversez-la.");
        return;
      }
      images.push(IMAGES[nom]);
    }
  }
  const graine = document.getElementById("graine").value;
  const r = await fetch("/video-h3/creer", {method: "POST", headers: H, body: JSON.stringify({
    mode: m, images: images,
    image_paroles: document.getElementById("image_paroles").value,
    ambiance: document.getElementById("ambiance").value,
    musique: document.getElementById("musique").value,
    langue: document.getElementById("langue").value,
    fiche: m === "references" ? (document.getElementById("fiche_ref").value || null) : null,
    longueur: Number(document.getElementById("longueur").value),
    definition: document.getElementById("definition").value,
    coupe_s: Number(document.getElementById("coupe").value),
    graine: graine === "" ? null : Number(graine)})});
  const d = await r.json();
  if (!r.ok){ alerteTexte(typeof d.detail === "string" ? d.detail : "Refusé."); return; }
  st.textContent = "Lancé.";
  suivre(d.id);
});

// Fiches de casting (PLAN 18.9) : le Studio fabrique les images angle par angle ;
// chacune se rejoue ou se supprime.
let FICHES = [], ANGLES = {};

function ficheEtat(t, refus){
  const e = document.getElementById("fiche_etat");
  e.className = refus ? "refus" : "note";
  e.textContent = t || "";
}

function bouton(texte, action){
  const b = document.createElement("button");
  b.type = "button";
  b.textContent = texte;
  b.addEventListener("click", action);
  return b;
}

async function chargerFiches(choisir){
  const r = await fetch("/video-h3/fiches", {headers: H});
  if (!r.ok) return;
  const d = await r.json();
  FICHES = d.fiches;
  ANGLES = d.angles;
  const choix = document.getElementById("fiche_choix");
  const ref = document.getElementById("fiche_ref");
  let garde = choisir !== undefined ? choisir : choix.value;
  const gardeRef = ref.value;
  if (!FICHES.some(f => f.id === garde)) garde = "";
  choix.innerHTML = '<option value="">Nouvelle fiche…</option>';
  ref.innerHTML = '<option value="">Aucun : images téléversées seulement</option>';
  for (const f of FICHES){
    const n = f.angles.length;
    for (const sel of [choix, ref]){
      const o = document.createElement("option");
      o.value = f.id;
      o.textContent = f.nom + " (" + n + " image" + (n > 1 ? "s" : "") + ")";
      sel.appendChild(o);
    }
  }
  choix.value = garde;
  ref.value = FICHES.some(f => f.id === gardeRef) ? gardeRef : "";
  for (const [idSel, vide] of [["scenario_fiche", "Choisissez une fiche…"], ["scenario_fiche2", "Aucun"]]){
    const sf = document.getElementById(idSel);
    const gardeSf = sf.value;
    sf.innerHTML = "";
    const v = document.createElement("option");
    v.value = "";
    v.textContent = vide;
    sf.appendChild(v);
    for (const f of FICHES.filter(x => x.angles.length)){
      const o = document.createElement("option");
      o.value = f.id;
      o.textContent = f.nom;
      sf.appendChild(o);
    }
    sf.value = FICHES.some(f => f.id === gardeSf) ? gardeSf : "";
  }
  await montrerFiche();
}

async function montrerFiche(){
  const id = document.getElementById("fiche_choix").value;
  document.getElementById("fiche_images").innerHTML = "";
  document.getElementById("fiche_supprimer").hidden = !id;
  document.getElementById("fiche_creer").hidden = !!id;
  for (const champ of ["fiche_nom", "fiche_description"]){
    document.getElementById(champ).disabled = !!id;
    if (!id) document.getElementById(champ).value = "";
  }
  if (!id) return;
  const r = await fetch("/video-h3/fiches/" + id, {headers: H});
  const f = await r.json();
  if (!r.ok){ ficheEtat(f.detail, true); return; }
  document.getElementById("fiche_nom").value = f.nom;
  document.getElementById("fiche_description").value = f.description;
  dessinerFiche(f);
}

function dessinerFiche(f){
  const grille = document.getElementById("fiche_images");
  grille.innerHTML = "";
  for (const [angle, titre] of Object.entries(ANGLES)){
    const cas = document.createElement("div");
    const t = document.createElement("b");
    t.textContent = titre;
    cas.appendChild(t);
    if (f.images[angle]){
      const img = document.createElement("img");
      img.src = f.images[angle];
      img.alt = titre;
      cas.appendChild(img);
    }
    cas.appendChild(bouton(f.images[angle] ? "Rejouer" : "Créer", () => faireImage(f.id, angle)));
    if (f.images[angle]) cas.appendChild(bouton("Supprimer", () => retirerImage(f.id, angle)));
    grille.appendChild(cas);
  }
}

async function faireImage(id, angle){
  ficheEtat("Image « " + ANGLES[angle] + " » en cours (10 à 30 s)…");
  const r = await fetch("/video-h3/fiches/" + id + "/images/" + angle, {method: "POST", headers: H, body: "{}"});
  const d = await r.json();
  if (!r.ok){ ficheEtat(typeof d.detail === "string" ? d.detail : "Refusé.", true); return false; }
  ficheEtat("");
  await chargerFiches(id);
  return true;
}

async function retirerImage(id, angle){
  const r = await fetch("/video-h3/fiches/" + id + "/images/" + angle, {method: "DELETE", headers: H});
  const d = await r.json();
  if (!r.ok){ ficheEtat(typeof d.detail === "string" ? d.detail : "Refusé.", true); return; }
  await chargerFiches(id);
}

document.getElementById("fiche_choix").addEventListener("change", () => { ficheEtat(""); montrerFiche(); });

document.getElementById("fiche_creer").addEventListener("click", async () => {
  const r = await fetch("/video-h3/fiches", {method: "POST", headers: H, body: JSON.stringify({
    nom: document.getElementById("fiche_nom").value,
    description: document.getElementById("fiche_description").value})});
  const d = await r.json();
  if (!r.ok){ ficheEtat(typeof d.detail === "string" ? d.detail : "Refusé.", true); return; }
  await chargerFiches(d.id);
  for (const angle of Object.keys(ANGLES)){
    if (!await faireImage(d.id, angle)) return;
  }
  ficheEtat("Fiche prête : choisissez-la en mode « Références », champ « Personnage ».");
});

document.getElementById("fiche_supprimer").addEventListener("click", async () => {
  const id = document.getElementById("fiche_choix").value;
  const f = FICHES.find(x => x.id === id);
  if (!f || !confirm("Supprimer la fiche « " + f.nom + " » et ses images ?")) return;
  const r = await fetch("/video-h3/fiches/" + id, {method: "DELETE", headers: H});
  if (!r.ok){ ficheEtat("Suppression refusée.", true); return; }
  ficheEtat("Fiche supprimée.");
  await chargerFiches("");
});

// Monter un scénario (PLAN 18.9) : des clips déjà faits, recollés dans l'ordre choisi.
let CLIPS = [], COCHES = new Set();

function quandLocal(ts){
  // L'heure du navigateur : le conteneur du Studio tourne en UTC.
  if (!ts) return "";
  const d = new Date(ts * 1000), p = n => String(n).padStart(2, "0");
  return dateFr(d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate())
    + " " + p(d.getHours()) + ":" + p(d.getMinutes()));
}

function montageEtat(t, refus){
  const e = document.getElementById("montage_etat");
  e.className = refus ? "refus" : "note";
  e.textContent = t || "";
}

async function chargerClips(){
  const r = await fetch("/video-h3/clips", {headers: H});
  if (!r.ok) return;
  const d = await r.json();
  const avant = CLIPS.map(c => c.id);
  // L'ordre déjà rangé est gardé ; les clips neufs arrivent en tête.
  CLIPS = d.clips.filter(c => !avant.includes(c.id))
    .concat(avant.map(id => d.clips.find(c => c.id === id)).filter(Boolean));
  COCHES = new Set([...COCHES].filter(id => CLIPS.some(c => c.id === id)));
  dessinerClips();
  for (const [idSel, vide] of [["scenario_chanson", "Aucune (musique décrite au clip)"], ["musique_chanson", ""]]){
    const sc = document.getElementById(idSel);
    const gardeSc = sc.value;
    sc.innerHTML = vide ? '<option value="">' + vide + '</option>' : "";
    for (const c of (d.chansons || [])){
      const o = document.createElement("option");
      o.value = c.id;
      o.textContent = c.titre + " (" + quandLocal(c.cree_a) + ")";
      sc.appendChild(o);
    }
    if ((d.chansons || []).some(c => c.id === gardeSc)) sc.value = gardeSc;
  }
  const mf = document.getElementById("musique_film");
  const gardeMf = mf.value;
  mf.innerHTML = "";
  for (const c of CLIPS){
    const o = document.createElement("option");
    o.value = c.id;
    o.textContent = quandLocal(c.cree_a) + " · " + fr(c.secondes || 0, 1) + " s · " + (c.invite || "").slice(0, 60);
    mf.appendChild(o);
  }
  if (CLIPS.some(c => c.id === gardeMf)) mf.value = gardeMf;
}

document.getElementById("musique_poser").addEventListener("click", async () => {
  const e = document.getElementById("musique_etat");
  e.className = "note";
  e.textContent = "Pose de la musique…";
  const r = await fetch("/video-h3/musique", {method: "POST", headers: H, body: JSON.stringify({
    film: document.getElementById("musique_film").value, chanson: document.getElementById("musique_chanson").value,
    debut_s: Number(document.getElementById("musique_debut").value) || 0,
    volume: Number(document.getElementById("musique_volume").value) || 0.3})});
  const j = await r.json();
  if (!r.ok){ e.className = "refus"; e.textContent = typeof j.detail === "string" ? j.detail : "Refusé."; return; }
  e.textContent = "Musique posée : le film est ci-dessus.";
  const lien = await fetch("/video/jobs/" + j.id, {headers: H}).then(x => x.json());
  document.getElementById("montage_resultat").hidden = false;
  document.getElementById("montage_lecteur").src = lien.video_url;
  document.getElementById("montage_telecharger").href = lien.video_url + "&telecharger=1&nom=film-h3";
  chargerClips();
});

function dessinerClips(){
  const liste = document.getElementById("clips_liste");
  liste.innerHTML = "";
  if (!CLIPS.length){ liste.textContent = "Aucun clip H3 réussi sur ce Studio pour l'instant."; return; }
  CLIPS.forEach((c, i) => {
    const ligne = document.createElement("div");
    ligne.className = "clip";
    const coche = document.createElement("input");
    coche.type = "checkbox";
    coche.checked = COCHES.has(c.id);
    coche.addEventListener("change", () => { coche.checked ? COCHES.add(c.id) : COCHES.delete(c.id); });
    const vid = document.createElement("video");
    vid.src = c.video_url;
    vid.controls = true;
    vid.preload = "metadata";
    const texte = document.createElement("div");
    texte.className = "note";
    texte.textContent = quandLocal(c.cree_a) + " ; "
      + fr(c.secondes, 1) + " s" + (c.fiche ? " ; " + c.fiche : "") + " — " + c.invite.slice(0, 220);
    const outils = document.createElement("div");
    outils.appendChild(coche);
    outils.appendChild(bouton("↑", () => deplacer(i, -1)));
    outils.appendChild(bouton("↓", () => deplacer(i, 1)));
    ligne.append(outils, vid, texte);
    liste.appendChild(ligne);
  });
}

function deplacer(i, pas){
  const j = i + pas;
  if (j < 0 || j >= CLIPS.length) return;
  [CLIPS[i], CLIPS[j]] = [CLIPS[j], CLIPS[i]];
  dessinerClips();
}

function cochesDansLOrdre(){
  return CLIPS.filter(c => COCHES.has(c.id)).map(c => c.id);
}

document.getElementById("scenario_ordonner").addEventListener("click", async () => {
  montageEtat("Le chat du Studio range les clips…");
  const r = await fetch("/video-h3/scenario/ordonner", {method: "POST", headers: H, body: JSON.stringify({
    scenario: document.getElementById("scenario").value, clips: cochesDansLOrdre()})});
  const d = await r.json();
  if (!r.ok){ montageEtat(typeof d.detail === "string" ? d.detail : "Refusé.", true); return; }
  const laisses = cochesDansLOrdre().filter(id => !d.ordre.includes(id)).length;
  CLIPS = d.ordre.map(id => CLIPS.find(c => c.id === id)).concat(CLIPS.filter(c => !d.ordre.includes(c.id)));
  COCHES = new Set(d.ordre);
  dessinerClips();
  montageEtat("Rangés selon le scénario" + (laisses ? " ; " + laisses + " clip(s) laissé(s) de côté par le chat." : ".")
    + " Vérifiez, puis assemblez.");
});

document.getElementById("montage_lancer").addEventListener("click", async () => {
  montageEtat("Assemblage…");
  document.getElementById("montage_resultat").hidden = true;
  const r = await fetch("/video-h3/montage", {method: "POST", headers: H, body: JSON.stringify({
    scenario: document.getElementById("scenario").value, clips: cochesDansLOrdre()})});
  const d = await r.json();
  if (!r.ok){ montageEtat(typeof d.detail === "string" ? d.detail : "Refusé.", true); return; }
  const j = await (await fetch("/video/jobs/" + d.id, {headers: H})).json();
  montageEtat("Film assemblé : " + d.video.plans + " clips, " + fr(d.video.secondes, 1) + " s.");
  document.getElementById("montage_resultat").hidden = false;
  document.getElementById("montage_lecteur").src = j.video_url;
  document.getElementById("montage_telecharger").href = j.video_url + "&telecharger=1&nom=film-h3";
  chargerClips();
});

// Tourner un scénario neuf : le chat découpe, le propriétaire relit, le Studio tourne.
let PLANS = [], ENCHAINEMENTS = __ENCHAINEMENTS__, SCENARIO = null;
// Un scénario déjà tourné, repris : ses plans initiaux (pour le gras) et les plans à retourner.
let PLANS_INITIAUX = null, SCENARIO_TOURNE = null, RETOURNER = new Set();

// Les mots du plan, en gras ce qui n'était pas dans le plan initial, barré ce qui en a été retiré.
function diffGras(avant, apres){
  const a = (avant || "").split(/\s+/).filter(Boolean), b = (apres || "").split(/\s+/).filter(Boolean);
  const L = Array.from({length: a.length + 1}, () => new Array(b.length + 1).fill(0));
  for (let i = a.length - 1; i >= 0; i--)
    for (let j = b.length - 1; j >= 0; j--)
      L[i][j] = a[i] === b[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
  const bloc = document.createElement("p");
  bloc.className = "note";
  const mot = (t, balise) => { const e = document.createElement(balise); e.textContent = t; bloc.append(e, " "); };
  let i = 0, j = 0;
  while (i < a.length || j < b.length){
    if (i < a.length && j < b.length && a[i] === b[j]){ mot(b[j], "span"); i++; j++; }
    else if (i < a.length && (j >= b.length || L[i + 1][j] >= L[i][j + 1])){ mot(a[i], "s"); i++; }
    else { mot(b[j], "b"); j++; }
  }
  return bloc;
}

function scenarioEtat(t, refus){
  const e = document.getElementById("scenario_etat");
  e.className = refus ? "refus" : "note";
  e.textContent = t || "";
}

function dessinerPlans(){
  const liste = document.getElementById("plans_liste");
  liste.innerHTML = "";
  PLANS.forEach((p, i) => {
    const bloc = document.createElement("div");
    bloc.className = "image_bord";
    const t = document.createElement("b");
    t.textContent = "Plan " + (i + 1);
    const vue = document.createElement("textarea");
    vue.value = p.image_paroles;
    const son = document.createElement("input");
    son.type = "text";
    son.value = p.ambiance;
    son.placeholder = "Ambiance sonore";
    const ecart = document.createElement("div");
    const init = PLANS_INITIAUX && PLANS_INITIAUX[i];
    const majEcart = () => {
      ecart.innerHTML = "";
      if (init) ecart.append(diffGras(init.image_paroles, p.image_paroles), diffGras(init.ambiance, p.ambiance));
    };
    majEcart();
    vue.addEventListener("input", () => { p.image_paroles = vue.value; majEcart(); });
    son.addEventListener("input", () => { p.ambiance = son.value; majEcart(); });
    const ench = document.createElement("select");
    for (const [cle, titre] of Object.entries(ENCHAINEMENTS)){
      const o = document.createElement("option");
      o.value = cle;
      o.textContent = titre;
      ench.appendChild(o);
    }
    ench.value = p.enchainement;
    ench.disabled = i === 0;
    ench.addEventListener("change", () => { p.enchainement = ench.value; });
    bloc.append(t, vue, son, ecart, ench, bouton("Retirer ce plan", () => { PLANS.splice(i, 1); dessinerPlans(); }));
    if (SCENARIO_TOURNE){
      const coche = document.createElement("input");
      coche.type = "checkbox";
      coche.checked = RETOURNER.has(i + 1);
      coche.addEventListener("change", () => { coche.checked ? RETOURNER.add(i + 1) : RETOURNER.delete(i + 1); });
      const etiquette = document.createElement("label");
      etiquette.append(coche, " Retourner ce plan même inchangé");
      bloc.appendChild(etiquette);
    }
    liste.appendChild(bloc);
  });
  const max = ETAT ? ETAT.prolonger.plans_max : 4;
  document.getElementById("plan_ajouter").hidden = !PLANS.length || PLANS.length >= max;
  // Un scénario repris se rejoue (plans changés seulement), il ne se retourne pas en entier.
  document.getElementById("scenario_tourner").hidden = !PLANS.length || !!SCENARIO_TOURNE;
  const opt = document.getElementById("longueur").selectedOptions[0];
  const prix = opt && ETAT ? (ETAT.durees.find(x => String(x.images) === opt.value) || {}).prix_estime_usd : null;
  document.getElementById("scenario_prix").textContent = PLANS.length
    ? PLANS.length + " plan(s) à tourner" + (prix ? ", environ " + fr(prix * PLANS.length, 2) + " $ en tout." : ".")
    : "";
}

document.getElementById("scenario_decouper").addEventListener("click", async () => {
  scenarioEtat("Le chat du Studio découpe le scénario…");
  const r = await fetch("/video-h3/scenario/decouper", {method: "POST", headers: H,
    body: JSON.stringify({scenario: document.getElementById("scenario").value})});
  const d = await r.json();
  if (!r.ok){ scenarioEtat(typeof d.detail === "string" ? d.detail : "Refusé.", true); return; }
  PLANS = d.plans;
  PLANS_INITIAUX = null;
  SCENARIO_TOURNE = null;
  document.getElementById("scenario_suite").hidden = true;
  dessinerPlans();
  if (d.continuite && d.continuite.ok === false)
    scenarioEtat("Continuité à revoir avant de tourner : " + texteContinuite(d.continuite), true);
  else scenarioEtat("Relisez et corrigez les plans, puis tournez.");
});

function texteContinuite(c){
  return c.problemes.map(p => "plan " + p.plan + ", " + p.quoi).join(" ; ");
}

async function chargerScenarios(){
  const r = await fetch("/video-h3/scenarios", {headers: H});
  if (!r.ok) return;
  const sel = document.getElementById("scenario_choix");
  const garde = sel.value;
  sel.innerHTML = '<option value="">Choisissez un scénario…</option>';
  for (const s of (await r.json()).scenarios.filter(x => x.etat === "réussi")){
    const o = document.createElement("option");
    o.value = s.id;
    o.textContent = quandLocal(s.cree_a) + " · " + s.plans + " plans · " + s.debut;
    sel.appendChild(o);
  }
  sel.value = garde;
}

let DEFAUTS = [];

function dessinerJugement(jugement){
  const zone = document.getElementById("jugement");
  zone.innerHTML = "";
  DEFAUTS = [];
  for (const j of jugement || []){
    if (!j.defauts.length){
      const p = document.createElement("p");
      p.className = "note";
      p.textContent = "Plan " + j.plan + " : " + (j.verdict === "ok" ? "rien à signaler." : "défaut signalé sans image précise.");
      zone.appendChild(p);
      continue;
    }
    for (const x of j.defauts){
      const d = {plan: j.plan, t_s: x.t_s, quoi: x.quoi, garde: true};
      DEFAUTS.push(d);
      const label = document.createElement("label");
      label.className = "refus";
      const c = document.createElement("input");
      c.type = "checkbox";
      c.checked = true;
      c.addEventListener("change", () => { d.garde = c.checked; });
      label.append(c, " Plan " + j.plan + ", à " + fr(x.t_s, 1) + " s : " + x.quoi);
      zone.appendChild(label);
      zone.appendChild(document.createElement("br"));
    }
  }
}

async function ouvrirScenario(sid){
  const sc = await fetch("/video-h3/scenario/" + sid, {headers: H}).then(r => r.json());
  if (sc.etat !== "réussi") return;
  SCENARIO_TOURNE = sid;
  PLANS = sc.plans.map(p => Object.assign({}, p));
  PLANS_INITIAUX = sc.plans_initiaux || sc.plans;
  RETOURNER = new Set();
  document.getElementById("scenario_suite").hidden = false;
  document.getElementById("scenario_choix").value = sid;
  dessinerJugement(sc.jugement);
  dessinerPlans();
  document.getElementById("scenario_tourner").hidden = true;
  if (sc.video_url){
    document.getElementById("montage_resultat").hidden = false;
    document.getElementById("montage_lecteur").src = sc.video_url;
    document.getElementById("montage_telecharger").href = sc.video_url + "&telecharger=1&nom=film-h3";
  }
}

document.getElementById("scenario_choix").addEventListener("change", e => {
  if (e.target.value) ouvrirScenario(e.target.value);
});

// Pendant qu'une action tourne : un bandeau avec chronomètre, et les commandes
// verrouillées. Le 28/09, sans ce signe, un second clic a payé deux fois le même plan.
let CHRONO = null;
const LIBRES_PENDANT = new Set(["scenario_arreter", "scenario_auto_payer", "scenario_auto_arreter"]);

function verrouiller(oui){
  for (const e of document.querySelectorAll("#montage_bloc button, #montage_bloc select"))
    if (!LIBRES_PENDANT.has(e.id)) e.disabled = oui;
}

function occupe(texte){
  const b = document.getElementById("scenario_occupe");
  document.getElementById("scenario_occupe_texte").textContent = texte;
  scenarioEtat("");
  if (!b.hidden) return;
  b.hidden = false;
  const debut = Date.now();
  const maj = () => {
    const s = Math.round((Date.now() - debut) / 1000);
    document.getElementById("scenario_chrono").textContent = "· " + Math.floor(s / 60) + " min "
      + String(s % 60).padStart(2, "0") + " s";
  };
  maj();
  CHRONO = setInterval(maj, 1000);
  verrouiller(true);
}

function libre(){
  document.getElementById("scenario_occupe").hidden = true;
  document.getElementById("scenario_arreter").hidden = true;
  clearInterval(CHRONO);
  verrouiller(false);
}

async function actionJuger(){
  occupe("Le juge regarde chaque plan (gratuit)…");
  const j = await appeler("/video-h3/scenario/" + SCENARIO_TOURNE + "/juger");
  dessinerJugement(j.jugement);
  scenarioEtat("Jugement reçu : décochez les fausses alertes, puis corrigez le texte ou rejouez.");
}

async function actionCorriger(){
  occupe("Correction du texte et contrôle de continuité (gratuit)…");
  const d = await appeler("/video-h3/scenario/" + SCENARIO_TOURNE + "/corriger",
    {retours: document.getElementById("retours").value, defauts: DEFAUTS.filter(x => x.garde)});
  PLANS = d.plans;
  dessinerPlans();
  if (d.continuite && d.continuite.ok === false)
    scenarioEtat("Texte corrigé, mais la continuité est à revoir : " + texteContinuite(d.continuite), true);
  else scenarioEtat("Texte corrigé : les changements sont en gras. Relisez, puis choisissez « Rejouer ».");
}

async function actionRejouer(){
  occupe("Contrôle et traduction des plans à retourner…");
  const r = await appeler("/video-h3/scenario/" + SCENARIO_TOURNE + "/rejouer", {plans: PLANS, retourner: [...RETOURNER]});
  const sc = await attendreScenario(r.id);
  if (sc.etat !== "réussi") return scenarioEtat("Rejeu " + sc.etat + (sc.erreur ? " : " + sc.erreur : "."), true);
  chargerClips();
  await chargerScenarios();
  await ouvrirScenario(r.id);
  scenarioEtat("Rejeu fini : " + (r.repris.length ? "plan(s) " + r.repris.join(", ") + " repris tels quels." : "tout a été retourné."));
}

const ACTIONS = {
  auto: ["Lancer", () => corrigerToutSeul(SCENARIO_TOURNE, Number(document.getElementById("auto_tours").value),
                                          document.getElementById("auto_sans_arret").checked)],
  juger: ["Faire juger", actionJuger],
  corriger: ["Corriger le texte", actionCorriger],
  rejouer: ["Rejouer (payant)", actionRejouer],
};

function majSuite(){
  const a = document.getElementById("suite_action").value;
  document.getElementById("suite_auto_options").hidden = a !== "auto";
  document.getElementById("suite_corriger_options").hidden = a !== "corriger";
  document.getElementById("suite_lancer").textContent = ACTIONS[a][0];
}
document.getElementById("suite_action").addEventListener("change", majSuite);
majSuite();

document.getElementById("suite_lancer").addEventListener("click", async () => {
  if (!SCENARIO_TOURNE) return;
  try {
    await ACTIONS[document.getElementById("suite_action").value][1]();
  } catch (e) {
    scenarioEtat(e.message, true);
  } finally {
    document.getElementById("suite_pause").hidden = true;
    libre();
  }
});

async function appeler(chemin, corps){
  const r = await fetch(chemin, {method: "POST", headers: H, body: JSON.stringify(corps || {})});
  const d = await r.json();
  if (!r.ok) throw new Error(typeof d.detail === "string" ? d.detail : "Refusé.");
  return d;
}

async function attendreScenario(sid){
  SCENARIO = sid;
  document.getElementById("scenario_arreter").hidden = false;
  occupe("Tournage lancé (payant)…");
  for (;;){
    await new Promise(ok => setTimeout(ok, 10000));
    const sc = await fetch("/video-h3/scenario/" + sid, {headers: H}).then(r => r.json());
    if (sc.etat !== "en cours"){
      document.getElementById("scenario_arreter").hidden = true;
      return sc;
    }
    const faits = (sc.statuts || []).filter(s => s.status === "succeeded").length;
    const repris = (sc.repris || []).length;
    occupe("Tournage (payant) : " + faits + " plan(s) tourné(s) sur " + (sc.plans.length - repris)
      + (repris ? ", " + repris + " repris tel(s) quel(s)" : "") + "…");
  }
}

// L'accord du propriétaire avant de payer : une promesse que tient l'un des deux boutons.
function attendreAccord(){
  const pause = document.getElementById("suite_pause");
  const payer = document.getElementById("scenario_auto_payer"), arreter = document.getElementById("scenario_auto_arreter");
  pause.hidden = false;
  occupe("En pause : à vous de décider");
  return new Promise(ok => {
    const fin = oui => { pause.hidden = true; payer.onclick = arreter.onclick = null; ok(oui); };
    payer.onclick = () => fin(true);
    arreter.onclick = () => fin(false);
  });
}

async function corrigerTexte(sid, defauts){
  const c = await appeler("/video-h3/scenario/" + sid + "/corriger", {retours: "", defauts: defauts});
  PLANS = c.plans;
  dessinerPlans();
  return c.continuite && c.continuite.ok === false ? texteContinuite(c.continuite) : "";
}

// La boucle du propriétaire (28/09) : juger, corriger le texte des plans
// fautifs, ne rejouer qu'eux, recoller, rejuger ; au plus N tours. Le juge se
// trompe parfois (28/09 : au plan 1, plusieurs défauts qui n'y étaient pas) : sauf
// « sans arrêt », pause avant de payer, pour décocher les fausses alertes.
async function corrigerToutSeul(sid, tours, sansArret){
  for (let tour = 1; ; tour++){
    occupe("Tour " + tour + " : le juge regarde chaque plan (gratuit)…");
    const j = await appeler("/video-h3/scenario/" + sid + "/juger");
    dessinerJugement(j.jugement);
    const fautifs = j.jugement.filter(x => x.defauts.length);
    if (!fautifs.length) return scenarioEtat("Tout seul : aucun défaut vu après " + (tour - 1) + " rejeu(x). Film prêt.");
    if (tour > tours) return scenarioEtat("Tout seul : " + tours + " tour(s) faits, défauts restants aux plans "
      + fautifs.map(x => x.plan).join(", ") + ". À vous de voir.", true);
    occupe("Tour " + tour + " : correction du texte des plans " + fautifs.map(x => x.plan).join(", ") + " (gratuit)…");
    const corriges = JSON.stringify(DEFAUTS);
    let casse = await corrigerTexte(sid, DEFAUTS);
    // Rien n'est payé sur un texte qui ne se tient plus : la main revient au propriétaire.
    if (casse) return scenarioEtat("Tout seul, arrêté avant de rejouer : la correction casse la continuité ("
      + casse + "). Relisez les plans en gras.", true);
    if (!sansArret){
      if (!await attendreAccord()) return scenarioEtat("Tout seul : arrêté par vous, rien n'a été rejoué à ce tour.");
    }
    const gardes = DEFAUTS.filter(d => d.garde);
    if (!gardes.length) return scenarioEtat("Tout seul : aucun défaut gardé, rien à rejouer. Film prêt.");
    // Des fausses alertes décochées : le texte est refait sans elles (gratuit), avant de payer.
    if (JSON.stringify(gardes) !== corriges){
      occupe("Correction refaite avec les seuls défauts gardés (gratuit)…");
      casse = await corrigerTexte(sid, gardes);
      if (casse) return scenarioEtat("Tout seul, arrêté avant de rejouer : la correction casse la continuité ("
        + casse + "). Relisez les plans en gras.", true);
    }
    const retourner = [...new Set(gardes.map(d => d.plan))];
    const r = await appeler("/video-h3/scenario/" + sid + "/rejouer", {plans: PLANS, retourner: retourner});
    const sc = await attendreScenario(r.id);
    if (sc.etat !== "réussi") return scenarioEtat("Tout seul : rejeu " + sc.etat + (sc.erreur ? " : " + sc.erreur : "."), true);
    sid = r.id;
    chargerClips();
    await chargerScenarios();
    await ouvrirScenario(sid);
  }
}

document.getElementById("plan_ajouter").addEventListener("click", () => {
  PLANS.push({image_paroles: "", ambiance: "", enchainement: "suite"});
  dessinerPlans();
});

async function suivreScenario(sid){
  const sc = await attendreScenario(sid);
  chargerClips();
  rafraichir();
  if (sc.etat !== "réussi") return scenarioEtat("Scénario " + sc.etat + (sc.erreur ? " : " + sc.erreur : "."), true);
  await chargerScenarios();
  await ouvrirScenario(sid);
  scenarioEtat("Scénario tourné : " + sc.plans.length + " plans recollés.");
}

document.getElementById("scenario_tourner").addEventListener("click", async () => {
  try {
    await tournerScenario();
  } catch (e) {
    scenarioEtat(e.message, true);
  } finally {
    libre();
  }
});

async function tournerScenario(){
  const graine = document.getElementById("graine").value;
  occupe("Contrôle et traduction des plans (gratuit)…");
  const f1 = document.getElementById("scenario_fiche").value, f2 = document.getElementById("scenario_fiche2").value;
  const l1 = document.getElementById("scenario_langue1").value, l2 = document.getElementById("scenario_langue2").value;
  const deux = f1 && f2 && f1 !== f2;
  const r = await fetch("/video-h3/scenario/tourner", {method: "POST", headers: H, body: JSON.stringify({
    plans: PLANS, fiche: deux ? null : (f1 || null), fiches: deux ? [f1, f2] : null,
    langues: deux ? {[f1]: l1, [f2]: l2} : null,
    musique_chanson: document.getElementById("scenario_chanson").value || null,
    musique_a_partir_du_plan: Number(document.getElementById("scenario_musique_plan").value) || 1,
    langue: f1 ? l1 : document.getElementById("langue").value,
    musique: document.getElementById("musique").value,
    longueur: Number(document.getElementById("longueur").value),
    definition: document.getElementById("definition").value,
    graine: graine === "" ? null : Number(graine)})});
  const d = await r.json();
  if (!r.ok) throw new Error(typeof d.detail === "string" ? d.detail : "Refusé.");
  await suivreScenario(d.id);
}

document.getElementById("scenario_arreter").addEventListener("click", async () => {
  if (!SCENARIO) return;
  await fetch("/video-h3/scenario/" + SCENARIO + "/arreter", {method: "POST", headers: H, body: "{}"});
  scenarioEtat("Arrêt demandé : aucun plan de plus.");
});

brancherBord("premiere");
brancherBord("derniere");
document.getElementById("image_paroles").addEventListener("input", majInvitesImages);
rafraichir().then(majInvitesImages).then(() => chargerFiches("")).then(chargerClips).then(chargerScenarios);
</script>
</body>
</html>
""".replace("__LANGUES__", "".join(
    f'<option value="{code}"{" selected" if code == LANGUE_PAROLES else ""}>{nom}</option>'
    for code, nom in LANGUES_PAROLES.items())).replace("__ENCHAINEMENTS__", json.dumps(ENCHAINEMENTS,
                                                                                      ensure_ascii=False))
