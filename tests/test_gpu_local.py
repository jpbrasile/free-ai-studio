"""La sonde de la carte locale : elle mesure, ou elle dit honnetement qu'elle ne sait pas.

Ce que ces tests gardent, defaut par defaut :

1. une sortie normale de nvidia-smi est lue correctement -- le format teste ici
   est CELUI mesure le 19/09/2026 depuis le conteneur du bac a sable avec la
   surcouche GPU : << NVIDIA GeForce RTX 4090, 24564, 24138 >> ;
2. **rien ne remonte en exception** : pas de nvidia-smi, code d'erreur, sortie
   illisible, delai depasse -- chacun rend << aucune carte vue >> avec son
   motif, et le routage part chez Modal comme avant. Une sonde qui casse le
   Studio parce qu'une carte manque serait pire que pas de sonde du tout ;
3. **la marge est prise sur la memoire LIBRE, pas sur la totale** : une carte
   occupee par un autre travail refuse, et le message dit qu'on va ailleurs
   plutot que d'arreter qui que ce soit ;
4. l'interrupteur GPU_LOCAL_ACTIF=false eteint tout sans rien deplacer.

Aucun appel reel a nvidia-smi : tout passe par une fausse commande.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]

# `sandbox-manager` entre dans le chemin AVANT l'exec : le module a des freres
# (`format_fr`) et un chargement par fichier seul ne les trouve pas. Le 22/09,
# ce fichier passait dans la suite entiere et ECHOUAIT seul, parce qu'un autre
# test avait deja mis `format_fr` dans `sys.modules`. Un test qui ne passe
# qu'apres un autre est un vert d'emprunt.
sys.path.insert(0, str(RACINE / "sandbox-manager"))
_spec = importlib.util.spec_from_file_location(
    "gpu_local", RACINE / "sandbox-manager" / "gpu_local.py"
)
gpu_local = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = gpu_local
_spec.loader.exec_module(gpu_local)
format_fr = sys.modules["format_fr"]

# Exactement ce que la carte a rendu le 19/09/2026 depuis le conteneur.
RELEVE_REEL = "NVIDIA GeForce RTX 4090, 24564, 24138\n"


class _Sortie:
    def __init__(self, code=0, stdout="", stderr=""):
        self.returncode = code
        self.stdout = stdout
        self.stderr = stderr


def _poser_hote(chemin, locataires=(), age_s=0.0):
    """Le fichier que la sonde de l'hote ecrit, tel qu'elle l'ecrit."""
    chemin.write_text(json.dumps({
        "ecrit_le_epoch": time.time() - age_s,
        "locataires": list(locataires),
    }), encoding="utf-8")


@pytest.fixture
def hote(monkeypatch, tmp_path):
    """Le relevé de l'hote : frais et vide par defaut. Rend son chemin."""
    chemin = tmp_path / "etat-carte-hote.json"
    _poser_hote(chemin)
    monkeypatch.setattr(gpu_local, "FICHIER_HOTE", str(chemin))
    return chemin


@pytest.fixture
def carte(monkeypatch, hote):
    """Une carte presente, dont on choisit la sortie. L'hote dit que personne
    d'autre ne la tient : les tests de l'hote le contredisent eux-memes."""
    monkeypatch.setattr(gpu_local, "ACTIF", True)
    monkeypatch.setattr(gpu_local, "MARGE_MO", 1024)
    monkeypatch.setattr(gpu_local.shutil, "which", lambda _: "/usr/bin/nvidia-smi")

    def poser(sortie):
        monkeypatch.setattr(gpu_local.subprocess, "run", lambda *a, **k: sortie)

    return poser


def test_sortie_reelle_lue_correctement(carte):
    carte(_Sortie(stdout=RELEVE_REEL))
    etat = gpu_local.releve()
    assert etat["vue"] is True
    assert etat["nom"] == "NVIDIA GeForce RTX 4090"
    assert (etat["totale_mo"], etat["libre_mo"]) == (24564, 24138)


def test_sans_nvidia_smi_aucune_carte(monkeypatch):
    """Cas du debutant sans carte, et cas de la surcouche non appliquee."""
    monkeypatch.setattr(gpu_local, "ACTIF", True)
    monkeypatch.setattr(gpu_local.shutil, "which", lambda _: None)
    etat = gpu_local.releve()
    assert etat["vue"] is False
    assert "docker-compose.gpu.yml" in etat["motif"]


def test_interrupteur_eteint(monkeypatch):
    monkeypatch.setattr(gpu_local, "ACTIF", False)
    etat = gpu_local.releve()
    assert etat["vue"] is False
    assert "GPU_LOCAL_ACTIF" in etat["motif"]


def test_code_de_retour_non_nul(carte):
    carte(_Sortie(code=9, stderr="Failed to initialize NVML: Unknown Error\n"))
    etat = gpu_local.releve()
    assert etat["vue"] is False
    assert "NVML" in etat["motif"]


@pytest.mark.parametrize("brut", ["", "\n", "bonjour", "4090, beaucoup, un peu"])
def test_sortie_illisible_ne_leve_jamais(carte, brut):
    carte(_Sortie(stdout=brut))
    etat = gpu_local.releve()
    assert etat["vue"] is False
    assert etat["libre_mo"] is None


def test_delai_depasse_ne_leve_jamais(monkeypatch):
    monkeypatch.setattr(gpu_local, "ACTIF", True)
    monkeypatch.setattr(gpu_local.shutil, "which", lambda _: "/usr/bin/nvidia-smi")

    def trop_lent(*a, **k):
        raise subprocess.TimeoutExpired(cmd="nvidia-smi", timeout=10)

    monkeypatch.setattr(gpu_local.subprocess, "run", trop_lent)
    etat = gpu_local.releve()
    assert etat["vue"] is False
    assert "TimeoutExpired" in etat["motif"]


def test_carte_libre_accepte_et_donne_les_chiffres(carte):
    carte(_Sortie(stdout=RELEVE_REEL))
    oui, phrase, etat = gpu_local.utilisable(8000)
    assert oui is True
    # Le chiffre doit rester lisible, ET groupe : la barre est la meme
    # qu'avant, plus l'exigence que cinq chiffres ne se lisent pas d'affilee.
    assert format_fr.en_memoire(24138) in phrase
    assert format_fr.en_memoire(8000, "") in phrase
    assert "24138" not in phrase, "cinq chiffres colles ne se lisent pas"
    assert etat["libre_mo"] == 24138


def test_carte_occupee_refuse_sans_arreter_personne(carte):
    """Le cas reel du 04/09 : un serveur LLM tient 15,5 Go sur la carte."""
    carte(_Sortie(stdout="NVIDIA GeForce RTX 4090, 24564, 8600\n"))
    oui, phrase, _ = gpu_local.utilisable(16000)
    assert oui is False
    assert format_fr.en_memoire(8600) in phrase
    assert "on n'arrête personne" in phrase


def test_la_marge_est_prise_sur_le_libre(carte):
    """Juste la place demandee ne suffit pas : la carte peut se remplir apres la mesure."""
    carte(_Sortie(stdout="NVIDIA GeForce RTX 4090, 24564, 8000\n"))
    assert gpu_local.utilisable(8000)[0] is False
    assert gpu_local.utilisable(8000 - gpu_local.MARGE_MO)[0] is True


def test_aucune_carte_refuse_avec_son_motif(monkeypatch):
    monkeypatch.setattr(gpu_local, "ACTIF", True)
    monkeypatch.setattr(gpu_local.shutil, "which", lambda _: None)
    oui, phrase, _ = gpu_local.utilisable(1000)
    assert oui is False
    assert "nvidia-smi absent" in phrase


def test_le_compose_et_le_script_visent_le_meme_dossier_de_poids():
    """Les 34 Go doivent atterrir la ou le bac a sable ira les lire.

    Defaut mesure le 19/09 : le compose montait un volume Docker vide des que
    GPU_MODELES_DIR n'etait pas pose par le lanceur, et le Studio repondait
    << les poids ne sont pas telecharges >> avec les 34 Go sur le disque. Le
    defaut est maintenant le cache du profil, des DEUX cotes -- et ce test est
    la pour que les deux ne puissent plus diverger en silence : diverger
    coute une heure de ligne a celui qui telecharge dans le mauvais dossier."""
    compose = (RACINE / "docker-compose.gpu.yml").read_text(encoding="utf-8")
    script = (RACINE / "scripts" / "telecharger-modele-video.ps1").read_text(encoding="utf-8")

    montage = [l.strip() for l in compose.splitlines()
               if "/cache/huggingface" in l and "- $" in l]
    # Deux depuis le 20/09 : le bac a sable LIT les poids, le decideur les
    # TELECHARGE (regle du proprietaire : vider une ressource ne doit pas fermer
    # une porte). Le nombre importe peu ; ce qui doit etre vrai, c'est qu'ils
    # visent TOUS le meme dossier. Deux chemins differents ici, c'est 34 Go
    # descendus la ou personne ne les lit, et un Studio qui continue de dire
    # qu'ils manquent.
    assert len(montage) >= 1, montage
    assert len(set(montage)) == 1, montage
    assert "GPU_MODELES_DIR" in montage[0]
    assert ".cache/huggingface" in montage[0]
    # Et le decideur doit savoir ou il ecrit, sinon il ne telecharge rien.
    assert "POIDS_VIDEO_DIR: /cache/huggingface" in compose
    # `HF_HOME` couvre tout appel de la bibliotheque qui ne passerait pas par
    # notre module : sans lui, il ecrit dans `/root/.cache/huggingface`, qui
    # n'est pas monte et disparait au redemarrage (mesure du 20/09 : 0 octet
    # arrive la ou le Studio regarde).
    assert compose.count("HF_HOME: /cache/huggingface") == 2

    assert "$env:GPU_MODELES_DIR" in script
    assert r'".cache\huggingface"' in script
    # Le volume Docker n'est plus un dernier recours du script : il ne serait
    # lu par personne.
    assert '$cible = "modeles-gpu"' not in script

    # Le jumeau Linux vise le meme dossier, par les memes deux regles.
    jumeau = (RACINE / "scripts" / "telecharger-modele-video.sh").read_text(encoding="utf-8")
    assert "GPU_MODELES_DIR" in jumeau
    assert '"$HOME/.cache/huggingface"' in jumeau
    # Le volume Docker n'est pas un dernier recours ici non plus. On juge les
    # lignes de code, pas les commentaires : le commentaire, lui, EXPLIQUE
    # pourquoi ce volume n'est plus vise, et doit pouvoir le nommer.
    code = [l for l in jumeau.splitlines() if l.strip() and not l.lstrip().startswith("#")]
    assert not [l for l in code if "modeles-gpu" in l], code


def test_le_lanceur_linux_applique_la_surcouche_comme_celui_de_windows():
    """Un debutant sous Linux avec une carte doit obtenir le meme Studio.

    Defaut releve le 19/09 : `start.sh` n'ajoutait JAMAIS
    docker-compose.gpu.yml -- la carte etait la, et tous les clips partaient
    chez le loueur sans un mot. Les deux lanceurs doivent maintenant faire les
    memes quatre choses, et ce test est ce qui les empeche de diverger
    pendant qu'on ne regarde que celui de Windows.

    Ce test lit les fichiers, il ne lance rien. Ce que lui ne voit pas a ete
    joue le 20/09 dans un conteneur Linux de cette machine avec `--gpus all` :
    carte vue, surcouche ajoutee, poids absents annonces, carte muette sans
    surcouche. Reste ouvert dans PLAN.md, etape 9, GPU-1 : un hote Linux dont
    le shell et le moteur Docker partagent le disque, pour le `compose up`
    reel et le clip fabrique a la maison."""
    sh = (RACINE / "start.sh").read_text(encoding="utf-8")
    ps1 = (RACINE / "scripts" / "demarrer.ps1").read_text(encoding="utf-8")

    # 1. la surcouche, et seulement si une carte repond
    assert "nvidia-smi" in sh
    assert "-f docker-compose.gpu.yml" in sh or "docker-compose.gpu.yml" in sh
    ligne_surcouche = [l for l in sh.splitlines() if "docker-compose.gpu.yml" in l and "#" not in l]
    assert len(ligne_surcouche) == 1, ligne_surcouche
    # elle est DANS le bloc conditionnel, pas dans la commande de base
    avant = sh.split(ligne_surcouche[0])[0]
    assert avant.rstrip().endswith("then") or 'if [ -n "$carte" ]' in avant

    # 2. le meme dossier de poids que partout ailleurs
    assert '"$HOME/.cache/huggingface"' in sh
    assert "GPU_MODELES_DIR" in sh
    # 3. le meme modele sonde pour dire << les 34 Go manquent >>
    assert "models--Wan-AI--Wan2.2-TI2V-5B-Diffusers" in sh
    assert "models--Wan-AI--Wan2.2-TI2V-5B-Diffusers" in ps1
    # 4. il nomme le script qui existe de SON cote
    assert "./scripts/telecharger-modele-video.sh" in sh
    assert "telecharger-modele-video.ps1" not in sh

    # Et les deux disent au service quelle machine c'est.
    assert "STUDIO_LANCEUR=linux" in sh
    assert '$env:STUDIO_LANCEUR = "windows"' in ps1
    assert "STUDIO_LANCEUR" in (RACINE / "docker-compose.yml").read_text(encoding="utf-8")


def test_la_suppression_des_34_go_se_demande_et_ne_vise_que_le_modele():
    """Rendre les 34 Go ne doit jamais etre un geste automatique.

    Deux choses sont gardees ici, et la seconde est celle qui ferait mal.

    1. Le script DEMANDE. Pas de suppression silencieuse : le dossier vise est
       le cache Hugging Face du compte, pas un dossier du Studio, et revenir en
       arriere coute 22 minutes de ligne (mesure du 20/09).
    2. Il ne supprime que `hub/models--Wan-AI--Wan2.2-TI2V-5B-Diffusers`.
       Supprimer la RACINE du cache emporterait les modeles que la personne a
       telecharges pour ses autres outils -- ComfyUI, un carnet, un autre
       studio. C'est l'erreur qu'une simplification bien intentionnee
       ecrirait un jour, et ce test est ce qui l'arrete."""
    sh = (RACINE / "scripts" / "supprimer-modele-video.sh").read_text(encoding="utf-8")
    ps1 = (RACINE / "scripts" / "supprimer-modele-video.ps1").read_text(encoding="utf-8")

    # 1. la question est posee, et attend un mot ecrit
    assert "read -r reponse" in sh
    assert "Read-Host" in ps1
    # un appelant peut la sauter, mais seulement en le disant
    assert "--oui" in sh and "-Oui" in ps1
    # sans terminal, le .sh refuse plutot que de supposer
    assert "[ ! -t 0 ]" in sh

    # 2. LE garde-fou : ce qui est efface est le sous-dossier du modele
    for source, efface in ((sh, "rm -rf"), (ps1, "Remove-Item")):
        lignes = [l for l in source.splitlines()
                  if efface in l and not l.lstrip().startswith("#")]
        assert len(lignes) == 1, lignes
        assert "modele" in lignes[0].lower(), lignes[0]
        # jamais la racine du cache, sous aucune de ses trois ecritures
        for racine_cache in ("$cible", "$HOME/.cache/huggingface",
                             "GPU_MODELES_DIR", "$cacheHF"):
            assert racine_cache not in lignes[0], lignes[0]

    # 3. la variable du modele est bien construite sur le cache + le sous-dossier
    assert 'modele="$cible/hub/models--Wan-AI--Wan2.2-TI2V-5B-Diffusers"' in sh
    assert 'Join-Path $cible "hub\\models--Wan-AI--Wan2.2-TI2V-5B-Diffusers"' in ps1

    # 4. et le chemin du retour est nomme, pour que le choix soit reversible
    assert "telecharger-modele-video.sh" in sh
    assert "telecharger-modele-video.ps1" in ps1


def test_les_lanceurs_n_ecrasent_pas_un_dossier_de_poids_deja_choisi():
    """La variable d'abord, le cache du profil ensuite -- comme le compose.

    Trouve le 20/09/2026 en cherchant a lancer la pile depuis un shell Linux.
    `docker-compose.gpu.yml` monte `${GPU_MODELES_DIR:-<cache du profil>}` : la
    variable D'ABORD. Les six autres scripts suivent cette regle. Les deux
    LANCEURS faisaient l'inverse : ils ecrasaient une valeur deja posee.

    Le degat n'est pas theorique -- le compose prevoit noir sur blanc le cas
    << garder les poids hors du profil >>. Celui qui pose la variable voyait son
    choix remplace sans un mot, et le Studio annoncait << les 34 Go ne sont pas
    telecharges >> avec les 34 Go sur son disque : une heure de ligne pour rien,
    et les clips partis sur une machine louee entre-temps.

    Le controle des poids doit viser le dossier EFFECTIF, sinon le message
    annonce le contraire de ce qui va se passer.
    """
    sh = (RACINE / "start.sh").read_text(encoding="utf-8")
    ps1 = (RACINE / "scripts" / "demarrer.ps1").read_text(encoding="utf-8")

    assert '[ -n "${GPU_MODELES_DIR:-}" ]' in sh
    assert "if ($env:GPU_MODELES_DIR) {" in ps1

    assert 'poids="$modeles/hub/models--Wan-AI--Wan2.2-TI2V-5B-Diffusers"' in sh
    assert r'$poids = Join-Path $modeles "hub\models--Wan-AI--Wan2.2-TI2V-5B-Diffusers"' in ps1
    # L'ancienne forme, celle qui regardait a cote du montage.
    assert 'poids="$cache_hf/hub' not in sh
    assert r'$poids = Join-Path $cacheHF "hub' not in ps1


# --- REG-1 : une carte libre pour un code dont on ignore l'appetit ----------
# `utilisable()` compare a un besoin MESURE. Pour le code tape dans /essai il
# n'y a pas de besoin mesurable, et il ne peut pas y en avoir : on regarde donc
# l'autre bout, l'OCCUPATION. Tranche par le proprietaire le 21/09/2026.

def test_une_carte_que_personne_ne_tient_est_libre(carte):
    """Mesure du 21/09/2026, bureau Windows allume et rien d'autre :
    426 Mo pris sur 24 564. Le bureau ne doit pas passer pour un locataire."""
    carte(_Sortie(stdout=RELEVE_REEL))
    libre, phrase, etat = gpu_local.libre_pour_un_code_inconnu()
    assert libre is True
    assert format_fr.en_memoire(24138) in phrase
    assert "24138" not in phrase, "cinq chiffres colles ne se lisent pas"
    assert "personne d'autre" in phrase
    assert etat["libre_mo"] == 24138


def test_une_carte_prise_n_est_pas_libre(carte):
    """Le cas reel : `llama-server` tient 15,5 Go en permanence sur cette machine.

    Le prendre de force ferait perdre le travail de quelqu'un d'autre.
    """
    carte(_Sortie(stdout="NVIDIA GeForce RTX 4090, 24564, 8600\n"))
    libre, phrase, _ = gpu_local.libre_pour_un_code_inconnu()
    assert libre is False
    assert format_fr.en_memoire(15964) in phrase, "la phrase doit dire COMBIEN est pris"
    assert "on ne l'arrête jamais" in phrase


def test_une_carte_invisible_n_est_pas_libre(monkeypatch):
    """Ne pas voir la carte n'est pas la voir libre -- c'est le faux vert type."""
    monkeypatch.setattr(gpu_local, "ACTIF", True)
    monkeypatch.setattr(gpu_local.shutil, "which", lambda _: None)
    libre, phrase, _ = gpu_local.libre_pour_un_code_inconnu()
    assert libre is False
    assert "nvidia-smi absent" in phrase


def test_le_seuil_separe_le_bureau_d_un_vrai_calcul(carte):
    """Un seuil qui laisserait passer un vrai locataire ne servirait a rien,
    et un seuil qui refuserait un bureau allume rendrait la case inutile."""
    bureau = gpu_local.OCCUPATION_TOLEREE_MO
    carte(_Sortie(stdout="NVIDIA GeForce RTX 4090, 24564, %d\n" % (24564 - bureau)))
    assert gpu_local.libre_pour_un_code_inconnu()[0] is True
    carte(_Sortie(stdout="NVIDIA GeForce RTX 4090, 24564, %d\n" % (24564 - bureau - 1)))
    assert gpu_local.libre_pour_un_code_inconnu()[0] is False


# SP-CARTE-LIBRE-SONDE-AVEUGLE, 23/09/2026. Mesure du 22/09 : `julia.exe`
# PID 64216 vivant, et `memory.free` a 24 138 Mo sur 24 564 a la meme seconde.
# Ces tests rejouent ce releve : la memoire dit libre, l'hote dit pris.

JULIA = {"nom": "julia.exe", "pid": 64216}


def test_un_julia_a_zero_mo_rend_la_carte_PRISE_pour_les_deux_questions(carte, hote):
    """Le test que le sous-plan exigeait rouge avant la reparation."""
    carte(_Sortie(stdout=RELEVE_REEL))
    _poser_hote(hote, [JULIA])
    libre, phrase, _ = gpu_local.libre_pour_un_code_inconnu()
    assert libre is False
    assert "julia.exe (PID 64216)" in phrase
    assert "on ne l'arrête jamais" in phrase
    # Et pour un besoin mesure qui tiendrait largement dans la memoire libre.
    assert gpu_local.utilisable(4000)[0] is False
    # Vu sur la vraie sonde le 23/09 : six processus << tient >> la carte.
    _poser_hote(hote, [JULIA, {"nom": "julia.exe", "pid": 7}])
    assert "tiennent la carte" in gpu_local.libre_pour_un_code_inconnu()[1]


@pytest.mark.parametrize("cas", ["absent", "perime", "illisible"])
def test_un_releve_de_l_hote_douteux_rend_la_carte_PRISE(carte, hote, cas):
    """Le doute tombe du cote prudent : decision du proprietaire, 23/09/2026."""
    carte(_Sortie(stdout=RELEVE_REEL))
    if cas == "absent":
        hote.unlink()
    elif cas == "perime":
        _poser_hote(hote, age_s=gpu_local.PEREMPTION_S + 1)
    else:
        hote.write_text("{pas du json", encoding="utf-8")
    libre, phrase, _ = gpu_local.libre_pour_un_code_inconnu()
    assert libre is False
    assert "on la considère prise" in phrase
    assert gpu_local.utilisable(4000)[0] is False


def test_un_releve_frais_a_la_limite_compte_encore(carte, hote):
    """La peremption est une borne, pas une approximation : juste dessous, le
    releve vaut ; juste dessus (test du dessus), il ne vaut plus."""
    carte(_Sortie(stdout=RELEVE_REEL))
    _poser_hote(hote, age_s=gpu_local.PEREMPTION_S - 2)
    assert gpu_local.libre_pour_un_code_inconnu()[0] is True


def test_les_deux_sondes_de_l_hote_ecrivent_le_meme_fichier():
    """Le jumeau Windows et le jumeau Linux ecrivent au meme endroit, avec les
    memes champs, sur le meme rythme : sinon un des deux hotes aurait une
    carte toujours prise, ou jamais."""
    ps1 = (RACINE / "scripts" / "sonde-carte.ps1").read_text(encoding="utf-8")
    sh = (RACINE / "scripts" / "sonde-carte.sh").read_text(encoding="utf-8")
    for texte in (ps1, sh):
        assert "etat-carte-hote.json" in texte
        assert "ecrit_le_epoch" in texte
        assert "locataires" in texte
        assert "julia" in texte
    assert "etat-carte-hote.json" in gpu_local.FICHIER_HOTE
