#!/usr/bin/env python3
"""
Télécharge le jeu de données officiel siret2idcc (Ministère du Travail,
data.gouv.fr) et en extrait la liste des IDCC réellement déclarés par de
vraies entreprises (via DSN) -- utile pour vérifier si un IDCC qu'on
n'arrive pas à résoudre est encore réellement utilisé aujourd'hui.

Ne tourne pas à chaque run (le fichier fait ~95 Mo et change peu) --
prévu pour être lancé ponctuellement, pas dans la veille automatique.

Usage:
    python3 check_siret2idcc.py --out output/idcc_reellement_utilises.json
"""
import os
import sys
import csv
import json
import argparse
import urllib.request

DATASET_URL = "https://www.data.gouv.fr/api/1/datasets/r/a22e54f7-b937-4483-9a72-aad2ea1316f1"


def download_csv(url, dest):
    print(f"Téléchargement de {url} (peut prendre quelques minutes, ~95 Mo)...")
    urllib.request.urlretrieve(url, dest)
    print(f"Téléchargé: {os.path.getsize(dest) / 1024 / 1024:.1f} Mo")


def extract_unique_idcc(csv_path):
    idcc_counts = {}
    with open(csv_path, encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        # Le nom exact de la colonne IDCC peut varier -- on cherche une colonne
        # dont le nom contient "idcc" (insensible à la casse)
        idcc_col = None
        for fieldname in reader.fieldnames or []:
            if "idcc" in fieldname.lower():
                idcc_col = fieldname
                break
        if not idcc_col:
            print(f"ERREUR: colonne IDCC introuvable. Colonnes disponibles: {reader.fieldnames}", file=sys.stderr)
            sys.exit(1)

        for row in reader:
            idcc = (row.get(idcc_col) or "").strip().lstrip("0")
            if idcc and idcc.isdigit():
                idcc_counts[idcc] = idcc_counts.get(idcc, 0) + 1

    return idcc_counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="output/idcc_reellement_utilises.json")
    ap.add_argument("--tmp-csv", default="/tmp/siret2idcc.csv")
    ap.add_argument("--unresolved-file", help="Fichier texte des IDCC non résolus à vérifier en priorité")
    args = ap.parse_args()

    download_csv(DATASET_URL, args.tmp_csv)
    idcc_counts = extract_unique_idcc(args.tmp_csv)
    print(f"IDCC uniques trouvés dans les déclarations réelles: {len(idcc_counts)}")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(idcc_counts, f, ensure_ascii=False, indent=2)

    if args.unresolved_file:
        unresolved = [line.strip() for line in open(args.unresolved_file) if line.strip()]
        found = {i: idcc_counts[i] for i in unresolved if i in idcc_counts}
        print(f"\nParmi les {len(unresolved)} non-résolus fournis, {len(found)} apparaissent dans de vraies déclarations:")
        for idcc, count in sorted(found.items(), key=lambda x: -x[1]):
            print(f"  IDCC {idcc}: {count} établissement(s) déclarés")

    os.remove(args.tmp_csv)


if __name__ == "__main__":
    main()
