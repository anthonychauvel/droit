#!/usr/bin/env python3
"""
combler_manques.py

Principe (proposé par Anthony le 18/08) : pour tout ce qu'on SAIT exister
(on a le numéro/l'IDCC) mais qu'on n'a pas réussi à récupérer en texte
intégral, écrire une fiche MINIMALE avec au moins le lien officiel --
jamais un trou complet. Le nom de fichier est IDENTIQUE à celui qu'un run
d'aspiration réussi écrirait -- donc dès qu'un vrai texte arrive (même bien
plus tard), il écrase naturellement la fiche minimale, sans code spécial de
coordination. Déjà le principe qui fait marcher les fiches OIT (thème+lien,
remplacées par le texte JORF quand trouvé) -- généralisé ici aux articles de
code et aux CCN.

RÈGLE D'OR : ne JAMAIS écraser un fichier déjà présent (peu importe qu'il
soit complet ou non) -- ce script ne fait QUE remplir des trous, jamais
retoucher à de l'existant.

Deux modes :

  --mode articles : compare un fichier "univers" (liste complète produite par
      list_all_code_articles.py) à un dossier de sortie déjà peuplé, et écrit
      une fiche minimale pour chaque article absent. Lien construit
      directement si l'identifiant est un LEGIARTI :
      https://www.legifrance.gouv.fr/codes/article_lc/<ID>

  --mode ccn : compare idcc_list_complet.txt à output/ccn/, écrit une fiche
      minimale par IDCC absent. Pas de lien direct possible sans
      l'identifiant KALICONT (pas dispo sans appel API) -- pointe vers la
      page de recherche officielle Légifrance avec l'IDCC affiché en clair.

⚠️ Le format exact des fichiers déjà produits par pull_ccn.py/
pull_code_travail.py n'est pas connu en détail ici -- la fiche minimale
utilise un format générique {num, titre, texte, url, stub, source}. À
ajuster après un premier essai si l'appli attend d'autres noms de champs.

Usage :
    python3 combler_manques.py --mode articles \
        --univers all_articles_code_travail.txt \
        --sortie output/code-travail \
        --nom-source "Code du travail"

    python3 combler_manques.py --mode ccn \
        --univers idcc_list_complet.txt \
        --sortie output/ccn \
        --nom-source "Convention collective"
"""
import argparse
import json
import os
import re
import sys


def deja_present(dossier, nom_fichier_base):
    return os.path.exists(os.path.join(dossier, nom_fichier_base + '.json'))


def combler_articles(univers_path, sortie_dir, nom_source):
    if not os.path.exists(univers_path):
        print('ERREUR : {} introuvable.'.format(univers_path), file=sys.stderr)
        sys.exit(1)
    os.makedirs(sortie_dir, exist_ok=True)

    with open(univers_path, encoding='utf-8') as f:
        univers = [l.strip() for l in f if l.strip()]

    combles, deja_ok = 0, 0
    for ligne in univers:
        nom_fichier = ligne.replace('/', '-')
        if deja_present(sortie_dir, nom_fichier):
            deja_ok += 1
            continue

        if ligne.startswith('LEGIARTI'):
            url = 'https://www.legifrance.gouv.fr/codes/article_lc/' + ligne
        else:
            url = 'https://www.legifrance.gouv.fr/search/code?query=' + ligne

        fiche = {
            'num': ligne,
            'titre': '{} — article {}'.format(nom_source, ligne),
            'texte': '',
            'url': url,
            'source': nom_source,
            'stub': True,
            'note': 'Texte pas encore récupéré automatiquement -- consultez le lien officiel ci-dessus en attendant.',
        }
        with open(os.path.join(sortie_dir, nom_fichier + '.json'), 'w', encoding='utf-8') as f:
            json.dump(fiche, f, ensure_ascii=False, indent=2)
        combles += 1

    print('{} : {} déjà présents, {} fiches minimales créées (sur {} au total).'.format(
        nom_source, deja_ok, combles, len(univers)))


def combler_ccn(univers_path, sortie_dir, nom_source):
    if not os.path.exists(univers_path):
        print('ERREUR : {} introuvable.'.format(univers_path), file=sys.stderr)
        sys.exit(1)
    os.makedirs(sortie_dir, exist_ok=True)

    with open(univers_path, encoding='utf-8') as f:
        lignes = [l.strip() for l in f if l.strip()]
    idccs = []
    for l in lignes:
        m = re.match(r'^(\d+)', l)
        if m:
            idccs.append(m.group(1))

    combles, deja_ok = 0, 0
    for idcc in idccs:
        if deja_present(sortie_dir, idcc):
            deja_ok += 1
            continue

        fiche = {
            'num': idcc,
            'titre': '{} IDCC {}'.format(nom_source, idcc),
            'texte': '',
            'url': 'https://www.legifrance.gouv.fr/liste/idcc?init=true',
            'source': nom_source,
            'stub': True,
            'note': ('Convention pas encore récupérée automatiquement -- '
                      'recherchez "IDCC {}" sur la page officielle Légifrance ci-dessus.').format(idcc),
        }
        with open(os.path.join(sortie_dir, idcc + '.json'), 'w', encoding='utf-8') as f:
            json.dump(fiche, f, ensure_ascii=False, indent=2)
        combles += 1

    print('{} : {} déjà présentes, {} fiches minimales créées (sur {} au total).'.format(
        nom_source, deja_ok, combles, len(idccs)))


def combler_eu(univers_path, sortie_dir, nom_source, prefixe_num):
    """EUR-Lex/CJUE : contrairement aux codes français, je n'ai jamais vu le
    fichier de recensement de ces deux sources (pipeline séparé, jamais
    consulté directement) -- ne présume donc PAS d'un nom de champ précis,
    marche récursivement dans le JSON comme pour l'OIT/JORF pour trouver des
    identifiants plausibles (CELEX ou "num" déjà utilisé par l'appli).
    Lien construit via le format CELEX d'EUR-Lex, fiable et bien documenté :
    https://eur-lex.europa.eu/legal-content/FR/TXT/?uri=CELEX:<id>
    (vaut aussi pour la jurisprudence CJUE, qui a des numéros CELEX)."""
    if not os.path.exists(univers_path):
        print('ERREUR : {} introuvable.'.format(univers_path), file=sys.stderr)
        sys.exit(1)
    os.makedirs(sortie_dir, exist_ok=True)

    with open(univers_path, encoding='utf-8') as f:
        brut = json.load(f)

    identifiants = []

    def marcher(o, cle_parente=None):
        if isinstance(o, dict):
            for k, v in o.items():
                lk = k.lower()
                if isinstance(v, str) and lk in ('celex', 'num', 'id', 'cid') and re.match(r'^[0-9A-Z].{5,}$', v):
                    identifiants.append(v)
                marcher(v, cle_parente=lk)
        elif isinstance(o, list):
            # Repli trouvé le 18/08 sur le vrai fichier EUR-Lex : une LISTE de
            # chaînes directement sous une clé "celex" (pas une liste
            # d'objets {"celex": "xxx"} comme je l'avais supposé) -- capturer
            # aussi ce cas, pas seulement les chaînes wrappées dans un dict.
            if cle_parente in ('celex', 'num', 'id', 'cid'):
                for v in o:
                    if isinstance(v, str) and re.match(r'^[0-9A-Z].{5,}$', v):
                        identifiants.append(v)
            for v in o:
                marcher(v, cle_parente=cle_parente)
    marcher(brut)
    identifiants = sorted(set(identifiants))

    if not identifiants:
        print('  AUCUN identifiant trouvé dans {} -- format de fichier '
              'probablement différent de ce que ce script attend. Contenu '
              'brut (pour diagnostic) :'.format(univers_path))
        print('  ' + json.dumps(brut, ensure_ascii=False)[:600])
        return

    combles, deja_ok = 0, 0
    for ident in identifiants:
        nom_fichier = ident.replace('/', '-')
        if deja_present(sortie_dir, nom_fichier):
            deja_ok += 1
            continue
        fiche = {
            'num': ident,
            'titre': '{} — {}'.format(nom_source, ident),
            'texte': '',
            'url': 'https://eur-lex.europa.eu/legal-content/FR/TXT/?uri=CELEX:' + ident,
            'source': nom_source,
            'stub': True,
            'note': 'Texte pas encore récupéré automatiquement -- consultez le lien officiel ci-dessus en attendant.',
        }
        with open(os.path.join(sortie_dir, nom_fichier + '.json'), 'w', encoding='utf-8') as f:
            json.dump(fiche, f, ensure_ascii=False, indent=2)
        combles += 1

    print('{} : {} déjà présents, {} fiches minimales créées (sur {} identifiants trouvés).'.format(
        nom_source, deja_ok, combles, len(identifiants)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mode', choices=['articles', 'ccn', 'eu'], required=True)
    ap.add_argument('--univers', required=True)
    ap.add_argument('--sortie', required=True)
    ap.add_argument('--nom-source', required=True)
    args = ap.parse_args()

    if args.mode == 'articles':
        combler_articles(args.univers, args.sortie, args.nom_source)
    elif args.mode == 'ccn':
        combler_ccn(args.univers, args.sortie, args.nom_source)
    else:
        combler_eu(args.univers, args.sortie, args.nom_source, None)


if __name__ == '__main__':
    main()
