#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PULL_BOCC.PY — aspire le Bulletin officiel des conventions collectives (BOCC)
depuis l'open data de la DILA, et en garde ce qui sert à la veille.

POURQUOI
    KALI (pull_ccn.py) donne les textes des conventions, mais beaucoup
    d'avenants « salaires » n'y ont que le titre, ou la mention « tableau non
    reproduit, consultable au BOCC ». Les grilles sont dans les PDF du BOCC.

SOURCE
    https://echanges.dila.gouv.fr/OPENDATA/BOCC/<année>/  (licence ouverte 2.0)
    Publication hebdomadaire. Le script NE suppose PAS le nom exact des
    fichiers : il lit la page d'index (dossiers et sous-dossiers) et prend
    tout ce qui ressemble à un bulletin : .pdf, .xml, ou une archive
    (.tar.gz, .tgz, .taz, .tar, .zip) qu'il ouvre pour y trouver PDF et XML.

CE QUI EST GARDÉ (output/bocc/<année>/<fichier>.json)
    Le texte n'est pas copié en entier (un bulletin fait des centaines de
    pages). Le PDF est découpé en « textes » (pages consécutives d'une même
    convention), et pour chacun :
      idcc       conventions citées (« IDCC 1801 », « (n° 1801) »)
      titre      première ligne qui ressemble à un titre (Avenant n°…, Accord…)
      pages      [première, dernière]
      salaires   true si le texte parle de salaires minima / grille / point
      montants   montants en euros entre 1 000 et 10 000 (candidats salaires
                 mensuels), dans l'ordre du texte
      texte      les 20 000 premiers caractères (pour les mots-clés de la veille)
      scanne     true si le PDF n'a pas de texte lisible (image) et que l'OCR
                 n'a pas été lancé ou n'a rien donné

MÉMOIRE (output/bocc/_vus.json)
    Les fichiers déjà traités : jamais retéléchargés. Premier passage : tout
    ce qui a plus de --recul-jours jours est noté « vu » sans être téléchargé
    (sinon on aspirerait des années de bulletins d'un coup).

LICENCE OUVERTE : chaque fiche garde l'URL, le nom et la date du fichier
(mentions exigées par la DILA).

USAGE
    python3 scripts/pull_bocc.py --out output/bocc [--max 25] [--ocr]
"""
import argparse
import html
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone, timedelta

BASE = "https://echanges.dila.gouv.fr/OPENDATA/BOCC/"
UA = "Mozilla/5.0 (veille SimulHeures; +https://github.com/anthonychauvel/droit)"
EXT_ARCHIVE = (".tar.gz", ".tgz", ".taz", ".tar", ".zip")
EXT_DOC = (".pdf", ".xml")
TEXTE_MAX = 20000

# « IDCC 1801 », « IDCC : 1801 », « IDCC n° 1801 », « (n° 1801) » après
# « convention collective », « brochure … IDCC 1801 »
_IDCC = re.compile(r"\bIDCC\s*(?::|n[°o])?\s*(\d{1,4})\b", re.I)
_IDCC_PAR = re.compile(r"convention collective[^()\n]{0,160}\(\s*n[°o]\s*(\d{1,4})\s*\)", re.I)
_TITRE = re.compile(r"^\s*((?:Avenant|Accord|Annexe|Protocole|Adh[ée]sion|D[ée]nonciation|Convention collective|Arr[êe]t[ée])\b.{5,200})$",
                    re.I | re.M)
_SALAIRES = re.compile(r"salaires? minima|salaires? minimum|grille (?:des |de )?(?:salaires|r[ée]mun[ée]rations)"
                       r"|r[ée]mun[ée]rations? minimales?|valeur du point|salaires? minimaux"
                       r"|r[ée]mun[ée]ration annuelle garantie|salaire minimum (?:conventionnel|hi[ée]rarchique)"
                       r"|\bSMH\b|\bRAG\b|\bRMAG\b|\bSMIC\b", re.I)
# 1 867,02 € · 1867,02 euros · 1 867 € · 2 100,00
# Un montant = décimales OU unité : sans l'un ni l'autre, « 2026 » (une année)
# ou « 1801 » (un IDCC) passeraient pour des salaires.
_MONTANT = re.compile(r"(?<![\d,.])(\d{1,2}[   .]?\d{3})(,\d{1,2})?\s*(€|euros?\b|EUR\b)?")
_DATE_SIGN = re.compile(r"\bdu\s+(\d{1,2}(?:er)?\s+(?:janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[uû]t|"
                        r"septembre|octobre|novembre|d[ée]cembre)\s+\d{4})", re.I)
# Ligne d'index Apache : <a href="x">x</a>   2026-09-28 10:12   1.2M
_LIEN = re.compile(r'<a\s+href="([^"?#]+)"[^>]*>.*?</a>\s*([0-9]{4}-[0-9]{2}-[0-9]{2}(?:\s+[0-9:]{4,8})?|[0-9]{2}-[A-Za-z]{3}-[0-9]{4}\s+[0-9:]{4,8})?',
                   re.I | re.S)


# ── réseau ────────────────────────────────────────────────────────────────
def ouvrir(url, essais=3, delai=60):
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


def _date_index(s):
    s = (s or "").strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d-%b-%Y %H:%M"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def lister(url, profondeur=2):
    """-> [(url_fichier, date_ou_None)] : fichiers utiles sous url (index Apache)."""
    try:
        page = ouvrir(url).decode("utf-8", "replace")
    except Exception as e:                           # noqa: BLE001
        print(f"  index illisible : {e}")
        return []
    out = []
    for href, date in _LIEN.findall(page):
        href = html.unescape(href)
        if href.startswith(("/", "..", "http")) and not href.startswith(url):
            continue                                 # dossier parent, tri, liens externes
        cible = urllib.parse.urljoin(url, href)
        bas = href.lower()
        if bas.endswith("/"):
            if profondeur > 0:
                out += lister(cible, profondeur - 1)
        elif bas.endswith(EXT_DOC + EXT_ARCHIVE):
            out.append((cible, _date_index(date)))
    return out


# ── extraction ────────────────────────────────────────────────────────────
def pages_pdf(chemin, ocr=False):
    """-> (liste de pages texte, scanne?)"""
    def lire(p):
        r = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", p, "-"],
                           capture_output=True, timeout=600)
        return r.stdout.decode("utf-8", "replace").split("\f")
    pages = lire(chemin)
    utile = sum(len(p.strip()) for p in pages)
    # Une page de BOCC fait ~2 000 caractères ; moins de 40 en moyenne = images seules.
    scanne = utile < 40 * max(1, len(pages))
    if scanne and ocr and shutil.which("ocrmypdf"):
        sortie = chemin + ".ocr.pdf"
        r = subprocess.run(["ocrmypdf", "-l", "fra", "--skip-text", "--quiet", chemin, sortie],
                           capture_output=True, timeout=1800)
        if r.returncode == 0 and os.path.exists(sortie):
            pages = lire(sortie)
            scanne = sum(len(p.strip()) for p in pages) < 40 * max(1, len(pages))
    return pages, scanne


def texte_xml(octets):
    t = octets.decode("utf-8", "replace")
    t = re.sub(r"<\?xml.*?\?>|<!DOCTYPE.*?>", " ", t, flags=re.S)
    t = re.sub(r"<[^>]+>", "\n", t)
    t = html.unescape(t)
    return [re.sub(r"\n\s*\n+", "\n", t)]


def idcc_de(t):
    s = {m.lstrip("0") or "0" for m in _IDCC.findall(t)} | {m.lstrip("0") or "0" for m in _IDCC_PAR.findall(t)}
    return sorted((x for x in s if x != "0"), key=int)


def montants_de(t):
    out = []
    for m in _MONTANT.finditer(t):
        if not (m.group(2) or m.group(3)):
            continue
        brut = re.sub(r"[   .]", "", m.group(1)) + (m.group(2) or "").replace(",", ".")
        try:
            v = float(brut)
        except ValueError:
            continue
        if 1000 <= v <= 10000:
            out.append(round(v, 2))
    return out[:120]


def titre_de(t):
    m = _TITRE.search(t)
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()[:240]
    for ligne in t.splitlines():
        if len(ligne.strip()) > 12:
            return re.sub(r"\s+", " ", ligne).strip()[:240]
    return ""


def decouper(pages):
    """Pages -> textes : une nouvelle convention citée en haut de page (ou un
    nouveau titre « Avenant/Accord… ») ouvre un nouveau texte."""
    textes, cur = [], None
    for i, p in enumerate(pages, 1):
        if not p.strip():
            continue
        haut = "\n".join(p.splitlines()[:25])
        ids = idcc_de(haut) or idcc_de(p)
        nouveau_titre = bool(_TITRE.search(haut))
        if cur is None or (ids and set(ids) != set(cur["idcc"])) or (nouveau_titre and cur["idcc"] and ids):
            cur = {"idcc": ids, "pages": [i, i], "_t": [p]}
            textes.append(cur)
        else:
            cur["pages"][1] = i
            cur["_t"].append(p)
            if not cur["idcc"] and ids:
                cur["idcc"] = ids
    out = []
    for t in textes:
        brut = "\n".join(t.pop("_t"))
        plat = re.sub(r"[ \t ]+", " ", brut)
        m = _DATE_SIGN.search(plat[:3000])
        out.append({
            "idcc": t["idcc"],
            "pages": t["pages"],
            "titre": titre_de(brut),
            "date_signature": m.group(1) if m else None,
            "salaires": bool(_SALAIRES.search(plat)),
            "montants": montants_de(plat),
            "texte": re.sub(r"\s+", " ", plat).strip()[:TEXTE_MAX],
        })
    return out


def documents(octets, nom):
    """Archive ou document -> [(nom_interne, octets)] des PDF et XML."""
    bas = nom.lower()
    if bas.endswith(EXT_DOC):
        return [(nom, octets)]
    docs = []
    try:
        if bas.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(octets)) as z:
                for n in z.namelist():
                    if n.lower().endswith(EXT_DOC):
                        docs.append((n, z.read(n)))
        else:
            with tarfile.open(fileobj=io.BytesIO(octets), mode="r:*") as t:
                for m in t.getmembers():
                    if m.isfile() and m.name.lower().endswith(EXT_DOC):
                        f = t.extractfile(m)
                        if f:
                            docs.append((m.name, f.read()))
    except Exception as e:                           # noqa: BLE001
        print(f"  archive illisible ({nom}) : {e}")
    return docs


def traiter(url, date, ocr, dossier_tmp):
    nom = urllib.parse.unquote(url.rstrip("/").rsplit("/", 1)[-1])
    octets = ouvrir(url, delai=300)
    fiche = {"source": "DILA — Bulletin officiel des conventions collectives (licence ouverte 2.0)",
             "url": url, "fichier": nom, "date_fichier": date,
             "recupere_le": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
             "documents": []}
    for n, contenu in documents(octets, nom):
        doc = {"nom": n, "textes": [], "scanne": False}
        if n.lower().endswith(".pdf"):
            p = os.path.join(dossier_tmp, "doc.pdf")
            open(p, "wb").write(contenu)
            try:
                pages, scanne = pages_pdf(p, ocr)
            except Exception as e:                   # noqa: BLE001
                doc["erreur"] = str(e)[:300]
                fiche["documents"].append(doc)
                continue
            doc["scanne"] = scanne
            doc["nb_pages"] = len(pages)
        else:
            pages = texte_xml(contenu)
        doc["textes"] = decouper(pages)
        fiche["documents"].append(doc)
    return fiche


# ── programme ─────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="output/bocc")
    ap.add_argument("--base", default=BASE, help="racine de l'open data (test : un serveur local)")
    ap.add_argument("--max", type=int, default=25, help="fichiers téléchargés au plus par passage")
    ap.add_argument("--recul-jours", type=int, default=60,
                    help="premier passage : plus ancien que ça = noté vu sans téléchargement")
    ap.add_argument("--ocr", action="store_true", help="OCR (ocrmypdf) des PDF sans texte")
    args = ap.parse_args()

    if not shutil.which("pdftotext"):
        print("pdftotext absent (paquet poppler-utils) : arrêt.")
        return 1
    os.makedirs(args.out, exist_ok=True)
    chemin_vus = os.path.join(args.out, "_vus.json")
    try:
        vus = json.load(open(chemin_vus, encoding="utf-8"))
    except Exception:
        vus = {}
    premier = "fichiers" not in vus
    deja = vus.setdefault("fichiers", {})

    an = datetime.now(timezone.utc).year
    annees = [an - 1, an] if datetime.now(timezone.utc).month <= 2 or premier else [an]
    candidats = []
    for a in annees:
        url = urllib.parse.urljoin(args.base, f"{a}/")
        trouves = lister(url)
        print(f"{url} : {len(trouves)} fichier(s) listé(s).")
        candidats += trouves
    if not candidats:
        # Aucun dossier par année : on tente la racine (structure différente).
        candidats = lister(args.base)
        print(f"{args.base} : {len(candidats)} fichier(s) listé(s) à la racine.")
    if not candidats:
        print("Rien listé : la structure de l'open data a peut-être changé. Ouvre "
              f"{args.base} dans un navigateur et adapte lister().")
        return 2

    limite = (datetime.now(timezone.utc) - timedelta(days=args.recul_jours)).strftime("%Y-%m-%d")
    a_faire = []
    for url, date in sorted(candidats, key=lambda c: (c[1] or "", c[0])):
        cle = url[len(args.base):] if url.startswith(args.base) else url
        if cle in deja:
            continue
        if premier and date and date < limite:
            deja[cle] = {"date": date, "statut": "ancien-non-telecharge"}
            continue
        a_faire.append((cle, url, date))
    print(f"{len(a_faire)} nouveau(x) fichier(s) ; {min(len(a_faire), args.max)} traité(s) ce passage.")

    faits = 0
    with tempfile.TemporaryDirectory() as tmp:
        for cle, url, date in a_faire[-args.max:]:  # les plus récents d'abord servis
            try:
                fiche = traiter(url, date, args.ocr, tmp)
            except Exception as e:                   # noqa: BLE001
                print(f"  ÉCHEC {cle} : {e}")
                deja[cle] = {"date": date, "statut": "echec", "erreur": str(e)[:200]}
                continue
            sous = os.path.join(args.out, (date or "sans-date")[:4])
            os.makedirs(sous, exist_ok=True)
            base = re.sub(r"[^A-Za-z0-9._-]+", "_", cle.replace("/", "_"))
            base = re.sub(r"\.(tar\.gz|tgz|taz|tar|zip|pdf|xml)$", "", base, flags=re.I)
            json.dump(fiche, open(os.path.join(sous, base + ".json"), "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
            n = sum(len(d["textes"]) for d in fiche["documents"])
            s = sum(1 for d in fiche["documents"] for t in d["textes"] if t["salaires"])
            sc = sum(1 for d in fiche["documents"] if d.get("scanne"))
            print(f"  {cle} : {n} texte(s), dont {s} sur les salaires"
                  + (f", {sc} PDF sans texte (image)" if sc else ""))
            deja[cle] = {"date": date, "statut": "ok", "fiche": os.path.relpath(os.path.join(sous, base + ".json"), args.out)}
            faits += 1

    vus["dernier_passage"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    json.dump(vus, open(chemin_vus, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"Terminé : {faits} fichier(s) aspiré(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
