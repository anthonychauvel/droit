#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PULL_DILA_FONDS.PY — aspire trois fonds open data de la DILA qui manquaient
à la veille (02/10/2026) :

  CIRCULAIRES  circulaires et instructions des ministères (dont DGT, DSS) :
               la position de l'administration du Travail, l'équivalent du
               BOSS côté droit du travail, et les instructions de
               revalorisation des prestations (CAF, minima…).
  CONSTIT      décisions du Conseil constitutionnel (QPC : un article du Code
               peut être censuré du jour au lendemain).
  JADE         décisions du Conseil d'État (annulation d'un décret, d'un
               arrêté d'extension…).

SOURCE   https://echanges.dila.gouv.fr/OPENDATA/<FONDS>/ (licence ouverte 2.0)
         Le nom exact des fichiers n'est pas supposé : la page d'index est lue
         (dossiers et sous-dossiers), les archives « globales » (le stock
         complet, plusieurs Go) sont ignorées, seules les mises à jour
         incrémentales sont prises.

GARDÉ    output/<fonds>/<id>.json, UNIQUEMENT pour les textes qui touchent
         l'écosystème (travail, sécurité sociale, chômage, retraite,
         prestations familiales…) : titre, date, numéro, solution, articles
         de code cités, extrait. Le reste est compté, pas stocké.
MÉMOIRE  output/<fonds>/_vus.json (archives déjà traitées). Premier passage :
         seules les --premier-max archives les plus récentes.

USAGE    python3 scripts/pull_dila_fonds.py --fonds CIRCULAIRES,CONSTIT,JADE --out output
"""
import argparse
import html
import io
import json
import os
import re
import sys
import tarfile
import time
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone

BASE = "https://echanges.dila.gouv.fr/OPENDATA/"
UA = "Mozilla/5.0 (veille SimulHeures; +https://github.com/anthonychauvel/droit)"
EXT_ARCHIVE = (".tar.gz", ".tgz", ".taz", ".tar", ".tar.bz2", ".zip")
GLOBAL = re.compile(r"freemium|global|stock|complet_|_full", re.I)
_LIEN = re.compile(r'<a\s+href="([^"?#]+)"[^>]*>.*?</a>\s*([0-9]{4}-[0-9]{2}-[0-9]{2}(?:\s+[0-9:]{4,8})?)?', re.I | re.S)

# Pertinence pour l'écosystème SimulHeures (texte normalisé sans accents).
SUJETS = re.compile(
    r"code du travail|code de la securite sociale|salarie|employeur|contrat de travail|duree du travail"
    r"|heures? supplementaires?|heures? complementaires?|conges? payes?|temps partiel|forfait (?:en )?jours"
    r"|convention collective|accord de branche|arrete d.extension|licenciement|rupture conventionnelle|prud.?hom"
    r"|cotisations? sociales?|reduction generale|smic|salaire minimum|assurance chomage|allocation d.aide au retour"
    r"|france travail|unedic|retraite|agirc|arrco|cnav|prestations? familiales?|allocations? familiales"
    r"|caf\b|base mensuelle|bmaf|revalorisation|apprenti|activite partielle|arret de travail|indemnites? journalieres?"
    r"|accident du travail|maladie professionnelle|inaptitude|teletravail|repos (?:quotidien|hebdomadaire)", re.I)
_REF = re.compile(r"\b([LRD])\.?\s?(\d{3,4}(?:-\d+){1,3})\b")


def ouvrir(url, delai=120, essais=3):
    der = None
    for i in range(essais):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=delai) as r:
                return r.read()
        except Exception as e:                       # noqa: BLE001
            der = e
            time.sleep(3 * (i + 1))
    raise RuntimeError(f"{url} : {der}")


def _date(s):
    s = (s or "").strip()
    for f in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, f).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def lister(url, profondeur=1):
    try:
        page = ouvrir(url, delai=60).decode("utf-8", "replace")
    except Exception as e:                           # noqa: BLE001
        print(f"  {url} : {e}")
        return []
    out = []
    for href, date in _LIEN.findall(page):
        href = html.unescape(href)
        if href.startswith(("/", "..", "http")) and not href.startswith(url):
            continue
        cible = urllib.parse.urljoin(url, href)
        if href.endswith("/"):
            if profondeur > 0:
                out += lister(cible, profondeur - 1)
        elif href.lower().endswith(EXT_ARCHIVE) and not GLOBAL.search(href):
            out.append((cible, _date(date)))
    return out


def plat(t):
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    return re.sub(r"\s+", " ", t).strip()


def normaliser(t):
    import unicodedata
    t = "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")
    return t.lower().replace("’", "'")


def champ(xml, *noms):
    for n in noms:
        m = re.search(rf"<{n}\b[^>]*>(.*?)</{n}>", xml, re.S | re.I)
        if m and plat(m.group(1)):
            return plat(m.group(1))
    return ""


def fiche_xml(nom, octets, fonds):
    xml = octets.decode("utf-8", "replace")
    texte = plat(champ(xml, "CONTENU", "TEXTE", "BLOC_TEXTUEL", "CORPS") or xml)
    titre = champ(xml, "TITRE_TXT", "TITREFULL", "TITRE", "INTITULE", "TITLE") or texte[:160]
    if not texte or len(texte) < 80:
        return None
    n = normaliser(titre + " " + texte[:60000])
    sujets = sorted({m.group(0) for m in SUJETS.finditer(n)})
    if not sujets:
        return None
    ident = champ(xml, "ID") or os.path.splitext(os.path.basename(nom))[0]
    return {
        "fonds": fonds,
        "id": ident,
        "titre": titre[:400],
        "date": champ(xml, "DATE_DEC", "DATE_SIGNATURE", "DATE_TEXTE", "DATE_PUBLI", "DATE")[:10],
        "numero": champ(xml, "NUMERO", "NUM", "NUMERO_AFFAIRE")[:80],
        "juridiction": champ(xml, "JURIDICTION", "FORMATION", "MINISTERE", "AUTORITE")[:200],
        "nature": champ(xml, "NATURE", "TYPE")[:80],
        "solution": champ(xml, "SOLUTION", "DISPOSITIF")[:300],
        "articles": sorted({m.group(1) + m.group(2) for m in _REF.finditer(texte)})[:60],
        "sujets": sujets[:15],
        "extrait": texte[:3000],
    }


def documents(octets, nom):
    out = []
    try:
        if nom.lower().endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(octets)) as z:
                for n in z.namelist():
                    if n.lower().endswith(".xml"):
                        out.append((n, z.read(n)))
        else:
            with tarfile.open(fileobj=io.BytesIO(octets), mode="r:*") as t:
                for m in t.getmembers():
                    if m.isfile() and m.name.lower().endswith(".xml"):
                        f = t.extractfile(m)
                        if f:
                            out.append((m.name, f.read()))
    except Exception as e:                           # noqa: BLE001
        print(f"  archive illisible ({nom}) : {e}")
    return out


def traiter_fonds(fonds, out, maxi, premier_max, diag):
    dossier = os.path.join(out, fonds.lower())
    os.makedirs(dossier, exist_ok=True)
    chemin_vus = os.path.join(dossier, "_vus.json")
    try:
        vus = json.load(open(chemin_vus, encoding="utf-8"))
    except Exception:
        vus = {}
    premier = "archives" not in vus
    deja = vus.setdefault("archives", {})
    racine = urllib.parse.urljoin(BASE, fonds + "/")
    cands = lister(racine)
    print(f"{fonds} : {len(cands)} archive(s) incrémentale(s) listée(s).")
    if diag:
        for u, d in cands[-8:]:
            print(f"   {d or '?'}  {urllib.parse.unquote(u.rsplit('/', 1)[-1])}")
    cands.sort(key=lambda c: (c[1] or "", c[0]))
    a_faire = [(u, d) for u, d in cands if urllib.parse.unquote(u.rsplit("/", 1)[-1]) not in deja]
    if premier and len(a_faire) > premier_max:
        for u, d in a_faire[:-premier_max]:
            deja[urllib.parse.unquote(u.rsplit("/", 1)[-1])] = {"date": d, "statut": "ancien-non-telecharge"}
        a_faire = a_faire[-premier_max:]
    gardes = vus_tot = 0
    for u, d in a_faire[-maxi:]:
        nom = urllib.parse.unquote(u.rsplit("/", 1)[-1])
        try:
            octets = ouvrir(u, delai=600)
        except Exception as e:                       # noqa: BLE001
            print(f"  ÉCHEC {nom} : {e}")
            deja[nom] = {"date": d, "statut": "echec"}
            continue
        n_xml = n_g = 0
        for n, contenu in documents(octets, nom):
            n_xml += 1
            f = fiche_xml(n, contenu, fonds)
            if not f:
                continue
            f["archive"], f["archive_date"] = nom, d
            sortie = os.path.join(dossier, re.sub(r"[^A-Za-z0-9._-]+", "_", f["id"])[:120] + ".json")
            json.dump(f, open(sortie, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            n_g += 1
        print(f"  {nom} : {n_xml} texte(s) XML, {n_g} gardé(s) (touchent l'écosystème)")
        deja[nom] = {"date": d, "statut": "ok", "xml": n_xml, "gardes": n_g}
        gardes += n_g
        vus_tot += n_xml
    vus["dernier_passage"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    json.dump(vus, open(chemin_vus, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return gardes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fonds", default="CIRCULAIRES,CONSTIT,JADE")
    ap.add_argument("--out", default="output")
    ap.add_argument("--max", type=int, default=15, help="archives par fonds et par passage")
    ap.add_argument("--premier-max", type=int, default=4)
    ap.add_argument("--diagnostic", action="store_true")
    args = ap.parse_args()
    total = 0
    for f in [x.strip().upper() for x in args.fonds.split(",") if x.strip()]:
        try:
            total += traiter_fonds(f, args.out, args.max, args.premier_max, args.diagnostic)
        except Exception as e:                       # noqa: BLE001
            print(f"{f} : erreur {e}")
    print(f"Terminé : {total} texte(s) gardé(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
