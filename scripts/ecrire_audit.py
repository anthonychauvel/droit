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
--> Ce schéma reste INCHANGÉ. La liste des fichiers touchés (nouveauté
    ci-dessous) vit UNIQUEMENT dans le .md, jamais dans l'index JSON, pour ne
    rien changer à la façon dont le front-end lit l'index.

NOUVEAUTÉ (--fichiers-depuis) :
    Le workflow calcule déjà `git diff --cached --name-only` (il ne gardait
    que le compte). En lui faisant écrire cette liste dans un fichier passé
    ici, on ajoute au rapport markdown une section « Fichiers touchés » — de
    quoi lire directement QUELS fichiers ont bougé, au lieu d'un simple
    nombre. Argument OPTIONNEL : absent, fichier introuvable ou vide => le
    rapport est exactement identique à avant (aucune section ajoutée).

Usage :
    python3 ecrire_audit.py \
        --slug oit --titre "OIT — construire l'index de recherche" \
        --resume "5 fiches enrichies avec le texte intégral JORF, 23 en attente." \
        --changements 5 \
        --fichiers-depuis "$RUNNER_TEMP/fichiers-touches-oit.txt"   # optionnel
"""
import argparse
import datetime
import json
import os


def _lire_fichiers_touches(chemin):
    """Lit la liste des fichiers modifiés, un chemin par ligne (tel que produit
    par `git diff --cached --name-only`). Renvoie une liste triée et
    dédoublonnée des chemins non vides.

    Tolérant par conception : chemin non fourni, fichier absent, illisible ou
    vide -> liste vide. Dans ce cas le rapport reste identique à avant (pas de
    section « Fichiers touchés »), ce qui garantit la compatibilité descendante
    pour tout appel qui n'utilise pas ce nouvel argument.
    """
    if not chemin or not os.path.isfile(chemin):
        return []
    vus = set()
    resultat = []
    try:
        with open(chemin, encoding='utf-8') as f:
            for ligne in f:
                p = ligne.strip()
                if p and p not in vus:
                    vus.add(p)
                    resultat.append(p)
    except Exception:
        return []
    resultat.sort()
    return resultat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--slug', required=True, help='identifiant court du workflow (oit, cedh, cgfp-civil-penal, combler-manques)')
    ap.add_argument('--titre', required=True)
    ap.add_argument('--resume', required=True, help='résumé en une phrase, affiché dans le rapport simplifié')
    ap.add_argument('--changements', type=int, default=0, help='nombre de VRAIS changements du droit (0 = juste une vérification de routine / un enrichissement)')
    ap.add_argument('--dossier-audits', default='audits')
    ap.add_argument('--fichiers-depuis', default=None,
                    help="(optionnel) chemin d'un fichier listant les fichiers modifiés, "
                         "un par ligne (ex. la sortie de `git diff --cached --name-only`). "
                         "S'il est fourni et non vide, la liste est ajoutée au rapport "
                         "markdown. Absent ou vide : rapport identique à avant.")
    args = ap.parse_args()

    os.makedirs(args.dossier_audits, exist_ok=True)

    maintenant = datetime.datetime.now(datetime.timezone.utc)
    date_str = maintenant.strftime('%Y-%m-%d')
    heure_str = maintenant.strftime('%Hh%M UTC')
    nom_fichier_md = '{}-{}.md'.format(args.slug, date_str)

    fichiers_touches = _lire_fichiers_touches(args.fichiers_depuis)

    contenu_md = '## {}\n\n{}\n'.format(args.titre, args.resume)
    if fichiers_touches:
        lignes = ['', '### Fichiers touchés ({})'.format(len(fichiers_touches)), '']
        lignes += ['- {}'.format(p) for p in fichiers_touches]
        contenu_md += '\n'.join(lignes) + '\n'
    with open(os.path.join(args.dossier_audits, nom_fichier_md), 'w', encoding='utf-8') as f:
        f.write(contenu_md)

    # index-<slug>.json : SCHÉMA INCHANGÉ (mêmes 6 champs qu'avant). La liste
    # des fichiers reste dans le .md ci-dessus, jamais ici, pour que le
    # front-end traite l'index exactement comme aujourd'hui.
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

    msg = 'Audit écrit : {} ({} changement(s) signalé(s)).'.format(chemin_index, args.changements)
    if fichiers_touches:
        msg += ' {} fichier(s) listé(s) dans {}.'.format(len(fichiers_touches), nom_fichier_md)
    print(msg)


if __name__ == '__main__':
    main()
