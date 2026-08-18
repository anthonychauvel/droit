#!/usr/bin/env python3
"""
build_search_index_extra.py

Construit l'index de recherche {num,title,snippet} (même format que les
autres sources de l'appli) pour Code civil, Code pénal et le CGFP, à partir
des fichiers individuels déjà produits par pull_code_travail.py (réel) ou
combler_manques.py (fiches minimales).

⚠️ Le format exact des fichiers produits par pull_code_travail.py n'a jamais
été vu directement ici -- ce script essaie plusieurs noms de champs
plausibles pour le titre et le texte (voir CHAMPS_TITRE/CHAMPS_TEXTE) plutôt
que d'en présumer un seul. Affiche la 1re entrée brute pour diagnostic.

Usage :
    python3 build_search_index_extra.py \
        --dossier output/code-civil-travail --sortie output/search-index-code-civil-travail.json
"""
import argparse
import json
import os
import sys

CHAMPS_TITRE = ['titre', 'title', 'titreLong', 'nom']
CHAMPS_TEXTE = ['texte', 'text', 'content', 'contenu']

# Mots-clés associés aux articles ciblés de Code civil/pénal -- même
# principe que pour l'OIT : améliore le matching sur une vraie formulation
# utilisateur ("harcèlement au travail") même quand le texte officiel emploie
# un vocabulaire plus formel. Utile même avec le texte intégral, le texte de
# loi n'emploie pas toujours les mots qu'un salarié tape spontanément.
MOTS_CLES = {
    # Code pénal
    '222-33': ['harcèlement sexuel'],
    '222-33-2': ['harcèlement moral au travail', 'dégradation des conditions de travail'],
    '222-33-2-1': ['harcèlement moral', 'pression au travail'],
    '222-33-2-2': ['cyberharcèlement', 'harcèlement en ligne'],
    '225-1': ['discrimination', 'critères de discrimination'],
    '225-2': ['discrimination à l\'embauche', 'refus d\'embauche discriminatoire', 'licenciement discriminatoire'],
    '225-3': ['exception discrimination justifiée'],
    '225-3-1': ['discrimination multiple', 'cumul de discriminations'],
    '225-4': ['discrimination par une entreprise', 'responsabilité de la personne morale'],
    '223-1': ['mise en danger d\'autrui', 'risque causé à autrui'],
    '225-4-1': ['traite des êtres humains'],
    '225-4-2': ['traite des êtres humains aggravée'],
    '225-4-13': ['travail forcé', 'exploitation par le travail'],
    '225-14': ['conditions de travail contraires à la dignité', 'hébergement indigne'],
    '225-14-1': ['abus de vulnérabilité au travail'],
    '225-14-2': ['soumission à des conditions de travail indignes'],
    '226-1': ['atteinte à la vie privée', 'enregistrement à l\'insu'],
    '226-2': ['diffusion d\'enregistrement privé'],
    '226-4-3': ['usurpation d\'identité numérique'],
    '226-7': ['complicité atteinte vie privée'],
    '433-13': ['usurpation de titre'],
    '431-1': ['délit d\'entrave', 'entrave à la liberté de réunion'],
    # Code civil
    '1103': ['force obligatoire du contrat'],
    '1104': ['bonne foi contractuelle', 'exécution de bonne foi'],
    '1112': ['négociation précontractuelle', 'rupture des négociations'],
    '1112-1': ['devoir d\'information précontractuelle'],
    '1193': ['modification du contrat', 'révocation du contrat'],
    '1217': ['inexécution du contrat', 'sanctions de l\'inexécution'],
    '1218': ['force majeure'],
    '1221': ['exécution forcée en nature'],
    '1223': ['réduction du prix'],
    '1231-1': ['dommages-intérêts', 'réparation du préjudice contractuel'],
    '1240': ['responsabilité civile délictuelle', 'faute', 'réparation du dommage'],
    '1241': ['responsabilité pour négligence'],
    '1242': ['responsabilité du fait d\'autrui'],
    '1244': ['solidarité entre coresponsables'],
    '1353': ['charge de la preuve'],
}


def premier_champ(d, noms):
    for n in noms:
        v = d.get(n)
        if v:
            return v
    return ''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dossier', required=True)
    ap.add_argument('--sortie', required=True)
    args = ap.parse_args()

    if not os.path.isdir(args.dossier):
        print('ERREUR : {} introuvable.'.format(args.dossier), file=sys.stderr)
        sys.exit(1)

    fichiers = sorted(f for f in os.listdir(args.dossier) if f.endswith('.json'))
    index = []
    for i, nom_fichier in enumerate(fichiers):
        chemin = os.path.join(args.dossier, nom_fichier)
        try:
            with open(chemin, encoding='utf-8') as f:
                d = json.load(f)
        except Exception as e:
            print('  {} : ignoré (JSON invalide, {})'.format(nom_fichier, e))
            continue

        if i == 0:
            print('Première entrée brute (pour vérifier les noms de champs) :')
            print(json.dumps(d, ensure_ascii=False)[:400])
            print('---')

        num = d.get('num') or os.path.splitext(nom_fichier)[0]
        titre = premier_champ(d, CHAMPS_TITRE) or num
        texte = premier_champ(d, CHAMPS_TEXTE)
        snippet = texte[:300]
        mots = MOTS_CLES.get(num, [])
        if mots:
            # Mots-clés en tête du snippet indexé -- garantit qu'ils
            # matchent même si le snippet est ensuite tronqué ailleurs.
            snippet = ' · '.join(mots) + ((' — ' + snippet) if snippet else '')
        index.append({'num': num, 'title': titre, 'snippet': snippet})

    with open(args.sortie, 'w', encoding='utf-8') as f:
        json.dump(index, f, ensure_ascii=False)

    print('{} fichiers -> {} entrées indexées -> {}'.format(len(fichiers), len(index), args.sortie))


if __name__ == '__main__':
    main()
