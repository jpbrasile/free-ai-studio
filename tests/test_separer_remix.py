"""Le fond continu d'un lieu (separer/remix.py, 05/10/2026). numpy seul : ni torch ni
DeepFilterNet ici, la voix « séparée » est fabriquée."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

_spec = importlib.util.spec_from_file_location(
    "separer_remix", Path(__file__).resolve().parents[1] / "separer" / "remix.py")
remix = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(remix)

SR = 8000


def _bruit(secondes, db, graine):
    x = np.random.default_rng(graine).standard_normal((int(secondes * SR), 2)).astype(np.float32)
    return x * 10 ** (db / 20)


def _voix(secondes, paroles):
    """Une voix : un son de 300 Hz à −20 dB sur chaque (début, fin), silence ailleurs."""
    v = np.zeros((int(secondes * SR), 2), np.float32)
    t = np.arange(len(v)) / SR
    for a, b in paroles:
        dedans = (t >= a) & (t < b)
        v[dedans] = (0.14 * np.sin(2 * np.pi * 300 * t[dedans]))[:, None]
    return v


def test_le_motif_est_le_plus_long_passage_loin_des_repliques():
    voix = _voix(10, [(5.0, 6.5)])
    a, b = remix.passage_sans_voix(voix, SR, 0, len(voix))
    # 0 à 5,0 s sans voix, moins la marge de 0,5 s avant la réplique
    assert a == 0 and abs(b / SR - (5.0 - remix.MARGE_VOIX_S)) <= remix.TRAME_S


def test_un_clip_qui_parle_tout_le_temps_n_a_pas_de_motif():
    voix = _voix(6, [(0.5, 2.0), (2.6, 4.0), (4.6, 6.0)])
    assert remix.passage_sans_voix(voix, SR, 0, len(voix)) is None


def test_la_boucle_couvre_la_duree_sans_trou():
    motif = _bruit(2.5, -40, 1)
    nappe = remix.boucler(motif, int(9 * SR), SR)
    assert len(nappe) == 9 * SR
    assert remix.niveaux(nappe, SR).min() > -50   # le fondu à puissance constante ne creuse pas


def test_le_fond_d_un_lieu_continue_sous_ses_coupes():
    """Deux clips du même lieu, chacun son fond (−50 et −35 dB) : après remix, le second a le
    fond du premier ; la voix reste."""
    fond = np.concatenate([_bruit(8, -50, 1), _bruit(8, -35, 2)])
    voix = _voix(16, [(5.0, 6.5), (11.0, 12.5)])
    sortie, rapport = remix.remixer(fond + voix, voix, SR, [8.0, 16.0], ["jardin", "jardin"])
    assert rapport["lieux"][0]["fond"][0] == 0.0
    second = remix.niveaux(sortie[int(8.5 * SR):int(10.5 * SR)], SR)
    assert np.median(second) < -44   # le fond du second clip est celui du lieu, pas le sien
    assert np.allclose(sortie[int(11.2 * SR):int(12.3 * SR)].std(), voix[int(11.2 * SR):int(12.3 * SR)].std(),
                       rtol=0.2)


def test_la_porte_rend_un_bruit_net_au_dessus_du_fond():
    """Un pas (−25 dB) que la voix n'a pas pris passe ; le fond propre du clip, lui, est remplacé."""
    fond = _bruit(10, -50, 3)
    voix = _voix(10, [(6.0, 7.0)])
    film = fond + voix
    pas = (int(8.0 * SR), int(8.3 * SR))
    film[pas[0]:pas[1]] += _bruit(0.3, -25, 4)
    sortie, _ = remix.remixer(film, voix, SR, [10.0], [0])
    assert remix.niveaux(sortie[pas[0]:pas[1]], SR).mean() > -30


def test_un_lieu_sans_passage_libre_garde_son_son():
    voix = _voix(6, [(0.5, 2.0), (2.6, 4.0), (4.6, 6.0)])
    film = _bruit(6, -40, 5) + voix
    sortie, rapport = remix.remixer(film, voix, SR, [6.0], ["gare"])
    assert rapport["lieux"][0]["fond"] is None and np.array_equal(sortie, np.clip(film, -1, 1))


def test_deux_lieux_ont_chacun_leur_fond():
    fond = np.concatenate([_bruit(8, -50, 1), _bruit(8, -30, 2), _bruit(8, -50, 6)])
    voix = _voix(24, [(5.5, 6.5), (13.5, 14.5), (21.5, 22.5)])
    sortie, rapport = remix.remixer(fond + voix, voix, SR, [8.0, 16.0, 24.0], ["a", "b", "a"])
    assert [x["clips"] for x in rapport["lieux"]] == [[1, 3], [2]]
    assert np.median(remix.niveaux(sortie[int(9 * SR):int(12 * SR)], SR)) > -35   # « b » garde le sien


def test_un_clip_muet_ne_donne_pas_son_silence_au_lieu():
    """Le premier clip a eu son son coupé au montage : le fond vient du second."""
    fond = np.concatenate([np.zeros((8 * SR, 2), np.float32), _bruit(8, -45, 8)])
    voix = _voix(16, [(13.0, 14.0)])
    voix[:8 * SR] = 0
    sortie, rapport = remix.remixer(fond + voix, voix, SR, [8.0, 16.0], [0, 0])
    assert rapport["lieux"][0]["fond"][0] >= 8.0
    assert np.median(remix.niveaux(sortie[SR:7 * SR], SR)) > -50   # le clip muet reçoit le fond du lieu


def test_bornes_et_lieux_doivent_aller_ensemble():
    x = _bruit(4, -40, 7)
    with pytest.raises(ValueError):
        remix.remixer(x, x * 0, SR, [2.0, 4.0], [0])
    with pytest.raises(ValueError):
        remix.remixer(x, x * 0, SR, [2.0, 2.0], [0, 0])
