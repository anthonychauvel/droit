#!/usr/bin/env python3
"""
Détermine quelle TRANCHE d'une liste (IDCC ou articles) revérifier à ce
run, pour étaler une revérification COMPLÈTE sur plusieurs runs au lieu de
tout refaire d'un coup ("veille tournante").

Nouveau rythme (demandé) : DEUX runs par semaine, sur CINQ semaines
  -> 10 tranches au total, une par run. Après 5 semaines, tout le corpus
     est repassé une fois, puis le cycle recommence.

Le numéro de tranche (0 à 9) est calculé de façon DÉTERMINISTE à partir de
la date, donc pas besoin de mémoriser où on en était : le calcul se refait
à l'identique à chaque run.

  numéro_de_run_global = (semaine_ISO * 2) + créneau
  créneau              = 0 pour le run du début de semaine (lundi),
                         1 pour le run de milieu de semaine (jeudi)
  tranche              = numéro_de_run_global % période        (période = 10)

Deux runs consécutifs de la même semaine tombent sur deux tranches qui se
suivent (2W puis 2W+1), donc on avance bien de deux tranches par semaine.

Le créneau est déduit du jour de la semaine de la date : lundi/mardi/mercredi
-> créneau 0, jeudi..dimanche -> créneau 1. On peut aussi le forcer avec
--creneau pour les tests.

Usage:
    python3 rotation_helper.py --in idcc_list_complet.txt --periode 10 --out /tmp/tranche_idcc.txt
    python3 rotation_helper.py --in all_articles_code_travail.txt --periode 10 --out /tmp/tranche_travail.txt
"""
import argparse
import datetime
import os


def numero_tranche(date, periode, creneau=None):
    """Renvoie (tranche, semaine_iso, creneau) pour une date donnée."""
    semaine_iso = date.isocalendar()[1]
    if creneau is None:
        # lundi=0, mardi=1, mercredi=2 -> créneau 0 ; jeudi..dimanche -> créneau 1
        creneau = 0 if date.weekday() < 3 else 1
    run_global = semaine_iso * 2 + creneau
    return run_global % periode, semaine_iso, creneau


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="in_file", required=True, help="Liste complète (un élément par ligne)")
    ap.add_argument("--out", required=True, help="Fichier de sortie : juste la tranche de ce run")
    ap.add_argument("--periode", type=int, default=10,
                    help="Nombre de runs pour un cycle complet (défaut 10 = 2/semaine x 5 semaines)")
    ap.add_argument("--creneau", type=int, default=None, choices=[0, 1],
                    help="Force le créneau (0=début de semaine, 1=milieu). Défaut : déduit de la date.")
    ap.add_argument("--date", default=None, help="Date à utiliser (défaut: aujourd'hui). Format AAAA-MM-JJ.")
    args = ap.parse_args()

    with open(args.in_file, encoding="utf-8") as f:
        items = [l.strip() for l in f if l.strip()]

    if not items:
        print(f"{args.in_file} est vide, rien à faire.")
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        open(args.out, "w", encoding="utf-8").close()
        return

    date = (datetime.date.fromisoformat(args.date) if args.date else datetime.date.today())
    tranche_num, semaine_iso, creneau = numero_tranche(date, args.periode, args.creneau)

    taille_tranche = max(1, -(-len(items) // args.periode))  # arrondi au-dessus
    debut = tranche_num * taille_tranche
    fin = min(debut + taille_tranche, len(items))
    # Au-delà de la dernière tranche réellement peuplée (si periode > nb d'items),
    # on ne renvoie rien plutôt que de planter.
    tranche = items[debut:fin] if debut < len(items) else []

    out_dir = os.path.dirname(args.out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write("\n".join(tranche))

    creneau_txt = "début de semaine (lundi)" if creneau == 0 else "milieu de semaine (jeudi)"
    print(f"Semaine ISO {semaine_iso}, {creneau_txt}, période {args.periode} runs "
          f"-> tranche {tranche_num} ({len(tranche)} élément(s) sur {len(items)} au total, "
          f"indices {debut}-{fin})")
    print(f"Écrit dans {args.out}")


if __name__ == "__main__":
    main()
