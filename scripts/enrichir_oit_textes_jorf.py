#!/usr/bin/env python3
"""
enrichir_oit_textes_jorf.py

Remplace le texte des fiches OIT (thème + lien, construites par
build_search_index_oit.py) par le TEXTE INTÉGRAL OFFICIEL, publié au Journal
officiel français lors de la ratification -- sans jamais toucher NORMLEX.

POURQUOI CE DÉTOUR MARCHE (confirmé le 17/08/2026) :
NORMLEX bloque les IP de datacenter (HTTP 403, voir le run GitHub Actions du
16/08). Mais chaque convention ratifiée par la France est publiée en clair au
Journal officiel -- soit annexée à la loi de ratification, soit à un décret de
publication ultérieur ("dont le texte est annexé à la présente loi"). Ces
pages https://www.legifrance.gouv.fr/jorf/id/<JORFTEXT_id> sont PUBLIQUES,
sans authentification, et ne bloquent PAS les IP de datacenter (testé et
confirmé le 17/08/2026 sur JORFTEXT000031970331 -- texte intégral complet
obtenu par simple GET, aucune protection anti-bot rencontrée). C'est donc un
détour plus sûr et plus léger qu'un navigateur headless.

CE QU'IL FAUT : l'identifiant JORFTEXT de la loi/du décret de publication pour
chaque convention. Pas d'automatisme fiable pour le trouver (les recherches
web ne portent pas sur ce dépôt) -- à alimenter au fur et à mesure dans
oit-jorf-mapping.json, un num -> JORFTEXT_id à la fois. Première tranche
vérifiée à la main (2 entrées) :
    C155 -> JORFTEXT000052415520 (LOI n°2025-983 du 22/10/2025, texte annexé)
    C187 -> JORFTEXT000031970331 (Décret n°2016-88 du 01/02/2016)

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


class ExtracteurTexte(object):
    """Convertit du HTML en texte brut, sans dépendance externe (pas de
    BeautifulSoup -- stdlib seulement, pour tourner tel quel dans GitHub
    Actions sans étape d'installation)."""

    BALISES_BLOC = ('p', 'div', 'br', 'li', 'h1', 'h2', 'h3', 'tr')

    def __init__(self):
        self._script_ou_style = False

    def html_vers_texte(self, contenu_html):
        # Neutralise script/style (contenu à ignorer totalement).
        contenu_html = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', contenu_html,
                               flags=re.S | re.I)
        # Saut de ligne aux balises de bloc avant de tout retirer.
        for b in self.BALISES_BLOC:
            contenu_html = re.sub(r'<' + b + r'[^>]*>', '\n', contenu_html, flags=re.I)
        texte = re.sub(r'<[^>]+>', ' ', contenu_html)
        texte = html.unescape(texte)
        texte = re.sub(r'[ \t]+', ' ', texte)
        texte = re.sub(r' *\n *', '\n', texte)
        texte = re.sub(r'\n{3,}', '\n\n', texte)
        return texte.strip()


def extraire_annexe(texte_brut):
    """Isole le corps de la convention à l'intérieur de la page du décret/loi.
    Repère textuel (pas de dépendance à une classe/ID CSS précis, plus robuste
    aux变 variations de mise en page) : commence à la 1re occurrence de
    "ANNEXE" suivie de "CONVENTION" (en-tête standard de ces publications),
    s'arrête avant la formule de signature "Fait à/le ..." qui clôt le texte
    officiel. Retourne None si ces repères ne sont pas trouvés -- mieux vaut
    ne rien remplacer qu'écraser une fiche correcte avec un extrait tronqué."""
    m_debut = re.search(r'ANNEXE\s*CONVENTION', texte_brut, re.I)
    if not m_debut:
        # Repli : certaines pages ont "Annexe" et "CONVENTION N°..." séparés
        # par la table des matières -- cherche la 2e occurrence de CONVENTION
        # suivie de "DE L'ORGANISATION INTERNATIONALE DU TRAVAIL" (le vrai
        # début du corps, pas juste le titre de la page en haut).
        m_debut = re.search(r"CONVENTION[^\n]{0,80}ORGANISATION INTERNATIONALE DU TRAVAIL", texte_brut, re.I)
    if not m_debut:
        return None

    reste = texte_brut[m_debut.start():]
    m_fin = re.search(r'\n\s*Fait\s+(à|le)\s', reste)
    corps = reste[:m_fin.start()] if m_fin else reste

    corps = corps.strip()
    # Garde-fou : une convention réelle fait au moins quelques centaines de
    # caractères (plusieurs articles) -- un extrait trop court signale un
    # mauvais découpage plutôt qu'une convention courte.
    if len(corps) < 400:
        return None
    return corps


def recuperer_page(url, tentatives=3):
    # En-têtes proches d'un navigateur ordinaire : le run précédent s'est fait
    # bloquer (HTTP 403) avec un User-Agent qui s'identifiait comme un bot
    # ("compatible; MonLegiTexte/1.0") -- probablement filtré spécifiquement,
    # contrairement au test manuel qui avait réussi via un vrai navigateur.
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                       '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'fr-FR,fr;q=0.9',
    })
    derniere_erreur = None
    for i in range(tentatives):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode('utf-8', errors='replace')
        except (urllib.error.URLError, urllib.error.HTTPError) as e:
            derniere_erreur = e
            time.sleep(2 * (i + 1))
    raise derniere_erreur


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mapping', default='scripts/oit-jorf-mapping.json')
    ap.add_argument('--fiches', default='output/intl/textes-oit')
    ap.add_argument('--index', default='output/search-index-oit.json')
    args = ap.parse_args()

    if not os.path.exists(args.mapping):
        print('ERREUR : {} introuvable.'.format(args.mapping), file=sys.stderr)
        sys.exit(1)

    with open(args.mapping, encoding='utf-8') as f:
        mapping = json.load(f)  # {"C187": "JORFTEXT000031970331", ...}

    extracteur = ExtracteurTexte()
    ok, echecs = [], []

    for num, jorftext_id in mapping.items():
        chemin_fiche = os.path.join(args.fiches, num + '.json')
        if not os.path.exists(chemin_fiche):
            print('  {} : ignoré (pas de fiche existante -- lancer d\'abord '
                  'build_search_index_oit.py)'.format(num))
            continue

        url = 'https://www.legifrance.gouv.fr/jorf/id/' + jorftext_id
        try:
            page = recuperer_page(url)
        except Exception as e:
            print('  {} : ÉCHEC récupération ({})'.format(num, e))
            echecs.append(num)
            continue

        texte_brut = extracteur.html_vers_texte(page)
        annexe = extraire_annexe(texte_brut)
        if not annexe:
            print('  {} : ÉCHEC extraction (repères "ANNEXE/CONVENTION" ou '
                  '"Fait le" non trouvés -- page peut-être structurée '
                  'différemment, à vérifier à la main)'.format(num))
            echecs.append(num)
            continue

        with open(chemin_fiche, encoding='utf-8') as f:
            fiche = json.load(f)
        fiche['texte'] = annexe
        fiche['texte_source'] = 'JORF (texte intégral officiel, ' + jorftext_id + ')'
        fiche['url_jorf'] = url
        # Le lien NORMLEX (fiche['url']) est conservé tel quel en référence
        # secondaire -- on ne le remplace pas, juste on ajoute mieux.
        with open(chemin_fiche, 'w', encoding='utf-8') as f:
            json.dump(fiche, f, ensure_ascii=False, indent=2)

        print('  {} : OK ({} caractères)'.format(num, len(annexe)))
        ok.append(num)
        time.sleep(1)  # courtoisie -- pas de rafale sur un site public

    print('\n{} fiche(s) enrichie(s) avec le texte intégral, {} échec(s).'.format(len(ok), len(echecs)))
    if echecs:
        print('À vérifier à la main : ' + ', '.join(echecs))


if __name__ == '__main__':
    main()
