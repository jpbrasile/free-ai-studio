"""L'essai client dit a l'assistant EXACTEMENT la phrase du README.

Sinon l'essai mesure une phrase que personne ne tapera : il passerait au vert
pendant que le README, lui, envoie ailleurs."""
from __future__ import annotations

import re
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
SCRIPT = (RACINE / "scripts" / "essai-client-linux.sh").read_text(encoding="utf-8")
README = (RACINE / "README.md").read_text(encoding="utf-8")


def test_la_phrase_de_l_essai_est_celle_du_readme():
    phrase = re.search(r'^PHRASE="(.+)"$', SCRIPT, re.M).group(1)
    assert f"> {phrase}\n" in README


def test_la_phrase_nomme_le_guide_qui_existe():
    phrase = re.search(r'^PHRASE="(.+)"$', SCRIPT, re.M).group(1)
    guide = re.search(r"(docs/\S+\.md)", phrase).group(1)
    assert (RACINE / guide).is_file()


def test_le_mode_local_n_emporte_jamais_les_cles():
    # Seul un clone nu part sur la machine d'essai : ni .env ni config/.
    assert "clone -q --bare" in SCRIPT
    assert 'docker cp "$RACINE/.' not in SCRIPT


def test_l_essai_se_juge_lui_meme_sans_croire_l_assistant():
    # Auto-test relance APRES l'assistant, fichiers suivis comptes, secrets cherches.
    assert "self-test.sh" in SCRIPT
    assert "status --porcelain --untracked-files=no" in SCRIPT
    assert "keys\\.json" in SCRIPT
