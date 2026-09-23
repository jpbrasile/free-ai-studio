"""Surlignage karaoke : une chanson COUPEE ne se recale pas sur toute sa partition.

Signale le 23/09/2026 : « la synchro de la partition n'est pas toujours
synchrone ». YuE2 ecrit toute la partition, puis chante jusqu'a la duree
choisie : le son coupe n'est que le debut du papier. Mesure le meme jour sur
les 20 chansons reussies : partition / son = 1,01 a 1,07 sur les 9 entieres,
1,19 a 18,3 sur les 11 coupees -- le recalage lineaire faisait filer le
curseur devant la voix, jusqu'a 18 fois trop vite.

La fonction de la page est executee pour de bon dans node, sur un faux lecteur.
"""
from __future__ import annotations

import json
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

LOCAL = "http://127.0.0.1:8020"

FAUX = r"""
const classes = () => { const s = new Set(); return {add: c => s.add(c), remove: c => s.delete(c), has: c => s.has(c)}; };
const noeuds = [0, 1, 2].map(() => ({classList: classes()}));
const ecouteurs = {};
const audio = {currentTime: 30, duration: 60, paused: true, ended: false,
               addEventListener: (n, f) => { (ecouteurs[n] = ecouteurs[n] || []).push(f); }};
const note = {textContent: ""};
const document = {getElementById: id => id === "lecteur" ? audio : (id === "note-surlignage" ? note : null),
                  body: {contains: () => true}};
const requestAnimationFrame = () => 0, cancelAnimationFrame = () => 0;
const fr = (v, d) => String(Math.round(v * 10) / 10);
const visuel = {setTiming: () => {}, getTotalTime: () => 150,
                noteTimings: [{milliseconds: 0, elements: [[noeuds[0]]]},
                              {milliseconds: 30000, elements: [[noeuds[1]]]},
                              {milliseconds: 75000, elements: [[noeuds[2]]]}]};
"""


def executer(page: str, coupe: bool) -> dict:
    debut = page.index("function suivreAuSon(")
    fin = page.index("\nfunction suivre(id)", debut)
    code = (FAUX + page[debut:fin]
            + "\nsuivreAuSon(visuel, 60, " + ("true" if coupe else "false") + ");\n"
            + "ecouteurs.timeupdate.forEach(f => f());\n"
            + "console.log(JSON.stringify({allumee: noeuds.findIndex(n => n.classList.has('surligne')),"
            + " note: note.textContent}));\n")
    sortie = subprocess.run(["node", "-e", code], capture_output=True, text=True,
                            encoding="utf-8", timeout=20)
    assert sortie.returncode == 0, sortie.stderr
    return json.loads(sortie.stdout)


@pytest.fixture
def page(sandbox):
    if not shutil.which("node"):
        pytest.skip("node absent")
    return TestClient(sandbox.app, base_url=LOCAL).get("/chanson").text


def test_une_chanson_coupee_suit_le_tempo_ecrit(page):
    r = executer(page, coupe=True)
    assert r["allumee"] == 1, (
        "a 30 s d'un son coupe, la note ecrite a 30 s doit etre allumee ; "
        "le recalage sur 150 s de partition fait sauter a celle de 75 s."
    )
    assert "début de la partition" in r["note"]
    assert "grossier" not in r["note"], (
        "une chanson coupee est accusee a tort de ne pas tenir son tempo."
    )


def test_une_chanson_entiere_reste_recalee(page):
    r = executer(page, coupe=False)
    assert r["allumee"] == 2, "le recalage des chansons entieres a disparu"
    assert "recalée sur les" in r["note"]


def test_la_page_transmet_la_coupure_au_surlignage(page):
    assert "!!((j.resume || {}).coupee || {}).son" in page
    assert "suivreAuSon(objets && objets[0], secondesAudio, sonCoupe)" in page
