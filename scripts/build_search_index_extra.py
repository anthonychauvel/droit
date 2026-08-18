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
    '225-1-1': ['discrimination témoin harcèlement sexuel', 'représailles après signalement de harcèlement'],
    '121-2': ['responsabilité pénale de l\'entreprise', 'responsabilité pénale personne morale'],
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
    '1101': ['définition du contrat'],
    '9': ['respect de la vie privée', 'vie privée au travail'],
    '2224': ['délai de prescription', 'prescription civile'],
}


def premier_champ(d, noms):
    for n in noms:
        v = d.get(n)
        if v:
            return v
    return ''


def extraire_titre_texte(d):
    """Cherche titre/texte n'importe où dans la structure (récursif), pas
    seulement au premier niveau -- la vraie forme découverte le 18/08 les
    niche sous une clé "article" : {"article": {"id":..., "texte":...}}.
    Marche pour n'importe quelle profondeur d'imbrication future aussi."""
    titre_trouve, texte_trouve = [None], ['']

    def marcher(o):
        if isinstance(o, dict):
            if titre_trouve[0] is None:
                t = premier_champ(o, CHAMPS_TITRE)
                if t:
                    titre_trouve[0] = t
            if not texte_trouve[0]:
                t = premier_champ(o, CHAMPS_TEXTE)
                if t:
                    texte_trouve[0] = t
            for v in o.values():
                marcher(v)
        elif isinstance(o, list):
            for v in o:
                marcher(v)
    marcher(d)
    return titre_trouve[0] or '', texte_trouve[0] or ''


def extraire_num(d, nom_fichier):
    """Le numéro peut lui aussi être niché sous "article" -- même marche
    récursive, avec repli sur le nom de fichier si rien n'est trouvé."""
    resultat = [None]

    def marcher(o):
        if resultat[0] or not isinstance(o, (dict, list)):
            return
        if isinstance(o, dict):
            v = o.get('num')
            if v:
                resultat[0] = v
                return
            for vv in o.values():
                marcher(vv)
        elif isinstance(o, list):
            for vv in o:
                marcher(vv)
    marcher(d)
    return resultat[0] or os.path.splitext(nom_fichier)[0]


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
    ignores = 0
    for i, nom_fichier in enumerate(fichiers):
        chemin = os.path.join(args.dossier, nom_fichier)
        try:
            with open(chemin, encoding='utf-8') as f:
                d = json.load(f)
        except Exception as e:
            print('  {} : ignoré (JSON invalide, {})'.format(nom_fichier, e))
            ignores += 1
            continue

        # Un fichier peut être une LISTE au premier niveau (rencontré le
        # 18/08) plutôt qu'un objet -- au lieu de planter (.get() sur une
        # liste), on prend le 1er élément s'il y en a un, sinon on ignore
        # ce fichier proprement.
        if isinstance(d, list):
            if not d:
                ignores += 1
                continue
            d = d[0]
        if not isinstance(d, dict):
            print('  {} : ignoré (structure JSON inattendue, ni objet ni liste d\'objets)'.format(nom_fichier))
            ignores += 1
            continue

        if i == 0:
            print('Première entrée brute (pour vérifier les noms de champs) :')
            print(json.dumps(d, ensure_ascii=False)[:400])
            print('---')

        num = extraire_num(d, nom_fichier)
        titre, texte = extraire_titre_texte(d)
        titre = titre or num
        snippet = texte[:300]
        mots = MOTS_CLES.get(num, [])
        if mots:
            # Mots-clés en tête du snippet indexé -- garantit qu'ils
            # matchent même si le snippet est ensuite tronqué ailleurs.
            snippet = ' · '.join(mots) + ((' — ' + snippet) if snippet else '')
        index.append({'num': num, 'title': titre, 'snippet': snippet})

    with open(args.sortie, 'w', encoding='utf-8') as f:
        json.dump(index, f, ensure_ascii=False)

    print('{} fichiers -> {} entrées indexées, {} ignorés -> {}'.format(
        len(fichiers), len(index), ignores, args.sortie))


if __name__ == '__main__':
    main()
