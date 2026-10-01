"""Le pont facultatif entre la file de la carte du Studio et la file d'attente de ce PC (scripts/pont_carte.py).

Ce qui est jugé, sans carte, sans llama, sans file dsh3 : la machine est remplacée par un faux.
1. `liberer` n'arrête llama que si le Studio a encore du travail, lance la garde AVANT l'arrêt, tient la carte
   tant que le Studio en a besoin (avec la grâce entre deux plans), puis relance llama ;
2. un échec de l'arrêt est écrit, et rien n'est relancé qui n'a pas été arrêté ;
3. la garde : lanceur encore là -> elle attend ; lanceur mort, llama arrêté -> elle relance, une fois la carte
   rendue ; lanceur fini proprement (llama écoute) -> elle ne fait rien ;
4. `veiller` ne dépose qu'un pont à la fois, et seulement quand le Studio attend.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_chemin = Path(__file__).resolve().parents[1] / "scripts" / "pont_carte.py"
_spec = importlib.util.spec_from_file_location("pont_carte", _chemin)
pc = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = pc
_spec.loader.exec_module(pc)


@pytest.fixture(autouse=True)
def journal_isole(tmp_path, monkeypatch):
    monkeypatch.setattr(pc, "JOURNAL", str(tmp_path / "pont.jsonl"))


class Horloge:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def dormir(self, s):
        self.t += s


class FausseMachine:
    def __init__(self, ecoute=True, arret_ok=True):
        self.profil = "defaut-1x64k"
        self.ecoute, self.arret_ok = ecoute, arret_ok
        self.actes = []

    def attendre_repos(self):
        self.actes.append("repos")
        return ["places"], 0.0

    def llama_ecoute(self):
        return self.ecoute

    def arreter_llama(self):
        self.actes.append("arret")
        if self.arret_ok:
            self.ecoute = False
        return self.arret_ok, "arrete" if self.arret_ok else "slot au travail"

    def relancer_llama(self, profil):
        self.actes.append("relance " + profil)
        self.ecoute = True
        return {"rc": 0}

    def rendre(self, fds):
        self.actes.append("rendre %s" % fds)


def _suite(*valeurs):
    """lire() qui rend ces valeurs puis la dernière, indéfiniment."""
    it = iter(valeurs)
    der = [valeurs[-1]]

    def lire():
        try:
            der[0] = next(it)
        except StopIteration:
            pass
        return der[0]
    return lire


def test_liberer_garde_avant_arret_tient_puis_relance():
    m, h, gardes = FausseMachine(), Horloge(), []
    ordre = []
    m_arreter = m.arreter_llama
    m.arreter_llama = lambda: (ordre.append("arret"), m_arreter())[1]
    lancer = lambda pid, profil: (ordre.append("garde"), gardes.append(profil), 4242)[2]
    # 1er appel : la vérification avant l'arrêt ; puis 2 travaux, 1, 0 (un plan monté), 1, puis plus rien
    rc = pc.liberer(m, lancer=lancer, lire=_suite(2, 2, 1, 0, 1, 0), dormir=h.dormir, horloge=h,
                    grace_s=60, sonde_s=20)
    assert rc == 0
    assert ordre == ["garde", "arret"], "la garde doit partir AVANT que llama soit arrêté"
    assert gardes == ["defaut-1x64k"]
    assert m.actes[0] == "repos" and m.actes[-2:] == ["rendre ['places']", "relance defaut-1x64k"]
    lignes = Path(pc.JOURNAL).read_text(encoding="utf-8")
    assert "plus rien pour la carte" in lignes and '"garde": 4242' in lignes


def test_liberer_ne_rend_pas_la_carte_entre_deux_plans():
    h = Horloge()
    # vide 40 s (moins que la grâce de 60 s), puis un plan revient : on tient toujours
    s, motif = pc.tenir(_suite(1, 0, 0, 1, 1, 0), dormir=h.dormir, horloge=h, grace_s=60, max_s=10_000, sonde_s=20)
    assert motif == "plus rien pour la carte"
    assert s == 160  # 5 sondes de 20 s avant le dernier vide, puis 60 s de grâce


def test_studio_muet_rend_la_carte_et_le_plafond_aussi():
    h = Horloge()
    assert pc.tenir(lambda: None, dormir=h.dormir, horloge=h, grace_s=60, sonde_s=20)[1] == "Studio muet"
    h = Horloge()
    assert pc.tenir(lambda: 1, dormir=h.dormir, horloge=h, grace_s=60, max_s=100, sonde_s=20)[1] \
        == "plafond de 100 s atteint"


def test_liberer_annule_pendant_l_attente_ne_touche_pas_llama():
    m = FausseMachine()
    rc = pc.liberer(m, lancer=lambda *a: pytest.fail("pas de garde"), lire=lambda: 0)
    assert rc == 0
    assert "arret" not in m.actes and not any(a.startswith("relance") for a in m.actes)
    assert m.actes[-1] == "rendre ['places']"


def test_liberer_arret_refuse_ecrit_l_echec_sans_relancer():
    m, h = FausseMachine(arret_ok=False), Horloge()
    rc = pc.liberer(m, lancer=lambda *a: 1, lire=lambda: 1, dormir=h.dormir, horloge=h)
    assert rc == 1
    assert not any(a.startswith("relance") for a in m.actes)
    assert "slot au travail" in Path(pc.JOURNAL).read_text(encoding="utf-8")


def test_liberer_llama_deja_arrete_tient_sans_relancer():
    m, h = FausseMachine(ecoute=False), Horloge()
    rc = pc.liberer(m, lancer=lambda *a: pytest.fail("pas de garde"), lire=_suite(1, 1, 0),
                    dormir=h.dormir, horloge=h, grace_s=20, sonde_s=20)
    assert rc == 0 and "arret" not in m.actes and not any(a.startswith("relance") for a in m.actes)


def test_garde_attend_le_lanceur_puis_le_conteneur_puis_relance():
    m, h = FausseMachine(ecoute=False), Horloge()
    vies, conteneurs = iter([True, True, False]), iter([True, False])
    pc.garde(77, 1.5, "defaut-1x64k", conteneur="studio-maison-77", m=m,
             en_vie=lambda pid, cree: next(vies), present=lambda nom: next(conteneurs), dormir=h.dormir)
    assert m.actes == ["relance defaut-1x64k"]
    assert h.t == 2 * 10 + 15
    assert "lanceur disparu" in Path(pc.JOURNAL).read_text(encoding="utf-8")


def test_garde_attend_que_le_studio_rende_la_carte():
    m, h = FausseMachine(ecoute=False), Horloge()
    pc.garde(77, None, "p", m=m, en_vie=lambda *a: False, lire=_suite(1, 1, 0), dormir=h.dormir, horloge=h,
             grace_s=40, sonde_s=20)
    assert m.actes == ["relance p"] and h.t == 80


def test_garde_ne_fait_rien_si_le_lanceur_a_relance():
    m = FausseMachine(ecoute=True)
    pc.garde(77, None, "p", conteneur="c", m=m, en_vie=lambda *a: False, present=lambda n: False,
             dormir=lambda s: None)
    assert m.actes == []


def test_vivant_compare_l_heure_de_creation(monkeypatch):
    monkeypatch.setattr(pc, "_cree", lambda pid: 100.0)
    assert pc.vivant(1, 100.0) and pc.vivant(1, None)
    assert not pc.vivant(1, 99.0), "un PID réutilisé n'est pas le lanceur"
    monkeypatch.setattr(pc, "_cree", lambda pid: None)
    assert not pc.vivant(1, 100.0)


def test_veiller_un_seul_pont_et_seulement_quand_le_studio_attend():
    deposes, en_file = [], [False]

    def deposer():
        deposes.append(1)
        en_file[0] = True
        return 0, "ok"
    pc.veiller(lire=_suite(0, None, 2, 2, 1), deja=lambda: en_file[0], deposer=deposer,
               dormir=lambda s: None, tours=5)
    assert len(deposes) == 1


def test_pont_en_file_lit_attente_et_encours(tmp_path):
    for d in ("attente", "encours"):
        (tmp_path / d).mkdir()
    assert not pc.pont_en_file(str(tmp_path))
    (tmp_path / "attente" / "20261001-1-m6-p1-t21.json").write_text("{}")
    assert not pc.pont_en_file(str(tmp_path))
    (tmp_path / "encours" / "20261001-2-studio-pont-carte.json").write_text("{}")
    assert pc.pont_en_file(str(tmp_path))


def test_deposer_passe_sans_suspension_et_ressource_gpu(monkeypatch):
    vu = {}

    class R:
        returncode, stdout, stderr = 0, "depose", ""
    monkeypatch.setattr(pc.subprocess, "run", lambda cmd, **kw: (vu.setdefault("cmd", cmd), R())[1])
    assert pc.deposer_liberer()[0] == 0
    cmd = vu["cmd"]
    assert cmd[cmd.index("--ressources") + 1] == "gpu" and "--sans-suspension" in cmd
    assert cmd[cmd.index("--nom") + 1] == pc.NOM and cmd[-1] == "liberer"
