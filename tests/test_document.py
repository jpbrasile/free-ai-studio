"""La dix-septieme brique : un document devient du texte, sans aucun modele.

CE QUE CES TESTS GARDENT, et le cas qui les a fait naitre.

Le 22/09/2026, treize phrases de client ont ete passees au compilateur sur
l'installation reelle. Douze etaient justes. La treizieme --
<< Resume ce document PDF en une page >> -- compilait en `conversation`, une
brique qui attend du TEXTE. Le client aurait depose un PDF et la chaine n'aurait
pas eu de premier maillon. Le controle de types ne pouvait pas l'attraper :
aucune des seize briques ne declarait `fichier` en entree, donc ce type du
vocabulaire ne servait a rien et rien ne pouvait s'y brancher.

Trois proprietes valent plus que les autres, et chacune a son paragraphe :

  - **un PDF scanne se REFUSE** au lieu de rendre une chaine vide. C'est le seul
    endroit de ce module ou l'erreur serait silencieuse : `extract_text()` rend
    "" sans lever quoi que ce soit, et la chaine resumerait le vide. Le client
    lirait un resume confiant bati sur zero signe ;
  - **un document trop long se REFUSE** au lieu d'etre tronque. Tronquer rendrait
    un resume des premieres pages presente comme le resume du tout ;
  - **le format se lit dans les OCTETS**, jamais dans le nom du fichier.

Aucun appel reseau, aucun modele, aucune cle.
"""
from __future__ import annotations

import importlib
import json
import sys

import pytest

from conftest import RACINE

sys.path.insert(0, str(RACINE / "sandbox-manager"))
document = importlib.import_module("document")
composite = importlib.import_module("composite")

REGISTRE = RACINE / "registry" / "apps.json"


@pytest.fixture
def apps():
    return json.loads(REGISTRE.read_text(encoding="utf-8"))["applications"]


@pytest.fixture
def par_id(apps):
    return {a["id"]: a for a in apps}


# --- Fabriquer de vrais PDF, sans dependance de plus -------------------------
#
# Ecrits octet par octet avec leur table d'adresses : un PDF bricole que pypdf
# accepterait << par reparation >> ne prouverait pas grand-chose du vrai cas.

def _pdf(flux: bytes) -> bytes:
    """Un PDF d'une page valide, dont le contenu est `flux`."""
    objets = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 300]/Contents 4 0 R"
        b"/Resources<</Font<</F1 5 0 R>>>>>>",
        b"<</Length " + str(len(flux)).encode() + b">>stream\n" + flux + b"\nendstream",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    sortie = bytearray(b"%PDF-1.4\n")
    adresses = []
    for numero, corps in enumerate(objets, 1):
        adresses.append(len(sortie))
        sortie += b"%d 0 obj" % numero + corps + b"endobj\n"

    debut_xref = len(sortie)
    sortie += b"xref\n0 %d\n" % (len(objets) + 1)
    sortie += b"0000000000 65535 f \n"
    for adresse in adresses:
        sortie += b"%010d 00000 n \n" % adresse
    sortie += b"trailer<</Size %d/Root 1 0 R>>\n" % (len(objets) + 1)
    sortie += b"startxref\n%d\n%%%%EOF\n" % debut_xref
    return bytes(sortie)


def pdf_avec_texte(texte: str = "Bonjour le Studio") -> bytes:
    return _pdf(b"BT /F1 12 Tf 20 200 Td (" + texte.encode("ascii") + b") Tj ET")


def pdf_scanne() -> bytes:
    """Un PDF dont la page ne porte AUCUN texte : un rectangle, rien d'autre.

    C'est la forme d'un document scanne ou photographie : l'oeil y lit des mots,
    le fichier n'en contient aucun.
    """
    return _pdf(b"0.5 0.5 0.5 rg 20 20 260 260 re f")


# --- 1. Le cas qui a fait naitre la brique -----------------------------------

def test_un_PDF_rend_son_texte():
    assert "Bonjour le Studio" in document.lire(pdf_avec_texte())


def test_un_fichier_texte_rend_son_texte():
    assert document.lire("Voici mes notes.".encode("utf-8")) == "Voici mes notes."


def test_le_markdown_passe_tel_quel_sans_etre_interprete():
    """Le Studio n'a pas a rendre du HTML : le modele lit tres bien du markdown."""
    brut = "# Titre\n\n- un point\n- un autre\n"
    assert document.lire(brut.encode("utf-8")) == brut.strip()


def test_l_accent_survit_au_passage():
    assert document.lire("Été à Brocéliande".encode("utf-8")) == "Été à Brocéliande"


# --- 2. Le refus qui compte le plus ------------------------------------------

def test_un_PDF_SCANNE_est_REFUSE_et_ne_rend_pas_une_chaine_vide():
    """LE test de ce fichier.

    `extract_text()` rend "" sur un PDF sans couche de texte, sans lever la
    moindre erreur. Sans ce refus, la chaine `document -> conversation` partirait
    resumer zero signe et le client lirait une reponse assuree batie sur rien.
    Une erreur silencieuse est la seule qu'on ne corrige jamais.
    """
    with pytest.raises(document.DocumentIllisible) as refus:
        document.lire(pdf_scanne())
    assert refus.value.motif == "pdf_sans_texte"


def test_le_refus_du_PDF_scanne_NOMME_la_sortie_que_le_client_a():
    """Un refus qui ne dit pas quoi faire se lit comme une panne.

    Ce cas-la a une vraie issue : le Studio sait lire une IMAGE. Le client n'a
    pas a le deviner, et la phrase doit le lui dire -- pas le motif, qui est
    fait pour le journal.
    """
    with pytest.raises(document.DocumentIllisible) as refus:
        document.lire(pdf_scanne())
    phrase = refus.value.phrase
    assert "image" in phrase.lower(), phrase
    assert "scann" in phrase.lower(), phrase


# --- 3. Trop long : refuse, jamais tronque -----------------------------------

def test_un_document_trop_long_est_REFUSE_et_non_tronque():
    """Tronquer rendrait un resume des premieres pages presente comme le tout.

    C'est le faux-vert exact que ce depot refuse partout ailleurs, et il serait
    invisible : la sortie aurait l'air parfaitement normale.
    """
    trop = ("phrase de remplissage. " * 3000).encode("utf-8")
    assert len(trop.decode()) > document.MAX_SIGNES
    with pytest.raises(document.DocumentIllisible) as refus:
        document.lire(trop)
    assert refus.value.motif == "document_trop_long"


def test_le_refus_pour_longueur_DIT_le_nombre_de_signes():
    """Un plafond sans le nombre atteint ne se debat pas : le client ne sait pas
    s'il doit couper en deux ou en vingt."""
    trop = ("x" * (document.MAX_SIGNES + 500)).encode("utf-8")
    with pytest.raises(document.DocumentIllisible) as refus:
        document.lire(trop)
    # Les milliers sont groupes par une espace insecable, comme partout ailleurs
    # dans le Studio : le nombre se cherche sous cette forme-la.
    import format_fr
    assert format_fr.en_memoire(document.MAX_SIGNES + 500, "") in refus.value.phrase


def test_un_document_JUSTE_SOUS_la_borne_passe():
    """La borne doit laisser passer ce qu'elle annonce, sinon elle ment d'un cran."""
    juste = ("x" * document.MAX_SIGNES).encode("utf-8")
    assert len(document.lire(juste)) == document.MAX_SIGNES


# --- 4. Les autres refus, tous nommes ----------------------------------------

def test_un_fichier_vide_est_refuse():
    with pytest.raises(document.DocumentIllisible) as refus:
        document.lire(b"")
    assert refus.value.motif == "document_vide"


def test_un_fichier_binaire_est_refuse_en_NOMMANT_ce_qui_est_accepte():
    """Un PNG depose par erreur dans le champ du document."""
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    with pytest.raises(document.DocumentIllisible) as refus:
        document.lire(png)
    assert refus.value.motif == "format_inconnu"
    assert "PDF" in refus.value.phrase and "texte" in refus.value.phrase


def test_un_texte_mal_encode_est_refuse_avec_le_geste_qui_repare():
    """Deviner l'encodage rendrait du charabia que personne ne verrait passer.

    cp1252 decode a peu pres n'importe quelle suite d'octets sans broncher : il
    n'y a donc AUCUN signal a attendre d'un essai de repli. Le refus est le seul
    resultat honnete, et sa phrase doit etre jouable par un debutant.
    """
    with pytest.raises(document.DocumentIllisible) as refus:
        document.lire("Été".encode("cp1252"))
    assert refus.value.motif == "texte_mal_encode"
    assert "UTF-8" in refus.value.phrase


def test_un_PDF_abime_est_refuse_sans_remonter_une_trace_technique():
    with pytest.raises(document.DocumentIllisible) as refus:
        document.lire(b"%PDF-1.4\nceci n'est pas un PDF")
    assert refus.value.motif == "pdf_abime"


def test_un_fichier_trop_lourd_est_refuse_AVANT_d_etre_analyse():
    """La borne d'octets garde le service : l'analyse d'un tres gros PDF le
    tiendrait pendant qu'elle tourne."""
    with pytest.raises(document.DocumentIllisible) as refus:
        document.lire(b"x" * (document.MAX_OCTETS + 1))
    assert refus.value.motif == "document_trop_lourd"


# --- 5. Le format vient des OCTETS, pas du nom -------------------------------

def test_un_PDF_renomme_en_txt_est_LU_COMME_UN_PDF():
    """Un nom se renomme ; les premiers octets, non.

    Meme discipline que `composite.type_de_sortie`, et pour la meme raison :
    faire confiance au nom, c'est accepter qu'un fichier passe pour un autre.
    `lire` ne recoit d'ailleurs AUCUN nom -- c'est ce qui rend la faute
    impossible plutot que deconseillee.
    """
    assert document.est_un_pdf(pdf_avec_texte())
    assert not document.est_un_pdf("%PDF ecrit dans du texte".encode("utf-8"))
    assert "Bonjour le Studio" in document.lire(pdf_avec_texte())


# --- 6. La brique dans le registre et dans la chaine -------------------------

def test_la_brique_est_la_SEULE_a_consommer_un_fichier(par_id):
    """Le type `fichier` existait dans le vocabulaire et personne ne s'y
    branchait : un type que rien ne porte est un controle qui ne peut pas
    sonner."""
    fiche = par_id["document_lecture"]
    assert fiche["entrees"] == ["fichier"]
    assert fiche["sorties"] == ["texte"]
    assert "fichier" in composite.TYPES


def test_la_fiche_ne_promet_ni_modele_ni_cle_ni_cout(par_id):
    """`modele: null` n'est pas un oubli ici : il n'y a aucun modele."""
    fiche = par_id["document_lecture"]
    assert fiche["modele"] is None
    assert fiche["cout_max_usd"] == 0
    assert not composite.exige_une_cle(fiche["cout"])
    assert fiche["modes"] == ["local"]


def test_la_chaine_document_puis_resume_s_enchaine_vraiment(apps):
    """La phrase du 22/09 qui n'avait pas de premier maillon en a un.

    `fichier -> texte -> texte` : le controle deterministe a enfin de quoi
    comparer sur cette chaine-la.
    """
    chaine = composite.chaine_depuis_briques(
        ["document_lecture", "chat_auto"], apps)
    etapes = chaine["etapes"]
    assert etapes[0]["entrees"] == ["fichier"]
    assert etapes[0]["sorties"] == ["texte"] == etapes[1]["entrees"]
    verdict = composite.verifier(chaine, sonde_budget=lambda _e: None)
    assert verdict["atteignable"] == composite.OUI, verdict


def test_une_chaine_qui_donne_du_TEXTE_au_lecteur_de_document_est_refusee(apps):
    """La garde se retourne : le type doit mordre dans les deux sens."""
    chaine = composite.chaine_depuis_briques(
        ["chat_auto", "document_lecture"], apps)
    verdict = composite.verifier(chaine, sonde_budget=lambda _e: None)
    assert verdict["atteignable"] == composite.NON, verdict
    assert "types_incompatibles" in verdict["motifs"]


# --- 7. Le lancement : aucune cle, aucun reseau ------------------------------

def test_le_noeud_se_lance_SANS_cle_et_SANS_routeur(monkeypatch):
    """La propriete qui distingue cette brique des treize autres.

    Elle est traitee AVANT `_cle_du_routeur()`. Sans cela, une installation nue
    verrait la chaine echouer sur << aucune cle >> pour un travail qui n'appelle
    personne -- un motif qui envoie le client reparer ce qui n'est pas casse.

    Le reseau est coupe pour de bon : `httpx.Client` leve si on l'ouvre.
    """
    import httpx

    monkeypatch.delenv("FREE_TIER_MANAGER_KEY", raising=False)
    monkeypatch.delenv("SANDBOX_MANAGER_KEY", raising=False)

    def interdit(*_a, **_k):
        raise AssertionError("la lecture d'un document a ouvert le reseau")

    monkeypatch.setattr(httpx, "Client", interdit)

    etape = {"brique": "document_lecture", "fonction": "Lire un document"}
    rendu = composite.lancer_par_le_routeur(etape, "Mes notes.".encode("utf-8"))
    assert rendu == "Mes notes."


def test_le_noeud_refuse_une_entree_qui_n_est_pas_un_fichier():
    """Aucune conversion implicite : un texte recu la ou un fichier est attendu
    se NOMME, il ne se rattrape pas."""
    etape = {"brique": "document_lecture", "fonction": "Lire un document"}
    with pytest.raises(composite.CompositeRefuse) as refus:
        composite.lancer_par_le_routeur(etape, "je suis du texte")
    assert refus.value.motif == "entree_du_mauvais_type"


def test_le_refus_du_module_traverse_la_chaine_avec_SON_motif(monkeypatch):
    """Le motif et la phrase du module remontent tels quels.

    Les reformuler dans `composite` ferait deux verites a maintenir, et c'est
    toujours la copie qui vieillit.
    """
    etape = {"brique": "document_lecture", "fonction": "Lire un document"}
    with pytest.raises(composite.CompositeRefuse) as refus:
        composite.lancer_par_le_routeur(etape, pdf_scanne())
    assert refus.value.motif == "pdf_sans_texte"
    assert refus.value.ou == composite.EXECUTION
    assert "image" in refus.value.phrase.lower()


# --- 8. La page peut recevoir le fichier -------------------------------------

def test_la_page_accepte_un_PDF():
    """Une brique lancable dont le client ne peut rien deposer ne sert a rien.

    Le defaut du 20/09 pris a l'avance : tests verts et image reconstruite ne
    prouvent pas qu'un champ de formulaire accepte le fichier.
    """
    assert "application/pdf" in composite.PAGE_HTML
    assert ".txt" in composite.PAGE_HTML
