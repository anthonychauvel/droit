#!/usr/bin/env python3
"""
Exporte la liste des CCN pour recherche.html, directement depuis les
données DU REPO DROIT (output/ccn/_summary.json) -- PAS depuis
conventions-collectives.js, qui est propre à l'app Heures Sup et n'a rien
à faire dans un moteur de consultation Légifrance général.

Résultat : les titres OFFICIELS Légifrance (pas les noms raccourcis
spécifiques à l'app), et toutes les CCN présentes dans le repo -- curatées
ou trouvées via l'univers complet, sans distinction (le badge conservé/
complet existe déjà séparément si besoin, cf classify_source.py).

Usage:
    python3 export_ccn_liste.py --ccn-dir output/ccn --out ccn-liste.json
"""
import argparse
import json
import os


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ccn-dir", default="output/ccn")
    ap.add_argument("--out", default="ccn-liste.json")
    args = ap.parse_args()

    summary_path = os.path.join(args.ccn_dir, "_summary.json")
    if not os.path.exists(summary_path):
        raise SystemExit(f"{summary_path} introuvable")

    with open(summary_path, encoding="utf-8") as f:
        summary = json.load(f)

    liste = []
    for entry in summary:
        if entry.get("status") != "ok":
            continue
        idcc = entry["idcc"]
        titre = entry.get("titre")
        if not titre:
            filepath = os.path.join(args.ccn_dir, f"{idcc}.json")
            if os.path.exists(filepath):
                try:
                    data = json.load(open(filepath, encoding="utf-8"))
                    titre = data.get("titre") or data.get("title")
                except Exception:
                    pass
        liste.append({"i": int(idcc), "n": titre or f"IDCC {idcc}"})

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(liste, f, ensure_ascii=False, separators=(",", ":"))

    print(f"{len(liste)} CCN exportées (titres officiels Légifrance) dans {args.out}")


if __name__ == "__main__":
    main()
