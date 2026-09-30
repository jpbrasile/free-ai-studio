"""Refaire les visages petits d'un clip H3 : ComfyUI-H3-FaceRefine (Carasibana, MIT).

Question du propriétaire, 30/09/2026 : « pour améliorer la qualité des visages en
champ lointain en basse résolution aucune astuce sur le web ? », puis « oui code la
route visages ». H3 rend mal un visage qui occupe peu de l'image ; un agrandisseur
(SeedVR2, agrandir.py) affine ce qui est là, il ne refait pas un visage. FaceRefine
détecte le visage à chaque image, recadre pour qu'il remplisse l'image, fait
regénérer ce recadrage par H3 à faible débruitage, puis le recolle.

Choix du Studio, sur l'étude du 30/09 (lecture seule du dépôt au tag v1.1.2) :
- un personnage par passe (dit par le nœud) ; deux au plus, la passe 2 part du
  résultat de la passe 1 ;
- l'identité vient des photos de la FICHE, données en références à H3 ; ni
  InsightFace (poids « non-commercial research only ») ni son suivi d'identité :
  le personnage est choisi par sa place dans l'image (le plus à gauche, …) ;
- sans MiniMaxH3NativeAudioLock (dépôt sans licence publiée) : le son régénéré est
  jeté, le son d'origine est reposé ;
- le détecteur `face_yolov8m.pt` (Bingsu/adetailer, révision épinglée) et
  ultralytics (AGPL-3.0) vivent dans la machine louée, jamais importés ici : le
  même schéma que ComfyUI (GPL). Une version hébergée ou vendue demanderait une
  licence Ultralytics ou un autre détecteur.

Temps et prix : le dépôt n'en publie aucun ; ceux ci-dessous viennent du premier
essai par le Studio, le 30/09/2026.
"""
import base64

import budget_modal
import video_h3

FR_DEPOT = "https://github.com/Carasibana/ComfyUI-H3-FaceRefine"
FR_COMMIT = "d8521d14fe0d721d80cd9417fff5a559cbc21aba"   # tag v1.1.2, lu le 30/09/2026
FR_DOSSIER = video_h3.DOSSIER_COMFY + "/custom_nodes/h3_face_refine"
# ultralytics seul : scipy vient avec ComfyUI ; scenedetect (coupes) et insightface
# (identité) ne sont importés que si on les demande, et on ne les demande pas.
COMMANDES = video_h3.COMMANDES + (
    f"git clone {FR_DEPOT} {FR_DOSSIER}",
    f"cd {FR_DOSSIER} && git checkout {FR_COMMIT}",
    "pip install ultralytics==8.4.166",
)
DETECTEUR = "face_yolov8m.pt"
DETECTEUR_DEPOT = "Bingsu/adetailer"
DETECTEUR_REVISION = "53cc19de382014514d9d4038601d261a7faa9b7b"   # relevée le 30/09/2026
DETECTEUR_OCTETS = 52026019
DOSSIER_DETECTEUR = video_h3.POINT_DE_MONTAGE + "/facerefine"
PAQUETS = ("huggingface_hub==1.9.2",)

# La machine d'un clip H3 : mêmes poids, même carte.
GPU, MEMOIRE_MB, COEURS = video_h3.GPU, video_h3.MEMOIRE_MB, video_h3.COEURS
DUREE_MAX_S = video_h3.DUREE_MAX_S
# Mesuré le 30/09/2026 (parc, plan 3, 123 images, 2 personnages de 32 px) : location
# 229 s, dont ComfyUI prêt en 30 s et calcul 78 s, soit 0,32 s par image et par passe ;
# pic 39,2 Go. Majoré : 150 s de démarrage (machine + ComfyUI), 0,4 s par image et passe.
DEMARRAGE_S = 150
S_PAR_IMAGE_ET_PASSE = 0.4
SUJETS_MAX = 2
PHOTOS_PAR_SUJET = 3
VIDEO_MAX_OCTETS = 60 * 1024 * 1024
# Valeurs des exemples du dépôt, sauf les pas : 4, ceux de notre LoRA Turbo.
DEBRUITAGE = 0.4
CHOIX = ("left_most", "right_most", "centre_most", "largest_face", "smallest_face")


def estimation_s(images: int, sujets: int) -> float:
    return DEMARRAGE_S + sujets * images * S_PAR_IMAGE_ET_PASSE


def delai_s(images: int, sujets: int) -> int:
    return min(DUREE_MAX_S, int(estimation_s(images, sujets) * 1.5) + 120)


def prix(images: int, sujets: int) -> dict:
    """Ce que la page affiche AVANT de payer ; ValueError si ce n'est pas faisable."""
    if images <= 0:
        raise ValueError("Vidéo vide.")
    if not 1 <= sujets <= SUJETS_MAX:
        raise ValueError("Un ou deux personnages par traitement.")
    estime = estimation_s(images, sujets)
    if estime > DUREE_MAX_S * 0.8:
        raise ValueError("Trop long en une fois (%d s de calcul estimées, %d au plus) : "
                         "traitez un plan à la fois." % (estime, int(DUREE_MAX_S * 0.8)))
    par_s = budget_modal.prix_seconde(GPU, MEMOIRE_MB, COEURS)
    return {"images": images, "sujets": sujets, "secondes_estimees": round(estime),
            "estime_usd": round(par_s * estime, 2), "pire_usd": round(par_s * delai_s(images, sujets), 2),
            "delai_s": delai_s(images, sujets), "mesure": True}


def invite(nb_photos: int) -> str:
    """Un sujet, ses photos, un gros plan : le recadrage ne montre que son visage."""
    return (video_h3.sujets_des_fiches([nb_photos]) + " detailed_description: A close-up of the face of "
            "<Subject 1>, who moves exactly as in the source frames. non_diegetic_music: N/A")


def graphe(sujets: list, prefixe: str = "visages/v") -> dict:
    """`sujets` : [(choix, nombre de photos)], dans l'ordre des passes. Format API."""
    nom = lambda chemin: chemin.split("/")[1]  # noqa: E731
    g = {
        "1": _n("LoadVideo", {"file": "source.mp4"}),
        "2": _n("GetVideoComponents", {"video": ["1", 0]}),
        "3": _n("UNETLoader", {"unet_name": nom(video_h3.FICHIERS[0]), "weight_dtype": "default"}),
        "4": _n("LoraLoaderModelOnly", {"model": ["3", 0], "lora_name": nom(video_h3.FICHIERS[4]),
                                         "strength_model": 1.0}),
        "5": _n("CLIPLoader", {"clip_name": nom(video_h3.FICHIERS[1]), "type": "minimax"}),
        "6": _n("VAELoader", {"vae_name": nom(video_h3.FICHIERS[2])}),
        "7": _n("VAELoader", {"vae_name": nom(video_h3.FICHIERS[3])}),
        "8": _n("KSamplerSelect", {"sampler_name": "res_multistep"}),
        "9": _n("RandomNoise", {"noise_seed": 42}),
    }
    images, photo = ["2", 0], 0
    for p, (choix, nb) in enumerate(sujets):
        b = 100 * (p + 1)
        k = lambda i: str(b + i)  # noqa: E731
        g[k(1)] = _n("H3FaceTrackCrop", {
            "images": images, "detector": DETECTEUR, "confidence": 0.35, "crop_factor": 3.0,
            "canvas_width": 768, "canvas_height": 768, "canvas_mode": "auto_capped_768",
            "smooth_window": 21, "size_smooth_window": 51, "smooth_method": "gaussian", "size_mode": "per_frame",
            "identity_track": False, "select": choix, "fallback_detector": "none", "cut_detection": "none",
            "absent_shots": "off"})
        entrees = {"clip": ["5", 0], "vae": ["6", 0], "audio_vae": ["7", 0], "prompt": invite(nb),
                   "ref_image_size": "match", "width": [k(1), 4], "height": [k(1), 5], "length": [k(1), 6]}
        for i in range(nb):
            g[k(10 + i)] = _n("LoadImage", {"image": "ref_%d.png" % (photo + i)})
            entrees["ref_images.ref_image_%d" % i] = [k(10 + i), 0]
        photo += nb
        g[k(2)] = _n("MiniMaxH3ReferenceToVideo", entrees)
        g[k(3)] = _n("H3InjectVideoLatent", {"av_latent": [k(2), 1], "images": [k(1), 0], "vae": ["6", 0]})
        g[k(4)] = _n("H3PerFrameDenoise", {
            "model": ["4", 0], "av_latent": [k(3), 0], "transform": [k(1), 1],
            "denoise_multiplier_small_face": 1.0, "denoise_multiplier_large_face": 0.35,
            "scale_mode": "absolute_px", "face_px_small": 30.0, "face_px_large": 120.0, "gamma": 1.0,
            "smooth_frames": 9})
        # Le modèle patché par PerFrameDenoise, sinon son effet est perdu sans message.
        g[k(5)] = _n("BasicGuider", {"model": [k(4), 2], "conditioning": [k(2), 0]})
        g[k(6)] = _n("BasicScheduler", {"model": [k(4), 2], "scheduler": "simple", "steps": 4,
                                         "denoise": DEBRUITAGE})
        g[k(7)] = _n("SamplerCustomAdvanced", {"noise": ["9", 0], "guider": [k(5), 0], "sampler": ["8", 0],
                                                "sigmas": [k(6), 0], "latent_image": [k(4), 0]})
        g[k(8)] = _n("VAEDecode", {"samples": [k(7), 0], "vae": ["6", 0]})
        g[k(9)] = _n("H3FaceStitch", {
            "base_images": images, "refined_crops": [k(8), 0], "transform": [k(1), 1],
            "paste_region": "face_only", "mask_dilation": 24, "feather": 24, "colour_match": 1.0,
            "blend": 1.0, "undetected_frames": "fade_out"})
        images = [k(9), 0]
    # Le son d'origine : celui que H3 régénère n'est tenu par rien (pas d'AudioLock).
    g["90"] = _n("CreateVideo", {"images": images, "fps": ["2", 2], "audio": ["2", 1]})
    g["91"] = _n("SaveVideo", {"video": ["90", 0], "filename_prefix": prefixe, "format": "auto",
                               "format.codec": "auto"})
    return g


def _n(classe: str, entrees: dict) -> dict:
    return {"class_type": classe, "inputs": entrees}


CLASSES = ("LoadVideo", "GetVideoComponents", "UNETLoader", "LoraLoaderModelOnly", "CLIPLoader", "VAELoader",
           "KSamplerSelect", "RandomNoise", "H3FaceTrackCrop", "LoadImage", "MiniMaxH3ReferenceToVideo",
           "H3InjectVideoLatent", "H3PerFrameDenoise", "BasicGuider", "BasicScheduler", "SamplerCustomAdvanced",
           "VAEDecode", "H3FaceStitch", "CreateVideo", "SaveVideo")


def photos(fid) -> list:
    """Les photos d'une fiche de personne (base64 nu), face d'abord, 3 au plus."""
    fiche = video_h3.fiche_lire(fid)
    if video_h3.fiche_est_objet(fiche):
        raise ValueError("« %s » est un objet : seuls les visages se refont." % fiche["nom"])
    images = video_h3.fiche_images(fid)[:PHOTOS_PAR_SUJET]
    if not images:
        raise ValueError("La fiche « %s » n'a pas de photo." % fiche["nom"])
    return images


def demande(video: bytes, sujets: list, de: int, a: int) -> dict:
    """`sujets` : [(fiche, choix)]. `de`, `a` : les images du clip à traiter [de, a)."""
    if len(video) > VIDEO_MAX_OCTETS:
        raise ValueError("Vidéo trop lourde pour être traitée ici.")
    if not 1 <= len(sujets) <= SUJETS_MAX:
        raise ValueError("Un ou deux personnages par traitement.")
    refs, passes = [], []
    for fid, choix in sujets:
        if choix not in CHOIX:
            raise ValueError("Place du personnage inconnue : %s." % choix)
        p = photos(fid)
        refs += p
        passes.append((choix, len(p)))
    return {"video": base64.b64encode(video).decode(), "de": int(de), "a": int(a),
            "images_par_seconde": video_h3.IMAGES_PAR_SECONDE,
            "images": {"ref_%d.png" % i: b for i, b in enumerate(refs)},
            "graphe": graphe(passes), "classes": list(CLASSES), "comfy": video_h3.DOSSIER_COMFY,
            "base_poids": video_h3.POINT_DE_MONTAGE, "fichiers": list(video_h3.FICHIERS),
            "detecteur": {"depot": DETECTEUR_DEPOT, "revision": DETECTEUR_REVISION, "nom": DETECTEUR,
                          "octets": DETECTEUR_OCTETS, "dossier": DOSSIER_DETECTEUR},
            # Le délai de la location : le script rend la main (DELAI) avant d'être coupé.
            "delai_s": delai_s(int(a) - int(de), len(sujets))}


def construire_script(video: bytes, sujets: list, de: int, a: int) -> str:
    return video_h3._emballer(_SCRIPT, demande(video, sujets, de, a))


def phrase_d_echec(stderr: str) -> str:
    s = stderr or ""
    for mot, phrase in (
            ("POIDS_ABSENTS", "Les poids de H3 ne sont pas sur le disque Modal : préparez d'abord H3."),
            ("DETECTEUR_ABSENT", "Le détecteur de visages n'a pas pu être posé sur le disque Modal."),
            ("NOEUD_ABSENT", "Ce ComfyUI n'a pas les nœuds de FaceRefine."),
            ("GRAPHE_REFUSE", "ComfyUI a refusé le graphe avant tout calcul. Le détail est dans le journal."),
            ("COMFY_ARRETE", "ComfyUI s'est arrêté pendant le calcul (mémoire ?). Le détail est dans le journal."),
            ("CALCUL_ECHOUE", "Les visages n'ont pas pu être refaits. Le détail est dans le journal."),
            ("MONTAGE_ECHOUE", "Le passage à traiter n'a pas pu être découpé."),
            ("DELAI", "Le traitement n'était pas fini avant le délai. Rien n'a été rendu.")):
        if mot in s:
            return phrase
    return ""


# --- Le script envoyé sur la machine louée -----------------------------------------

_SCRIPT = r'''
# Visages refaits du Free AI Studio : lance ComfyUI (GPL-3.0) avec FaceRefine (MIT) et
# ultralytics (AGPL-3.0), et lui envoie un graphe par HTTP. Rien n'en est importé ici.
import base64, json, os, shutil, subprocess, sys, time, urllib.error, urllib.request
from pathlib import Path

D = json.loads(base64.b64decode("__DEMANDE_B64__").decode())
OUT = Path(os.environ.get("FREE_AI_OUTPUT_DIR", "/tmp/free_ai_output"))
OUT.mkdir(parents=True, exist_ok=True)
BASE, COMFY, DET = Path(D["base_poids"]), Path(D["comfy"]), D["detecteur"]
t0, pic = time.time(), 0.0

manque = [f for f in D["fichiers"] if not (BASE / f).is_file()]
if manque:
    print("POIDS_ABSENTS " + ", ".join(manque), file=sys.stderr)
    sys.exit(3)
poids = Path(DET["dossier"]) / DET["nom"]
if not poids.is_file() or poids.stat().st_size != DET["octets"]:
    try:
        from huggingface_hub import hf_hub_download
        hf_hub_download(DET["depot"], DET["nom"], revision=DET["revision"], local_dir=DET["dossier"])
        subprocess.run(["sync"], check=False)
    except Exception as exc:
        print("DETECTEUR_ABSENT " + repr(exc)[:500], file=sys.stderr)
        sys.exit(3)
    if not poids.is_file() or poids.stat().st_size != DET["octets"]:
        print("DETECTEUR_ABSENT taille inattendue", file=sys.stderr)
        sys.exit(3)
bbox = COMFY / "models" / "ultralytics" / "bbox"
bbox.mkdir(parents=True, exist_ok=True)
shutil.copyfile(poids, bbox / DET["nom"])

Path("/tmp/chemins.yaml").write_text(
    "h3:\n  base_path: " + str(BASE) + "\n  diffusion_models: diffusion_models\n"
    "  text_encoders: text_encoders\n  vae: vae\n  loras: loras\n")
entree = COMFY / "input"
entree.mkdir(exist_ok=True)
for nom, b64 in D["images"].items():
    (entree / nom).write_bytes(base64.b64decode(b64))
film = Path("/tmp/film.mp4")
film.write_bytes(base64.b64decode(D["video"]))
ips, de, a = D["images_par_seconde"], D["de"], D["a"]
r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(film), "-vf",
                    "select='between(n\\,%d\\,%d)',setpts=N/FRAME_RATE/TB" % (de, a - 1),
                    "-af", "aselect='between(t\\,%.4f\\,%.4f)',asetpts=N/SR/TB" % (de / ips, a / ips),
                    "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    str(entree / "source.mp4")], capture_output=True, text=True)
if r.returncode:
    print("MONTAGE_ECHOUE " + r.stderr[-1500:], file=sys.stderr)
    sys.exit(9)

journal = open("/tmp/comfy.log", "w")
proc = subprocess.Popen(
    [sys.executable, "main.py", "--listen", "127.0.0.1", "--port", "8188", "--disable-pinned-memory",
     "--extra-model-paths-config", "/tmp/chemins.yaml", "--output-directory", "/tmp/sortie"],
    cwd=str(COMFY), stdout=journal, stderr=subprocess.STDOUT)
URL = "http://127.0.0.1:8188"


def lire(chemin):
    with urllib.request.urlopen(URL + chemin, timeout=30) as r:
        return json.loads(r.read())


def echouer(code, mot, detail=""):
    journal.flush()
    print(mot + " " + str(detail)[:3000], file=sys.stderr)
    print("--- journal ComfyUI ---\n" + Path("/tmp/comfy.log").read_text(errors="replace")[-6000:], file=sys.stderr)
    proc.kill()
    sys.exit(code)


def vram():
    try:
        return int(subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                                  capture_output=True, text=True, timeout=5).stdout.split()[0]) / 1024
    except Exception:
        return 0.0


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
absents = [x for x in D["classes"] if x not in info]
if absents:
    echouer(4, "NOEUD_ABSENT", absents)

corps = json.dumps({"prompt": D["graphe"], "client_id": "free-ai-studio"}).encode()
try:
    with urllib.request.urlopen(urllib.request.Request(URL + "/prompt", data=corps,
                                headers={"Content-Type": "application/json"}), timeout=60) as r:
        rep = json.loads(r.read())
except urllib.error.HTTPError as e:
    echouer(5, "GRAPHE_REFUSE", e.read().decode(errors="replace"))
if rep.get("node_errors") or "prompt_id" not in rep:
    echouer(5, "GRAPHE_REFUSE", json.dumps(rep))
pid, etat, limite = rep["prompt_id"], None, t0 + D["delai_s"] - 60
while time.time() < limite:
    h = lire("/history/" + pid)
    if pid in h:
        etat = h[pid]
        break
    if proc.poll() is not None:
        echouer(7, "COMFY_ARRETE", "pendant le calcul")
    pic = max(pic, vram())
    time.sleep(2)
if etat is None:
    echouer(8, "DELAI", "%d s" % D["delai_s"])
if etat.get("status", {}).get("status_str") != "success":
    echouer(6, "CALCUL_ECHOUE", json.dumps(etat.get("status", {}).get("messages", []))[-3000:])
calcul_s = round(time.time() - t_pret, 1)
journal.flush()
rapports = [l for l in Path("/tmp/comfy.log").read_text(errors="replace").splitlines() if "[H3FaceRefine]" in l]
proc.kill()
sortis = sorted(Path("/tmp/sortie/visages").glob("v*"))
if not sortis:
    echouer(6, "CALCUL_ECHOUE", "aucun fichier rendu")
shutil.copyfile(sortis[-1], OUT / "video.mp4")
resume = {"de": de, "a": a, "calcul_s": calcul_s, "demarrage_comfy_s": round(t_pret - t0, 1),
          "total_s": round(time.time() - t0, 1), "pic_vram_go": round(pic, 1), "rapports": rapports[-20:]}
(OUT / "resume.json").write_text(json.dumps(resume, ensure_ascii=False))
print("VISAGES " + json.dumps(resume, ensure_ascii=False), flush=True)
'''
