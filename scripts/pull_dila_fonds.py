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

REPLI API (03/10/2026) : le 03/10, echanges.dila.gouv.fr a coupé toutes les
         connexions de GitHub (« Connection reset by peer »). Si l'open data
         ne répond pas, le même contenu est demandé à l'API Légifrance (PISTE,
         mêmes secrets que l'aspirateur) : fonds CIRC, CONSTIT et CETAT,
         textes des --jours derniers jours, même tri par sujets, mêmes
         fichiers de sortie. --source opendata|api|auto (défaut auto).

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
import urllib.error
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
# Décisions (Conseil d'État, cours administratives, Conseil constitutionnel) :
# « salarié » apparaît aussi dans un refus de titre de séjour. On exige une
# vraie attache au droit du travail / de la Sécu, et on écarte le droit des
# étrangers et l'urbanisme (test du 03/10/2026 : 27 décisions gardées, presque
# toutes hors sujet).
FORT_DECISION = re.compile(
    r"code du travail|code de la securite sociale|convention collective|accord collectif|arrete d.extension"
    r"|heures? supplementaires|duree du travail|cotisations? (?:sociales|patronales|salariales)|urssaf"
    r"|licenciement|salarie protege|inspect(?:eur|ion) du travail|reduction generale|smic"
    r"|assurance chomage|france travail|unedic|prestations? familiales|retraite complementaire", re.I)
HORS_SUJET_DECISION = re.compile(
    r"entree et (?:du )?sejour des etrangers|titre de sejour|obligation de quitter le territoire|\bceseda\b"
    r"|permis de construire|code de l.urbanisme", re.I)
_DATE_TITRE = re.compile(r"(\d{2})/(\d{2})/(\d{4})")


def pertinent(fonds, titre, texte):
    """Sujets touchés, ou [] si le texte n'est pas pour l'écosystème."""
    n = normaliser(titre + " " + texte[:60000])
    sujets = sorted({m.group(0) for m in SUJETS.finditer(n)})
    if not sujets or fonds == "CIRCULAIRES":
        return sujets
    if HORS_SUJET_DECISION.search(n) and not re.search(r"code du travail|code de la securite sociale", n):
        return []
    forts = {m.group(0) for m in FORT_DECISION.finditer(n)}
    return sujets if forts else []


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
    sujets = pertinent(fonds, titre, texte)
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


# ───────────────────────── Repli : API Légifrance (PISTE) ─────────────────────────
FONDS_API = {"CIRCULAIRES": "CIRC", "CONSTIT": "CONSTIT", "JADE": "CETAT"}
# Amorce large (n'importe lequel de ces mots) ; le vrai tri se fait ensuite
# avec SUJETS, comme pour l'open data.
AMORCE_API = ("travail salarié salariés employeur employeurs cotisations sociale "
              "chômage retraite prestations familiales licenciement convention collective "
              "durée heures congés smic apprentissage")
# Le nom exact de la facette de date et du tri n'est pas le même d'un fonds à
# l'autre : on essaie dans l'ordre, la première combinaison acceptée gagne.
VARIANTES_API = {
    "CIRC": [("DATE_SIGNATURE", "SIGNATURE_DATE_DESC"), ("DATE_PUBLICATION", "PUBLICATION_DATE_DESC"),
             ("DATE_SIGNATURE", "PERTINENCE"), (None, "PERTINENCE")],
    "CONSTIT": [("DATE_DECISION", "DATE_DESC"), ("DATE_DECISION", "DATE_DECISION_DESC"),
                ("DATE_DECISION", "PERTINENCE"), (None, "PERTINENCE")],
    "CETAT": [("DATE_DECISION", "DATE_DESC"), ("DATE_DECISION", "DATE_DECISION_DESC"),
              ("DATE_DECISION", "PERTINENCE"), (None, "PERTINENCE")],
}


class ClientPiste:
    def __init__(self):
        cid, sec = os.environ.get("PISTE_CLIENT_ID"), os.environ.get("PISTE_CLIENT_SECRET")
        if not cid or not sec:
            raise RuntimeError("PISTE_CLIENT_ID / PISTE_CLIENT_SECRET absents (secrets du dépôt)")
        prod = os.environ.get("PISTE_ENV", "production").lower() == "production"
        self.token_url = ("https://oauth.piste.gouv.fr/api/oauth/token" if prod
                          else "https://sandbox-oauth.piste.gouv.fr/api/oauth/token")
        self.base = ("https://api.piste.gouv.fr/dila/legifrance/lf-engine-app" if prod
                     else "https://sandbox-api.piste.gouv.fr/dila/legifrance/lf-engine-app")
        data = urllib.parse.urlencode({"grant_type": "client_credentials", "client_id": cid,
                                       "client_secret": sec, "scope": "openid"}).encode()
        req = urllib.request.Request(self.token_url, data=data, method="POST",
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=30) as r:
            self.jeton = json.loads(r.read())["access_token"]

    def appel(self, chemin, corps):
        req = urllib.request.Request(self.base + chemin, data=json.dumps(corps).encode(), method="POST",
                                     headers={"Authorization": "Bearer " + self.jeton,
                                              "Content-Type": "application/json", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            return {"_erreur": e.code, "_detail": e.read().decode("utf-8", "replace")[:300]}
        except Exception as e:                       # noqa: BLE001
            return {"_erreur": "exception", "_detail": str(e)[:300]}


def _corps_recherche(fond, facette, tri, debut, fin, page):
    r = {"champs": [{"typeChamp": "ALL", "operateur": "ET",
                     "criteres": [{"valeur": AMORCE_API, "typeRecherche": "UN_DES_MOTS", "operateur": "ET"}]}],
         "sort": tri, "fromAdvancedRecherche": False, "pageNumber": page, "pageSize": 50,
         "typePagination": "DEFAUT", "operateur": "ET"}
    if facette:
        r["filtres"] = [{"facette": facette, "dates": {"start": debut, "end": fin}}]
    return {"fond": fond, "recherche": r}


def _resultats(rep):
    out = []
    for r in rep.get("results") or rep.get("resultats") or []:
        titre = r.get("titre") or r.get("title") or ""
        ident = r.get("id") or ""
        for t in r.get("titles") or r.get("titres") or []:
            ident = ident or t.get("id") or ""
            titre = titre or t.get("titre") or t.get("title") or ""
            if t.get("id"):
                ident = t["id"]
                break
        date = ""
        for k in ("dateDecision", "dateSignature", "datePublication", "date", "dateTexte"):
            v = r.get(k)
            if isinstance(v, str) and re.match(r"\d{4}-\d{2}-\d{2}", v):
                date = v[:10]
                break
        if not date:
            m = _DATE_TITRE.search(plat(titre))
            if m:
                date = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
        num = r.get("numero") or r.get("num") or r.get("numeroAffaire") or ""
        if isinstance(num, list):
            num = ", ".join(map(str, num))
        out.append({"id": str(ident).split("_")[0], "titre": plat(titre), "date": date,
                    "numero": str(num)[:80], "brut": r})
    return [o for o in out if o["id"]]


def _texte_api(client, fond, ident):
    """Texte intégral si l'API le donne ; sinon chaîne vide (on garde le titre)."""
    essais = [("/consult/circulaire", {"id": ident})] if fond == "CIRC" else [("/consult/juri", {"textId": ident})]
    for chemin, corps in essais:
        rep = client.appel(chemin, corps)
        if "_erreur" in rep:
            continue
        t = rep.get("text") or rep
        brut = json.dumps(t, ensure_ascii=False)
        morceaux = [t.get(k) for k in ("texte", "texteHtml", "content", "contenu", "texteIntegral") if isinstance(t, dict) and t.get(k)]
        txt = plat(" ".join(map(str, morceaux))) if morceaux else plat(brut)
        meta = {k: t.get(k) for k in ("solution", "juridiction", "formation", "nature", "ministere", "autorite")
                if isinstance(t, dict) and t.get(k)}
        return txt, meta
    return "", {}


def traiter_fonds_api(fonds, out, jours, maxi, diag, client):
    from datetime import date, timedelta
    fond = FONDS_API[fonds]
    dossier = os.path.join(out, fonds.lower())
    os.makedirs(dossier, exist_ok=True)
    chemin_vus = os.path.join(dossier, "_vus.json")
    try:
        vus = json.load(open(chemin_vus, encoding="utf-8"))
    except Exception:
        vus = {}
    deja = set(vus.get("api_ids") or [])
    fin = date.today()
    debut = fin - timedelta(days=jours)
    variante = vus.get("api_variante")
    candidats = []
    essais = ([tuple(variante)] if variante else []) + [v for v in VARIANTES_API[fond] if list(v) != variante]
    for facette, tri in essais:
        rep = client.appel("/search", _corps_recherche(fond, facette, tri, debut.isoformat(), fin.isoformat(), 1))
        if "_erreur" in rep:
            if diag:
                print(f"  API {fond} facette={facette} tri={tri} : refus {rep['_erreur']} {rep.get('_detail','')[:160]}")
            continue
        res = _resultats(rep)
        if diag:
            print(f"  API {fond} facette={facette} tri={tri} : {rep.get('totalResultNumber', '?')} résultat(s), {len(res)} lu(s)")
            for r in res[:3]:
                print(f"     {r['date']} {r['id']} {r['titre'][:90]}")
                if not r['date']:
                    print("     (clés du résultat : " + ", ".join(sorted(r['brut'].keys()))[:200] + ")")
        vus["api_variante"] = [facette, tri]
        candidats = res
        page = 2
        while len(rep.get("results") or []) == 50 and page <= 4:
            rep = client.appel("/search", _corps_recherche(fond, facette, tri, debut.isoformat(), fin.isoformat(), page))
            if "_erreur" in rep:
                break
            candidats += _resultats(rep)
            page += 1
        break
    else:
        raise RuntimeError(f"API Légifrance : aucune variante de recherche acceptée pour {fond}")
    if facette is None:   # pas de filtre de date accepté : on filtre nous-mêmes
        candidats = [c for c in candidats if not c["date"] or c["date"] >= debut.isoformat()]
    gardes, titres_vus = 0, set()
    for c in [c for c in candidats if c["id"] not in deja][:maxi * 20]:
        deja.add(c["id"])
        if c["titre"] in titres_vus:
            continue                                  # même décision publiée deux fois
        titres_vus.add(c["titre"])
        texte, meta = _texte_api(client, fond, c["id"])
        sujets = pertinent(fonds, c["titre"], texte)
        if not sujets:
            continue
        f = {"fonds": fonds, "id": c["id"], "titre": c["titre"][:400], "date": c["date"],
             "numero": c["numero"], "juridiction": str(meta.get("juridiction") or meta.get("formation")
                                                        or meta.get("ministere") or meta.get("autorite") or "")[:200],
             "nature": str(meta.get("nature") or "")[:80], "solution": str(meta.get("solution") or "")[:300],
             "articles": sorted({m.group(1) + m.group(2) for m in _REF.finditer(texte)})[:60],
             "sujets": sujets[:15], "extrait": (texte or c["titre"])[:3000], "source": "api-legifrance"}
        sortie = os.path.join(dossier, re.sub(r"[^A-Za-z0-9._-]+", "_", f["id"])[:120] + ".json")
        json.dump(f, open(sortie, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        gardes += 1
        if diag:
            print(f"   GARDÉ {f['date']} | {f['titre'][:100]} | art. {','.join(f['articles'][:5])}")
        time.sleep(0.3)
    vus["api_ids"] = sorted(deja)[-20000:]
    vus["dernier_passage"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    vus["dernier_mode"] = "api"
    json.dump(vus, open(chemin_vus, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{fonds} (API {fond}) : {len(candidats)} texte(s) des {jours} derniers jours, {gardes} gardé(s).")
    return gardes


class OpenDataInjoignable(Exception):
    pass


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
    try:
        ouvrir(racine, delai=30, essais=1)
    except Exception as e:                           # noqa: BLE001
        raise OpenDataInjoignable(str(e))
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
            if diag:
                print(f"   GARDÉ {f['date']} | {f['titre'][:100]} | art. {','.join(f['articles'][:5])}")
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
    ap.add_argument("--source", choices=["auto", "opendata", "api"], default="auto")
    ap.add_argument("--jours", type=int, default=21, help="fenêtre de l'API (jours)")
    args = ap.parse_args()
    total, echecs, client = 0, 0, None
    for f in [x.strip().upper() for x in args.fonds.split(",") if x.strip()]:
        try:
            if args.source == "api":
                raise OpenDataInjoignable("source API demandée")
            total += traiter_fonds(f, args.out, args.max, args.premier_max, args.diagnostic)
            continue
        except OpenDataInjoignable as e:
            if args.source == "opendata":
                print(f"{f} : open data injoignable ({e})")
                echecs += 1
                continue
            print(f"{f} : open data injoignable ({str(e)[:120]}) → API Légifrance.")
        except Exception as e:                       # noqa: BLE001
            print(f"{f} : erreur {e}")
            echecs += 1
            continue
        try:
            client = client or ClientPiste()
            total += traiter_fonds_api(f, args.out, args.jours, args.max, args.diagnostic, client)
        except Exception as e:                       # noqa: BLE001
            print(f"{f} : API Légifrance en échec : {e}")
            echecs += 1
    print(f"Terminé : {total} texte(s) gardé(s), {echecs} fonds en échec.")
    # Un fonds en échec = étape en échec (le tableau de bord l'affiche).
    return 1 if echecs else 0


if __name__ == "__main__":
    sys.exit(main())
