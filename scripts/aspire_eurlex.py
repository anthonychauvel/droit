#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
ASPIRATION EUR-Lex — telecharge le TEXTE INTEGRAL de chaque acte recense.

Lit la liste des CELEX depuis output/intl/recensement-eurlex.json, telecharge
le texte (rendu HTML d'EUR-Lex) et le range en JSON, un fichier par acte, dans
output/intl/textes-eurlex/<CELEX>.json.

- REPRENABLE : saute les actes deja telecharges (relance sans re-tout-faire).
- PAR LOTS : traite au plus LOT actes par run (evite de depasser la duree d'un
  job). Relancer le workflow reprend la suite.
- DEFENSIF : retries + backoff ; si le texte extrait est vide/trop court, on
  marque l'acte "a_revoir" (on n'ecrit pas un fichier bidon).

Source : rendu HTML public d'EUR-Lex (sans cle).
/!\ L'extraction du texte depuis le HTML peut demander un ajustement au 1er run
(structure de page). Le script est verbeux et compte les succes/echecs.
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
LOT = 250                 # nb max d'actes telecharges par run (reprenable)
TIMEOUT = 60
MIN_LEN = 200             # en-deca, on considere l'extraction ratee
# Rendu texte d'un acte (FR ; bascule EN si FR absent geree plus bas).
URL_FR = "https://eur-lex.europa.eu/legal-content/FR/TXT/HTML/?uri=CELEX:%s"
URL_EN = "https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:%s"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/122.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}

def get(url, tries=3):
    for i in range(tries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            if r.status_code == 200 and r.text:
                return r.text
        except Exception as e:
            pass
        time.sleep(2 ** i)
    return None

def extraire_texte(html):
    """Extrait le texte principal, tolerant a la structure."""
    soup = BeautifulSoup(html, "html.parser")
    for bad in soup(["script", "style", "nav", "header", "footer"]):
        bad.decompose()
    # EUR-Lex : le corps de l'acte est souvent dans un conteneur dedie.
    cont = (soup.find("div", id="text") or soup.find("div", class_="eli-main-content")
            or soup.find("div", id="document1") or soup.body or soup)
    txt = cont.get_text("\n", strip=True)
    txt = re.sub(r"\n{3,}", "\n\n", txt)
    # titre
    t = soup.find("title")
    titre = (t.get_text(strip=True) if t else "").replace(" - EUR-Lex", "")
    return titre, txt

def charger_celex():
    with open(RECENSEMENT, encoding="utf-8") as f:
        d = json.load(f)
    return d.get("celex", [])

def main():
    if not os.path.exists(RECENSEMENT):
        print("ERREUR: %s introuvable (lance d'abord le recensement)." % RECENSEMENT); sys.exit(1)
    os.makedirs(DEST, exist_ok=True)
    celex = charger_celex()
    total = len(celex)
    faits = set(f[:-5] for f in os.listdir(DEST) if f.endswith(".json"))
    a_faire = [c for c in celex if c not in faits]
    print("=== Aspiration EUR-Lex ===")
    print("Total recense : %d | deja faits : %d | restants : %d" % (total, len(faits), len(a_faire)))
    print("Ce run en traite au plus %d." % LOT)

    ok = ko = 0
    for c in a_faire[:LOT]:
        html = get(URL_FR % c) or get(URL_EN % c)
        if not html:
            ko += 1; print("  %s : echec reseau" % c); continue
        titre, texte = extraire_texte(html)
        if not texte or len(texte) < MIN_LEN:
            ko += 1; print("  %s : texte vide/trop court (a_revoir)" % c); continue
        rec = {"celex": c, "source": "EUR-Lex", "titre": titre,
               "url": (URL_FR % c), "date_aspiration": datetime.date.today().isoformat(),
               "texte": texte}
        with open(os.path.join(DEST, c + ".json"), "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False)
        ok += 1
        if ok % 25 == 0:
            print("  ... %d telecharges (%d Ko dernier)" % (ok, len(texte) // 1024))
        time.sleep(0.5)  # politesse

    restants = len(a_faire) - min(LOT, len(a_faire))
    print("\n--- RESULTAT DU RUN ---")
    print("Telecharges OK : %d | echecs : %d" % (ok, ko))
    print("Restants apres ce run : %d (relance le workflow pour continuer)" % max(0, restants))

if __name__ == "__main__":
    main()
