#!/usr/bin/env python3
"""
enrichir_oit_textes_jorf.py

Remplace le texte des fiches OIT (thème + lien, construites par
build_search_index_oit.py) par le TEXTE INTÉGRAL OFFICIEL, publié au Journal
officiel français lors de la ratification -- sans jamais toucher NORMLEX.

HISTORIQUE (important pour comprendre ce script) :
1re version : scraping direct de https://www.legifrance.gouv.fr/jorf/id/<ID>,
qui marchait lors d'un test manuel MAIS s'est fait bloquer (HTTP 403) une fois
lancé depuis GitHub Actions -- même après avoir imité un navigateur (en-têtes
réalistes). Conclusion : legifrance.gouv.fr bloque bel et bien les IP de
datacenter, comme NORMLEX -- le test manuel passait par une autre voie de
sortie qui n'est pas représentative d'un runner CI.

CETTE VERSION utilise à la place l'API PISTE officielle (point d'entrée
/consult/jorf), documentée dans la FAQ API Légifrance, et RÉUTILISE
l'authentification PISTE déjà en place dans ce dépôt pour l'aspiration JORF
existante (mêmes secrets GitHub, même flux OAuth) -- donc pas de nouveau
blocage IP à craindre, c'est le même canal qui fonctionne déjà pour aspirer
le reste du corpus JORF.

⚠️ POINT À VÉRIFIER AU PREMIER RUN : le nom exact du paramètre attendu par
/consult/jorf (probablement "textCid" ou "textId" -- non confirmé, la
documentation publique ne montre pas le corps JSON exact) et la forme de la
réponse (le texte peut être réparti sur plusieurs champs). Ce script :
  - essaie plusieurs noms de paramètres l'un après l'autre si le premier
    échoue (voir PARAM_CONSULT_JORF)
  - ne présume PAS d'un nom de champ précis dans la réponse : il parcourt
    tout le JSON reçu, concatène toutes les chaînes de texte trouvées, puis
    cherche les repères "ANNEXE/CONVENTION" dedans (même logique de repérage
    que la version précédente, juste appliquée à une source différente)
  - affiche la réponse brute de la 1re requête dans le log pour diagnostic si
    jamais rien n'est trouvé

Secrets nécessaires (mêmes que l'aspiration JORF existante du dépôt) :
    PISTE_CLIENT_ID, PISTE_CLIENT_SECRET
(si tes secrets existants portent un autre nom, ajuste le workflow -- ce
script lit juste les variables d'environnement du même nom)

Usage :
    python3 enrichir_oit_textes_jorf.py \
        --mapping scripts/oit-jorf-mapping.json \
        --fiches output/intl/textes-oit \
        --index output/search-index-oit.json
"""
import argparse
import html
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
import urllib.parse


PARAM_CONSULT_JORF = ['textCid', 'textId', 'id']


def urls_piste():
    """Bascule sandbox/production comme le reste du dépôt (variable PISTE_ENV,
    même convention que l'aspirateur Légifrance principal)."""
    if os.environ.get('PISTE_ENV', 'production') == 'sandbox':
        return ('https://sandbox-oauth.piste.gouv.fr/api/oauth/token',
                'https://sandbox-api.piste.gouv.fr/dila/legifrance/lf-engine-app/consult/jorf')
    return ('https://oauth.piste.gouv.fr/api/oauth/token',
            'https://api.piste.gouv.fr/dila/legifrance/lf-engine-app/consult/jorf')


class ExtracteurTexte(object):
    """Convertit du HTML en texte brut, sans dépendance externe."""

    BALISES_BLOC = ('p', 'div', 'br', 'li', 'h1', 'h2', 'h3', 'tr')

    def html_vers_texte(self, contenu_html):
        contenu_html = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', contenu_html,
                               flags=re.S | re.I)
        for b in self.BALISES_BLOC:
            contenu_html = re.sub(r'<' + b + r'[^>]*>', '\n', contenu_html, flags=re.I)
        texte = re.sub(r'<[^>]+>', ' ', contenu_html)
        texte = html.unescape(texte)
        texte = re.sub(r'[ \t]+', ' ', texte)
        texte = re.sub(r' *\n *', '\n', texte)
        texte = re.sub(r'\n{3,}', '\n\n', texte)
        return texte.strip()


def extraire_toutes_chaines(obj, acc):
    """Parcourt récursivement un JSON (dict/list/str) et accumule toutes les
    chaînes de texte trouvées -- on ne sait pas dans quel(s) champ(s) exact(s)
    /consult/jorf renvoie le contenu, donc on ne suppose rien : on regarde
    partout plutôt que de deviner un nom de clé qui pourrait être faux."""
    if isinstance(obj, str):
        if len(obj) > 20:  # ignore les codes/identifiants courts, pas utiles ici
            acc.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            extraire_toutes_chaines(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            extraire_toutes_chaines(v, acc)


def extraire_annexe(texte_brut):
    m_debut = re.search(r'ANNEXE\s*CONVENTION', texte_brut, re.I)
    if not m_debut:
        m_debut = re.search(r"CONVENTION[^\n]{0,80}ORGANISATION INTERNATIONALE DU TRAVAIL", texte_brut, re.I)
    if not m_debut:
        return None
    reste = texte_brut[m_debut.start():]
    m_fin = re.search(r'\n\s*Fait\s+(à|le)\s', reste)
    corps = (reste[:m_fin.start()] if m_fin else reste).strip()
    if len(corps) < 400:
        return None
    return corps


def obtenir_jeton(client_id, client_secret):
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


def consulter_jorf(jeton, jorftext_id, verbeux=False):
    """Essaie successivement les noms de paramètres plausibles jusqu'à ce que
    l'un fonctionne (voir PARAM_CONSULT_JORF) -- garde le 1er succès."""
    derniere_erreur = None
    _, url_consult = urls_piste()
    for nom_param in PARAM_CONSULT_JORF:
        corps = json.dumps({nom_param: jorftext_id}).encode('utf-8')
        req = urllib.request.Request(url_consult, data=corps, method='POST', headers={
            'Content-Type': 'application/json',
            'Authorization': 'Bearer ' + jeton,
        })
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                reponse = json.loads(r.read().decode('utf-8'))
                if verbeux:
                    print('    (paramètre "{}" accepté)'.format(nom_param))
                return reponse
        except urllib.error.HTTPError as e:
            derniere_erreur = e
            continue
    raise derniere_erreur


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mapping', default='scripts/oit-jorf-mapping.json')
    ap.add_argument('--fiches', default='output/intl/textes-oit')
    ap.add_argument('--index', default='output/search-index-oit.json')
    args = ap.parse_args()

    client_id = os.environ.get('PISTE_CLIENT_ID')
    client_secret = os.environ.get('PISTE_CLIENT_SECRET')
    if not client_id or not client_secret:
        print('ERREUR : variables d\'environnement PISTE_CLIENT_ID / '
              'PISTE_CLIENT_SECRET absentes -- à passer depuis les secrets '
              'GitHub du dépôt (les mêmes que pour l\'aspiration JORF '
              'existante) dans le step du workflow.', file=sys.stderr)
        sys.exit(1)

    if not os.path.exists(args.mapping):
        print('ERREUR : {} introuvable.'.format(args.mapping), file=sys.stderr)
        sys.exit(1)
    with open(args.mapping, encoding='utf-8') as f:
        mapping = json.load(f)

    jeton = obtenir_jeton(client_id, client_secret)
    extracteur = ExtracteurTexte()
    ok, echecs = [], []

    for i, (num, jorftext_id) in enumerate(mapping.items()):
        chemin_fiche = os.path.join(args.fiches, num + '.json')
        if not os.path.exists(chemin_fiche):
            print('  {} : ignoré (pas de fiche existante)'.format(num))
            continue

        try:
            reponse = consulter_jorf(jeton, jorftext_id, verbeux=(i == 0))
        except Exception as e:
            print('  {} : ÉCHEC requête PISTE ({})'.format(num, e))
            echecs.append(num)
            continue

        if i == 0:
            print('  Réponse brute (1er essai, pour diagnostic) :')
            print('  ' + json.dumps(reponse, ensure_ascii=False)[:600])

        chaines = []
        extraire_toutes_chaines(reponse, chaines)
        texte_brut = extracteur.html_vers_texte('\n'.join(chaines))
        annexe = extraire_annexe(texte_brut)
        if not annexe:
            print('  {} : ÉCHEC extraction (repères non trouvés dans la '
                  'réponse -- voir la réponse brute ci-dessus si 1er essai)'.format(num))
            echecs.append(num)
            continue

        with open(chemin_fiche, encoding='utf-8') as f:
            fiche = json.load(f)
        fiche['texte'] = annexe
        fiche['texte_source'] = 'JORF via API PISTE (texte intégral officiel, ' + jorftext_id + ')'
        fiche['url_jorf'] = 'https://www.legifrance.gouv.fr/jorf/id/' + jorftext_id
        with open(chemin_fiche, 'w', encoding='utf-8') as f:
            json.dump(fiche, f, ensure_ascii=False, indent=2)

        print('  {} : OK ({} caractères)'.format(num, len(annexe)))
        ok.append(num)
        time.sleep(0.5)

    print('\n{} fiche(s) enrichie(s), {} échec(s).'.format(len(ok), len(echecs)))
    if echecs:
        print('À vérifier : ' + ', '.join(echecs))


if __name__ == '__main__':
    main()
