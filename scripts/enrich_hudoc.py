#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
ENRICHISSEMENT HUDOC (CEDH) — via l'API query qui FONCTIONNE (pas l'endpoint
texte, lui bloque le runner).

Le texte integral des arrets n'est accessible que sur l'endpoint docx->html de
HUDOC, qui bloque les IP datacenter GitHub (timeouts confirmes). MAIS l'API
'app/query/results' (celle du recensement) fonctionne, elle, et peut renvoyer
des champs RICHES : conclusion, mots-cles (kpthesaurus), resume
(HighlightedSummary), importance, article, violation/nonviolation, respondent.

Ce script recupere ces champs pour les ~5214 arrets emploi (art. 8/14) et ecrit
un fichier par arret dans output/intl/textes-hudoc/<itemid>.json, au MEME
format que les autres sources (champ 'texte' = fiche de synthese lisible +
'url' = lien HUDOC). -> meme affichage que EUR-Lex/CJUE, cherchable par theme.

NB honnete : ce n'est PAS le raisonnement complet de l'arret (impossible a
recuperer par cette voie), c'est une fiche riche + lien vers le texte integral.
"""

import json, sys, time, datetime, os, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import requests
except ImportError:
    print("ERREUR: 'requests' requis.", file=sys.stderr); sys.exit(2)

DEST = "output/intl/textes-hudoc"
BASE = "https://hudoc.echr.coe.int/app/query/results"
# Meme requete que le recensement -> memes ~5214 arrets.
QUERY = ('contentsitename:ECHR '
         'AND (documentcollectionid2:"JUDGMENTS") '
         'AND (article:"8" OR article:"14") '
         'AND (employment OR employee OR dismissal OR workplace OR employer '
         'OR "trade union" OR occupational OR "private life")')
# Champs RICHES disponibles via l'API query (verifies dans echr-extractor).
FIELDS = ("itemid,docname,appno,article,ecli,kpthesaurus,conclusion,importance,"
          "violation,nonviolation,issue,respondent,kpdate,HighlightedSummary")
PAGE = 500
MAX_PAGES = 40
TIMEOUT = 60
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) MonLegiTexte-enrich/1.0",
           "Accept": "application/json"}


def _safe(itemid):
    return re.sub(r"[^A-Za-z0-9._-]", "_", itemid)


def _clean(v):
    """Nettoie une valeur de champ (peut contenir du HTML de surlignage)."""
    if v is None:
        return ""
    if isinstance(v, list):
        v = " ; ".join(str(x) for x in v)
    v = re.sub(r"<[^>]+>", "", str(v))          # retire les balises
    v = v.replace("&nbsp;", " ").replace("&amp;", "&")
    return re.sub(r"\s+", " ", v).strip()


def fetch(start, length, tries=4):
    params = {"query": QUERY, "select": FIELDS, "sort": "kpdate Descending",
              "start": start, "length": length}
    last = None
    for i in range(tries):
        try:
            r = requests.get(BASE, params=params, headers=HEADERS, timeout=TIMEOUT)
            if r.status_code == 200:
                return r.json()
            last = "HTTP %s" % r.status_code
        except Exception as e:
            last = repr(e)
        time.sleep(2 ** i)
    raise RuntimeError("Echec requete HUDOC query: %s" % last)


def composer_texte(c):
    """Fiche de synthese lisible, champs les PLUS cherchables en premier
    (docname, mots-cles, conclusion, question), puis le reste."""
    docname = _clean(c.get("docname"))
    motscles = _clean(c.get("kpthesaurus"))
    conclusion = _clean(c.get("conclusion"))
    issue = _clean(c.get("issue"))
    resume = _clean(c.get("HighlightedSummary"))
    appno = _clean(c.get("appno"))
    date = _clean(c.get("kpdate")) or _clean(c.get("judgementdate"))
    respondent = _clean(c.get("respondent"))
    article = _clean(c.get("article"))
    violation = _clean(c.get("violation"))
    nonviolation = _clean(c.get("nonviolation"))
    importance = _clean(c.get("importance"))

    parts = []
    if docname: parts.append(docname)
    if motscles: parts.append("Mots-cles : " + motscles)
    if conclusion: parts.append("Conclusion : " + conclusion)
    if issue: parts.append("Question : " + issue)
    if resume: parts.append(resume)
    meta = []
    if appno: meta.append("Requete no " + appno)
    if date: meta.append(date)
    if respondent: meta.append("Etat : " + respondent)
    if article: meta.append("Article(s) : " + article)
    if violation: meta.append("Violation : " + violation)
    if nonviolation: meta.append("Non-violation : " + nonviolation)
    if importance: meta.append("Importance : " + importance)
    if meta: parts.append(" · ".join(meta))
    parts.append("— Fiche de synthèse (mots-clés, conclusion, résumé). Le texte "
                 "intégral de l'arrêt de la Cour est consultable sur HUDOC via le "
                 "lien ci-dessous. —")
    return "\n\n".join(parts)


def main():
    os.makedirs(DEST, exist_ok=True)
    print("=== Enrichissement HUDOC (via API query qui fonctionne) ===")
    total_annonce = None
    ecrits = 0
    vus = set()
    for page in range(MAX_PAGES):
        start = page * PAGE
        data = fetch(start, PAGE)
        if total_annonce is None:
            total_annonce = data.get("resultcount")
            print("HUDOC annonce %s arrets" % total_annonce)
        results = data.get("results") or []
        if not results:
            break
        for it in results:
            c = it.get("columns", it) or {}
            iid = c.get("itemid")
            if not iid or iid in vus:
                continue
            vus.add(iid)
            texte = composer_texte(c)
            rec = {
                "itemid": iid, "source": "CEDH",
                "titre": _clean(c.get("docname")) or ("Arrêt CEDH " + iid),
                "url": "https://hudoc.echr.coe.int/fre?i=%s" % iid,
                "appno": _clean(c.get("appno")), "date": _clean(c.get("kpdate")),
                "ecli": _clean(c.get("ecli")),
                "conclusion": _clean(c.get("conclusion")),
                "motscles": _clean(c.get("kpthesaurus")),
                "date_enrichissement": datetime.date.today().isoformat(),
                "texte": texte,
                "synthese": True,   # marqueur : fiche, pas le texte integral
            }
            with open(os.path.join(DEST, _safe(iid) + ".json"), "w", encoding="utf-8") as f:
                json.dump(rec, f, ensure_ascii=False)
            ecrits += 1
        print("  page %d : %d arrets ecrits (total %d)" % (page + 1, len(results), ecrits))
        if len(results) < PAGE:
            break
        time.sleep(1)

    print("\n--- RESULTAT ---")
    print("Arrets enrichis ecrits : %d (sur %s annonces)" % (ecrits, total_annonce))
    print("Dossier : %s" % DEST)
    if ecrits == 0:
        print("/!\\ 0 ecrit : si l'API query renvoie une erreur, elle a peut-etre "
              "change -> verifier la requete/les champs.")


if __name__ == "__main__":
    main()
