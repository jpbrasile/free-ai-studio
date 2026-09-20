"""Chansons chantees a partir de paroles, sur un GPU loue ou gratuit.

Un seul modele : YuE2-3B (m-a-p, Multimodal Art Projection), 3,6 milliards de
parametres, qui compose une partition puis la chante, voix et instruments, en
48 kHz stereo. Ses poids sont sous licence CC BY-NC 4.0 : usage non commercial.
La page le dit a l'endroit ou l'on choisit, pas dans une note en bas de page.

Deux endroits ou le faire tourner :
- Modal, carte L4 louee a la seconde : le pipeline officiel, tel quel. Il a son
  propre compteur et son propre plafond, et refuse AVANT de lancer.
- Kaggle, T4 gratuit : le pipeline officiel refuse cette carte (pas de bfloat16).
  Le script applique alors les correctifs d'un carnet Kaggle public (voir plus
  bas). Coupe des que le Studio sert d'autres personnes, comme partout ailleurs.

Colab a ete retire du choix le 16/09/2026, POUR LA CHANSON SEULEMENT : essaye en
reel, la session gratuite meurt faute de memoire vive (~12,7 Go, et une seule
carte, quand Kaggle en donne deux et ~30 Go). Le carnet Colab du bac a sable,
lui, reste en service : c'est une autre fonction, et elle sert. La route
/chanson/colab et carnet_colab() restent cote serveur, sans entree dans la page.

Un seul script part sur la machine distante, quel que soit l'endroit : il choisit
son chemin d'apres la carte qu'il trouve.
"""

from __future__ import annotations

import base64
import json
import os
import re
import secrets

import budget_modal

# Le compteur des depenses Modal est commun aux quatre usages -- la video, la
# chanson, le dialogue et le bac a sable lui-meme. Il tient le fichier, le
# verrou, la table des prix et le plafond ; ce module n'en garde que des
# renvois. CONFIG_DIR a disparu d'ici avec le fichier qu'il servait a nommer.
BUDGET_FICHIER = budget_modal.FICHIER

# TABLE UNIQUE depuis le 19/09/2026 : les prix Modal vivent dans
# budget_modal.py et ce module les LIT au lieu d'en garder une copie. Les noms
# sont conserves parce que les tests et les pages les citent ; ce ne sont plus
# que des renvois.
#
# Ce que la copie coutait, et qu'aucun test ne voyait : video.py portait les
# HUIT cartes, chanson.py et dialogue.py n'en portaient que QUATRE. Le test qui
# gardait ce flanc ne comparait que les cartes COMMUNES, donc il passait au
# vert -- pendant que prix_seconde() facturait une A100 au tarif L40S et une
# H100 a la MOITIE de son prix, parce qu'une carte inconnue retombe sur la plus
# chere CONNUE. Une table tronquee rend ce repli menteur.
PRIX_RELEVE_LE = budget_modal.PRIX_RELEVE_LE
PRIX_GPU_USD_S = budget_modal.PRIX_GPU_USD_S
PRIX_CPU_USD_S = budget_modal.PRIX_CPU_USD_S
PRIX_MEMOIRE_USD_S = budget_modal.PRIX_MEMOIRE_USD_S

# Ce que les DEMANDES peuvent atteindre : le plafond unique moins la part
# reservee au bac a sable. CHANSON_BUDGET_USD_PAR_MOIS n'est plus lu. Le
# commentaire qui etait ici disait << aucun des deux compteurs ne voit
# l'autre >> : c'est exactement ce qui est referme. Voir budget_modal.py.
BUDGET_MENSUEL_USD = budget_modal.plafond_de("chanson")
CREDIT_OFFERT_USD = budget_modal.CREDIT_OFFERT_USD

# Garde-fou dur sur Modal : au-dela, la machine est arretee et le compteur
# encaisse ce qui a ete consomme. Le premier lancement telecharge environ 7 Go.
DUREE_MAX_S = int(os.getenv("CHANSON_TIMEOUT_SECONDS", "1800"))
GPU_MODAL = os.getenv("CHANSON_GPU", "L4")
# La fiche du modele demande 24 Go de memoire vive a cote de la carte.
MEMOIRE_MB = int(os.getenv("CHANSON_MEMORY_MB", "24576"))
# Meme disque persistant que la video : un seul volume a surveiller chez Modal.
VOLUME_MODELES = os.getenv("VIDEO_MODAL_VOLUME", "free-ai-studio-modeles")
CACHE_MODAL = "/modeles/hf"

# Kaggle choisit la carte d'apres machine_shape. NvidiaTeslaT4 est l'exemple de
# la documentation du CLI Kaggle ; qu'il donne une carte ou deux n'est pas dit.
# Le script marche avec une ou deux.
KAGGLE_MACHINE = os.getenv("CHANSON_KAGGLE_MACHINE", "NvidiaTeslaT4")
# Sur Kaggle, rien n'est garde d'une fois sur l'autre : pip et 7 Go de poids a
# chaque chanson, puis un calcul en float16 sur une carte de 2018. Duree non
# mesuree par le Studio, d'ou un delai large.
KAGGLE_DELAI_S = int(os.getenv("CHANSON_KAGGLE_TIMEOUT_SECONDS", "5400"))

MODELE = {
    "hf": "m-a-p/YuE2-3B",
    # Revisions epinglees le 15/09/2026 : un depot qui change sous nos pieds
    # changerait le son sans que personne le sache.
    "revision": "29b3558dd46954a0cd9021dc76d5c91864a0f1c7",
    "vae": "m-a-p/YuE2-Vae",
    "vae_revision": "9a94e1d0ea9f8087e98f77fa88df4a4068104d2a",
    "roue": "yue2_infer-0.1.5-py3-none-any.whl",
    "parametres": "3,6 milliards",
    # 3,63 milliards de parametres en 16 bits, sans compter le decodeur.
    "poids_go": 7.3,
    "licence": "CC BY-NC 4.0",
    "restriction": "usage non commercial",
    "territoire": "aucune restriction de pays",
    "code_licence": "Apache 2.0",
    "langues": "anglais et chinois",
    "fiche": "https://huggingface.co/m-a-p/YuE2-3B",
}

# La roue installe elle-meme ses dependances epinglees (torch 2.10.0,
# transformers 4.57.6...) : c'est l'installation officielle, rien de plus.
URL_ROUE = "https://huggingface.co/%s/resolve/%s/%s" % (MODELE["hf"], MODELE["revision"], MODELE["roue"])
PAQUETS_MODAL = (URL_ROUE,)

# Jeu de poids optionnel, FUSIONNE dans le modele de base avant de composer :
# W += echelle * (B @ A). Ce n'est pas un autre modele, c'est le meme, modifie.
# Essaye en reel le 17/09/2026 (job 730e9d75...) : la MECANIQUE de fusion marche
# (196 couples A/B fusionnes, poids modifies). Ce que cet essai n'etablit PAS,
# corrige le soir meme : que ce soit ELLE qui supprime le chant. Le rendu temoin
# fait SANS LoRA n'avait pas de voix non plus -- les trois branches partageaient
# lyrics="[Instrumental]" et un style en anglais. L'absence de voix reste donc la
# promesse de son auteur, pas une mesure a nous : ne pas la presenter autrement.
#
# DEUX RESERVES ECRITES ICI PLUTOT QU'OUBLIEES :
# 1. REVISION NON EPINGLEE. Le modele de base l'est (voir plus haut : un depot
#    qui change sous nos pieds changerait le son sans que personne le sache).
#    Celui-ci ne l'est pas : je n'ai pas verifie de hash. Meme risque, assume
#    faute de mieux, et dit dans le resume de chaque chanson.
# 2. VERIFIE SUR L4 (Modal) SEULEMENT. Le chemin Turing de Kaggle calcule en
#    float16 avec des correctifs non officiels ; la fusion n'y a jamais tourne.
#    preparer() refuse donc la combinaison au lieu de parier.
LORA = {
    "hf": "Mothersuperior/YuE2-instrumental-cot-full-loras",
    "fichier": "ar_lora_inst_v3abc.bf16.safetensors",
    "revision": None,
    "couples": 196,          # 392 tenseurs = 196 couples A/B ; 7 projections x 28 couches
    "echelle": 1.0,
    "megaoctets": 139.5,
    "licence": "CC BY-NC 4.0",
    "restriction": "usage non commercial",
    "territoire": "aucune restriction de pays",
    "fiche": "https://huggingface.co/Mothersuperior/YuE2-instrumental-cot-full-loras",
    "verifie_sur": "Modal (L4)",
}

# 25 jetons de son par seconde (48 000 / 1 920) : 1 500 jetons font une minute.
# C'est un plafond : la chanson peut finir avant.
DUREES = {
    "1": {"jetons": 1500, "secondes": 60},
    "2": {"jetons": 3000, "secondes": 120},
    "3": {"jetons": 4500, "secondes": 180},
}

MAX_STYLE = 600
MAX_PAROLES = 4000


# --- Compteur de depense ------------------------------------------------------
#
# UN SEUL compteur depuis le 19/09/2026 : budget_modal.py, partage avec les
# deux autres fonctions ET avec le bac a sable lui-meme, qui envoyait du code
# sur Modal sans etre compte par personne. Ce qui suit ne compte plus rien :
# ce sont des renvois, gardes pour que app.py, les tests et les pages n'aient
# pas a savoir ou vit le compteur. Le motif est en tete de budget_modal.py.


def budget_lire() -> dict:
    """L'etat du mois, TOUS usages confondus, vu du plafond de celui-ci."""
    etat = budget_modal.vue("chanson")
    etat["chansons"] = etat["appels"]["chanson"]
    return etat


def budget_ecrire(secondes: float, usd: float, chansons: int) -> None:
    """Pose l'etat de cet usage. Outil de TEST : le service passe par
    budget_consommer(), qui ajoute au lieu de poser."""
    budget_modal.poser("chanson", secondes, usd, chansons)


def prix_seconde(gpu: str) -> float:
    return budget_modal.prix_seconde(gpu, MEMOIRE_MB)


def budget_verifier(gpu: str, duree_max_s: int) -> dict:
    """Refuse AVANT de lancer si le pire cas entame ce qui reste a cet usage."""
    etat = budget_modal.verifier(
        "chanson", gpu, duree_max_s, MEMOIRE_MB,
        quoi="Une chanson", suite="Kaggle reste possible, gratuitement.")
    etat["cout_max_usd"] = etat["cout_max_usd"]
    etat["chansons"] = etat["appels"]["chanson"]
    return etat


def budget_consommer(gpu: str, secondes: float) -> dict:
    """Encaisse le temps reellement passe, meme si la chanson a echoue."""
    etat = budget_modal.consommer("chanson", gpu, secondes, MEMOIRE_MB)
    etat["chansons"] = etat["appels"]["chanson"]
    return etat


# LA MEME exception pour les trois, et c'etait un piege arme : un
# `except video.BudgetDepasse` attrapait jusqu'ici une classe differente de
# celle que chanson.py levait.
BudgetDepasse = budget_modal.BudgetDepasse


# --- Le script envoye sur la machine distante ---------------------------------

_SCRIPT = r'''# -*- coding: utf-8 -*-
"""Fait chanter des paroles par YuE2-3B. Genere par Free AI Studio.

Deux chemins, choisis d'apres la carte :
- carte qui calcule en bfloat16 (L4, A10, A100...) : le pipeline officiel, sans
  rien changer ;
- carte Turing (le T4 de Kaggle et de Colab gratuits) : le pipeline officiel
  refuse de demarrer. Ce script applique alors une partie des correctifs du carnet
  Kaggle << YuE2-3B - Frontier Full-Song Music Generation >> (AIQUEST Academy,
  licence Apache 2.0), numerotes comme dans le carnet : float16, attention SDPA,
  integration en float32, decodage par tuiles, decodeur sur la 2e carte s'il y en
  a deux. Ce chemin n'est pas celui des auteurs du modele : le resume le dit.
"""
import base64, json, os, subprocess, sys, time

DEBUT = time.time()
D = json.loads(base64.b64decode("__DEMANDE__").decode("utf-8"))
SORTIE = os.environ.get("FREE_AI_OUTPUT_DIR", "/tmp/free_ai_output")
os.makedirs(SORTIE, exist_ok=True)
if D.get("cache"):
    os.makedirs(D["cache"], exist_ok=True)
    os.environ["HF_HOME"] = D["cache"]
# Pose AVANT le premier import de torch, sinon ignore en silence.
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
AVERTISSEMENTS = []


def installer(*args):
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", *args])


if D.get("installer"):
    # Kaggle et Colab : leur PyTorch est garde, il est compile pour leur carte.
    # Le reste est epingle aux versions que la roue yue2 declare. numpy n'est pas
    # touche : dans ces images, il est lie a scipy et a numba.
    print("Installation des bibliotheques ...", flush=True)
    installer("transformers==4.57.6", "huggingface-hub==0.36.2", "safetensors==0.7.0",
              "tiktoken==0.12.0", "soundfile==0.13.1", "accelerate==1.13.0")
    from huggingface_hub import hf_hub_download
    roue = hf_hub_download(D["modele"], D["roue"], revision=D["revision"])
    # Sans ses dependances : elles exigeraient torch 2.10 a la place du leur.
    installer("--no-deps", "--force-reinstall", roue)

import soundfile as sf
import torch

if not torch.cuda.is_available():
    print("ECHEC : aucune carte graphique sur cette machine. Sur Colab : menu "
          "Execution > Modifier le type d'execution > GPU T4.", file=sys.stderr)
    sys.exit(2)

CARTES = torch.cuda.device_count()
nom_gpu = torch.cuda.get_device_name(0)
vram_go = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
# Le verrou officiel demande le bfloat16. Une carte Turing le << supporte >> en
# emulation lente : on regarde donc la generation de la carte, pas ce drapeau.
BF16 = torch.cuda.get_device_capability(0) >= (8, 0)
CHEMIN = "officiel" if BF16 else "correctifs Turing (non officiels)"
print("Carte : %s, %.1f Go, %d carte(s). Chemin : %s." % (nom_gpu, vram_go, CARTES, CHEMIN), flush=True)

import yue2.pipeline as ypipe


def correctifs_turing():
    """Correctifs du carnet AIQUEST Academy (Apache 2.0), numerotes comme lui."""
    from pathlib import Path
    import yue2.cuda_graph as ycg
    import yue2.nar as ynar
    import yue2.protocol as yproto

    # 1. Pas de verrou bfloat16 ; modele sur cuda:0, decodeur sur cuda:1 s'il existe.
    def init(self, model_dir, vae_dir, *, device="auto", memory_budget_gib=14,
             backend="torch", generation_config=None, verify_hashes=False,
             vae_core_frames=512, quantization="none", offload_ar=False, progress=True):
        self.progress = progress
        self.backend, self.quantization = backend, quantization
        self.model_dir, self.vae_dir = Path(model_dir), Path(vae_dir)
        self.offload_ar = offload_ar
        self.vae_core_frames = vae_core_frames
        self.device = torch.device("cuda:0")
        self.vae_device = torch.device("cuda:1") if CARTES >= 2 else self.device
        self.memory_budget_gib = float(memory_budget_gib)
        self.generation_config = generation_config or yproto.GenerationConfig()
        self.tokenizer = ypipe.YuE2TextTokenizer(self.model_dir / "qwen.tiktoken")
        torch.backends.cuda.matmul.allow_fp16_reduced_precision_reduction = True
        torch.backends.cudnn.benchmark = False
        with self._status("Verifying model files"):
            self.weights = {"mot": ypipe.model_identity(self.model_dir, verify_hashes),
                            "vae": ypipe.model_identity(self.vae_dir, verify_hashes)}
        self.runtime_sha256 = "correctifs-turing-free-ai-studio"
        self._model, self._vae = None, None
        self.load_timing = {}
    ypipe.YuE2Pipeline.__init__ = init

    # 2. Poids en float16, que toute carte Turing sait calculer.
    def charger(self, for_nar=False):
        if self._model is None:
            from yue2.modeling_yue2 import YuE2ForCausalLM
            debut = time.perf_counter()
            self._model = YuE2ForCausalLM.from_pretrained(
                self.model_dir, local_files_only=True, torch_dtype=torch.float16,
                low_cpu_mem_usage=True).eval()
            self.load_timing["mot_load_seconds"] = time.perf_counter() - debut
        # Le decodage gare le modele en memoire vive quand une seule carte sert
        # aux deux : on le remet a sa place a chaque fois.
        if next(self._model.parameters()).device != self.device:
            self._model.to(self.device)
        return self._model
    ypipe.YuE2Pipeline._load_model = charger

    # 3. Le decodeur a graphe CUDA detecte une FlashAttention qui n'existe pas
    #    sur Turing : SDPA ordinaire.
    graphar_init = ycg.GraphAR.__init__

    def graphar(self, model, prefixes, max_tokens, *, capture=True,
                attention_backend="auto", fuse_projections=False):
        if attention_backend == "auto":
            attention_backend = "sdpa"
        graphar_init(self, model, prefixes, max_tokens, capture=capture,
                     attention_backend=attention_backend, fuse_projections=fuse_projections)
    ycg.GraphAR.__init__ = graphar

    # 3b. Capture du graphe refusee : decodage ordinaire, step() le fait deja
    #     quand self.graph vaut None.
    capture_orig = ycg.GraphAR._capture

    def capture(self):
        try:
            capture_orig(self)
        except Exception as exc:
            print("Graphe CUDA refuse (%s) : decodage ordinaire." % exc, flush=True)
            self.graph = None
            self.output = None
            self.positions.copy_(self.initial_positions)
    ycg.GraphAR._capture = capture

    # 4. Sans FlashAttention, SDPA peut poser toute la matrice des scores : les
    #    tuiles de requetes sont taillees pour rester pres de 384 Mo.
    tuile = 384 * 2 ** 20

    def attention(self, q, k, v, causal=False):
        bloc = getattr(self, "query_chunk_size", None)
        if not bloc:
            par_requete = max(1, len(k) * q.shape[1] * 2)
            bloc = max(256, min(len(q), tuile // par_requete))
        return ynar.attention(q, k, v, causal=causal, backend=self.backend, query_chunk_size=int(bloc))
    ynar.CachedNAR._attention = attention

    # 5. Integration du flot en float32, la vitesse restant calculee en float16.
    #    Meme schema du point milieu et memes pas que l'officiel.
    @torch.inference_mode()
    def resoudre(self, steps=32, cancelled=None, on_progress=None):
        etat = self.chunk.noise.to(device=self.device, dtype=torch.float32)
        dt = 1.0 / steps
        for pas in range(steps):
            if cancelled is not None and cancelled():
                raise InterruptedError("Cancelled during acoustic flow matching")
            t = 1.0 - pas * dt
            brut = torch.logit(torch.tensor(t, dtype=torch.float64)).clamp(-20, 20).item()
            v1 = self.velocity(etat.to(self.dtype), brut).float()
            milieu = etat - v1 * (dt / 2)
            brut_m = torch.logit(torch.tensor(t - dt / 2, dtype=torch.float64)).clamp(-20, 20).item()
            etat = etat - self.velocity(milieu.to(self.dtype), brut_m).float() * dt
            if on_progress is not None:
                on_progress(pas + 1, int(steps))
        resultat = etat.float().cpu()
        if not torch.isfinite(resultat).all():
            n = int((~torch.isfinite(resultat)).sum())
            AVERTISSEMENTS.append("%d valeur(s) non finie(s) dans les latents, ramenee(s) "
                                  "a une valeur finie : le son peut etre abime." % n)
            resultat = torch.nan_to_num(resultat, nan=0.0, posinf=1.0, neginf=-1.0)
        return resultat
    ynar.CachedNAR.solve = resoudre

    # 6. Decodage par tuiles de 512 trames sur la carte du decodeur ; le modele
    #    ne quitte sa carte que s'il n'y en a qu'une.
    def decoder(self, latents, *, full=False, vae=None):
        from yue2.modeling_vae import YuE2VAE
        carte = self.vae_device
        if carte == self.device and self._model is not None:
            self._model.to("cpu")
            torch.cuda.empty_cache()
        if self._vae is None:
            self._vae = YuE2VAE.from_pretrained(self.vae_dir, decoder_only=True, device="cpu",
                                                local_files_only=True)
        modele = self._vae.to(carte)
        z = torch.as_tensor(latents, dtype=torch.float32)
        if z.ndim == 2 and z.shape[1] == 64:
            z = z.T.unsqueeze(0)
        try:
            with torch.inference_mode():
                son = modele.decode_tiled(z, core_frames=self.vae_core_frames or 512,
                                          halo_frames=16, output_device="cpu")
            if not torch.isfinite(son).all():
                n = int((~torch.isfinite(son)).sum())
                AVERTISSEMENTS.append("%d echantillon(s) non fini(s) remis a zero." % n)
                son = torch.nan_to_num(son, nan=0.0)
            return son[0].float().clamp(-1, 1).T.contiguous().numpy()
        finally:
            modele.to("cpu")
            torch.cuda.empty_cache()
    ypipe.YuE2Pipeline.decode = decoder


if not BF16:
    correctifs_turing()

print("Chargement de %s (le premier lancement telecharge environ 7 Go) ..." % D["modele"], flush=True)
TEMPS = {}
t0 = time.time()
options = dict(vae=D["vae"], revision=D["revision"], vae_revision=D["vae_revision"], progress=False)
if BF16:
    options["device"] = "cuda"
pipe = ypipe.YuE2Pipeline.from_pretrained(D["modele"], **options)
TEMPS["chargement"] = round(time.time() - t0, 1)
print("Modele pret en %.0f s" % TEMPS["chargement"], flush=True)

# --- Version instrumentale : la LoRA fusionnee dans les poids ------------------
# W += echelle * (B @ A). Chaque garde-fou arrete AVANT de composer : un rendu
# paye puis jete est pire qu'un echec immediat. Une boucle a zero tour
# << reussirait >> sans rien changer -- d'ou le comptage des couples.
LORA_FAIT = None
if D.get("lora"):
    t0 = time.time()
    from huggingface_hub import hf_hub_download
    from safetensors.torch import load_file
    L = D["lora"]
    chemin_lora = hf_hub_download(L["hf"], L["fichier"],
                                  **({"revision": L["revision"]} if L.get("revision") else {}))
    tenseurs = load_file(chemin_lora)
    couples = sorted(k[:-len(".lora_A")] for k in tenseurs if k.endswith(".lora_A"))
    if len(couples) != int(L["couples"]):
        print("ECHEC : la LoRA a %d couples A/B, %d attendus. Forme inattendue : on ne "
              "fusionne pas a l'aveugle." % (len(couples), int(L["couples"])), file=sys.stderr)
        sys.exit(5)
    if not hasattr(pipe, "_load_model"):
        print("ECHEC : pipe._load_model absent de cette version de la roue. C'est une "
              "methode privee ; pas de contournement improvise.", file=sys.stderr)
        sys.exit(4)
    bloc = pipe._load_model().model

    def _cible(nom):
        bouts = nom.split(".")
        i = bouts.index("layers")
        return getattr(getattr(bloc.layers[int(bouts[i + 1])], bouts[i + 2]), bouts[i + 3])

    norme_avant = float(_cible(couples[0]).weight.detach().float().norm())
    fusionnes = 0
    for base in couples:
        b = tenseurs.get(base + ".lora_B")
        if b is None:
            print("ECHEC : %s a un lora_A sans lora_B." % base, file=sys.stderr)
            sys.exit(5)
        lin = _cible(base)
        mat_a = tenseurs[base + ".lora_A"].to(lin.weight.device, torch.float32)
        mat_b = b.to(lin.weight.device, torch.float32)
        lin.weight.data.add_((float(L["echelle"]) * (mat_b @ mat_a)).to(lin.weight.dtype))
        fusionnes += 1
    norme_apres = float(_cible(couples[0]).weight.detach().float().norm())
    if norme_apres == norme_avant:
        print("ECHEC : la fusion n'a change aucun poids.", file=sys.stderr)
        sys.exit(6)
    TEMPS["lora"] = round(time.time() - t0, 1)
    LORA_FAIT = {"depot": L["hf"], "fichier": L["fichier"],
                 "revision": L["revision"] or "non epinglee (main)",
                 "couples_fusionnes": fusionnes, "echelle": float(L["echelle"]),
                 "norme_avant": round(norme_avant, 4), "norme_apres": round(norme_apres, 4)}
    print("LoRA fusionnee : %d couples, norme %.4f -> %.4f, en %.0f s"
          % (fusionnes, norme_avant, norme_apres, TEMPS["lora"]), flush=True)
    AVERTISSEMENTS.append(
        "Version instrumentale : la LoRA " + L["hf"] + " a ete fusionnee dans les poids. "
        "Sa revision n'est PAS epinglee, contrairement au modele de base : si le depot "
        "change, ce rendu n'est pas reproductible a l'identique.")

# Sur Turing, la partition est plafonnee comme dans le carnet (1 200 jetons) :
# sans plafond, elle a ete vue partir jusqu'a 3 800 jetons, et tout le reste
# ralentit d'autant. Sur le chemin officiel, les reglages des auteurs.
t0 = time.time()
plan = pipe.plan(style=D["style"], lyrics=D["paroles"], cot=D["cot"], seed=int(D["graine"]),
                 abc_sampling=None if BF16 else {"max_tokens": 1200})
TEMPS["partition"] = round(time.time() - t0, 1)
print("1/4 Partition : %d jetons en %.0f s" % (len(plan.abc_ids), TEMPS["partition"]), flush=True)

t0 = time.time()
semantique = pipe.generate_semantic(plan, sampling={"max_tokens": int(D["jetons"])})
TEMPS["son"] = round(time.time() - t0, 1)
print("2/4 Jetons de son : %d en %.0f s (%s)" % (
    len(semantique.tokens), TEMPS["son"], semantique.timing.get("execution")), flush=True)

t0 = time.time()
latents = pipe.synthesize(semantique)
TEMPS["flot"] = round(time.time() - t0, 1)
print("3/4 Flot acoustique : %d trames en %.0f s" % (latents.shape[0], TEMPS["flot"]), flush=True)

t0 = time.time()
son = pipe.decode(latents)
TEMPS["decodage"] = round(time.time() - t0, 1)
print("4/4 Decodage : %.0f s" % TEMPS["decodage"], flush=True)

# 16 bits : sans perte a l'oreille, plus leger, et les navigateurs lisent mal
# la duree d'un fichier 24 bits (remarque du carnet Kaggle).
chemin = os.path.join(SORTIE, "chanson.flac")
sf.write(chemin, son, 48000, subtype="PCM_16")
if plan.abc:
    with open(os.path.join(SORTIE, "partition.abc"), "w", encoding="utf-8") as f:
        f.write(plan.abc)

for message in AVERTISSEMENTS:
    print("AVERTISSEMENT : " + message, flush=True)

resume = {
    "fichier": "chanson.flac",
    "octets": os.path.getsize(chemin),
    "secondes_audio": round(len(son) / 48000.0, 1),
    "jetons_demandes": int(D["jetons"]),
    "jetons_partition": len(plan.abc_ids),
    "jetons_son": len(semantique.tokens),
    "coupee": {"partition": bool(plan.truncated), "son": bool(semantique.truncated)},
    "graine": int(D["graine"]),
    "modele": "%s@%s" % (D["modele"], D["revision"][:12]),
    "carte": nom_gpu,
    "cartes": CARTES,
    "chemin": CHEMIN,
    "precision": "bfloat16" if BF16 else "float16",
    "temps": TEMPS,
    "lora": LORA_FAIT,
    "avertissements": AVERTISSEMENTS,
    "secondes_calcul": round(time.time() - DEBUT, 1),
}
with open(os.path.join(SORTIE, "resume.json"), "w", encoding="utf-8") as f:
    json.dump(resume, f, ensure_ascii=False, indent=2)
print(json.dumps(resume, ensure_ascii=False), flush=True)
'''


def construire_script(demande: dict) -> str:
    """Le script autonome, demande comprise : un seul fichier part, partout."""
    charge = base64.b64encode(
        json.dumps(demande, ensure_ascii=False).encode("utf-8")
    ).decode("ascii")
    return _SCRIPT.replace("__DEMANDE__", charge)


def preparer(payload: dict, ou: str = "modal") -> dict:
    """Traduit ce que la page a envoye en une demande complete et bornee."""
    style = " ".join(str(payload.get("style") or "").split())
    if not style:
        raise ValueError("Décrivez le style en quelques mots : langue, genre, instruments, voix, tempo.")
    style = style[:MAX_STYLE]

    # La LoRA instrumentale est FUSIONNEE dans les poids du modele de base : ce
    # n'est pas un autre modele, c'est le meme, modifie avant de composer.
    lora = bool(payload.get("lora"))
    if lora and ou != "modal":
        raise ValueError(
            "La version instrumentale n'est vérifiée que sur Modal (carte L4). Le chemin "
            "Kaggle applique déjà des correctifs non officiels pour sa carte T4, et la fusion "
            "n'y a jamais tourné : le Studio refuse plutôt que de vous laisser payer un essai "
            "dont personne ne connaît le résultat. Choisissez Modal, ou la version qui chante.")

    paroles = str(payload.get("paroles") or "").replace("\r\n", "\n").strip()
    # Sans LoRA, le modele chante : il lui faut des paroles. Avec, son auteur
    # l'annonce instrumentale, donc en exiger serait absurde -- mais nous ne
    # l'avons pas verifie : le temoin sans LoRA n'avait pas de voix non plus.
    # << [Instrumental] >> n'est pas une balise documentee : c'est ce qui a servi
    # aux trois rendus du 17/09, rien de plus.
    if lora and not paroles:
        paroles = "[Instrumental]"
    if not paroles:
        raise ValueError("Il faut des paroles à chanter.")
    if len(paroles) > MAX_PAROLES:
        raise ValueError(f"Paroles trop longues ({len(paroles)} caractères, {MAX_PAROLES} au plus). "
                         f"Trois minutes de chanson tiennent en bien moins.")
    # Le modele attend des sections ([Verse], [Chorus]...). Sans aucune, on en
    # pose une, et la page le dit. Inutile quand rien n'est chante.
    balise_ajoutee = (not lora) and not re.search(r"^\s*\[[^\]\n]+\]", paroles, re.M)
    if balise_ajoutee:
        paroles = "[Verse]\n" + paroles

    duree = str(payload.get("duree") or "1")
    if duree not in DUREES:
        duree = "1"

    try:
        graine = int(payload.get("graine"))
    except (TypeError, ValueError):
        graine = -1
    if not 0 <= graine < 2 ** 31:
        graine = secrets.randbelow(2 ** 31)

    pour_modal = ou == "modal"
    demande = {
        "modele": MODELE["hf"],
        "revision": MODELE["revision"],
        "vae": MODELE["vae"],
        "vae_revision": MODELE["vae_revision"],
        "roue": MODELE["roue"],
        "style": style,
        "paroles": paroles,
        "cot": "full",
        "graine": graine,
        "jetons": DUREES[duree]["jetons"],
        # Modal : bibliotheques dans l'image, poids sur le disque persistant.
        # Kaggle et Colab : tout s'installe et se telecharge a chaque fois.
        "cache": CACHE_MODAL if pour_modal else "",
        "installer": not pour_modal,
        "lora": {
            "hf": LORA["hf"],
            "fichier": LORA["fichier"],
            "revision": LORA["revision"],
            "couples": LORA["couples"],
            "echelle": LORA["echelle"],
        } if lora else None,
    }
    carte = {"modal": GPU_MODAL + " (Modal)", "kaggle": "T4 (Kaggle)", "colab": "T4 (Colab)"}.get(ou, ou)
    return {
        "duree": duree,
        "gpu": GPU_MODAL,
        "demande": demande,
        "resume_public": {
            "modele": MODELE["hf"],
            "licence": MODELE["licence"] + ", " + MODELE["restriction"],
            "carte": carte,
            "secondes_max": DUREES[duree]["secondes"],
            "graine": graine,
            "balise_ajoutee": balise_ajoutee,
            # Deux licences quand la LoRA est fusionnee : celle du modele et la
            # sienne. La fiche du travail doit porter les deux, pas la premiere.
            "instrumental": lora,
            "lora": (LORA["hf"] + " — " + LORA["licence"] + ", " + LORA["restriction"]
                     + " ; révision non épinglée") if lora else None,
        },
    }


def carnet_colab(demande: dict) -> dict:
    """Un carnet Colab pret a lancer, la demande dedans."""
    explication = (
        "# 🎵 Chanson — Free AI Studio\n\n"
        "1. Menu **Exécution › Modifier le type d’exécution** : choisissez **GPU T4**, puis Enregistrer.\n"
        "2. Menu **Exécution › Tout exécuter**. Comptez l’installation, puis environ 7 Go de "
        "téléchargement, puis le calcul ; durée non mesurée par le Studio.\n"
        "   > ⚠ **Essayé le 16/09 sur Colab gratuit : la session est morte faute de mémoire "
        "vive** (~12,7 Go, et une seule carte, ce qui oblige à garer le modèle en mémoire "
        "entre les étapes). Sur Kaggle, deux cartes T4 et ~30 Go, la même chanson passe. Ce "
        "carnet n’a de chance que sur une session à mémoire élevée.\n"
        "3. La chanson se joue sous la dernière cellule et se télécharge (`chanson.flac`).\n\n"
        "Modèle [YuE2-3B](%s) de m-a-p : poids sous licence **%s**, %s. Il chante en %s. "
        "Sur la carte T4, le pipeline officiel refuse de démarrer : le script applique des "
        "correctifs non officiels, repris du carnet Kaggle « YuE2-3B - Frontier Full-Song Music "
        "Generation » (AIQUEST Academy, licence Apache 2.0).\n"
    ) % (MODELE["fiche"], MODELE["licence"], MODELE["restriction"], MODELE["langues"])
    lecture = (
        "from IPython.display import Audio, display\n"
        "chemin = '/content/chanson/chanson.flac'\n"
        "display(Audio(chemin))\n"
        "from google.colab import files\n"
        "files.download(chemin)\n"
    )

    def code(source: str) -> dict:
        return {"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": source}

    return {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {
            "accelerator": "GPU",
            "colab": {"name": "Free AI Studio - chanson", "gpuType": "T4"},
            "kernelspec": {"name": "python3", "display_name": "Python 3"},
        },
        "cells": [
            {"cell_type": "markdown", "metadata": {}, "source": explication},
            code("import os\nos.environ['FREE_AI_OUTPUT_DIR'] = '/content/chanson'\n"),
            code(construire_script(demande)),
            code(lecture),
        ],
    }


# --- La page ------------------------------------------------------------------

PAGE_HTML = r"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Chanson — Free AI Studio</title>
<style>
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;max-width:900px;
 margin:34px auto;padding:0 18px;line-height:1.55}
h1{font-size:1.5rem;margin-bottom:4px}
.sous{opacity:.8;margin-top:0}
.banniere{padding:14px 16px;border-radius:14px;margin:16px 0;border:1px solid #bbb;background:#eef4fb}
.ligne{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:14px 0}
select,button,input{font:inherit;padding:9px 12px;border-radius:10px;border:1px solid #666;background:#fff}
input.large{width:100%;box-sizing:border-box}
button.primaire{background:#222;color:#fff;border-color:#222;cursor:pointer}
button[disabled]{opacity:.5;cursor:default}
a.bouton{display:inline-block;font:inherit;padding:10px 16px;border-radius:10px;
 border:1px solid #222;background:#222;color:#fff;text-decoration:none;cursor:pointer}
a.bouton.discret{background:#fff;color:#222;border-color:#666}
textarea{font:inherit;width:100%;box-sizing:border-box;height:190px;padding:12px;
 border-radius:12px;border:1px solid #999}
label.titre{display:block;font-weight:600;margin:16px 0 6px}
pre{background:#f6f6f6;border:1px solid #ddd;border-radius:12px;padding:12px;
 overflow-x:auto;white-space:pre-wrap;word-break:break-word;font-size:.82rem}
audio{width:100%;margin-top:12px}
.ok{color:#1d6b32}.ko{color:#9b2116}
button.danger{background:#9b2116;color:#fff;border-color:#9b2116;cursor:pointer}
.avert{font-size:.86rem;opacity:.75}
button.discret{font:inherit;font-size:.86rem;padding:5px 10px;border-radius:8px;
 border:1px solid #666;background:#fff;color:#222;cursor:pointer;margin-right:8px}
.licence{padding:10px 14px;border-radius:12px;border:1px solid #d9ad63;background:#fdf6e8;font-size:.9rem}
.jauge{height:9px;border-radius:999px;background:#e6e6e6;overflow:hidden;margin:6px 0 2px}
.jauge span{display:block;height:100%;background:#5b8c5a}
.pied{margin-top:26px;padding-top:16px;border-top:1px solid #ddd;font-size:.9rem;opacity:.8}
.portee{background:#fff;border:1px solid #ddd;border-radius:12px;padding:8px 4px;
 margin:8px 0;overflow-x:auto}
.portee svg{max-width:100%}
.portee svg g.surligne, .portee svg g.surligne path{fill:#9b2116}
</style>
<!-- abcjs 6.7.0 (MIT) : dessine la partition en vraies portees. Servie par le
     service lui-meme (route /chanson/abcjs.js), jamais par un CDN : le Studio
     doit marcher sans acces reseau. PAS DE LECTEUR : la page montre plus bas le
     son vraiment rendu par le modele, dans <audio controls>. Un bouton de
     lecture MIDI ferait entendre autre chose que ce qui a ete genere -- deux
     sons differents pour une meme partition, c'est pire que pas de bouton.
     Le surlignage ajoute le 17/09 ne rompt PAS cette regle : il ne produit
     aucun son, il est mene par l'horloge du FLAC lui-meme (audio.currentTime).
     La seule source sonore de la page reste le fichier rendu par le modele. -->
<script src="/chanson/abcjs.js"></script>
</head><body>
<h1>🎵 Faire chanter des paroles</h1>
<p class="sous">Écrivez des paroles et décrivez un style : le modèle compose la mélodie et
la chante, voix et instruments, jusqu’à trois minutes.</p>

<div id="banniere" class="banniere">Vérification en cours…</div>
<div id="reel" class="avert"></div>

<label class="titre" for="style">Style</label>
<input id="style" class="large" maxlength="600"
 placeholder="English, acoustic folk, warm female voice, fingerpicked guitar, soft cello, 92 BPM">
<p class="avert">En anglais de préférence, en commençant par la langue chantée : genre,
instruments, voix, tempo.</p>
<p><button type="button" id="modele-style" class="discret">Utiliser cet exemple</button>
<span id="note-style" class="avert"></span></p>

<label class="titre" for="paroles">Paroles</label>
<textarea id="paroles" maxlength="4000" placeholder="[Verse]
Paper boats along the stream
Carry every little dream
[Chorus]
Sing it low and sing it clear
Every morning brings you here"></textarea>
<p class="avert">Découpez en sections : <code>[Verse]</code>, <code>[Chorus]</code>,
<code>[Bridge]</code>… Sans aucune, le Studio met tout dans un seul couplet.
<b>Le modèle chante en anglais et en chinois</b> selon sa fiche ; le français n’y est pas
annoncé : essayez, sans garantie.</p>
<p><button type="button" id="modele-paroles" class="discret">Utiliser cet exemple</button>
<span id="note-paroles" class="avert"></span></p>

<div class="ligne">
  <label>Version
    <select id="modele">
      <option value="base" selected>YuE2-3B — chante les paroles</option>
      <option value="lora">YuE2-3B + LoRA — instrumental selon son auteur</option>
    </select>
  </label>
  <label>Durée
    <select id="duree"><option value="1" selected>jusqu’à 1 minute</option><option value="2">jusqu’à 2 minutes</option><option value="3">jusqu’à 3 minutes</option></select>
  </label>
  <label>Où
    <select id="ou">
      <option value="modal" selected>Modal — machine louée (carte bancaire exigée)</option>
      <option value="kaggle">Kaggle — gratuit, plus lent</option>
    </select>
  </label>
  <button id="lancer" class="primaire">Chanter</button>
</div>
<p id="modele-texte" class="licence" hidden></p>
<p id="ou-texte" class="avert"></p>
<p id="licence" class="licence"></p>

<div id="etat" class="ligne"></div>
<div class="ligne"><button id="arreter" class="danger" hidden>⛔ Arrêt d’urgence</button>
<span id="arreter-texte" class="avert"></span></div>
<details id="detailJournal" hidden><summary>Voir le détail technique</summary>
<pre id="journal"></pre></details>
<div id="resultat"></div>

<div class="pied" id="pied"></div>

<script>
const CLE = "__CLE__";
const ENTETES = {"Authorization":"Bearer "+CLE, "Content-Type":"application/json"};
let minuteur = null;
let ETAT = null;

// Ce que chaque endroit implique, dit la ou l'on choisit.
function majOu(){
  const ou = document.getElementById("ou").value;
  const texte = {
    modal: "Pipeline officiel sur une carte " + (ETAT ? ETAT.carte_modal : "L4")
      + " louée à la seconde. Au pire " + (ETAT ? ETAT.cout_max_modal_usd.toFixed(2) : "?")
      + " $ par chanson (carte, processeur et 24 Gio de mémoire, jusqu’au délai maximal) ; "
      + "le prix réel dépend de la durée du calcul.",
    kaggle: "Carte T4 gratuite, sur votre compte Kaggle. Le pipeline officiel refuse cette carte : "
      + "le Studio applique des correctifs non officiels, essayés avec succès le 15/09. Tout se "
      + "retélécharge à chaque chanson (environ 7 Go)."
  }[ou];
  document.getElementById("ou-texte").textContent = texte || "";
  majBouton();
}
document.getElementById("ou").addEventListener("change", majOu);

const PAROLES_ORIGINE = document.getElementById("paroles").placeholder;
const STYLE_ORIGINE = document.getElementById("style").placeholder;

// L'exemple de style d'origine reclame une << warm female voice >>, ce qui n'a
// aucun sens pour la version instrumentale : choisir la LoRA laissait donc a
// l'ecran un exemple demandant une voix. Celui-ci est propre a l'instrumental,
// et plus complet : instruments, EVOLUTION de l'arrangement, tempo, tonalite,
// climat. Le style est la seule entree qui reste quand les paroles sont
// eteintes -- il merite l'exemple le plus riche, pas le plus pauvre.
const STYLE_LORA = "Instrumental, no vocals, cinematic neo-classical: fingerpicked "
  + "nylon guitar lead, warm cello counter-melody, soft brushed drums entering at the "
  + "second section, analog pad underneath, 88 BPM, D minor, calm and wistful";

// Le bouton depose l'exemple QUI S'APPLIQUE : deposer l'exemple chante alors
// que la version instrumentale est choisie serait un contresens.
function exempleStyle(){ return estLora() ? STYLE_LORA : STYLE_ORIGINE; }

// L'exemple en grise disparaissait au premier caractere : il ne servait qu'une
// fois, et il fallait ensuite le retaper de memoire. Ces boutons le DEPOSENT
// dans le champ, ou il devient modifiable -- un modele de depart, plus une
// simple illustration.
//
// Trois regles, chacune pour un degat precis :
//  - on n'ecrase JAMAIS un texte deja saisi. Effacer le travail de
//    l'utilisateur d'un seul clic serait pire que l'absence du bouton ; on le
//    dit, et on ne touche a rien.
//  - on lit la constante capturee au chargement, JAMAIS .placeholder : sous
//    LoRA, majModele() remplace le placeholder par << Ignore ici... >>, et
//    deposer cette phrase-la comme paroles n'aurait aucun sens.
//  - on ne remplit pas un champ desactive : la LoRA eteint les paroles, le
//    bouton ne doit pas les ressusciter par la bande.
function deposerExemple(champId, texte, noteId){
  const champ = document.getElementById(champId);
  const note = document.getElementById(noteId);
  if(champ.disabled){ return; }
  if(champ.value.trim()){
    note.textContent = "Le champ n’est pas vide : je n’efface pas ce que vous avez écrit.";
    return;
  }
  champ.value = texte;
  note.textContent = "";
  champ.focus();
}

document.getElementById("modele-style").addEventListener("click", () => {
  deposerExemple("style", exempleStyle(), "note-style");
});
document.getElementById("modele-paroles").addEventListener("click", () => {
  deposerExemple("paroles", PAROLES_ORIGINE, "note-paroles");
});

function estLora(){ return document.getElementById("modele").value === "lora"; }
function majBouton(){
  document.getElementById("lancer").textContent = estLora() ? "Composer" : "Chanter";
}

// La licence se dit A L'ENDROIT DU CHOIX, pas en note de bas de page : c'est ici
// qu'on decide, donc ici qu'on doit savoir ce qu'on prend. Et les deux reserves
// (revision non epinglee, verifiee sur Modal seulement) se disent avec.
function majModele(){
  const zone = document.getElementById("modele-texte");
  const paroles = document.getElementById("paroles");
  const kaggle = document.querySelector('#ou option[value="kaggle"]');
  if(!estLora()){
    zone.hidden = true;
    zone.textContent = "";
    paroles.disabled = false;
    paroles.placeholder = PAROLES_ORIGINE;
    document.getElementById("modele-paroles").disabled = false;
    document.getElementById("note-paroles").textContent = "";
    document.getElementById("style").placeholder = STYLE_ORIGINE;
    // Ne jamais rouvrir Kaggle si c'est le Studio partage qui l'a ferme.
    if(kaggle && !(ETAT && ETAT.kaggle_permis === false)){ kaggle.disabled = false; }
    majBouton();
    return;
  }
  const l = ETAT && ETAT.lora;
  zone.hidden = false;
  zone.innerHTML = l
    ? ('Poids <a href="' + l.fiche + '" target="_blank" rel="noopener">' + l.hf + '</a> '
       + 'fusionnés dans le modèle : licence <b>' + l.licence + '</b>, <b>' + l.restriction
       + '</b>, ' + l.territoire + '.<br><b>Son auteur l’annonce instrumentale</b> ; nous ne '
       + 'l’avons pas vérifié : le rendu témoin fait sans elle n’avait pas de voix non plus, '
       + 'donc notre essai ne prouve rien sur ce point. Les paroles sont ignorées. '
       + 'Sa révision n’est <b>pas épinglée</b>, contrairement au modèle de base : '
       + 'si le dépôt change, le rendu n’est plus reproductible. Vérifiée sur <b>'
       + l.verifie_sur + '</b> seulement, donc indisponible sur Kaggle.')
    : "Version instrumentale : licence et détails non chargés, le service ne répond pas.";
  paroles.disabled = true;
  paroles.placeholder = "Ignoré ici : cette version est annoncée instrumentale par son auteur.";
  // Le bouton suit le champ. Un bouton vivant au-dessus d'un champ eteint
  // promet une action qui n'arrivera pas.
  document.getElementById("modele-paroles").disabled = true;
  document.getElementById("note-paroles").textContent = "";
  // Le style devient la SEULE entree : il lui faut l'exemple instrumental, et
  // surtout pas celui qui reclame une voix.
  document.getElementById("style").placeholder = STYLE_LORA;
  if(kaggle){
    kaggle.disabled = true;
    if(document.getElementById("ou").value === "kaggle"){
      document.getElementById("ou").value = "modal";
      majOu();
    }
  }
  majBouton();
}
document.getElementById("modele").addEventListener("change", majModele);

function budgetTexte(b){
  const part = Math.min(100, 100 * b.usd / b.plafond_usd);
  // Le nombre affiché vient de Modal dès que leur relevé est là et qu'il est le
  // plus grand des deux. Le dire, parce que « estimation » et « relevé » ne se
  // discutent pas de la même façon.
  const reel = (b.usd_reel !== null && b.usd_reel !== undefined
                && b.usd_reel >= b.usd_estime);
  return "Dépensé sur Modal ce mois-ci " + (reel ? "selon Modal" : "selon le Studio")
    + ", tous usages confondus : <b>"
    + b.usd.toFixed(2) + " $</b> sur les " + b.plafond_usd.toFixed(2)
    + " $ ouverts aux demandes. " + b.chansons + " chanson(s) sur cette page."
    + '<div class="jauge"><span style="width:' + part.toFixed(1) + '%"></span></div>'
    + '<span class="avert">'
    + (reel
       // Les 8 % décrivent la MÉTHODE de comptage, pas le total affiché : ce total court
       // sur tout le mois et peut contenir des travaux comptés AVANT la correction des
       // tarifs du 20/09/2026, à des prix trop bas. Mesuré ce jour-là sur cette page :
       // 1,39 $ estimé contre 3,80 $ facturés, soit 37 % — annoncer 8 % sur CE nombre
       // serait faux de loin.
       ? 'Chiffre <b>relevé chez Modal</b> le ' + b.usd_reel_le + ' : leur compte, pas '
         + 'le nôtre. Notre estimation locale, d’après les prix relevés le '
         + b.prix_releve_le + ', dit ' + b.usd_estime.toFixed(2) + ' $. La méthode '
         + 'sous-compte d’environ 8 %, le temps de processeur réellement utilisé dépassant '
         + 'le cœur réservé — et ce total peut contenir des travaux comptés avant le '
         + b.prix_releve_le + ', à des tarifs plus bas. '
       : 'Estimation locale d’après les prix relevés le ' + b.prix_releve_le
         + ', pas une facture : Modal n’a pas répondu. La méthode <b>sous-compte d’environ '
         + '8 %</b> (le processeur réellement utilisé dépasse le cœur réservé, et cela ne se '
         + 'sait qu’après), et ce total peut contenir des travaux comptés avant cette date, '
         + 'à des tarifs plus bas. ')
    + 'Ce compteur est <b>unique</b> depuis le 19/09/2026 : il compte '
    + 'ensemble les clips, les chansons, les dialogues et le code envoyé au Sandbox, sur un '
    + 'budget de ' + b.plafond_total_usd.toFixed(2) + ' $, dont '
    + b.reserve_autonome_usd.toFixed(2) + ' $ sont réservés au Sandbox et ne peuvent pas '
    + 'être entamés ici. '
    + 'Le crédit de '
    + b.credit_offert_usd.toFixed(0) + ' $ par mois est celui que vous avez déclaré, non vérifié '
    + 'chez Modal, qui exige une carte bancaire et facture au-delà : '
    + '<a href="https://modal.com/settings/usage" target="_blank" rel="noopener">réglez votre '
    + 'limite de dépense au plus bas</a>. Kaggle ne coûte rien.</span>';
}

function montantTexte(v){
  return (typeof v === 'number') ? v.toFixed(2) + ' $' : String(v);
}

function reelAfficher(d){
  const zone = document.getElementById('reel');
  if(!d || !d.disponible){
    const pourquoi = (d && d.raison) ? d.raison : 'le service n’a pas répondu.';
    zone.textContent = 'Chiffre réel de Modal : non obtenu — ' + pourquoi;
    return;
  }
  const m = d.montants || {};
  const bouts = [];
  if(m.facture !== undefined) bouts.push('facturé <b>' + montantTexte(m.facture) + '</b>');
  if(m.mesure !== undefined) bouts.push('mesuré ' + montantTexte(m.mesure));
  const detail = [];
  if(m.calcul !== undefined) detail.push('calcul ' + montantTexte(m.calcul));
  if(m.stockage !== undefined) detail.push('stockage ' + montantTexte(m.stockage));
  if(detail.length) bouts.push('dont ' + detail.join(' et '));
  const deduits = [];
  if(m.credits !== undefined) deduits.push('crédits ' + montantTexte(m.credits));
  if(m.stockage_offert !== undefined) deduits.push('stockage offert ' + montantTexte(m.stockage_offert));
  if(deduits.length) bouts.push('déduits : ' + deduits.join(', '));
  let texte;
  if(bouts.length){
    texte = 'Chez Modal, pour tout l’espace de travail ce mois-ci : ' + bouts.join(', ')
      + '. Relevé le ' + d.releve_le + '. Ce compte-là fait foi, et il couvre aussi la vidéo '
      + 'et les essais du bac à sable, que le compteur ci-dessus ne voit pas.';
  } else {
    texte = 'Modal a répondu, mais le Studio n’a reconnu aucun montant. '
      + (d.raison || '') + ' Relevé le ' + d.releve_le + '.';
  }
  if(d.brut){
    texte += '<details><summary>Voir la réponse de Modal</summary><pre id="brutModal"></pre></details>';
  }
  zone.innerHTML = texte;
  if(d.brut){ document.getElementById('brutModal').textContent = d.brut; }
}

function reelCharger(){
  const zone = document.getElementById('reel');
  zone.textContent = 'Chiffre réel de Modal : demandé…';
  return fetch('/depenses/etat', {headers:{'Authorization':'Bearer '+CLE}})
    .then(r => r.json())
    .then(reelAfficher)
    .catch(() => {
      zone.textContent = 'Chiffre réel de Modal : non obtenu — le service Sandbox ne répond pas.';
    });
}

function rafraichir(){
  return fetch("/chanson/etat", {headers:{"Authorization":"Bearer "+CLE}})
    .then(r => r.json())
    .then(d => {
      ETAT = d;
      document.getElementById("banniere").innerHTML = budgetTexte(d.budget);
      const m = d.modele;
      document.getElementById("licence").innerHTML = "Modèle <a href=\"" + m.fiche
        + "\" target=\"_blank\" rel=\"noopener\">" + m.hf + "</a> (" + m.parametres
        + " de paramètres) : poids sous licence <b>" + m.licence + "</b>, <b>" + m.restriction
        + "</b>, " + m.territoire + ". Ce que cette licence permet de faire des chansons produites "
        + "n’est pas tranché ici : pour un usage commercial, lisez la fiche du modèle. Il chante en "
        + m.langues + ".";
      if(d.kaggle_permis === false){
        const k = document.querySelector('#ou option[value="kaggle"]');
        k.disabled = true;
        k.textContent = "Kaggle — coupé ici : Studio partagé";
      }
      majOu();
      majModele();
      document.getElementById("pied").innerHTML = "Rien ne part chez un fournisseur d’IA : le "
        + "modèle tourne sur une machine que vous louez ou qui vous est prêtée."
        + '<br><a href="/">Retour au Sandbox</a> &nbsp; <a href="/cles">Brancher Modal ou Kaggle</a>';
      return d;
    })
    .catch(() => {
      document.getElementById("banniere").textContent =
        "État non vérifiable : le service Sandbox ne répond pas.";
    });
}

function condenser(t){
  // Une ligne par pourcentage de telechargement : on ne garde que la ligne
  // d'arrivee de chaque barre, et on dit combien ont ete mises de cote.
  const gardees = []; let cachees = 0;
  for(const ligne of (t || "").split("\n")){
    if(/\d+%\|/.test(ligne) && !/100%\|/.test(ligne)){ cachees++; continue; }
    gardees.push(ligne);
  }
  if(cachees) gardees.push("… " + cachees + " lignes d’avancement masquées.");
  return gardees.join("\n");
}

function afficherJournal(t){
  document.getElementById("detailJournal").hidden = !t;
  document.getElementById("journal").textContent = condenser(t);
}

function nomDeFichier(extension){
  const d = new Date();
  const jour = d.getFullYear() + "-" + String(d.getMonth()+1).padStart(2,"0") + "-"
    + String(d.getDate()).padStart(2,"0");
  const heure = String(d.getHours()).padStart(2,"0") + "h" + String(d.getMinutes()).padStart(2,"0");
  const source = document.getElementById("paroles").value.replace(/\[[^\]]*\]/g, " ")
    || document.getElementById("style").value;
  const mots = source.normalize("NFD").replace(/[^\x00-\x7F]/g, "")
    .toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+/, "").slice(0, 40).replace(/-+$/, "");
  return jour + "-" + heure + "-" + (mots || "chanson") + extension;
}

function echapper(t){
  return String(t).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[c]));
}

function afficherChanson(j){
  const r = j.resume || {};
  const nom = nomDeFichier(".flac");
  const lien = j.son_url + "&telecharger=1&nom=" + encodeURIComponent(nom);
  let html = '<audio id="lecteur" controls src="' + j.son_url + '"></audio>'
    + '<div class="ligne"><a class="bouton" href="' + lien + '" download="' + nom + '">⬇️ Télécharger la chanson</a>'
    + '<span class="avert">Fichier FLAC, sans perte, 48 kHz stéréo.</span></div>';
  const notes = [];
  // Le 17/09, un rendu a produit 60 s d'audio depuis une partition de 422 lignes
  // ne contenant PAS UNE SEULE note : le plan avait atteint son plafond de jetons
  // en bouclant sur une mesure vide. Rien a l'ecran ne le disait -- seul
  // << coupee.son >> etait rapporte. Une partition tronquee est pourtant la panne
  // la plus grave des deux : elle vide le morceau au lieu de l'ecourter.
  if(r.coupee && r.coupee.partition) notes.push("Le modèle n’a pas fini d’écrire sa partition : il a atteint son plafond de notes. Le morceau peut tourner en rond, voire ne contenir aucune note jouée.");
  if(r.coupee && r.coupee.son) notes.push("La chanson a atteint la durée choisie : elle s’arrête là, sans fin composée.");
  if(r.chemin && r.chemin.indexOf("officiel") !== 0) notes.push("Calculée par le chemin non officiel (" + echapper(r.chemin) + ").");
  (r.avertissements || []).forEach(a => notes.push(echapper(a)));
  if(j.chanson && j.chanson.balise_ajoutee) notes.push("Vos paroles n’avaient aucune section : elles ont été chantées comme un seul couplet.");
  if(notes.length) html += '<p class="avert">' + notes.join("<br>") + "</p>";
  if(j.partition){
    html += '<details open><summary>Voir la partition composée</summary>'
      + '<div id="portee" class="portee"></div>'
      + '<p id="note-surlignage" class="avert"></p>'
      + '<details><summary>La même en notation ABC (texte)</summary><pre>'
      + echapper(j.partition) + '</pre></details></details>';
  }
  document.getElementById("resultat").innerHTML = html;
  // Le dessin vient APRES l'insertion : avant, le div n'existe pas encore.
  if(j.partition) dessinerPortee(j.partition, (j.resume || {}).secondes_audio || 0);
}

// Dessine la partition en vraies portees. Ne casse jamais la page : si la
// bibliotheque n'a pas pu se charger, ou si cet ABC-la ne lui plait pas, on le
// DIT, et la notation texte reste lisible juste en dessous. Un echec muet
// ferait chercher la panne ailleurs.
function dessinerPortee(abc, secondesAudio){
  const cible = document.getElementById("portee");
  if(!cible) return;
  const lib = (typeof ABCJS !== "undefined") ? ABCJS
            : (typeof abcjs !== "undefined" ? abcjs : null);
  if(!lib){
    cible.innerHTML = '<p class="avert">La portée n’a pas pu être dessinée : '
      + 'bibliothèque absente. La notation ABC reste lisible ci-dessous.</p>';
    return;
  }
  try {
    // La valeur de retour etait JETEE. C'est elle qui porte le minutage des
    // notes et les noeuds SVG a colorer : sans elle, aucun surlignage possible.
    const objets = lib.renderAbc(cible, abc, {responsive:"resize"});
    suivreAuSon(objets && objets[0], secondesAudio);
  } catch(e) {
    cible.innerHTML = '<p class="avert">Cette partition n’a pas pu être dessinée : '
      + echapper(String((e && e.message) || e))
      + '. La notation ABC reste lisible ci-dessous.</p>';
  }
}

// Surligne la note en cours, facon karaoke. Demande de l'utilisateur le 17/09 :
// « pourrais-je avoir un highlight style caraoke sur les notes de musique qd
// elles sont jouees ».
//
// CE QUE CA SUIT, ET CE QUE CA NE SUIT PAS. La page joue le FLAC rendu par le
// modele ; la portee montre la partition qu'il a ECRITE. Rien ne garantit qu'il
// ait chante au tempo qu'il a note. On recale donc lineairement la partition sur
// la duree REELLE du son : le reperage devient exact aux deux bouts et l'erreur
// au milieu reste bornee, au lieu de s'accumuler comme au tempo brut. Le rapport
// est affiche ; loin de 1, la page dit elle-meme que le repere est grossier.
// AUCUNE ECOUTE n'a jamais valide ce reglage sur ce projet -- la page le dit
// aussi, plutot que de laisser croire a une synchronisation verifiee.
function suivreAuSon(visuel, secondesAudio){
  const note = document.getElementById("note-surlignage");
  const audio = document.getElementById("lecteur");
  if(!visuel || !audio || !note) return;
  let evenements = [];
  let totalPartition = 0;
  try {
    // setTiming(0, 0) : le 0 veut dire « garde le tempo ecrit dans la partition »,
    // le Q:1/4=96 que le modele pose lui-meme en tete de ses ABC.
    visuel.setTiming(0, 0);
    totalPartition = visuel.getTotalTime() || 0;
    evenements = (visuel.noteTimings || [])
      .filter(t => t.elements && t.elements.length)
      .map(t => ({ms: t.milliseconds, noeuds: [].concat.apply([], t.elements)}));
  } catch(e){
    note.textContent = "Les notes de cette partition n’ont pas pu être repérées dans le temps : "
      + String((e && e.message) || e) + ". La chanson s’écoute normalement.";
    return;
  }
  if(!evenements.length || !(totalPartition > 0)){
    note.textContent = "Cette partition ne contient aucune note repérable dans le temps : "
      + "il n’y a rien à surligner.";
    return;
  }

  function dureeSon(){
    // audio.duration est la seule mesure vraie, mais elle n'arrive qu'avec
    // l'en-tete du fichier ; d'ici la, on se rabat sur le compte du serveur.
    const d = audio.duration;
    return (isFinite(d) && d > 0) ? d : (secondesAudio > 0 ? secondesAudio : 0);
  }
  let courant = -1;
  function eteindre(){
    if(courant >= 0){
      evenements[courant].noeuds.forEach(n => n.classList.remove("surligne"));
    }
    courant = -1;
  }
  function placer(){
    const son = dureeSon();
    if(!(son > 0)) return;
    const ms = audio.currentTime * (totalPartition / son) * 1000;
    let i = 0;
    while(i + 1 < evenements.length && evenements[i + 1].ms <= ms){ i++; }
    if(i === courant) return;
    eteindre();
    courant = i;
    evenements[i].noeuds.forEach(n => n.classList.add("surligne"));
  }
  let anim = null;
  function boucle(){
    // Un nouveau lancement remplace tout le bloc resultat : le lecteur d'avant
    // est detache mais reste « en train de jouer » pour le navigateur. Sans ce
    // garde, sa boucle tournerait sans fin sur des noeuds plus affiches.
    if(audio.paused || audio.ended || !document.body.contains(audio)){ anim = null; return; }
    placer();
    anim = requestAnimationFrame(boucle);
  }
  audio.addEventListener("play", () => { if(anim === null){ anim = requestAnimationFrame(boucle); } });
  audio.addEventListener("pause", () => { if(anim !== null){ cancelAnimationFrame(anim); anim = null; } });
  audio.addEventListener("ended", () => {
    if(anim !== null){ cancelAnimationFrame(anim); anim = null; }
    eteindre();
  });
  audio.addEventListener("seeked", placer);
  audio.addEventListener("loadedmetadata", annoncer);
  // requestAnimationFrame NE S'EXECUTE PAS dans un onglet en arriere-plan :
  // constate le 17/09, le curseur restait fige sur la premiere note pendant
  // 8,9 s de lecture reelle. « timeupdate » est emis meme onglet cache (environ
  // 4 fois par seconde) : il rattrape le retard, la boucle fluide reprenant la
  // main des que l'onglet redevient visible. Sans lui, revenir sur l'onglet
  // ferait sauter le curseur au lieu de le faire avancer.
  audio.addEventListener("timeupdate", placer);

  function annoncer(){
    const son = dureeSon();
    if(!(son > 0)){
      note.textContent = "Le surlignage suit la partition écrite ; la durée réelle du son "
        + "n’est pas encore connue.";
      return;
    }
    const ecart = Math.round(Math.abs(totalPartition / son - 1) * 100);
    let texte = "Le surlignage suit la partition écrite (" + totalPartition.toFixed(1)
      + " s au tempo que le modèle a noté), recalée sur les " + son.toFixed(1)
      + " s réellement chantées.";
    if(ecart >= 15){
      texte += " L’écart entre les deux est de " + ecart + " % : le modèle n’a pas chanté "
        + "au tempo qu’il avait écrit, le repère est donc grossier.";
    }
    texte += " Personne n’a vérifié à l’oreille que la note surlignée est bien celle "
      + "qu’on entend.";
    note.textContent = texte;
  }
  annoncer();
}

function suivre(id){
  const etat = document.getElementById("etat");
  minuteur = setInterval(() => {
    fetch("/chanson/jobs/" + id, {headers:{"Authorization":"Bearer "+CLE}})
      .then(r => r.json())
      .then(j => {
        if(["running","queued","preparing","submitting"].indexOf(j.status) >= 0){
          const t = Math.round((Date.now()/1000) - (j.created_at || Date.now()/1000));
          etat.innerHTML = "⏳ En cours depuis " + t + " s. La première chanson est la plus "
            + "longue : le modèle se télécharge.";
          montrerArret(id);
          return;
        }
        clearInterval(minuteur); minuteur = null;
        cacherArret();
        document.getElementById("lancer").disabled = false;
        afficherJournal([j.stdout, j.stderr].filter(Boolean).join("\n"));
        rafraichir();
        if(j.son_url){
          const r = j.resume || {};
          etat.innerHTML = '<span class="ok">✔ Chanson prête</span> — '
            + (r.secondes_audio ? r.secondes_audio + " s de chanson, " + r.secondes_calcul + " s de calcul" : "");
          afficherChanson(j);
        } else if(j.status === "cancelled"){
          // Un arret VOULU n'est pas une panne. Le 17/09, le premier essai du
          // bouton a affiche en rouge « Modal unavailable: NotFoundError ...
          // already shut down » : c'etait la preuve que l'arret avait REUSSI,
          // presentee comme une panne, et en anglais. L'utilisateur ne pouvait
          // pas distinguer son propre arret d'un plantage du service.
          etat.innerHTML = '<span class="avert">⛔ Arrêté à votre demande.</span> '
            + echapper(j.arret_detail || "");
        } else {
          etat.innerHTML = '<span class="ko">✖ Échec</span> — ' + echapper(j.message || "voir le détail technique.");
        }
      })
      .catch(() => {});
  }, 5000);
}

document.getElementById("lancer").addEventListener("click", () => {
  const bouton = document.getElementById("lancer");
  const etat = document.getElementById("etat");
  const ou = document.getElementById("ou").value;
  const corps = {
    style: document.getElementById("style").value,
    paroles: document.getElementById("paroles").value,
    duree: document.getElementById("duree").value,
    ou: ou,
    // Sans cette ligne, le menu s'affiche, change le libelle du bouton et montre
    // sa licence -- puis le serveur compose avec le modele qui CHANTE, alors
    // qu'on vient de choisir l'instrumental. Rien a l'ecran ne le dirait.
    lora: estLora(),
  };
  bouton.disabled = true;
  etat.textContent = "Envoi…";
  document.getElementById("resultat").innerHTML = "";
  afficherJournal("");
  fetch("/chanson/creer", {method:"POST", headers:ENTETES, body:JSON.stringify(corps)})
    .then(async r => {
      const d = await r.json().catch(() => ({}));
      if(!r.ok){ throw new Error(d.detail || ("HTTP " + r.status)); }
      return d;
    })
    .then(d => { etat.textContent = "⏳ Lancé."; suivre(d.id); })
    .catch(e => {
      bouton.disabled = false;
      etat.innerHTML = '<span class="ko">✖ ' + echapper(e.message) + "</span>";
    });
});

// LE BOUTON VIT HORS DE #etat, ET C'EST VOULU. suivre() reecrit
// etat.innerHTML toutes les 5 secondes : un bouton pose dedans serait detruit
// et recree a chaque tour, et l'etat << Arret demande... >> disparaitrait sous
// les doigts. Ici il est cree une fois, on ne fait que le montrer ou le cacher.
let travailEnCours = null;

function montrerArret(id){
  travailEnCours = id;
  const b = document.getElementById("arreter");
  if(b.hidden){ b.hidden = false; b.disabled = false; b.textContent = "⛔ Arrêt d’urgence"; }
}

function cacherArret(){
  travailEnCours = null;
  document.getElementById("arreter").hidden = true;
  document.getElementById("arreter-texte").textContent = "";
}

document.getElementById("arreter").addEventListener("click", () => {
  if(!travailEnCours){ return; }
  const b = document.getElementById("arreter");
  const t = document.getElementById("arreter-texte");
  b.disabled = true;
  b.textContent = "Arrêt demandé…";
  fetch("/jobs/" + travailEnCours + "/arreter", {method:"POST", headers:ENTETES})
    .then(async r => {
      const d = await r.json().catch(() => ({}));
      if(!r.ok){ throw new Error(d.detail || ("HTTP " + r.status)); }
      return d;
    })
    .then(d => { t.textContent = d.detail || ""; })
    .catch(e => {
      b.disabled = false;
      b.textContent = "⛔ Arrêt d’urgence";
      t.innerHTML = '<span class="ko">✖ ' + echapper(e.message) + "</span>";
    });
});

rafraichir();
reelCharger();
</script>
</body></html>"""
