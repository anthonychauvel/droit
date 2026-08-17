#!/usr/bin/env python3
"""
build_search_index_oit.py

Construit output/search-index-oit.json (même format {num,title,snippet} que
les autres sources) ET output/intl/textes-oit/<num>.json (une fiche par
convention, comme pour la CEDH -- theme/lien vers le texte officiel, PAS le
texte intégral) à partir de la liste curée output/intl/oit-liste-curee.json.

Pourquoi une fiche et pas le texte intégral : NORMLEX bloque l'aspiration
automatisée (confirmé le 16/08 -- HTTP 403 sur les IP de datacenter GitHub,
même blocage que HUDOC pour la CEDH) -- donc, comme pour la CEDH, on affiche
thème + lien officiel plutôt que le texte complet.

Fichier source : output/intl/oit-liste-curee.json -- liste curée à la main
(PAS le fichier de statut output/intl/recensement-normlex.json, qui appartient
au workflow intl-recensement.yml et ne doit pas être touché ici). Première
tranche : 12 conventions vérifiées (les 10 fondamentales + les 2 conventions
de gouvernance sur l'inspection du travail), sourcées auprès de l'OIT/du Sénat/
du ministère du Travail le 16/08/2026. À compléter au fur et à mesure.

⚠️ Ce script reste DÉFENSIF sur les noms de champs (plusieurs variantes
essayées par entrée) au cas où la liste curée serait un jour reprise ou
étoffée avec une autre structure -- voir le résumé affiché au lancement.

Usage :
    python3 build_search_index_oit.py \
        --entree output/intl/recensement-normlex.json \
        --sortie-index output/search-index-oit.json \
        --sortie-fiches output/intl/textes-oit
"""
import json
import argparse
import os
import re
import sys
import unicodedata

# Noms de champs plausibles, du plus probable au moins probable. Le premier
# champ présent (et non vide) dans l'entrée est utilisé.
CHAMPS_ID     = ['id', 'num', 'numero', 'code', 'convention', 'ref', 'c_num']
CHAMPS_TITRE  = ['titre', 'title', 'nom', 'name', 'intitule', 'libelle']
CHAMPS_THEME  = ['theme', 'themes', 'sujet', 'subject', 'categorie', 'category']
CHAMPS_URL    = ['url', 'lien', 'link', 'href', 'source_url', 'normlex_url']
CHAMPS_DATE   = ['date', 'date_adoption', 'annee', 'year']
CHAMPS_STATUT = ['statut', 'status', 'etat', 'en_vigueur']


def normaliser(s):
    if not s:
        return ''
    s = unicodedata.normalize('NFKD', str(s))
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return s.lower().strip()


def premier_champ(entree, noms):
    for n in noms:
        if n in entree and entree[n] not in (None, '', []):
            return entree[n]
    return None


def extraire(entree, index_pos):
    """Retourne (num, titre, theme, url, date, statut) au mieux, ou None si
    l'entrée n'a même pas de titre exploitable (signale une entrée à examiner
    à la main plutôt que de produire une fiche vide)."""
    num = premier_champ(entree, CHAMPS_ID)
    titre = premier_champ(entree, CHAMPS_TITRE)
    theme = premier_champ(entree, CHAMPS_THEME)
    url = premier_champ(entree, CHAMPS_URL)
    date = premier_champ(entree, CHAMPS_DATE)
    statut = premier_champ(entree, CHAMPS_STATUT)

    if theme and isinstance(theme, list):
        theme = ', '.join(str(t) for t in theme)

    if not titre:
        return None

    if not num:
        # Repli : numéro généré depuis l'index si aucun identifiant trouvé.
        # Mieux vaut une fiche accessible (num='OIT-3') qu'une fiche perdue.
        num = 'OIT-{}'.format(index_pos + 1)

    return {
        'num': str(num),
        'titre': str(titre),
        'theme': str(theme) if theme else '',
        'url': str(url) if url else '',
        'date': str(date) if date else '',
        'statut': str(statut) if statut else '',
    }


def construire_snippet(fiche):
    parts = []
    if fiche['theme']:
        parts.append('Thème : ' + fiche['theme'])
    if fiche['date']:
        parts.append('Adoptée en ' + fiche['date'])
    if fiche['statut']:
        parts.append(fiche['statut'])
    return ' — '.join(parts) if parts else 'Convention de l\'Organisation internationale du travail.'


def construire_texte_fiche(fiche):
    """Corps affiché dans la fiche (branche payload.source==='OIT' du
    front-end, qui découpe sur \\n\\n -> chaque paragraphe ci-dessous devient
    un <p>)."""
    paras = []
    if fiche['theme']:
        paras.append('Thème : ' + fiche['theme'])
    if fiche['date']:
        paras.append('Convention adoptée en ' + fiche['date'] + '.')
    if fiche['statut']:
        paras.append('Statut : ' + fiche['statut'] + '.')
    paras.append(
        'Le texte intégral officiel de cette convention n\'est pas repris ici '
        '(NORMLEX bloque l\'aspiration automatisée) -- consultez-le via le lien '
        'officiel ci-dessous.'
    )
    return '\n\n'.join(paras)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--entree', default='output/intl/oit-liste-curee.json')
    ap.add_argument('--sortie-index', default='output/search-index-oit.json')
    ap.add_argument('--sortie-fiches', default='output/intl/textes-oit')
    args = ap.parse_args()

    if not os.path.exists(args.entree):
        print('ERREUR : {} introuvable.'.format(args.entree), file=sys.stderr)
        sys.exit(1)

    with open(args.entree, encoding='utf-8') as f:
        brut = json.load(f)

    # La liste curée peut être un tableau direct, ou un objet avec une clé
    # 'conventions'/'liste'/'items' -- on gère les deux formes courantes.
    if isinstance(brut, dict):
        for cle in ('conventions', 'liste', 'items', 'data', 'oit'):
            if cle in brut and isinstance(brut[cle], list):
                entrees = brut[cle]
                break
        else:
            print('ERREUR : {} est un objet mais aucune clé liste connue '
                  '(conventions/liste/items/data/oit) n\'y a été trouvée.'.format(args.entree),
                  file=sys.stderr)
            print('Contenu complet de l\'objet (pour comprendre sa vraie nature) :',
                  file=sys.stderr)
            print(json.dumps(brut, ensure_ascii=False, indent=2)[:3000], file=sys.stderr)
            sys.exit(1)
    elif isinstance(brut, list):
        entrees = brut
    else:
        print('ERREUR : format inattendu (ni liste ni objet).', file=sys.stderr)
        sys.exit(1)

    if entrees:
        print('Première entrée brute (pour vérifier les noms de champs) :')
        print(json.dumps(entrees[0], ensure_ascii=False, indent=2)[:800])
        print('---')

    index_search = []
    manquantes = []
    os.makedirs(args.sortie_fiches, exist_ok=True)

    for i, e in enumerate(entrees):
        fiche = extraire(e, i)
        if fiche is None:
            manquantes.append(i)
            continue

        index_search.append({
            'num': fiche['num'],
            'title': fiche['titre'],
            'snippet': construire_snippet(fiche),
        })

        detail = {
            'source': 'OIT',
            'titre': fiche['titre'],
            'texte': construire_texte_fiche(fiche),
            'url': fiche['url'],
        }
        chemin = os.path.join(args.sortie_fiches, re.sub(r'[^A-Za-z0-9_-]', '-', fiche['num']) + '.json')
        with open(chemin, 'w', encoding='utf-8') as f:
            json.dump(detail, f, ensure_ascii=False, indent=2)

    with open(args.sortie_index, 'w', encoding='utf-8') as f:
        json.dump(index_search, f, ensure_ascii=False)

    print('{} entrées lues, {} fiches construites, {} sans titre exploitable (index : {}).'.format(
        len(entrees), len(index_search), len(manquantes), manquantes))
    print('-> {}'.format(args.sortie_index))
    print('-> {}/ ({} fichiers)'.format(args.sortie_fiches, len(index_search)))
    if manquantes:
        print('\n⚠️  {} entrée(s) sans titre trouvé avec les noms de champs '
              'connus -- vérifier CHAMPS_TITRE dans ce script contre les vraies '
              'clés affichées ci-dessus.'.format(len(manquantes)))


if __name__ == '__main__':
    main()
