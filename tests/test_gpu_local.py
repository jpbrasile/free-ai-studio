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
import subprocess
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location(
    "gpu_local", RACINE / "sandbox-manager" / "gpu_local.py"
)
gpu_local = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = gpu_local
_spec.loader.exec_module(gpu_local)

# Exactement ce que la carte a rendu le 19/09/2026 depuis le conteneur.
RELEVE_REEL = "NVIDIA GeForce RTX 4090, 24564, 24138\n"


class _Sortie:
    def __init__(self, code=0, stdout="", stderr=""):
        self.returncode = code
        self.stdout = stdout
        self.stderr = stderr


@pytest.fixture
def carte(monkeypatch):
    """Une carte presente, dont on choisit la sortie."""
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
    assert "24138" in phrase and "8000" in phrase
    assert etat["libre_mo"] == 24138


def test_carte_occupee_refuse_sans_arreter_personne(carte):
    """Le cas reel du 04/09 : un serveur LLM tient 15,5 Go sur la carte."""
    carte(_Sortie(stdout="NVIDIA GeForce RTX 4090, 24564, 8600\n"))
    oui, phrase, _ = gpu_local.utilisable(16000)
    assert oui is False
    assert "8600" in phrase
    assert "on n'arrete personne" in phrase


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
