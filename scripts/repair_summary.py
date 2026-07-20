#!/usr/bin/env python3
"""
Répare _summary.json en le reconstruisant à partir des fichiers .json
RÉELLEMENT présents sur le disque -- pas de leur historique de runs.

Nécessaire suite à un bug corrigé le 20/07/2026 dans pull_code_travail.py :
_summary.json était écrasé (pas fusionné) à chaque run, donc un run qui ne
traitait qu'une tranche (rotation hebdomadaire, lot du batch "code-travail-
complet") effaçait le souvenir de tout ce que les runs précédents avaient
déjà récupéré -- alors que les fichiers .json individuels, eux, étaient
bien restés sur le disque. Ce script répare la trace sans rien re-télécharger.

Usage:
    python3 repair_summary.py --dir output/code-travail
    python3 repair_summary.py --dir output/code-travail-complet
    python3 repair_summary.py --dir output/ccn --idcc
"""
import argparse
import json
import os


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="Dossier à réparer (ex: output/code-travail)")
    ap.add_argument("--idcc", action="store_true",
                     help="Mode CCN (clé 'idcc' au lieu de 'article' dans le résumé)")
    args = ap.parse_args()

    if not os.path.isdir(args.dir):
        raise SystemExit(f"{args.dir} n'existe pas")

    cle = "idcc" if args.idcc else "article"
    summary = []
    n_ok, n_error = 0, 0

    for fn in sorted(os.listdir(args.dir)):
        if not fn.endswith(".json") or fn.startswith("_"):
            continue
        num = fn[:-5]  # retire ".json" -- le nom de fichier EST le numéro
        filepath = os.path.join(args.dir, fn)
        try:
            with open(filepath, encoding="utf-8") as f:
                data = json.load(f)
            ok = "_error" not in data
        except Exception:
            ok = False

        summary.append({cle: num, "status": "ok" if ok else "error"})
        if ok:
            n_ok += 1
        else:
            n_error += 1

    summary_path = os.path.join(args.dir, "_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"{args.dir} : {len(summary)} fichier(s) trouvé(s) sur le disque "
          f"({n_ok} ok, {n_error} en erreur) -- _summary.json reconstruit en conséquence.")


if __name__ == "__main__":
    main()
