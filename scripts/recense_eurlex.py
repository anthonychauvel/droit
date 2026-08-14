#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
RECENSEMENT EUR-Lex v2 — droit social / travail de l'Union europeenne.

Corrige la requete SPARQL (proprietes exactes reprises du package R 'eurlex')
et ESSAIE PLUSIEURS FORMATS de code de repertoire automatiquement, pour
trouver en UN seul run celui qui renvoie des resultats.

Source : point d'acces public CELLAR SPARQL (sans cle, sans compte).
"""

import json, sys, time, datetime, os
try:
    import requests
except ImportError:
    print("ERREUR: le module 'requests' est requis (pip install requests).", file=sys.stderr)
    sys.exit(2)

ENDPOINT = "http://publications.europa.eu/webapi/rdf/sparql"
CODES_CANDIDATS = ["0520", "05.20", "05", "052020", "05.20.20"]
PAGE = 500
MAX_PAGES = 60
TIMEOUT = 90
OUT = "output/intl/recensement-eurlex.json"

TYPES = ("<http://publications.europa.eu/resource/authority/resource-type/DIR>||"
         "?type=<http://publications.europa.eu/resource/authority/resource-type/DIR_IMPL>||"
         "?type=<http://publications.europa.eu/resource/authority/resource-type/DIR_DEL>||"
         "?type=<http://publications.europa.eu/resource/authority/resource-type/REG>||"
         "?type=<http://publications.europa.eu/resource/authority/resource-type/REG_IMPL>||"
         "?type=<http://publications.europa.eu/resource/authority/resource-type/REG_DEL>")

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
    return (PREFIXES + "SELECT DISTINCT ?celex ?force WHERE {" + bloc_where(code) +
            "  OPTIONAL { ?work cdm:resource_legal_id_celex ?celex. }\n"
            "  OPTIONAL { ?work cdm:resource_legal_in-force ?force. }\n"
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

def main():
    print("=== Recensement EUR-Lex v2 (champ social/travail) ===")
    print("Test des formats de code de repertoire :")
    scores = {}
    for code in CODES_CANDIDATS:
        n = compter(code)
        scores[code] = n
        print("  code %-9s -> %s resultats" % (code, n if n >= 0 else "erreur"))
        time.sleep(1)

    best = max(scores, key=lambda c: scores[c])
    if scores[best] <= 0:
        result = {"source": "EUR-Lex / CELLAR", "date_recensement": datetime.date.today().isoformat(),
                  "total_actes": 0, "codes_testes": scores,
                  "note": "Aucun code n'a renvoye de resultats. A investiguer : format du code fd_555."}
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print("\n/!\\ Aucun resultat sur tous les codes. Voir output pour le detail.")
        return

    print("\n-> Code retenu : %s (%d actes). Recuperation de la liste..." % (best, scores[best]))
    celex = {}
    for page in range(MAX_PAGES):
        data = sparql(q_list(best, PAGE, page * PAGE))
        rows = data.get("results", {}).get("bindings", [])
        if not rows:
            break
        for b in rows:
            c = b.get("celex", {}).get("value")
            if c:
                celex[c] = b.get("force", {}).get("value", "")
        print("  page %d : +%d (total %d)" % (page + 1, len(rows), len(celex)))
        if len(rows) < PAGE:
            break
        time.sleep(1)

    ids = sorted(celex.keys())
    en_vigueur = [c for c in ids if celex[c] in ("true", "1", "")]
    result = {
        "source": "EUR-Lex / CELLAR",
        "champ": "Directives + reglements, repertoire %s (droit social/travail)" % best,
        "date_recensement": datetime.date.today().isoformat(),
        "code_repertoire_retenu": best,
        "codes_testes": scores,
        "total_actes": len(ids),
        "dont_en_vigueur_estime": len(en_vigueur),
        "note": "Ne comprend PAS la jurisprudence CJUE (a recenser separement).",
        "celex": ids,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print("\n--- RESULTAT ---")
    print("Code repertoire    : %s" % best)
    print("Actes trouves      : %d (dont ~%d en vigueur)" % (len(ids), len(en_vigueur)))
    print("Ecrit dans         : %s" % OUT)
    if ids:
        print("Echantillon CELEX  : %s" % ", ".join(ids[:8]))

if __name__ == "__main__":
    main()
