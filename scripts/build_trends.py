#!/usr/bin/env python3
"""
Mode évolutif — repère automatiquement, à chaque run, les mots-clés et
expressions qui reviennent le plus dans le corpus déjà récupéré, et surtout
ceux qui NE SONT PAS ENCORE couverts par une catégorie : la liste « à classer
en priorité ».

Entrée : output/search-index.json (produit juste avant par build_search_index.py)

Sortie : output/search-trends.json
  {
    "generated": "AAAA-MM-JJ",
    "terms":      [["contingent", 1234], ...],   # mots fréquents (utile: prédiction + vocabulaire fuzzy)
    "phrases":    [["heures supplementaires", 456], ...],
    "to_classify":[["teletravail", 210], ...]    # fréquents MAIS hors catégories -> à classer
  }

Le front (index.html) charge ce fichier (repli propre s'il est absent) pour
enrichir l'autocomplétion et la tolérance aux fautes — donc le moteur
« apprend » le vocabulaire du corpus qui grandit, sans intervention.

Usage :
    python3 build_trends.py --index output/search-index.json --out output/search-trends.json
"""
import json
import os
import re
import argparse
import unicodedata
import datetime
from collections import Counter

# On réutilise la taxonomie de build_search_index si possible (même dossier).
try:
    from build_search_index import KEYWORDS
except Exception:
    KEYWORDS = {}

MIN_LEN = 4               # longueur minimale d'un mot retenu
TOP_TERMS = 250
TOP_PHRASES = 120
TOP_CLASSIFY = 60
MIN_CLASSIFY_COUNT = 4    # seuil pour proposer un terme à classer


def norm(s):
    """Identique au normaliser côté client : minuscules, sans accents, alphanum."""
    if not s:
        return ""
    s = unicodedata.normalize("NFD", str(s).lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# Mots-outils + remplissage juridique ultra-fréquent mais peu informatif.
STOP = set((
    "de du des la le les un une et en au aux ou que qui dans sur sous pour par avec sans "
    "ce cet cette ces mon ton son ses mes tes nos vos leur leurs se ne pas est sont ete etre "
    "il elle on nous vous ils elles mais donc car ni or ainsi selon lors dont chaque tout toute "
    "toutes tous plus moins tres apres avant entre vers chez afin lorsque lequel laquelle "
    "article articles alinea alineas chapitre titre section paragraphe annexe avenant "
    "present presente presentes dispositions disposition condition conditions cas lieu effet "
    "application applicable applicables concerne concernant relatif relative fixe fixee fixees "
    "prevu prevue prevues defini definie suivant suivante suivantes ci dessous dessus "
    "convention collective nationale accord entreprise entreprises employeur employeurs "
    "salarie salaries salariee salariees personnel date periode duree montant nombre "
    "compris inclus notamment egalement peut doit sera etat"
).split())


def texts_from_index(idx):
    """Flux de textes du corpus à partir de l'index compact."""
    out = []
    for c in idx.get("ccn", []):
        if c.get("title"):
            out.append(c["title"])
        for h in c.get("hits", []):
            out.append((h.get("title") or "") + " " + (h.get("kw") or ""))
    for key in ("code", "code_secu", "juris"):
        for a in idx.get(key, []):
            out.append((a.get("title") or "") + " " + (a.get("snippet") or ""))
    return out


def tokens_of(text):
    return [w for w in norm(text).split()
            if len(w) >= MIN_LEN and w not in STOP and not w.isdigit()]


def covered_terms():
    """Ensemble des mots déjà « couverts » par une catégorie (pour repérer
    ce qui reste à classer)."""
    covered = set()
    for kws in KEYWORDS.values():
        for kw in kws:
            for w in norm(kw).split():
                if len(w) >= 3:
                    covered.add(w)
    return covered


def title_terms(idx):
    """Mots issus des noms de conventions : ce sont des IDENTIFIANTS (métier/
    secteur), pas des thèmes à classer — on les écarte de la liste à classer."""
    terms = set()
    for c in idx.get("ccn", []):
        for w in norm(c.get("title") or "").split():
            if len(w) >= MIN_LEN:
                terms.add(w)
    return terms


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", default="output/search-index.json")
    ap.add_argument("--out", default="output/search-trends.json")
    args = ap.parse_args()

    if not os.path.exists(args.index):
        print(f"[tendances] index absent ({args.index}) — rien à faire.")
        return

    idx = json.load(open(args.index, encoding="utf-8"))
    texts = texts_from_index(idx)

    uni = Counter()
    bi = Counter()
    for text in texts:
        toks = tokens_of(text)
        uni.update(toks)
        for i in range(len(toks) - 1):
            bi[toks[i] + " " + toks[i + 1]] += 1

    covered = covered_terms()
    ignore = covered | title_terms(idx)
    to_classify = [(t, c) for t, c in uni.most_common()
                   if c >= MIN_CLASSIFY_COUNT and t not in ignore][:TOP_CLASSIFY]

    trends = {
        "generated": datetime.date.today().isoformat(),
        "terms": uni.most_common(TOP_TERMS),
        "phrases": [p for p in bi.most_common(TOP_PHRASES) if p[1] >= 2],
        "to_classify": to_classify,
    }

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(trends, f, ensure_ascii=False, separators=(",", ":"))

    size_kb = os.path.getsize(args.out) / 1024
    print(f"[tendances] {len(trends['terms'])} mots, {len(trends['phrases'])} expressions "
          f"({size_kb:.0f} Ko) -> {args.out}")
    if to_classify:
        apercu = ", ".join(f"{t} ({c})" for t, c in to_classify[:15])
        print(f"[a classer en priorite] {apercu}")


if __name__ == "__main__":
    main()
