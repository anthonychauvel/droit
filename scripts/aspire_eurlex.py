#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
ASPIRATION EUR-Lex v2 — via CELLAR (publications.europa.eu), pas eur-lex.europa.eu.

Le run precedent : tout en "echec reseau" -> eur-lex.europa.eu bloque le runner.
Or CELLAR (publications.europa.eu) est joignable (le recensement le prouve).
On reprend donc la methode EXACTE du package R 'eurlex' pour recuperer le texte :
  URL   : http://publications.europa.eu/resource/celex/<CELEX>
  En-tetes Accept : text/html, ...  + Accept-Language: fr
  Statut 200 -> contenu direct ; 300 -> plusieurs versions, on suit les liens.

Ecrit un JSON par acte dans output/intl/textes-eurlex/<CELEX>.json.
REPRENABLE (saute les faits), PAR LOTS, avec log des STATUTS HTTP.
"""

import json, sys, time, datetime, os, re
try:
    import requests
except ImportError:
    print("ERREUR: 'requests' requis.", file=sys.stderr); sys.exit(2)
try:
    from bs4 import BeautifulSoup
except ImportError:
    print("ERREUR: 'beautifulsoup4' requis.", file=sys.stderr); sys.exit(2)

RECENSEMENT = "output/intl/recensement-eurlex.json"
DEST = "output/intl/textes-eurlex"
LOT = 250
TIMEOUT = 60
MIN_LEN = 200
BASE = "http://publications.europa.eu/resource/celex/%s"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) MonLegiTexte-aspiration/2.0",
    "Accept-Language": "fr",
    "Content-Language": "fr",
    "Accept": ("text/html, text/html;type=simplified, text/plain, "
               "application/xhtml+xml, application/xhtml+xml;type=simplified"),
}

STATUTS = {}  # compteur de statuts HTTP pour diagnostic

def _get(url, tries=3):
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
            return r
        except Exception as e:
            last = repr(e)
            time.sleep(2 ** i)
    return None  # echec reseau franc

def fetch_celex(celex):
    """Renvoie (html, statut). Gere 200 (direct) et 300 (multi-versions)."""
    r = _get(BASE % celex)
    if r is None:
        STATUTS["reseau"] = STATUTS.get("reseau", 0) + 1
        return None, "reseau"
    STATUTS[r.status_code] = STATUTS.get(r.status_code, 0) + 1
    if r.status_code == 200 and r.text:
        return r.text, 200
    if r.status_code == 300 and r.text:
        # Plusieurs manifestations : suivre les liens (on privilegie FR).
        soup = BeautifulSoup(r.text, "html.parser")
        liens = [a.get("href") for a in soup.find_all("a") if a.get("href")]
        liens = [l for l in liens if l and l.startswith("http")]
        liens_fr = [l for l in liens if "/FR/" in l or ".FRA." in l or "_FR." in l] or liens
        morceaux = []
        for l in liens_fr[:6]:
            rr = _get(l)
            if rr is not None and rr.status_code == 200 and rr.text:
                morceaux.append(rr.text)
        if morceaux:
            return "\n".join(morceaux), 300
    return None, r.status_code

def extraire_texte(html):
    soup = BeautifulSoup(html, "html.parser")
    for bad in soup(["script", "style", "nav", "header", "footer", "link", "meta"]):
        bad.decompose()
    cont = (soup.find("div", id="text") or soup.find("div", class_="eli-main-content")
            or soup.body or soup)
    txt = cont.get_text("\n", strip=True)
    txt = re.sub(r"\n{3,}", "\n\n", txt)
    t = soup.find("title")
    titre = (t.get_text(strip=True) if t else "").replace(" - EUR-Lex", "").strip()
    return titre, txt

def main():
    if not os.path.exists(RECENSEMENT):
        print("ERREUR: %s introuvable." % RECENSEMENT); sys.exit(1)
    os.makedirs(DEST, exist_ok=True)
    with open(RECENSEMENT, encoding="utf-8") as f:
        celex = json.load(f).get("celex", [])
    faits = set(x[:-5] for x in os.listdir(DEST) if x.endswith(".json"))
    a_faire = [c for c in celex if c not in faits]
    print("=== Aspiration EUR-Lex v2 (via CELLAR) ===")
    print("Total %d | faits %d | restants %d | ce lot: %d max" % (len(celex), len(faits), len(a_faire), LOT))

    ok = ko = 0
    for c in a_faire[:LOT]:
        html, st = fetch_celex(c)
        if not html:
            ko += 1
            if ko <= 8: print("  %s : statut %s" % (c, st))
            continue
        titre, texte = extraire_texte(html)
        if not texte or len(texte) < MIN_LEN:
            ko += 1
            if ko <= 8: print("  %s : texte trop court (statut %s)" % (c, st))
            continue
        rec = {"celex": c, "source": "EUR-Lex", "titre": titre, "statut_http": st,
               "url": BASE % c, "date_aspiration": datetime.date.today().isoformat(), "texte": texte}
        with open(os.path.join(DEST, c + ".json"), "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False)
        ok += 1
        if ok % 25 == 0: print("  ... %d OK (dernier: %d Ko)" % (ok, len(texte) // 1024))
        time.sleep(0.4)

    print("\n--- RESULTAT DU RUN ---")
    print("OK: %d | echecs: %d" % (ok, ko))
    print("Statuts HTTP rencontres: %s" % STATUTS)
    print("Restants apres ce run: %d" % max(0, len(a_faire) - min(LOT, len(a_faire))))
    if ok == 0 and ko > 0:
        print("/!\\ 0 succes. Regarde 'Statuts HTTP' : 403/blocage, 406 (format), "
              "ou 'reseau'. On ajuste selon ce qu'on voit.")

if __name__ == "__main__":
    main()
