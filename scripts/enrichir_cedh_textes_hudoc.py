#!/usr/bin/env python3
"""
enrichir_cedh_textes_hudoc.py

Remplace le texte des fiches CEDH (thème + conclusion + lien, construites par
enrich_hudoc.py) par le TEXTE INTÉGRAL OFFICIEL de l'arrêt, récupéré via le
point de conversion PDF public de HUDOC -- qui, contrairement au visualiseur
HUDOC principal (bloqué / page JS), répond normalement en GET simple.

DÉCOUVERTE (17/08/2026) : ce point d'accès marche, testé et confirmé :
    https://hudoc.echr.coe.int/app/conversion/docx/pdf?library=ECHR&id=<ID>&filename=CEDH.pdf
    (ID au format "001-XXXXX", l'identifiant HUDOC natif de chaque arrêt)
Retourne un PDF avec le texte intégral (confirmé sur 001-62184 -- 38
paragraphes complets, en français, obtenus par simple GET, aucun blocage
rencontré). Nécessite pdfplumber pour extraire le texte (déjà utilisé dans ce
dépôt pour les logs PDF -- même dépendance).

ÉCHELLE (différence majeure avec l'OIT) : ~5200 fiches, pas 30. Ce script
tourne donc PAR LOTS et REPREND où il s'est arrêté :
  - ignore les fiches déjà enrichies (texte_source déjà posé) à chaque run
  - s'arrête après --limite fiches OU --budget-minutes minutes, ce qui arrive
    en premier (repli si le run doit rester court sur un runner partagé)
  - traitement dans un ORDRE STABLE (tri alphabétique des fichiers) pour que
    des runs successifs avancent dans le corpus sans repasser sur les mêmes
    fiches ni en sauter

Usage (à répéter -- ex. cron hebdomadaire comme tes autres pipelines -- pour
couvrir tout le corpus au fil des runs) :
    python3 enrichir_cedh_textes_hudoc.py \
        --fiches output/intl/textes-hudoc \
        --limite 700 --budget-minutes 300
"""
import argparse
import io
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error


def extraire_id_hudoc(fiche):
    """Cherche l'identifiant HUDOC (format 001-XXXXX) dans les champs
    plausibles de la fiche -- soit directement (num/id), soit dans le
    paramètre i= d'un lien HUDOC existant (url/lien/hudoc_url/source)."""
    for champ in ('id_hudoc', 'num', 'id'):
        v = fiche.get(champ)
        if v and re.match(r'^\d{3}-\d+$', str(v)):
            return str(v)
    for champ in ('url', 'lien', 'hudoc_url', 'source', 'source_url'):
        v = fiche.get(champ)
        if v:
            m = re.search(r'[?&]i=(\d{3}-\d+)', str(v))
            if m:
                return m.group(1)
    return None


def recuperer_pdf(id_hudoc, tentatives=3):
    url = ('https://hudoc.echr.coe.int/app/conversion/docx/pdf'
           '?library=ECHR&id={}&filename=CEDH.pdf').format(id_hudoc)
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (compatible; MonLegiTexte/1.0; +https://monlegitexte.heuressupfrance.workers.dev)'
    })
    derniere_erreur = None
    for i in range(tentatives):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                donnees = r.read()
                if not donnees.startswith(b'%PDF'):
                    raise ValueError('réponse non-PDF (probablement une page d\'erreur HTML)')
                return donnees
        except Exception as e:
            derniere_erreur = e
            time.sleep(2 * (i + 1))
    raise derniere_erreur


def pdf_vers_texte(donnees_pdf):
    import pdfplumber
    texte = []
    with pdfplumber.open(io.BytesIO(donnees_pdf)) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                texte.append(t)
    return '\n\n'.join(texte).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--fiches', default='output/intl/textes-hudoc')
    ap.add_argument('--limite', type=int, default=700,
                     help='nombre max de fiches à enrichir sur ce run (défaut 700, comme le rythme de commit des autres pipelines du dépôt)')
    ap.add_argument('--budget-minutes', type=float, default=300,
                     help='arrête le run après ce délai même si la limite n\'est pas atteinte (défaut 300 = 5h, comme le budget documenté des autres runs longs)')
    args = ap.parse_args()

    if not os.path.isdir(args.fiches):
        print('ERREUR : {} introuvable.'.format(args.fiches), file=sys.stderr)
        sys.exit(1)

    debut = time.time()
    budget_s = args.budget_minutes * 60

    fichiers = sorted(f for f in os.listdir(args.fiches) if f.endswith('.json'))
    traites, deja_faits, sans_id, echecs = 0, 0, [], []

    for nom_fichier in fichiers:
        if traites >= args.limite:
            print('Limite de {} fiches atteinte, arrêt (relancer pour continuer).'.format(args.limite))
            break
        if time.time() - debut > budget_s:
            print('Budget de {} min dépassé, arrêt (relancer pour continuer).'.format(args.budget_minutes))
            break

        chemin = os.path.join(args.fiches, nom_fichier)
        with open(chemin, encoding='utf-8') as f:
            fiche = json.load(f)

        if fiche.get('texte_source', '').startswith('HUDOC PDF'):
            deja_faits += 1
            continue  # déjà enrichie lors d'un run précédent -- on saute

        id_hudoc = extraire_id_hudoc(fiche)
        if not id_hudoc:
            sans_id.append(nom_fichier)
            continue

        try:
            donnees = recuperer_pdf(id_hudoc)
            texte = pdf_vers_texte(donnees)
        except Exception as e:
            print('  {} ({}) : ÉCHEC ({})'.format(nom_fichier, id_hudoc, e))
            echecs.append(nom_fichier)
            traites += 1
            time.sleep(1)
            continue

        if len(texte) < 200:
            print('  {} ({}) : ÉCHEC (texte extrait trop court, {} car. -- PDF '
                  'peut-être vide ou protégé)'.format(nom_fichier, id_hudoc, len(texte)))
            echecs.append(nom_fichier)
            traites += 1
            time.sleep(1)
            continue

        fiche['texte'] = texte
        fiche['texte_source'] = 'HUDOC PDF (texte intégral officiel, ' + id_hudoc + ')'
        with open(chemin, 'w', encoding='utf-8') as f:
            json.dump(fiche, f, ensure_ascii=False, indent=2)

        traites += 1
        if traites % 50 == 0:
            print('  ... {} fiches enrichies ({:.0f} min écoulées)'.format(
                traites, (time.time() - debut) / 60))
        time.sleep(1)  # courtoisie -- pas de rafale sur un site public

    print('\n{} fiche(s) enrichie(s) ce run, {} déjà faites (sautées), '
          '{} sans identifiant HUDOC trouvé, {} échec(s).'.format(
              traites - len(echecs), deja_faits, len(sans_id), len(echecs)))
    restantes = len(fichiers) - deja_faits - traites
    if restantes > 0:
        print('{} fiche(s) restent à traiter -- relancer le run pour continuer '
              '(reprend automatiquement là où celui-ci s\'est arrêté).'.format(restantes))
    if sans_id:
        print('Sans identifiant (à examiner, {} au total, ex. : {})'.format(
            len(sans_id), ', '.join(sans_id[:5])))


if __name__ == '__main__':
    main()
