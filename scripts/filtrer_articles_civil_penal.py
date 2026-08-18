#!/usr/bin/env python3
"""
filtrer_articles_civil_penal.py

Remplace l'approche /search (qui échoue avec le fond CODE -- HTTP 400,
probablement parce que CODE couvre ~80 codes et exige de préciser lequel,
contrairement à JORF qui est un corpus unique) par une méthode qui réutilise
UNIQUEMENT des briques déjà prouvées :

  1. list_all_code_articles.py (déjà utilisé pour Code du travail/Code
     sécu/CGFP) donne la liste COMPLÈTE des articles d'un code -- pas de
     recherche, juste un listing, donc pas soumis au même problème.
  2. CE script filtre localement cette liste sur les numéros d'articles
     réellement pertinents pour le droit du travail (liste curée à la main,
     ARTICLES_CIVIL/ARTICLES_PENAL ci-dessous) -- aucun appel réseau.
  3. Le fichier filtré résultant se passe tel quel à pull_code_travail.py
     (déjà prouvé, comme pour Code du travail/Code sécu/CGFP).

Zéro nouvelle surface d'API par rapport à ce qui marche déjà.

Usage :
    python3 filtrer_articles_civil_penal.py \
        --entree all_articles_code_civil.txt \
        --sortie all_articles_code_civil_travail.txt \
        --code civil
"""
import argparse
import re
import sys

ARTICLES_PENAL = [
    "222-33", "222-33-2", "222-33-2-1", "222-33-2-2", "225-1", "225-2",
    "225-3", "225-3-1", "225-4", "223-1", "225-4-1", "225-4-2", "225-4-13",
    "225-14", "225-14-1", "225-14-2", "226-1", "226-2", "226-4-3", "226-7",
    "433-13", "431-1",
]
ARTICLES_CIVIL = [
    "1103", "1104", "1112", "1112-1", "1193", "1217", "1218", "1221",
    "1223", "1231-1", "1240", "1241", "1242", "1244", "1353",
]

CODES = {
    'civil': ARTICLES_CIVIL,
    'penal': ARTICLES_PENAL,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--entree', required=True, help='fichier produit par list_all_code_articles.py')
    ap.add_argument('--sortie', required=True)
    ap.add_argument('--code', choices=['civil', 'penal'], required=True)
    args = ap.parse_args()

    cibles = CODES[args.code]
    patterns = [re.compile(r'(?<![\d-])' + re.escape(c) + r'(?![\d-])') for c in cibles]

    try:
        with open(args.entree, encoding='utf-8') as f:
            lignes = [l.strip() for l in f if l.strip()]
    except FileNotFoundError:
        print('ERREUR : {} introuvable -- lancer list_all_code_articles.py '
              'avant ce script.'.format(args.entree), file=sys.stderr)
        sys.exit(1)

    gardees = [l for l in lignes if any(p.search(l) for p in patterns)]

    with open(args.sortie, 'w', encoding='utf-8') as f:
        f.write('\n'.join(gardees) + ('\n' if gardees else ''))

    print('{} lignes lues, {} retenues (sur {} numéros ciblés) -> {}'.format(
        len(lignes), len(gardees), len(cibles), args.sortie))
    trouves = set()
    for c, p in zip(cibles, patterns):
        if any(p.search(l) for l in lignes):
            trouves.add(c)
    manquants = [c for c in cibles if c not in trouves]
    if manquants:
        print('Numéros ciblés SANS correspondance dans la liste complète '
              '(à vérifier -- peut-être un autre format de numérotation) : '
              + ', '.join(manquants))


if __name__ == '__main__':
    main()
