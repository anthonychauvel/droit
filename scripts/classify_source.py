#!/usr/bin/env python3
"""
Distingue, pour ce qui est déjà dans output/, ce qui vient de la liste
"conservée" (idcc_list.txt, articles_list.txt, articles_list_css.txt) de ce
qui n'existe QUE parce que la veille tournante l'a pris dans l'univers
complet (idcc_list_complet.txt, all_articles_code_travail.txt, etc.).

Ne modifie AUCUN fichier déjà récupéré -- c'est une simple comparaison
d'ensembles, écrite dans un manifeste séparé. build_search_index.py et
lecteur.html peuvent le lire pour afficher un badge "conservé"/"complet"
sans rien casser de l'existant.

Usage:
    python3 classify_source.py --out output/classification-source.json
"""
import argparse
import json
import os


def charger_liste(path):
    if not os.path.exists(path):
        return set()
    with open(path, encoding="utf-8") as f:
        return set(l.strip() for l in f if l.strip())


def classifier(ccn_dir, conserves, complets):
    result = {}
    if not os.path.isdir(ccn_dir):
        return result
    for fn in os.listdir(ccn_dir):
        if not fn.endswith(".json") or fn.startswith("_"):
            continue
        num = fn[:-5]
        if num in conserves:
            result[num] = "conserve"
        elif num in complets:
            result[num] = "complet_uniquement"
        else:
            result[num] = "inconnu"  # récupéré autrement (dispatch manuel avec --idcc, etc.)
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="output/classification-source.json")
    args = ap.parse_args()

    idcc_conserves = charger_liste("idcc_list.txt")
    idcc_complets = charger_liste("idcc_list_complet.txt")
    art_travail_conserves = charger_liste("articles_list.txt")
    art_travail_complets = charger_liste("all_articles_code_travail.txt")
    art_secu_conserves = charger_liste("articles_list_css.txt")
    art_secu_complets = charger_liste("all_articles_code_secu.txt")

    manifeste = {
        "ccn": classifier("output/ccn", idcc_conserves, idcc_complets),
        "code_travail": classifier("output/code-travail", art_travail_conserves, art_travail_complets),
        "code_secu": classifier("output/code-secu", art_secu_conserves, art_secu_complets),
    }

    for cat, d in manifeste.items():
        compte = {"conserve": 0, "complet_uniquement": 0, "inconnu": 0}
        for v in d.values():
            compte[v] += 1
        print(f"{cat}: {compte['conserve']} conservé(s), {compte['complet_uniquement']} "
              f"complet-uniquement, {compte['inconnu']} inconnu(s)")

    out_dir = os.path.dirname(args.out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(manifeste, f, ensure_ascii=False, separators=(",", ":"))
    print(f"Manifeste écrit dans {args.out}")


if __name__ == "__main__":
    main()
