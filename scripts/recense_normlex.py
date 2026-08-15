#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
RECENSEMENT OIT (conventions ratifiees par la France) — LISTE CUREE.

NORMLEX bloque tout acces automatise (403 depuis les IP datacenter GitHub, et
meme via d'autres voies). On ne s'acharne donc pas : on fournit une LISTE
CUREE des conventions ratifiees par la France PERTINENTES pour un salarie
(fondamentales + gouvernance + techniques generales d'emploi).

Volontairement EXCLUES : conventions maritimes, peche, sectorielles ou
denoncees -> sans interet pour un salarie, elles n'ajoutent que du bruit.

/!\ Liste a VERIFIER/COMPLETER contre NORMLEX quand un acces sera possible.
Elle couvre les conventions bien etablies comme ratifiees par la France ;
quelques-unes peuvent demander confirmation. Facile a editer (variable CUREE).
"""

import json, sys, datetime, os

# Numero -> intitule (francais). Conventions ratifiees par la France, utiles
# a un salarie. Ordre par numero.
CUREE = [
    # --- Fondamentales ---
    ("C029", "Travail force, 1930", "fondamentale"),
    ("C087", "Liberte syndicale et protection du droit syndical, 1948", "fondamentale"),
    ("C098", "Droit d'organisation et de negociation collective, 1949", "fondamentale"),
    ("C100", "Egalite de remuneration, 1951", "fondamentale"),
    ("C105", "Abolition du travail force, 1957", "fondamentale"),
    ("C111", "Discrimination (emploi et profession), 1958", "fondamentale"),
    ("C138", "Age minimum, 1973", "fondamentale"),
    ("C155", "Securite et sante des travailleurs, 1981", "fondamentale"),
    ("C182", "Pires formes de travail des enfants, 1999", "fondamentale"),
    # --- Gouvernance ---
    ("C081", "Inspection du travail, 1947", "gouvernance"),
    ("C122", "Politique de l'emploi, 1964", "gouvernance"),
    ("C129", "Inspection du travail (agriculture), 1969", "gouvernance"),
    ("C144", "Consultations tripartites (normes internationales du travail), 1976", "gouvernance"),
    # --- Techniques generales d'emploi ---
    ("C001", "Duree du travail (industrie), 1919", "technique"),
    ("C014", "Repos hebdomadaire (industrie), 1921", "technique"),
    ("C026", "Methodes de fixation des salaires minima, 1928", "technique"),
    ("C095", "Protection du salaire, 1949", "technique"),
    ("C097", "Travailleurs migrants (revisee), 1949", "technique"),
    ("C102", "Securite sociale (norme minimum), 1952", "technique"),
    ("C106", "Repos hebdomadaire (commerce et bureaux), 1957", "technique"),
    ("C118", "Egalite de traitement (securite sociale), 1962", "technique"),
    ("C132", "Conges payes (revisee), 1970", "technique"),
    ("C135", "Representants des travailleurs, 1971", "technique"),
    ("C142", "Mise en valeur des ressources humaines, 1975", "technique"),
    ("C154", "Negociation collective, 1981", "technique"),
    ("C156", "Travailleurs ayant des responsabilites familiales, 1981", "technique"),
    ("C158", "Licenciement, 1982", "technique"),
    ("C175", "Travail a temps partiel, 1994", "technique"),
    ("C181", "Agences d'emploi privees, 1997", "technique"),
    ("C190", "Violence et harcelement, 2019", "technique"),
]

OUT = "output/intl/recensement-normlex.json"

def main():
    print("=== Recensement OIT (liste curee — NORMLEX inaccessible) ===")
    items = [{"num": n, "intitule": t, "categorie": c} for (n, t, c) in CUREE]
    par_cat = {}
    for it in items:
        par_cat[it["categorie"]] = par_cat.get(it["categorie"], 0) + 1
    result = {
        "source": "OIT (liste curee)",
        "date_recensement": datetime.date.today().isoformat(),
        "statut": "CUREE",
        "raison": "NORMLEX bloque l'acces automatise (403). Liste curee des conventions "
                  "ratifiees par la France pertinentes pour un salarie.",
        "exclus": "Conventions maritimes / peche / sectorielles / denoncees (bruit pour un salarie).",
        "a_verifier": "Liste a confirmer/completer contre NORMLEX quand un acces sera possible.",
        "total": len(items),
        "par_categorie": par_cat,
        "conventions": items,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("Conventions curees : %d" % len(items))
    print("  par categorie : %s" % par_cat)
    print("Ecrit dans        : %s" % OUT)

if __name__ == "__main__":
    main()
