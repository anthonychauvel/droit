#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
RECENSEMENT EUR-Lex — droit social / travail de l'Union europeenne.

But : COMPTER, sans rien telecharger d'autre, combien d'actes (directives +
reglements) EN VIGUEUR relevent du champ social/travail, et sortir la liste de
leurs identifiants CELEX. Sert a dimensionner l'aspiration avant de la lancer.

Source : point d'acces public CELLAR SPARQL (Office des publications de l'UE).
  -> PAS de cle, PAS de compte (contrairement a PISTE cote francais).
  -> Pas de CORS : appel cote script uniquement (ce qui est notre cas).

/!\ A CONFIRMER AU 1er RUN : la requete SPARQL ci-dessous suit les schemas
documentes de CELLAR, mais les proprietes exactes de l'ontologie peuvent
demander un petit ajustement. Le script est VERBEUX expres : il affiche ce
qu'il recoit et un echantillon, pour qu'on cale la requete sur du reel.
"""

import json, sys, time, datetime, urllib.parse, os
try:
    import requests
except ImportError:
    print("ERREUR: le module 'requests' est requis (pip install requests).", file=sys.stderr)
    sys.exit(2)

# ------------------------------------------------------------------ REGLAGES
ENDPOINT = "http://publications.europa.eu/webapi/rdf/sparql"
# Code de repertoire EUR-Lex du champ vise :
#   05.20 = "Libre circulation des travailleurs et politique sociale"
DIRECTORY_PREFIX = "05.20"
PAGE = 500          # taille de page (CELLAR plafonne + timeout 60s -> on pagine)
MAX_PAGES = 40      # garde-fou anti-boucle
TIMEOUT = 90
OUT = "output/intl/recensement-eurlex.json"

# Requete : directives + reglements portant sur un concept de repertoire dont
# la notation commence par 05.20. On remonte le CELEX, la date, l'etat.
SPARQL = """
PREFIX cdm:  <http://publications.europa.eu/ontology/cdm#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
SELECT DISTINCT ?celex ?date ?inforce WHERE {{
  ?work cdm:work_has_resource-type ?type .
  FILTER(?type IN (
    <http://publications.europa.eu/resource/authority/resource-type/DIR>,
    <http://publications.europa.eu/resource/authority/resource-type/REG>
  ))
  ?work cdm:resource_legal_id_celex ?celex .
  ?work cdm:work_is_about_concept_directory-code ?dir .
  ?dir skos:notation ?code .
  FILTER(STRSTARTS(STR(?code), "{prefix}"))
  OPTIONAL {{ ?work cdm:resource_legal_in-force ?inforce . }}
  OPTIONAL {{ ?work cdm:work_date_document ?date . }}
}}
ORDER BY ?celex
LIMIT {limit} OFFSET {offset}
"""

def http_get(params, tries=4):
    """GET avec retries + backoff. Renvoie le JSON des resultats SPARQL."""
    headers = {"Accept": "application/sparql-results+json",
               "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) MonLegiTexte-recensement/1.1"}
    last = None
    for i in range(tries):
        try:
            r = requests.get(ENDPOINT, params=params, headers=headers, timeout=TIMEOUT)
            if r.status_code == 200:
                return r.json()
            last = "HTTP %s" % r.status_code
        except Exception as e:
            last = repr(e)
        wait = 2 ** i
        print("  ... tentative %d/%d echouee (%s), pause %ds" % (i + 1, tries, last, wait))
        time.sleep(wait)
    raise RuntimeError("Echec requete SPARQL: %s" % last)

def main():
    print("=== Recensement EUR-Lex (champ social/travail, code %s) ===" % DIRECTORY_PREFIX)
    celex = {}   # celex -> {date, inforce}
    for page in range(MAX_PAGES):
        q = SPARQL.format(prefix=DIRECTORY_PREFIX, limit=PAGE, offset=page * PAGE)
        print("Page %d (offset %d)..." % (page + 1, page * PAGE))
        data = http_get({"query": q})
        rows = data.get("results", {}).get("bindings", [])
        if not rows:
            print("  (plus de resultats)")
            break
        for b in rows:
            c = b.get("celex", {}).get("value")
            if not c:
                continue
            celex[c] = {
                "date": b.get("date", {}).get("value", ""),
                "inforce": b.get("inforce", {}).get("value", ""),
            }
        print("  +%d lignes (total unique: %d)" % (len(rows), len(celex)))
        if len(rows) < PAGE:
            break
        time.sleep(1)  # politesse

    ids = sorted(celex.keys())
    en_vigueur = [c for c in ids if celex[c]["inforce"] in ("true", "1", "")]
    result = {
        "source": "EUR-Lex / CELLAR",
        "champ": "Directives + reglements, code repertoire %s (droit social/travail)" % DIRECTORY_PREFIX,
        "date_recensement": datetime.date.today().isoformat(),
        "total_actes": len(ids),
        "dont_en_vigueur_estime": len(en_vigueur),
        "note": "Compte indicatif. 'en vigueur' depend du champ inforce (a fiabiliser au 1er run). Ne COMPREND PAS la jurisprudence CJUE (a recenser separement).",
        "celex": ids,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print("\n--- RESULTAT ---")
    print("Actes trouves      : %d" % len(ids))
    print("Dont en vigueur    : ~%d" % len(en_vigueur))
    print("Ecrit dans         : %s" % OUT)
    if ids:
        print("Echantillon CELEX  : %s" % ", ".join(ids[:8]))
    else:
        print("/!\\ AUCUN resultat : la requete SPARQL est probablement a ajuster "
              "(proprietes d'ontologie). Voir la doc CELLAR / le package R 'eurlex'.")

if __name__ == "__main__":
    main()
