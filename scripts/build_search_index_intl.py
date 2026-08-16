#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
Construit les fichiers d'index de recherche pour les textes INTERNATIONAUX
deja aspires (output/intl/textes-eurlex/, textes-cjue/, textes-hudoc/), au
MEME format que build_search_index.py pour le droit francais : une liste
d'entrees {num, title, snippet, ...} par source, ecrite dans
output/search-index-<src>.json -- pour que le front les charge et les
cherche EXACTEMENT comme les sources francaises (meme mecanique, zero code
special cote lecture).

Usage :
    python3 scripts/build_search_index_intl.py

Ne touche JAMAIS aux fichiers search-index-<source FR>.json (ccn, code,
code_secu, juris, jorf, acco) : sujet totalement separe, ecrit par
build_search_index.py.
"""

import argparse, glob, json, os, re

# Longueurs d'extrait, memes conventions que le pipeline francais :
# JORF/ACCO (textes longs/legislatifs) -> 300 ; jurisprudence -> 220.
SNIPPET_LEGISLATIF = 300   # EUR-Lex (directives/reglements)
SNIPPET_JURIS = 220        # CJUE et CEDH (arrets)


def strip_espaces(raw):
    """Aplati le texte (deja brut, sans HTML) pour un extrait de recherche
    compact -- meme logique que strip_html() du pipeline francais (les
    sauts de ligne multiples ne doivent pas gonfler l'extrait)."""
    if not raw:
        return ""
    return re.sub(r"\s+", " ", raw).strip()


def build_eurlex_index(src_dir):
    if not os.path.isdir(src_dir):
        return []
    index = []
    for filepath in sorted(glob.glob(os.path.join(src_dir, "*.json"))):
        try:
            data = json.load(open(filepath, encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict) or not data.get("celex"):
            continue
        texte = strip_espaces(data.get("texte") or "")
        if not texte:
            continue
        index.append({
            "num": data["celex"],
            "title": data.get("titre") or ("Texte UE " + data["celex"]),
            "snippet": texte[:SNIPPET_LEGISLATIF],
        })
    return index


def build_cjue_index(src_dir):
    if not os.path.isdir(src_dir):
        return []
    index = []
    for filepath in sorted(glob.glob(os.path.join(src_dir, "*.json"))):
        try:
            data = json.load(open(filepath, encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict) or not data.get("celex"):
            continue
        texte = strip_espaces(data.get("texte") or "")
        if not texte:
            continue
        index.append({
            "num": data["celex"],
            "title": data.get("titre") or ("Arrêt CJUE " + data["celex"]),
            "snippet": texte[:SNIPPET_JURIS],
        })
    return index


def build_cedh_index(src_dir):
    if not os.path.isdir(src_dir):
        return []
    index = []
    for filepath in sorted(glob.glob(os.path.join(src_dir, "*.json"))):
        try:
            data = json.load(open(filepath, encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict) or not data.get("itemid"):
            continue
        texte = strip_espaces(data.get("texte") or "")
        if not texte:
            continue
        entry = {
            "num": data["itemid"],
            "title": data.get("titre") or data.get("docname") or ("Arrêt CEDH " + data["itemid"]),
            "snippet": texte[:SNIPPET_JURIS],
        }
        if data.get("appno"):
            entry["appno"] = data["appno"]
        index.append(entry)
    return index


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--eurlex-dir", default="output/intl/textes-eurlex")
    ap.add_argument("--cjue-dir", default="output/intl/textes-cjue")
    ap.add_argument("--cedh-dir", default="output/intl/textes-hudoc")
    ap.add_argument("--out-dir", default="output")
    args = ap.parse_args()

    parts = {
        "eurlex": build_eurlex_index(args.eurlex_dir),
        "cjue": build_cjue_index(args.cjue_dir),
        "cedh": build_cedh_index(args.cedh_dir),
    }

    os.makedirs(args.out_dir, exist_ok=True)
    for src, rows in parts.items():
        path = os.path.join(args.out_dir, f"search-index-{src}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, separators=(",", ":"))
        taille_mo = os.path.getsize(path) / 1024 / 1024
        print(f"  {path} : {len(rows)} entrées, {taille_mo:.2f} Mo")

    print(f"\nIndex international construit : {len(parts['eurlex'])} textes UE, "
          f"{len(parts['cjue'])} arrêts CJUE, {len(parts['cedh'])} arrêts CEDH.")


if __name__ == "__main__":
    main()
