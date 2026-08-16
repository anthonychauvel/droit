#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
ASPIRATION CJUE v2 — memes URLs CELLAR que EUR-Lex, memes ameliorations
(sans plafond, commits
PERIODIQUES et budget de temps interne.

Changements vs v3 :
- Plus de "LOT" qui limite le nombre TENTE par run -> on traite TOUT le
  restant en une seule invocation (le budget de temps ci-dessous protege
  quand meme contre un run infini).
- COMMIT + PUSH tous les COMMIT_TOUS fichiers reussis (pas seulement a la
  toute fin) -> si le job est interrompu, le travail deja fait est deja sur
  main, jamais perdu.
- BUDGET DE TEMPS INTERNE (MAX_MINUTES) : le script s'arrete PROPREMENT (avec
  un dernier commit) avant la limite externe du job (5h30), pour ne jamais se
  faire tuer en pleine ecriture/commit.

Methode de recuperation inchangee (CELLAR, avec repli pour les actes recents
sans manifestation "simplified") : deja prouvee sur 677/702 actes.
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
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _git_commit

RECENSEMENT = "output/intl/recensement-cjue.json"
DEST = "output/intl/textes-cjue"
COMMIT_TOUS = 700          # commit+push tous les N fichiers reussis
MAX_MINUTES = 315          # budget interne (5h15) ; marge sous le 5h30 externe
TIMEOUT = 60
MIN_LEN = 200
BASE = "http://publications.europa.eu/resource/celex/%s"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) MonLegiTexte-aspiration/4.0",
    "Accept-Language": "fr", "Content-Language": "fr",
    "Accept": ("text/html, text/html;type=simplified, text/plain, "
               "application/xhtml+xml, application/xhtml+xml;type=simplified"),
}
HEADERS_REPLI = dict(HEADERS)
HEADERS_REPLI["Accept"] = "application/xhtml+xml, text/html, text/plain, application/pdf"

STATUTS = {}


def _get2(url, headers, tries=3):
    for i in range(tries):
        try:
            return requests.get(url, headers=headers, timeout=TIMEOUT, allow_redirects=True)
        except Exception:
            time.sleep(2 ** i)
    return None


def _get(url, tries=3):
    return _get2(url, HEADERS, tries)


def fetch_celex(celex):
    r = _get2(BASE % celex, HEADERS)
    tentative = "std"
    if r is None or r.status_code not in (200, 300):
        r2 = _get2(BASE % celex, HEADERS_REPLI)
        if r2 is not None and r2.status_code in (200, 300):
            r = r2; tentative = "repli"
    if r is None:
        STATUTS["reseau"] = STATUTS.get("reseau", 0) + 1
        return None, "reseau"
    cle = "%s(%s)" % (r.status_code, tentative) if tentative == "repli" else r.status_code
    STATUTS[cle] = STATUTS.get(cle, 0) + 1
    if r.status_code == 200 and r.text:
        return r.text, cle
    if r.status_code == 300 and r.text:
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
            return "\n".join(morceaux), cle
    return None, cle


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
        _d = json.load(f)
        celex = [it.get("celex") for it in _d.get("items", []) if it.get("celex")]
    faits = set(x[:-5] for x in os.listdir(DEST) if x.endswith(".json"))
    a_faire = [c for c in celex if c not in faits]
    print("=== Aspiration CJUE v2 (via CELLAR, sans plafond) ===")
    print("Total %d | faits %d | restants %d" % (len(celex), len(faits), len(a_faire)))
    print("Commit tous les %d | budget interne %d min" % (COMMIT_TOUS, MAX_MINUTES))

    debut = time.time()
    ok = ko = ok_depuis_commit = 0
    arret_budget = False
    for idx, c in enumerate(a_faire, 1):
        if (time.time() - debut) / 60 > MAX_MINUTES:
            print("\n/!\\ Budget de temps atteint (%d min) -> arret propre." % MAX_MINUTES)
            arret_budget = True
            break
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
        rec = {"celex": c, "source": "CJUE", "titre": titre, "statut_http": st,
               "url": BASE % c, "date_aspiration": datetime.date.today().isoformat(), "texte": texte}
        with open(os.path.join(DEST, c + ".json"), "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False)
        ok += 1; ok_depuis_commit += 1
        if ok % 25 == 0: print("  ... %d OK (dernier: %d Ko)" % (ok, len(texte) // 1024))
        if ok_depuis_commit >= COMMIT_TOUS:
            cok, detail = _git_commit.commit_et_push(
                [DEST], "Aspiration CJUE (auto, %d faits) [skip ci]" % (len(faits) + ok))
            print("  -- commit intermediaire (%d fichiers) : %s (%s)" % (ok_depuis_commit, cok, detail))
            ok_depuis_commit = 0
        time.sleep(0.4)

    if ok_depuis_commit > 0:
        cok, detail = _git_commit.commit_et_push(
            [DEST], "Aspiration CJUE (auto, final) [skip ci]")
        print("  -- commit final (%d fichiers) : %s (%s)" % (ok_depuis_commit, cok, detail))

    print("\n--- RESULTAT DU RUN ---")
    print("OK: %d | echecs: %d | arret pour budget de temps: %s" % (ok, ko, arret_budget))
    print("Statuts HTTP rencontres: %s" % STATUTS)
    print("Restants apres ce run: %d" % (len(a_faire) - ok - ko))


if __name__ == "__main__":
    main()
