#!/usr/bin/env python3
"""
ecrire_audit.py

Ajoute une entrée dans l'onglet "Vérification"/"Mise à jour" de MonLégiTexte
pour un run qui vient de se terminer -- même principe que les vérifications
France (généré par generate_audit_report.py), mais dans un fichier SÉPARÉ par
workflow pour ne jamais entrer en conflit git avec les autres (chaque
workflow n'écrit QUE dans le sien -- audits/index-<slug>.json). Le front-end
(chargerAudits() dans index.html) charge et fusionne tous ces fichiers.

Écrit deux choses :
  1. Un petit rapport markdown dans audits/<slug>-<date>.md
  2. Une entrée ajoutée en TÊTE de audits/index-<slug>.json (plus récent en
     premier, comme l'index principal)

Champs de l'entrée (mêmes noms que l'index principal, pour que le front-end
les traite identiquement -- voir _majSansChangement()/simplifierRapport()
dans index.html) :
    date, heure, fichier, titre, resume, changements_droit

Usage :
    python3 ecrire_audit.py \
        --slug oit --titre "OIT — construire l'index de recherche" \
        --resume "5 fiches enrichies avec le texte intégral JORF, 23 en attente." \
        --changements 5
"""
import argparse
import datetime
import json
import os
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--slug', required=True, help='identifiant court du workflow (oit, cedh, cgfp-civil-penal, combler-manques)')
    ap.add_argument('--titre', required=True)
    ap.add_argument('--resume', required=True, help='résumé en une phrase, affiché dans le rapport simplifié')
    ap.add_argument('--changements', type=int, default=0, help='nombre de VRAIS changements du droit (0 = juste une vérification de routine)')
    ap.add_argument('--dossier-audits', default='audits')
    args = ap.parse_args()

    os.makedirs(args.dossier_audits, exist_ok=True)

    maintenant = datetime.datetime.now(datetime.timezone.utc)
    date_str = maintenant.strftime('%Y-%m-%d')
    heure_str = maintenant.strftime('%Hh%M UTC')
    nom_fichier_md = '{}-{}.md'.format(args.slug, date_str)

    contenu_md = '## {}\n\n{}\n'.format(args.titre, args.resume)
    with open(os.path.join(args.dossier_audits, nom_fichier_md), 'w', encoding='utf-8') as f:
        f.write(contenu_md)

    chemin_index = os.path.join(args.dossier_audits, 'index-{}.json'.format(args.slug))
    entrees = []
    if os.path.exists(chemin_index):
        try:
            with open(chemin_index, encoding='utf-8') as f:
                entrees = json.load(f)
            if not isinstance(entrees, list):
                entrees = []
        except Exception:
            entrees = []

    nouvelle_entree = {
        'date': date_str,
        'heure': heure_str,
        'fichier': nom_fichier_md,
        'titre': args.titre,
        'resume': args.resume,
        'changements_droit': args.changements,
    }
    entrees.insert(0, nouvelle_entree)
    entrees = entrees[:200]

    with open(chemin_index, 'w', encoding='utf-8') as f:
        json.dump(entrees, f, ensure_ascii=False, indent=2)

    print('Audit écrit : {} ({} changement(s) signalé(s)).'.format(chemin_index, args.changements))


if __name__ == '__main__':
    main()
