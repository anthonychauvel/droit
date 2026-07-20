#!/usr/bin/env python3
"""
Détermine quelle TRANCHE d'une liste (IDCC ou articles) revérifier cette
semaine, pour étaler une revérification complète sur plusieurs lundis au
lieu de tout refaire d'un coup chaque semaine ("veille tournante").

Principe : le numéro de semaine ISO (1 à 53) modulo la période choisie
donne le numéro de tranche à traiter cette semaine. Stable et déterministe
-- pas besoin de mémoriser où on en était, le calcul se refait à l'identique
chaque lundi à partir de la date.

Exemple avec une liste de 316 IDCC et une période de 4 semaines :
  semaine ISO 29 (juillet) -> 29 % 4 = 1 -> tranche 1 (IDCC 80 à 158)
  semaine ISO 30 -> 30 % 4 = 2 -> tranche 2 (IDCC 159 à 237)
  etc. -- après 4 semaines, tout est repassé une fois.

Usage:
    python3 rotation_helper.py --in idcc_list.txt --periode 4 --out /tmp/tranche_idcc.txt
    python3 rotation_helper.py --in articles_list.txt --periode 4 --out /tmp/tranche_articles.txt
"""
import argparse
import datetime
import os


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="in_file", required=True, help="Liste complète (un élément par ligne)")
    ap.add_argument("--out", required=True, help="Fichier de sortie : juste la tranche de cette semaine")
    ap.add_argument("--periode", type=int, default=4,
                     help="Nombre de semaines pour un cycle complet (défaut 4 = un mois)")
    ap.add_argument("--date", default=None, help="Date à utiliser (défaut: aujourd'hui). Format AAAA-MM-JJ.")
    args = ap.parse_args()

    with open(args.in_file, encoding="utf-8") as f:
        items = [l.strip() for l in f if l.strip()]

    if not items:
        print(f"{args.in_file} est vide, rien à faire.")
        with open(args.out, "w", encoding="utf-8") as f:
            pass
        return

    date = (datetime.date.fromisoformat(args.date) if args.date
            else datetime.date.today())
    semaine_iso = date.isocalendar()[1]
    tranche_num = semaine_iso % args.periode

    taille_tranche = max(1, -(-len(items) // args.periode))  # arrondi au-dessus
    debut = tranche_num * taille_tranche
    fin = min(debut + taille_tranche, len(items))
    tranche = items[debut:fin]

    out_dir = os.path.dirname(args.out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write("\n".join(tranche))

    print(f"Semaine ISO {semaine_iso}, période {args.periode} semaines -> tranche {tranche_num} "
          f"({len(tranche)} élément(s) sur {len(items)} au total, indices {debut}-{fin})")
    print(f"Écrit dans {args.out}")


if __name__ == "__main__":
    main()
