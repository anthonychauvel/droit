#!/usr/bin/env python3
"""
Construit un index de recherche compact (mots-clés) à partir de tous les
fichiers déjà récupérés dans output/ccn/ et output/code-travail/.

Contrairement au contenu complet (~30 Mo+), cet index ne garde que les
titres de section + un court extrait de texte par section -- assez pour
une recherche plein texte côté client, sans devoir télécharger tout le
corpus à chaque recherche.

Usage:
    python3 build_search_index.py --out output/search-index.json
"""
import json
import os
import re
import glob
import argparse

SNIPPET_LEN = 180


def strip_html(raw):
    if not raw:
        return ""
    text = re.sub(r"<[^>]+>", " ", raw)
    text = re.sub(r"\s+", " ", text).strip()
    return text


KEYWORDS = {
    "minima_salariaux": ["salaire", "rémunération", "minima", "minimum", "classification",
                          "grille", "traitement", "appointement", "rémunérations", "salaires"],
    "contingent_hs": ["contingent", "contingent annuel", "contingent d'heures"],
    "majoration_hs": ["majoration", "bonification", "taux de majoration", "heures majorées",
                       "majorées à"],
    "duree_travail": ["durée du travail", "temps de travail", "horaire de travail",
                       "durée légale", "durée maximale", "heures supplémentaires"],
    "astreintes": ["astreinte", "astreintes"],
    "temps_partiel": ["temps partiel", "heures complémentaires"],
    "modulation_annualisation": ["modulation", "annualisation", "aménagement du temps de travail",
                                  "répartition de la durée"],
    "repos": ["repos compensateur", "repos quotidien", "repos hebdomadaire", "repos récupérateur"],
    "conges": ["congé", "congés", "absence"],
    "rupture_preavis": ["préavis", "licenciement", "rupture", "démission", "indemnité de rupture"],
}


def matches_category(titre):
    titre_lower = titre.lower()
    for cat, kws in KEYWORDS.items():
        if any(kw in titre_lower for kw in kws):
            return cat
    return None


def walk_ccn_sections(node, path_titles=None, is_root=True):
    """Ne garde que les sections dont le titre matche une des catégories utiles.
    Le chemin ne répète pas le titre de la convention elle-même (déjà connu
    au niveau supérieur de l'entrée), pour ne pas gonfler l'index."""
    if path_titles is None:
        path_titles = []
    results = []
    if not isinstance(node, dict):
        return results
    titre = node.get("title") or node.get("titre")
    current_path = path_titles if is_root else (path_titles + ([titre] if titre else []))
    if titre and not is_root:
        cat = matches_category(titre)
        if cat:
            results.append({"path": " > ".join(current_path), "title": titre, "cat": cat})
    for child in (node.get("sections") or []):
        results.extend(walk_ccn_sections(child, current_path, is_root=False))
    return results


def build_ccn_index(ccn_dir):
    summary_path = os.path.join(ccn_dir, "_summary.json")
    if not os.path.exists(summary_path):
        return []
    summary = json.load(open(summary_path, encoding="utf-8"))
    index = []
    for entry in summary:
        if entry.get("status") != "ok":
            continue
        idcc = entry["idcc"]
        filepath = os.path.join(ccn_dir, f"{idcc}.json")
        if not os.path.exists(filepath):
            continue
        try:
            data = json.load(open(filepath, encoding="utf-8"))
        except Exception:
            continue
        hits = walk_ccn_sections(data)
        index.append({
            "num": idcc,
            "title": data.get("titre") or data.get("title") or "",
            "hits": hits,
        })
    return index


def build_code_index(code_dir):
    summary_path = os.path.join(code_dir, "_summary.json")
    if not os.path.exists(summary_path):
        return []
    summary = json.load(open(summary_path, encoding="utf-8"))
    index = []
    for entry in summary:
        if entry.get("status") != "ok":
            continue
        art = entry["article"]
        safe_name = art.replace("/", "-")
        filepath = os.path.join(code_dir, f"{safe_name}.json")
        if not os.path.exists(filepath):
            continue
        try:
            data = json.load(open(filepath, encoding="utf-8"))
        except Exception:
            continue
        text = strip_html(
            data.get("texte") or data.get("content") or data.get("texteHtml") or ""
        )
        index.append({
            "num": art,
            "title": f"Article {art}",
            "snippet": text[:100],
        })
    return index


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ccn-dir", default="output/ccn")
    ap.add_argument("--code-dir", default="output/code-travail")
    ap.add_argument("--code-secu-dir", default="output/code-secu")
    ap.add_argument("--out", default="output/search-index.json")
    args = ap.parse_args()

    ccn_index = build_ccn_index(args.ccn_dir)
    code_index = build_code_index(args.code_dir)
    code_secu_index = build_code_index(args.code_secu_dir) if os.path.exists(args.code_secu_dir) else []

    full_index = {"ccn": ccn_index, "code": code_index, "code_secu": code_secu_index}

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(full_index, f, ensure_ascii=False, separators=(",", ":"))

    size_kb = os.path.getsize(args.out) / 1024
    print(f"Index construit: {len(ccn_index)} CCN, {len(code_index)} articles travail, {len(code_secu_index)} articles sécu.")
    print(f"Taille: {size_kb:.0f} Ko -> {args.out}")


if __name__ == "__main__":
    main()
