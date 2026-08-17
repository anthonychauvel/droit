#!/usr/bin/env python3
"""
rechercher_articles_code_civil_penal.py

Recherche ÉLARGIE (pas une petite liste figée) des articles du Code civil et
du Code pénal pertinents pour le droit du travail, via l'API PISTE (fond
CODE, même API que le Code du travail/Code sécu -- pas de blocage à
craindre). Contrairement à une aspiration complète (CGFP), ces deux codes
sont énormes et généralistes (~2500 et ~1200+ articles au total, mariage/
succession/vol/terrorisme...) -- on ne veut que le sous-ensemble utile,
trouvé par recherche plutôt que par une liste à la main qui manquerait des
choses.

MÉTHODE :
1. Pour chaque mot-clé de la liste ÉLARGIE ci-dessous (MOTS_CLES_*), lance
   une recherche PISTE dans le fond CODE.
2. Filtre les résultats pour ne garder que ceux dont le code source est bien
   Code civil ou Code pénal (pas un des ~80 autres codes) -- via le champ de
   contexte renvoyé par la recherche (nom du code), pas une restriction côté
   requête (dont le paramètre exact n'est pas documenté publiquement).
3. Déduplique les articles trouvés (un même article peut sortir sur
   plusieurs mots-clés).
4. Récupère le contenu intégral de chaque article via /consult/code.
5. Écrit un fichier JSON par article dans le dossier de sortie (même format
   que les autres corpus : source/titre/texte/id), plus un index de
   recherche séparé par code.

⚠️ Comme pour les scripts OIT/JORF précédents, plusieurs points du schéma
PISTE ne sont PAS documentés publiquement et sont donc des HYPOTHÈSES
raisonnables plutôt que des certitudes : le nom du champ indiquant le code
source dans un résultat de recherche, et la structure exacte de
/consult/code. Le script imprime la réponse brute du premier appel de
chaque type pour un diagnostic rapide si jamais rien ne correspond.

Usage :
    python3 rechercher_articles_code_civil_penal.py \
        --sortie-civil output/code-civil-travail \
        --sortie-penal output/code-penal-travail \
        --index-civil output/search-index-code-civil-travail.json \
        --index-penal output/search-index-code-penal-travail.json
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
import urllib.parse


MOTS_CLES_PENAL = [
    "harcèlement moral au travail", "harcèlement sexuel", "discrimination emploi",
    "discrimination embauche", "délit d'entrave", "entrave institution représentative",
    "mise en danger d'autrui travail", "travail dissimulé", "marchandage",
    "prêt illicite de main d'oeuvre", "atteinte à la dignité", "agression sexuelle travail",
    "homicide involontaire travail", "blessures involontaires travail",
    "obligation de sécurité employeur", "traite des êtres humains", "réduction en servitude",
    "travail forcé pénal", "conditions de travail indignes", "emploi étranger sans titre",
    "dissimulation d'emploi salarié", "usure travail", "abus de faiblesse travail",
    "atteinte à la vie privée salarié", "discrimination syndicale pénal",
]
MOTS_CLES_CIVIL = [
    "contrat exécution de bonne foi", "responsabilité contractuelle",
    "responsabilité délictuelle", "dommages-intérêts inexécution", "force majeure contrat",
    "résiliation du contrat", "préjudice réparation", "faute civile",
    "obligation de moyens", "obligation de résultat", "mandat civil",
    "louage de services", "capacité juridique contracter", "personnalité morale",
    "droit à l'image salarié", "secret professionnel civil", "vie privée civil",
    "consentement contrat", "nullité du contrat", "clause abusive",
]

URL_TOKEN_PROD = 'https://oauth.piste.gouv.fr/api/oauth/token'
URL_SEARCH_PROD = 'https://api.piste.gouv.fr/dila/legifrance/lf-engine-app/search'
URL_CONSULT_PROD = 'https://api.piste.gouv.fr/dila/legifrance/lf-engine-app/consult/code'
URL_TOKEN_SANDBOX = 'https://sandbox-oauth.piste.gouv.fr/api/oauth/token'
URL_SEARCH_SANDBOX = 'https://sandbox-api.piste.gouv.fr/dila/legifrance/lf-engine-app/search'
URL_CONSULT_SANDBOX = 'https://sandbox-api.piste.gouv.fr/dila/legifrance/lf-engine-app/consult/code'


def urls_piste():
    if os.environ.get('PISTE_ENV', 'production') == 'sandbox':
        return URL_TOKEN_SANDBOX, URL_SEARCH_SANDBOX, URL_CONSULT_SANDBOX
    return URL_TOKEN_PROD, URL_SEARCH_PROD, URL_CONSULT_PROD


def obtenir_jeton(client_id, client_secret):
    url_token, _, _ = urls_piste()
    donnees = urllib.parse.urlencode({
        'grant_type': 'client_credentials',
        'client_id': client_id,
        'client_secret': client_secret,
        'scope': 'openid',
    }).encode('utf-8')
    req = urllib.request.Request(url_token, data=donnees, method='POST',
                                  headers={'Content-Type': 'application/x-www-form-urlencoded'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode('utf-8'))['access_token']


def rechercher(jeton, requete, taille=20):
    _, url_search, _ = urls_piste()
    corps = json.dumps({
        "fond": "CODE",
        "recherche": {
            "champs": [{
                "typeChamp": "ALL",
                "operateur": "ET",
                "criteres": [{"valeur": requete, "typeRecherche": "UN_DES_MOTS", "operateur": "ET"}],
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
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        detail = e.read().decode('utf-8', errors='replace')[:500]
        raise RuntimeError('{} -- détail : {}'.format(e, detail))


def extraire_candidats(obj, acc):
    """Marche récursive générique (même technique que pour l'OIT/JORF) :
    cherche tout objet avec un titre + un identifiant d'article (LEGIARTI),
    et capture aussi le nom du code source s'il est présent à proximité
    (champ contenant 'code' dans son nom, valeur texte)."""
    if isinstance(obj, dict):
        titre, article_id, nom_code = None, None, None
        for k, v in obj.items():
            lk = k.lower()
            if isinstance(v, str):
                if titre is None and ('titr' in lk or lk == 'title'):
                    titre = v
                if article_id is None and v.startswith('LEGIARTI'):
                    article_id = v
                if nom_code is None and 'code' in lk and ('nom' in lk or 'titre' in lk):
                    nom_code = v
        if titre and article_id:
            acc.append({'id': article_id, 'titre': titre, 'nom_code': nom_code or ''})
        for v in obj.values():
            extraire_candidats(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            extraire_candidats(v, acc)


def consulter_article(jeton, article_id):
    _, _, url_consult = urls_piste()
    for nom_param in ('id', 'articleId', 'cid'):
        corps = json.dumps({nom_param: article_id}).encode('utf-8')
        req = urllib.request.Request(url_consult, data=corps, method='POST', headers={
            'Content-Type': 'application/json',
            'Authorization': 'Bearer ' + jeton,
        })
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode('utf-8'))
        except urllib.error.HTTPError:
            continue
    return None


def extraire_texte(reponse):
    """Récupère le texte le plus long trouvé dans la réponse -- ne présume
    pas d'un nom de champ précis (voir la note en tête de fichier)."""
    chaines = []

    def marcher(o):
        if isinstance(o, str):
            if len(o) > 30:
                chaines.append(o)
        elif isinstance(o, dict):
            for v in o.values():
                marcher(v)
        elif isinstance(o, list):
            for v in o:
                marcher(v)
    marcher(reponse)
    return max(chaines, key=len) if chaines else ''


def traiter_code(jeton, nom_code_attendu, mots_cles, dossier_sortie, chemin_index, verbeux_premier=True):
    os.makedirs(dossier_sortie, exist_ok=True)
    candidats_par_id = {}

    for i, mc in enumerate(mots_cles):
        try:
            reponse = rechercher(jeton, mc)
        except Exception as e:
            print('  recherche "{}" : ÉCHEC ({})'.format(mc, e))
            continue
        if verbeux_premier and i == 0:
            print('  Réponse brute recherche (1er essai, pour diagnostic) :')
            print('  ' + json.dumps(reponse, ensure_ascii=False)[:600])
        cands = []
        extraire_candidats(reponse, cands)
        pertinents = [c for c in cands if nom_code_attendu.lower() in c['nom_code'].lower()] or cands
        for c in pertinents:
            candidats_par_id[c['id']] = c['titre']
        print('  "{}" : {} résultat(s) ({} rattachés à {})'.format(
            mc, len(cands), len(pertinents), nom_code_attendu))
        time.sleep(0.3)

    print('  -> {} articles uniques à récupérer pour {}'.format(len(candidats_par_id), nom_code_attendu))

    index_recherche = []
    for j, (article_id, titre) in enumerate(candidats_par_id.items()):
        reponse = consulter_article(jeton, article_id)
        if reponse is None:
            print('    {} : ÉCHEC consultation'.format(article_id))
            continue
        if verbeux_premier and j == 0:
            print('  Réponse brute consultation (1er article, pour diagnostic) :')
            print('  ' + json.dumps(reponse, ensure_ascii=False)[:600])
        texte = extraire_texte(reponse)
        num_match = re.search(r'([LRD]\.?\s*\d[\d\-]*)', titre)
        num = num_match.group(1).replace(' ', '') if num_match else article_id

        detail = {'source': nom_code_attendu, 'titre': titre, 'texte': texte, 'id': article_id}
        with open(os.path.join(dossier_sortie, article_id + '.json'), 'w', encoding='utf-8') as f:
            json.dump(detail, f, ensure_ascii=False, indent=2)
        index_recherche.append({'num': num, 'title': titre, 'snippet': texte[:300]})
        time.sleep(0.3)

    with open(chemin_index, 'w', encoding='utf-8') as f:
        json.dump(index_recherche, f, ensure_ascii=False)
    print('  -> {} ({} articles)'.format(chemin_index, len(index_recherche)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sortie-civil', default='output/code-civil-travail')
    ap.add_argument('--sortie-penal', default='output/code-penal-travail')
    ap.add_argument('--index-civil', default='output/search-index-code-civil-travail.json')
    ap.add_argument('--index-penal', default='output/search-index-code-penal-travail.json')
    args = ap.parse_args()

    client_id = os.environ.get('PISTE_CLIENT_ID')
    client_secret = os.environ.get('PISTE_CLIENT_SECRET')
    if not client_id or not client_secret:
        print('ERREUR : PISTE_CLIENT_ID / PISTE_CLIENT_SECRET absents.', file=sys.stderr)
        sys.exit(1)

    jeton = obtenir_jeton(client_id, client_secret)

    print('=== Code pénal ===')
    traiter_code(jeton, 'Code pénal', MOTS_CLES_PENAL, args.sortie_penal, args.index_penal)

    print('=== Code civil ===')
    traiter_code(jeton, 'Code civil', MOTS_CLES_CIVIL, args.sortie_civil, args.index_civil, verbeux_premier=False)


if __name__ == '__main__':
    main()
