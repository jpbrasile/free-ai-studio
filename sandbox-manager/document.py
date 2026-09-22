# -*- coding: utf-8 -*-
"""La dix-septieme brique : un document devient du texte, sans aucun modele.

CE QU'ELLE FERME. Le 22/09/2026, treize phrases de client ont ete passees au
compilateur sur l'installation reelle. Douze etaient justes. La treizieme,
<< Resume ce document PDF en une page >>, a compile en `conversation` -- une
brique qui attend du TEXTE. Le client aurait donne un PDF et la chaine n'aurait
pas eu de premier maillon. Le controle de types ne pouvait pas l'attraper :
aucune des seize briques ne declarait `fichier` en entree, donc le type
`fichier` du vocabulaire ne servait a rien et rien ne pouvait s'y brancher.

CE QU'ELLE NE FAIT PAS, ET C'EST VOULU.
  - Aucun modele, aucune cle, aucune sortie reseau. Elle lit des octets et rend
    du texte. Son cout est zero, pas << zero au palier gratuit >>.
  - Elle ne DEVINE pas. Un PDF scanne ne porte pas de texte : il porte des
    images de texte. Rendre une chaine vide en ferait un resume de rien, et le
    client lirait une reponse confiante batie sur zero signe. Ce cas se REFUSE,
    avec son nom et la phrase qui dit quoi faire.
  - Elle ne tronque pas en silence. Un document plus long que la borne est
    REFUSE en disant combien il porte. Tronquer donnerait un resume des
    premieres pages presente comme un resume du tout : c'est le faux-vert exact
    que ce depot refuse partout ailleurs.

LE FORMAT SE LIT DANS LES OCTETS, pas dans le nom du fichier. Meme discipline
que `composite.type_de_sortie`, et pour la meme raison : un nom se renomme.
"""
import io

import format_fr

# Deux bornes, et ce sont des CHOIX, pas des mesures -- dit ici pour que
# personne ne les cite comme un nombre mesure.
#   - 10 Mio : au-dela, l'analyse tiendrait le service pendant qu'elle attend.
#   - 40 000 signes : de quoi tenir dans la fenetre des modeles de palier
#     gratuit avec de la marge, soit une cinquantaine de pages de texte plein.
MAX_OCTETS = 10 * 1024 * 1024
MAX_SIGNES = 40_000

SIGNATURE_PDF = b"%PDF-"


class DocumentIllisible(ValueError):
    """Un refus qui porte son motif NOMME et sa phrase de remede.

    Volontairement independante de `composite.CompositeRefuse` : ce module ne
    connait pas les chaines, il lit un fichier. C'est `composite` qui traduit.
    """

    def __init__(self, motif: str, phrase: str):
        super().__init__(phrase)
        self.motif = motif
        self.phrase = phrase


def est_un_pdf(octets: bytes) -> bool:
    """Les octets commencent-ils par la signature d'un PDF ?"""
    return bytes(octets or b"")[:len(SIGNATURE_PDF)] == SIGNATURE_PDF


def _refus_de_taille(signes: int) -> DocumentIllisible:
    return DocumentIllisible(
        "document_trop_long",
        "Ce document porte %s signes, et la limite est de %s. Il n'est pas "
        "tronqué : un résumé des premières pages présenté comme le résumé du "
        "tout serait faux. Découpez-le, ou donnez la partie qui vous "
        "intéresse." % (format_fr.en_memoire(signes, ""),
                        format_fr.en_memoire(MAX_SIGNES, "")))


def _texte_du_pdf(octets: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover -- l'image l'installe
        raise DocumentIllisible(
            "lecteur_pdf_absent",
            "Ce Studio n'a pas de lecteur de PDF installé. Recréez les "
            "conteneurs.") from exc

    try:
        lecteur = PdfReader(io.BytesIO(bytes(octets)))
        if lecteur.is_encrypted:
            # `decrypt("")` ouvre un PDF protege en ECRITURE seulement, cas
            # frequent et parfaitement lisible. Un PDF protege en LECTURE
            # resiste, et c'est ce qu'on nomme.
            try:
                ouvert = lecteur.decrypt("")
            except Exception:  # noqa: BLE001
                ouvert = 0
            if not ouvert:
                raise DocumentIllisible(
                    "pdf_protege",
                    "Ce PDF est protégé par un mot de passe. Le Studio ne peut "
                    "pas l'ouvrir. Enregistrez-en une copie sans protection.")
        pages = [(page.extract_text() or "") for page in lecteur.pages]
    except DocumentIllisible:
        raise
    except Exception as exc:  # noqa: BLE001
        raise DocumentIllisible(
            "pdf_abime",
            "Ce fichier se présente comme un PDF mais ne s'ouvre pas (%s). "
            "Il est peut-être incomplet." % type(exc).__name__) from exc

    texte = "\n\n".join(p.strip() for p in pages if p.strip()).strip()
    if not texte:
        # LE cas qui justifie ce module. Un PDF scanne rend zero signe sans
        # lever la moindre erreur : sans ce refus, la chaine resumerait le vide.
        raise DocumentIllisible(
            "pdf_sans_texte",
            "Ce PDF ne contient aucun texte : c'est une image de page, comme "
            "un document scanné ou photographié. Le Studio sait lire une image "
            "— demandez-lui plutôt « qu'est-ce qu'il y a sur cette image ».")
    return texte


def _texte_nu(octets: bytes) -> str:
    octets = bytes(octets)
    if b"\x00" in octets[:4096]:
        raise DocumentIllisible(
            "format_inconnu",
            "Le Studio ne reconnaît pas ce fichier. Il sait lire un PDF, et un "
            "fichier texte (.txt, .md, .csv).")
    try:
        texte = octets.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DocumentIllisible(
            "texte_mal_encode",
            "Ce fichier texte n'est pas enregistré dans le format que le "
            "Studio sait lire. Ouvrez-le dans le Bloc-notes, puis "
            "« Enregistrer sous » en choisissant l'encodage UTF-8.") from exc
    return texte.strip()


def lire(octets) -> str:
    """Les octets d'un document -> son texte. Leve `DocumentIllisible` sinon.

    Jamais de valeur de repli : un document qu'on ne sait pas lire se dit, il
    ne se remplace pas par une chaine vide que la suite prendrait pour un
    contenu.
    """
    octets = bytes(octets or b"")
    if not octets:
        raise DocumentIllisible(
            "document_vide", "Le fichier reçu est vide.")
    if len(octets) > MAX_OCTETS:
        raise DocumentIllisible(
            "document_trop_lourd",
            "Ce fichier pèse %.1f Mo, et la limite est de %d Mo."
            % (len(octets) / (1024 * 1024), MAX_OCTETS // (1024 * 1024)))

    texte = _texte_du_pdf(octets) if est_un_pdf(octets) else _texte_nu(octets)

    if not texte:
        raise DocumentIllisible(
            "document_sans_texte", "Ce document ne contient aucun texte.")
    if len(texte) > MAX_SIGNES:
        raise _refus_de_taille(len(texte))
    return texte
