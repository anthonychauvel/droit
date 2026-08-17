#!/usr/bin/env python3
"""
decouvrir_jorf_mapping.py

Pour chaque convention OIT de la liste curée qui n'a PAS encore d'entrée dans
oit-jorf-mapping.json, cherche automatiquement (via /search, fond JORF) le
texte de ratification/publication correspondant, et complète le mapping --
au lieu de chercher chaque JORFTEXT à la main un par un.

MÉTHODE : recherche "convention <numéro> organisation internationale travail"
dans le fond JORF, puis ne garde un résultat que si son TITRE contient à la
fois le numéro de convention ET un mot clé de ratification/publication
("ratification" ou "publication") -- pour éviter de prendre un texte qui
mentionne juste la convention en passant plutôt que LE texte qui la publie.
En cas de plusieurs candidats valides, garde le plus RÉCENT (dateParution) --
un décret de publication est généralement postérieur à la loi d'autorisation
et contient le texte, contrairement à celle-ci (voir le cas C155 : la loi
seule ne suffit pas toujours).

⚠️ Comme pour /consult/jorf, le schéma exact de la réponse /search n'est pas
documenté publiquement -- ce script ne présume d'aucun nom de champ précis
(voir extraire_candidats, qui cherche n'importe quel objet ressemblant à un
résultat -- un titre + un identifiant JORFTEXT -- peu importe comment les
champs s'appellent).

Usage :
    python3 decouvrir_jorf_mapping.py \
        --liste output/intl/oit-liste-curee.json \
        --mapping scripts/oit-jorf-mapping.json
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error


def urls_piste():
    if os.environ.get('PISTE_ENV', 'production') == 'sandbox':
        return ('https://sandbox-oauth.piste.gouv.fr/api/oauth/token',
                'https://sandbox-api.piste.gouv.fr/dila/legifrance/lf-engine-app/search')
    return ('https://oauth.piste.gouv.fr/api/oauth/token',
            'https://api.piste.gouv.fr/dila/legifrance/lf-engine-app/search')


def obtenir_jeton(client_id, client_secret):
    import urllib.parse
    donnees = urllib.parse.urlencode({
        'grant_type': 'client_credentials',
        'client_id': client_id,
        'client_secret': client_secret,
        'scope': 'openid',
    }).encode('utf-8')
    url_token, _ = urls_piste()
    req = urllib.request.Request(url_token, data=donnees, method='POST',
                                  headers={'Content-Type': 'application/x-www-form-urlencoded'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode('utf-8'))['access_token']


def rechercher_jorf(jeton, requete, taille=10):
    _, url_search = urls_piste()
    corps = json.dumps({
        "fond": "JORF",
        "recherche": {
            "champs": [{
                "typeChamp": "ALL",
                "operateur": "ET",
                "criteres": [{"valeur": requete, "typeRecherche": "TOUS_LES_MOTS", "operateur": "ET"}],
            }],
            "pageNumber": 1,
            "pageSize": taille,
            "typePagination": "DEFAUT",
            "operateur": "ET",
            "sort": "PERTINENCE",
        },
    }).encode('utf-8')
    req = urllib.request.Request(url_search, data=corps, method='POST', headers={
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + jeton,
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode('utf-8'))


def extraire_candidats(obj, acc):
    """Cherche récursivement des objets qui ressemblent à des résultats de
    recherche (titre + identifiant JORFTEXT), peu importe les noms exacts de
    champs utilisés par la réponse -- schéma non documenté publiquement."""
    if isinstance(obj, dict):
        titre, cid, date = None, None, None
        for k, v in obj.items():
            lk = k.lower()
            if isinstance(v, str):
                if titre is None and ('titr' in lk or lk == 'title'):
                    titre = v
                if cid is None and lk in ('cid', 'id', 'textcid') and v.startswith('JORFTEXT'):
                    cid = v
            if date is None and 'date' in lk and isinstance(v, (int, float)):
                date = v
        if titre and cid:
            acc.append({'cid': cid, 'titre': titre, 'date': date or 0})
        for v in obj.values():
            extraire_candidats(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            extraire_candidats(v, acc)


def meilleur_candidat(candidats, num_sans_c):
    """Ne garde que les résultats dont le titre contient vraiment le numéro
    de convention ET un mot de ratification/publication -- puis le plus
    récent parmi ceux-là (un décret de publication vient souvent après la
    loi d'autorisation et contient le texte, contrairement à elle seule)."""
    valides = []
    for c in candidats:
        t = c['titre'].lower()
        a_le_numero = re.search(r'\bn[o°]?\.?\s*' + re.escape(num_sans_c) + r'\b', t) is not None
        a_mot_cle = 'ratification' in t or 'publication' in t
        a_oit = 'internationale du travail' in t or 'oit' in t
        if a_le_numero and a_mot_cle and a_oit:
            valides.append(c)
    if not valides:
        return None
    valides.sort(key=lambda c: c['date'], reverse=True)
    return valides[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--liste', default='output/intl/oit-liste-curee.json')
    ap.add_argument('--mapping', default='scripts/oit-jorf-mapping.json')
    args = ap.parse_args()

    client_id = os.environ.get('PISTE_CLIENT_ID')
    client_secret = os.environ.get('PISTE_CLIENT_SECRET')
    if not client_id or not client_secret:
        print('ERREUR : PISTE_CLIENT_ID / PISTE_CLIENT_SECRET absents.', file=sys.stderr)
        sys.exit(1)

    with open(args.liste, encoding='utf-8') as f:
        conventions = json.load(f)
    mapping = {}
    if os.path.exists(args.mapping):
        with open(args.mapping, encoding='utf-8') as f:
            mapping = json.load(f)

    jeton = obtenir_jeton(client_id, client_secret)
    trouves, non_trouves = [], []

    for conv in conventions:
        num = conv['num']
        if num in mapping:
            continue  # déjà mappée (à la main ou par un run précédent)

        num_sans_c = num.lstrip('Cc0') or '0'  # "C029" -> "29", "C001" -> "1"
        requete = 'convention {} organisation internationale travail'.format(num_sans_c)
        try:
            reponse = rechercher_jorf(jeton, requete)
        except Exception as e:
            print('  {} : ÉCHEC recherche ({})'.format(num, e))
            non_trouves.append(num)
            continue

        candidats = []
        extraire_candidats(reponse, candidats)
        meilleur = meilleur_candidat(candidats, num_sans_c)

        if meilleur:
            mapping[num] = meilleur['cid']
            print('  {} : trouvé -> {} ({})'.format(num, meilleur['cid'], meilleur['titre'][:80]))
            trouves.append(num)
        else:
            print('  {} : rien de fiable trouvé ({} candidat(s) bruts examinés)'.format(num, len(candidats)))
            non_trouves.append(num)

        time.sleep(0.5)

    with open(args.mapping, 'w', encoding='utf-8') as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)

    print('\n{} trouvée(s) et ajoutée(s) au mapping, {} non trouvée(s).'.format(len(trouves), len(non_trouves)))
    if non_trouves:
        print('À chercher à la main si besoin : ' + ', '.join(non_trouves))


if __name__ == '__main__':
    main()
