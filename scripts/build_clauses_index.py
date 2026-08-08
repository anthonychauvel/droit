#!/usr/bin/env python3
"""
build_clauses_index.py — extrait les clauses thématiques déjà récupérées dans
les fichiers CCN et les regroupe par thème, pour les onglets « Heures sup »,
« Forfait jours », « Temps partiel », « Classifications », « Salaires » de
MonLegiTexte.

Les scripts fetch_*_details.py enrichissent chaque output/ccn/<idcc>.json avec
le texte intégral de certaines clauses, en les marquant d'un champ
_type_complement ("heures_sup", "salaire", etc.). Ces données sont donc DÉJÀ
là -- mais noyées dans l'arbre complet de chaque CCN, invisibles sans ouvrir
la convention entière. Ce script les remonte à la surface : un index par
thème, où chaque entrée dit « pour l'IDCC X, voici la clause heures sup, avec
son texte ».

Produit output/clauses-index.json :
    {
      "heures_sup":   [ {idcc, ccn_titre, clause_titre, texte}, ... ],
      "salaire":      [ ... ],
      "forfait_jours":[ ... ],
      "temps_partiel":[ ... ],
      "classification":[ ... ]
    }

Ne récupère RIEN sur le réseau : lit seulement ce qui est déjà sur disque.

Usage:
    python3 build_clauses_index.py --ccn-dir output/ccn --out output/clauses-index.json
"""
import os
import re
import json
import glob
import argparse


THEMES = ["heures_sup", "salaire", "forfait_jours", "temps_partiel", "classification"]


def strip_html(s):
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"&#160;|&nbsp;", " ", s)
    s = re.sub(r"&amp;", "&", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def texte_du_noeud(noeud):
    """Rassemble le texte lisible d'une clause : le contenu de ses articles
    (et sous-sections), aplati en une chaîne."""
    morceaux = []

    def walk(n):
        if isinstance(n, dict):
            for champ in ("content", "texte", "texteHtml"):
                if n.get(champ):
                    morceaux.append(strip_html(n[champ]))
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)

    walk(noeud.get("articles", []))
    walk(noeud.get("sections", []))
    return " ".join(m for m in morceaux if m).strip()


def _norm_titre(t):
    t = str(t or "").lower()
    for a, b in [("é","e"),("è","e"),("ê","e"),("à","a"),("ô","o"),("û","u"),("ç","c"),("î","i")]:
        t = t.replace(a, b)
    return t

# Mots dans le TITRE d'une section qui trahissent une clause de classification,
# même si elle n'a pas été enrichie par un fetch_* (pas de _type_complement).
_TITRE_CLASSIF = ["classification", "coefficient", "qualification", "echelon",
                  "grille", "categorie professionnelle", "niveaux", "classement"]


def collecter_clauses(data):
    """Parcourt tout l'arbre d'une CCN et renvoie les nœuds à indexer, avec le
    thème associé. Deux sources :
      1. les nœuds enrichis par les fetch_* (champ _type_complement) — texte
         complet déjà récupéré ;
      2. EN PLUS, pour la classification : les sections dont le TITRE l'indique
         (classification, coefficient, échelon…), même sans enrichissement — on
         utilise alors le texte brut de leurs articles. Sinon on ratait la
         majorité des grilles (ex. la 573 : 8 enrichies sur 14 réelles).
    """
    trouves = []       # liste de (theme, noeud)
    vus = set()        # éviter les doublons (même section captée deux fois)

    def cle(n):
        return n.get("id") or n.get("cid") or id(n)

    def walk(n):
        if isinstance(n, dict):
            k = cle(n)
            # Source 1 : nœud enrichi par un fetch_*
            if n.get("_type_complement") and n.get("_texte_complet_recupere"):
                if k not in vus:
                    trouves.append((n["_type_complement"], n))
                    vus.add(k)
            # Source 2 : section de classification repérée par son titre
            elif n.get("title"):
                tn = _norm_titre(n.get("title"))
                if any(m in tn for m in _TITRE_CLASSIF):
                    # On n'indexe que si elle a un contenu exploitable (articles).
                    if (n.get("articles") or n.get("sections")) and k not in vus:
                        trouves.append(("classification", n))
                        vus.add(k)
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)

    walk(data)
    return trouves


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ccn-dir", default="output/ccn")
    ap.add_argument("--out", default="output/clauses-index.json")
    args = ap.parse_args()

    index = {theme: [] for theme in THEMES}
    n_ccn, n_clauses = 0, 0

    for filepath in sorted(glob.glob(os.path.join(args.ccn_dir, "*.json"))):
        base = os.path.basename(filepath)
        if base.startswith("_"):
            continue
        idcc = os.path.splitext(base)[0]
        try:
            data = json.load(open(filepath, encoding="utf-8"))
        except Exception:
            continue

        ccn_titre = data.get("titre") or data.get("title") or f"IDCC {idcc}"
        clauses = collecter_clauses(data)
        if clauses:
            n_ccn += 1

        for theme, clause in clauses:
            if theme not in index:
                continue
            texte = texte_du_noeud(clause)
            index[theme].append({
                "idcc": idcc,
                "ccn_titre": ccn_titre,
                "clause_titre": clause.get("title") or clause.get("titre") or "",
                "texte": texte,
            })
            n_clauses += 1

    # Tri par IDCC dans chaque thème, pour un affichage stable.
    for theme in index:
        index[theme].sort(key=lambda e: int(e["idcc"]) if e["idcc"].isdigit() else 0)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, separators=(",", ":"))

    print(f"{n_clauses} clause(s) extraite(s) de {n_ccn} CCN, réparties par thème :")
    for theme in THEMES:
        print(f"  {theme:16} : {len(index[theme])}")
    size_kb = os.path.getsize(args.out) / 1024
    print(f"Écrit dans {args.out} ({size_kb:.0f} Ko)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
