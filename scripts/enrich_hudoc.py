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
    raise HudocInjoignable("Echec requete HUDOC query: %s" % last)


class HudocInjoignable(RuntimeError):
    """HUDOC ne repond pas au runner. Depuis le 14/09/2026, plus aucun acces
    HUDOC ne passe depuis GitHub (recensement fige au 07/09, lot CEDH du 16/09
    « rien de nouveau »), alors que l'API repond normalement ailleurs : blocage
    des IP datacenter, comme l'endpoint texte avant elle. Ce n'est pas une
    panne du script -> avertissement, pas echec (plus de mail rouge chaque
    lundi), et SURTOUT aucun fichier touche."""


def themes_fr(article):
    """Tags thematiques FR DERIVES des articles CEDH. On a l'article de facon
    fiable -> on en deduit des mots-cles francais, ce qui rend les fiches
    cherchables par theme EN FRANCAIS malgre un contenu (nom, conclusion) en
    anglais et des mots-cles d'origine numeriques. Tout le corpus etant filtre
    sur le contexte travail, on ajoute systematiquement emploi/salarie."""
    a = (article or "").upper()
    nums = set(re.findall(r"\d+", a))
    tags = ["travail", "emploi", "salarié"]
    if "8" in nums:  tags += ["vie privée", "correspondance", "données personnelles", "surveillance"]
    if "14" in nums: tags += ["discrimination", "égalité de traitement"]
    if "10" in nums: tags += ["liberté d'expression"]
    if "11" in nums: tags += ["liberté d'association", "liberté syndicale", "syndicat"]
    if "9" in nums:  tags += ["liberté de religion", "convictions"]
    if "6" in nums:  tags += ["procès équitable"]
    if "4" in nums:  tags += ["travail forcé", "servitude"]
    if "P1" in a:    tags += ["biens", "propriété"]
    # dedup en gardant l'ordre
    vus = set(); out = []
    for t in tags:
        if t not in vus: vus.add(t); out.append(t)
    return out


def composer_texte(c):
    """Fiche de synthese lisible. On NE MET PAS kpthesaurus (codes numeriques
    illisibles: '343;100;464') ni issue (references legislatives brutes). On
    garde le nom d'affaire, des THEMES FR derives de l'article, la conclusion,
    le resume s'il existe, et les metadonnees."""
    docname = _clean(c.get("docname"))
    conclusion = _clean(c.get("conclusion"))
    resume = _clean(c.get("HighlightedSummary"))
    appno = _clean(c.get("appno"))
    date = _clean(c.get("kpdate"))[:10]
    respondent = _clean(c.get("respondent"))
    article = _clean(c.get("article"))
    violation = _clean(c.get("violation"))
    importance = _clean(c.get("importance"))

    parts = []
    if docname: parts.append(docname)
    tags = themes_fr(article)
    if tags: parts.append("Thèmes : " + ", ".join(tags))   # tôt = dans l'extrait cherchable
    if conclusion: parts.append("Conclusion (résumé officiel de la Cour) : " + conclusion)
    if resume: parts.append(resume)
    meta = []
    if appno: meta.append("Requête n° " + appno)
    if date: meta.append(date)
    if respondent: meta.append("État défendeur : " + respondent)
    if article: meta.append("Article(s) : " + article)
    if violation: meta.append("Violation : " + violation)
    if importance: meta.append("Importance : " + importance)
    if meta: parts.append(" · ".join(meta))
    parts.append("— Fiche de synthèse (nom, conclusion, articles). Le texte "
                 "intégral de l'arrêt est consultable sur HUDOC via le lien "
                 "ci-dessous. —")
    return "\n\n".join(parts)


def main():
    os.makedirs(DEST, exist_ok=True)
    print("=== Enrichissement HUDOC (via API query qui fonctionne) ===")
    total_annonce = None
    ecrits = gardes = inchanges = 0
    vus = set()
    for page in range(MAX_PAGES):
        start = page * PAGE
        try:
            data = fetch(start, PAGE)
        except HudocInjoignable as e:
            print("::warning::HUDOC injoignable depuis le runner (%s). "
                  "Aucune fiche modifiee (%d ecrites avant l'arret)." % (e, ecrits))
            return 0
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
            chemin = os.path.join(DEST, _safe(iid) + ".json")
            existant = None
            if os.path.exists(chemin):
                try:
                    existant = json.load(open(chemin, encoding="utf-8"))
                except Exception:
                    existant = None
            # NE JAMAIS ECRASER LE TEXTE INTEGRAL. Le workflow du mercredi
            # (enrichir_cedh_textes_hudoc.py) remplace la fiche de synthese par
            # le texte officiel et pose « texte_source ». Ce script reecrivait
            # tout chaque lundi : le 07/09, 5 242 fichiers reecrits, 13 700
            # lignes supprimees -- les 646 textes integraux du 02/09 effaces,
            # refaits le 09/09, et ainsi de suite chaque semaine.
            if existant and existant.get("texte_source"):
                gardes += 1
                continue
            texte = composer_texte(c)
            rec = {
                "itemid": iid, "source": "CEDH",
                "titre": _clean(c.get("docname")) or ("Arrêt CEDH " + iid),
                "url": "https://hudoc.echr.coe.int/fre?i=%s" % iid,
                "appno": _clean(c.get("appno")), "date": _clean(c.get("kpdate")),
                "ecli": _clean(c.get("ecli")),
                "conclusion": _clean(c.get("conclusion")),
                "date_enrichissement": datetime.date.today().isoformat(),
                "texte": texte,
                "synthese": True,   # marqueur : fiche, pas le texte integral
            }
            # Fiche inchangee (hors date) -> on ne la reecrit pas : sinon la
            # seule date_enrichissement modifiait les 5 242 fichiers chaque
            # semaine, un commit geant pour rien.
            if existant:
                a = dict(existant); a.pop("date_enrichissement", None)
                b = dict(rec); b.pop("date_enrichissement", None)
                if a == b:
                    inchanges += 1
                    continue
            with open(chemin, "w", encoding="utf-8") as f:
                json.dump(rec, f, ensure_ascii=False)
            ecrits += 1
        print("  page %d : %d arrets ecrits (total %d)" % (page + 1, len(results), ecrits))
        if len(results) < PAGE:
            break
        time.sleep(1)

    print("\n--- RESULTAT ---")
    print("Arrets enrichis ecrits : %d (sur %s annonces)" % (ecrits, total_annonce))
    print("Textes integraux preserves : %d · fiches inchangees non reecrites : %d"
          % (gardes, inchanges))
    print("Dossier : %s" % DEST)
    if ecrits == 0 and gardes == 0 and inchanges == 0:
        print("/!\\ 0 ecrit : si l'API query renvoie une erreur, elle a peut-etre "
              "change -> verifier la requete/les champs.")


if __name__ == "__main__":
    sys.exit(main())
