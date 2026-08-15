#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
RECENSEMENT CJUE — jurisprudence sociale/travail de la Cour de justice de l'UE.

Meme mecanique que recense_eurlex.py (auto-detection du code de repertoire),
mais on cible les TYPES "jurisprudence" (arrets, ordonnances, avis) au lieu des
directives/reglements. Sort les CELEX + ECLI.

Source : CELLAR SPARQL public (sans cle, sans compte).

/!\ La jurisprudence est-elle bien classee par code de repertoire dans CELLAR ?
On le saura au run : si tous les codes renvoient 0, il faudra classer autrement
(par ex. les arrets CITANT les grandes directives sociales). Le script le dit.
"""

import json, sys, time, datetime, os
try:
    import requests
except ImportError:
    print("ERREUR: le module 'requests' est requis (pip install requests).", file=sys.stderr)
    sys.exit(2)

ENDPOINT = "http://publications.europa.eu/webapi/rdf/sparql"
CODES_CANDIDATS = ["05", "0520", "052020"]   # 05 = chapitre entier (le plus large)
PAGE = 500
MAX_PAGES = 60
TIMEOUT = 90
OUT = "output/intl/recensement-cjue.json"

# Types "jurisprudence" (repris du package eurlex).
TYPES = ("<http://publications.europa.eu/resource/authority/resource-type/JUDG>||"
         "?type=<http://publications.europa.eu/resource/authority/resource-type/ORDER>||"
         "?type=<http://publications.europa.eu/resource/authority/resource-type/OPIN_JUR>")

def bloc_where(code):
    return """
  ?work cdm:work_has_resource-type ?type.
  FILTER(?type=%s)
  VALUES (?value) {
    (<http://publications.europa.eu/resource/authority/fd_555/%s>)
    (<http://publications.europa.eu/resource/authority/dir-eu-legal-act/%s>)
  }
  { ?work cdm:resource_legal_is_about_concept_directory-code ?value. }
  UNION
  { ?work cdm:resource_legal_is_about_concept_directory-code ?dir.
    ?value skos:narrower+ ?dir. }
""" % (TYPES, code, code)

PREFIXES = ("PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>\n"
            "PREFIX skos: <http://www.w3.org/2004/02/skos/core#>\n")

def q_count(code):
    return PREFIXES + "SELECT (COUNT(DISTINCT ?work) AS ?n) WHERE {" + bloc_where(code) + "}"

def q_list(code, limit, offset):
    return (PREFIXES + "SELECT DISTINCT ?celex ?ecli WHERE {" + bloc_where(code) +
            "  OPTIONAL { ?work cdm:resource_legal_id_celex ?celex. }\n"
            "  OPTIONAL { ?work cdm:case-law_ecli ?ecli. }\n"
            "} ORDER BY ?celex LIMIT %d OFFSET %d" % (limit, offset))

def sparql(query, tries=4):
    headers = {"Accept": "application/sparql-results+json",
               "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) MonLegiTexte-recensement/2.0"}
    last = None
    for i in range(tries):
        try:
            r = requests.get(ENDPOINT, params={"query": query}, headers=headers, timeout=TIMEOUT)
            if r.status_code == 200:
                return r.json()
            last = "HTTP %s" % r.status_code
        except Exception as e:
            last = repr(e)
        wait = 2 ** i
        print("  ... tentative %d/%d echouee (%s), pause %ds" % (i + 1, tries, last, wait))
        time.sleep(wait)
    raise RuntimeError("Echec requete SPARQL: %s" % last)

def compter(code):
    try:
        data = sparql(q_count(code))
        b = data.get("results", {}).get("bindings", [])
        return int(b[0]["n"]["value"]) if b else 0
    except Exception as e:
        print("  (code %s: erreur %s)" % (code, e))
        return -1

def ecrire(result):
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

def main():
    print("=== Recensement CJUE (jurisprudence sociale/travail) ===")
    print("Test des formats de code de repertoire :")
    scores = {}
    for code in CODES_CANDIDATS:
        n = compter(code)
        scores[code] = n
        print("  code %-9s -> %s" % (code, n if n >= 0 else "erreur"))
        time.sleep(1)

    best = max(scores, key=lambda c: scores[c])
    if scores[best] <= 0:
        ecrire({"source": "CJUE / CELLAR", "date_recensement": datetime.date.today().isoformat(),
                "total_arrets": 0, "codes_testes": scores,
                "note": "Aucun arret via le repertoire. La jurisprudence n'est peut-etre pas "
                        "classee par directory-code -> pivoter (arrets citant les grandes "
                        "directives sociales, ou par matiere EuroVoc)."})
        print("\n/!\\ Aucun arret via le repertoire. On pivotera d'approche.")
        return

    print("\n-> Code retenu : %s (%d arrets). Recuperation..." % (best, scores[best]))
    arrets = {}
    for page in range(MAX_PAGES):
        data = sparql(q_list(best, PAGE, page * PAGE))
        rows = data.get("results", {}).get("bindings", [])
        if not rows:
            break
        for b in rows:
            c = b.get("celex", {}).get("value")
            if c:
                arrets[c] = b.get("ecli", {}).get("value", "")
        print("  page %d : +%d (total %d)" % (page + 1, len(rows), len(arrets)))
        if len(rows) < PAGE:
            break
        time.sleep(1)

    ids = sorted(arrets.keys())
    ecrire({
        "source": "CJUE / CELLAR",
        "champ": "Jurisprudence (arrets/ordonnances/avis), repertoire %s" % best,
        "date_recensement": datetime.date.today().isoformat(),
        "code_repertoire_retenu": best,
        "codes_testes": scores,
        "total_arrets": len(ids),
        "items": [{"celex": c, "ecli": arrets[c]} for c in ids],
    })
    print("\n--- RESULTAT ---")
    print("Arrets trouves     : %d" % len(ids))
    print("Ecrit dans         : %s" % OUT)
    if ids:
        print("Echantillon CELEX  : %s" % ", ".join(ids[:8]))

if __name__ == "__main__":
    main()
