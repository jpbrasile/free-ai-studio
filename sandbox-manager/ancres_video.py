# -*- coding: utf-8 -*-
"""Ce que des clips reels ont pris sur la carte. Engendre, jamais retape.

PROVENANCE -- c'est tout l'objet de ce fichier. Une table tenue a la main derive
de ce qui l'a produite : on ne sait plus sur quelle carte, a quelle definition,
avec combien de passes ni avec quelle version de torch un chiffre a ete pris. La
relecture adverse du 21/09/2026 avait fait retirer pour cette raison une
fonction qui reecrivait les ancres a l'execution ; elle devait revenir << avec
son fichier a provenance, pas avant >>.

  Date de la campagne : 2026-09-21
  Carte et versions   : 2.6.0+cu124 0.40.0 12.4 NVIDIA GeForce RTX 4090
  Definition          : 1280x704
  Passes              : 2, la ou la production en fait 50
  Machine hote        : Windows build 10.0.26200

L'INSTRUMENT, ET POURQUOI IL A CHANGE. Les deux ancres du 19/09 avaient ete
prises avec `torch.cuda.max_memory_allocated()` : le compteur interne de
l'allocateur torch. Il ne compte ni le contexte CUDA, ni les blocs que
l'allocateur garde en reserve sans les rendre au pilote. Or la decision compare
ce nombre a la memoire LIBRE de la carte, rendue par `nvidia-smi` -- deux
grandeurs differentes, et l'ecart allait dans le mauvais sens : on reservait
moins que ce que le clip prend vraiment. Les chiffres ci-dessous sont la memoire
LIBRE qu'un vrai clip a consommee : pic pris sur la carte (`total - free`,
echantillonne a 1 Hz ; `memory.used` rend 0 sur ce pilote Windows WDDM) moins ce
qui y residait deja avant le lancement. C'est la grandeur que `utilisable()`
compare a `memory.free`, donc la seule qui reponde a la question posee.

CE QUE CETTE METHODE NE VOIT PAS, et il faut le lire avec les chiffres : un
releve par seconde ne peut pas attraper une pointe plus courte qu'une seconde.
Chaque nombre ci-dessous est donc un MINORANT du vrai pic. Le nombre de releves
est ecrit a cote de chacun pour qu'on sache sur combien d'occasions il a ete
cherche. La marge de `gpu_local.MARGE_MO` (1 024 Mo) est ce qui couvre ce
residu, en plus de ce qu'un voisin peut prendre entre la mesure et le lancement.

DEUX PROVENANCES DANS UNE SEULE TABLE, et il faut le savoir en la lisant :
`memoire_mo` vient de cette campagne a 2 passes ; `secondes` vient des
mesures du 19/09 A 50 PASSES, parce que le TEMPS, lui, depend des passes. Une
duree sans `secondes` n'a jamais ete chronometree a 50 passes : `_loi()`
n'ajuste le temps que sur celles qui en portent un.

TEMOINS. Les deux durees deja mesurees le 19/09 ont ete refaites ici, et
comparees AVEC LE MEME COMPTEUR : si le pic avait dependu du nombre de passes,
la campagne entiere aurait ete a jeter.
#   73 images, compteur torch des deux cotes : 19/09 a 50 passes 12841 Mo,
#              21/09 a 2 passes 12828 Mo, ecart -0.1 %. Le pic ne depend donc
#              PAS du nombre de passes, et la campagne est comparable.
#              Libre reellement consommee dans ce meme run : 14751 Mo, soit
#              +14.9 % de plus que ce que la table annoncait -- contexte CUDA
#              et reserve de l'allocateur, que le compteur interne ne voit pas.
#   121 images, compteur torch des deux cotes : 19/09 a 50 passes 14902 Mo,
#              21/09 a 2 passes 14882 Mo, ecart -0.1 %. Le pic ne depend donc
#              PAS du nombre de passes, et la campagne est comparable.
#              Libre reellement consommee dans ce meme run : 16351 Mo, soit
#              +9.7 % de plus que ce que la table annoncait -- contexte CUDA
#              et reserve de l'allocateur, que le compteur interne ne voit pas.
"""

# images -> ce qu'un vrai clip a pris sur la carte, et le temps quand il est connu
ANCRES = {
    25: {"memoire_mo": 11771},
    #   memoire : libre consommee, 2 passes, 1280x704, 132 releves a 1 Hz.
    #             Pic sur la carte 12197 Mo, dont 426 deja pris avant le
    #             lancement. Compteur torch du meme run : 11111 alloues,
    #             11310 reserves -- c'est ce compteur-la, et lui seul, que
    #             les ancres du 19/09 portaient.
    49: {"memoire_mo": 13413},
    #   memoire : libre consommee, 2 passes, 1280x704, 195 releves a 1 Hz.
    #             Pic sur la carte 13839 Mo, dont 426 deja pris avant le
    #             lancement. Compteur torch du meme run : 11802 alloues,
    #             12510 reserves -- c'est ce compteur-la, et lui seul, que
    #             les ancres du 19/09 portaient.
    73: {"memoire_mo": 14751, "secondes": 411.8},
    #   memoire : libre consommee, 2 passes, 1280x704, 166 releves a 1 Hz.
    #             Pic sur la carte 15177 Mo, dont 426 deja pris avant le
    #             lancement. Compteur torch du meme run : 12828 alloues,
    #             14290 reserves -- c'est ce compteur-la, et lui seul, que
    #             les ancres du 19/09 portaient.
    #   secondes : calcul a 50 passes, mesure du 19/09 -- PAS de cette campagne,
    #             le temps depend des passes (170 s ici a 2 passes).
    97: {"memoire_mo": 16711},
    #   memoire : libre consommee, 2 passes, 1280x704, 164 releves a 1 Hz.
    #             Pic sur la carte 17137 Mo, dont 426 deja pris avant le
    #             lancement. Compteur torch du meme run : 13855 alloues,
    #             16250 reserves -- c'est ce compteur-la, et lui seul, que
    #             les ancres du 19/09 portaient.
    121: {"memoire_mo": 16351, "secondes": 597.9},
    #   memoire : libre consommee, 2 passes, 1280x704, 194 releves a 1 Hz.
    #             Pic sur la carte 16777 Mo, dont 426 deja pris avant le
    #             lancement. Compteur torch du meme run : 14882 alloues,
    #             15890 reserves -- c'est ce compteur-la, et lui seul, que
    #             les ancres du 19/09 portaient.
    #   secondes : calcul a 50 passes, mesure du 19/09 -- PAS de cette campagne,
    #             le temps depend des passes (199 s ici a 2 passes).
    145: {"memoire_mo": 17411},
    #   memoire : libre consommee, 2 passes, 1280x704, 203 releves a 1 Hz.
    #             Pic sur la carte 17837 Mo, dont 426 deja pris avant le
    #             lancement. Compteur torch du meme run : 15909 alloues,
    #             16950 reserves -- c'est ce compteur-la, et lui seul, que
    #             les ancres du 19/09 portaient.
    169: {"memoire_mo": 18991},
    #   memoire : libre consommee, 2 passes, 1280x704, 216 releves a 1 Hz.
    #             Pic sur la carte 19417 Mo, dont 426 deja pris avant le
    #             lancement. Compteur torch du meme run : 16935 alloues,
    #             18530 reserves -- c'est ce compteur-la, et lui seul, que
    #             les ancres du 19/09 portaient.
    193: {"memoire_mo": 20451},
    #   memoire : libre consommee, 2 passes, 1280x704, 242 releves a 1 Hz.
    #             Pic sur la carte 20877 Mo, dont 426 deja pris avant le
    #             lancement. Compteur torch du meme run : 17962 alloues,
    #             19990 reserves -- c'est ce compteur-la, et lui seul, que
    #             les ancres du 19/09 portaient.
}
