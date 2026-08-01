#!/usr/bin/env python3
"""
pull_jorf.py — Module 2 (Journal Officiel, volet social) : recherche les
textes RH parus au JO sur la fenêtre glissante de 10 ans, puis récupère leur
contenu intégral.

HISTORIQUE DES APPROCHES (pour ne pas refaire les mêmes erreurs) :
  1) /search par mot-clé dans le TITRE -> plafonnait à ~40 résultats. Abandonné.
  2) Énumération conteneur-par-conteneur via lastNJo + jorfCont -> jorfCont
     IGNORAIT le textCid demandé et renvoyait toujours le même JO (erreur
     "mismatch" en boucle sur des milliers de JO). Abandonné le 01/08/2026.
  3) ACTUELLE : /search sur le fonds JORF, borné par DATE_PUBLICATION, découpé
     en tranches MENSUELLES (une recherche par mois sur 10 ans = ~121 tranches).
     Avantages : pas de mismatch possible (on ne demande jamais un JO précis),
     titres renvoyés directement, chaque mois reste sous le plafond de résultats.

Flux :
  a. rechercher_jorf_par_dates(debut, fin)  -> /search, une tranche mensuelle,
     paginée. Renvoie (id, titre) des textes.
  b. filtre MOTIF_RH sur le titre               -> ne garde que le RH.
  c. /consult/jorf {textCid}                    -> contenu intégral (fonctionne
     depuis le correctif CID, avec renouvellement de token sur 401).

Variables d'environnement : PISTE_CLIENT_ID / PISTE_CLIENT_SECRET / PISTE_ENV.

Fenêtre : 10 ans glissants, recalculée à chaque run. Ne supprime jamais
l'existant. --only-missing pour reprendre là où un run précédent s'est arrêté ;
garde-temps (--minutes-max) pour s'arrêter proprement avant le timeout GitHub
de 6h, en committant par lots (--lot).
"""
import os
import sys
import re
import json
import time
import argparse
import urllib.request
import urllib.error
import urllib.parse
from datetime import date, datetime, timedelta


def get_urls():
    env = os.environ.get("PISTE_ENV", "sandbox").lower()
    if env == "production":
        return ("https://oauth.piste.gouv.fr/api/oauth/token",
                "https://api.piste.gouv.fr/dila/legifrance/lf-engine-app")
    return ("https://sandbox-oauth.piste.gouv.fr/api/oauth/token",
            "https://sandbox-api.piste.gouv.fr/dila/legifrance/lf-engine-app")


def get_token(token_url, client_id, client_secret):
    data = urllib.parse.urlencode({
        "grant_type": "client_credentials", "client_id": client_id,
        "client_secret": client_secret, "scope": "openid",
    }).encode()
    req = urllib.request.Request(token_url, data=data, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())["access_token"]
    except urllib.error.HTTPError as e:
        print(f"ERREUR jeton ({e.code}): {e.read().decode(errors='replace')[:500]}", file=sys.stderr)
        sys.exit(1)


# Le token PISTE expire (~1h). Sur un run long (plusieurs heures pour couvrir
# 10 ans de JORF), prendre le token une seule fois au début fait échouer TOUS
# les appels en 401 dès l'expiration -- c'est exactement le "0 récupéré, 12
# échec (401)" observé le 01/08. Ce client garde les identifiants et redemande
# un token tout seul dès qu'un 401 tombe, puis rejoue l'appel une fois.
class PisteClient:
    def __init__(self, token_url, base_url, client_id, client_secret):
        self.token_url = token_url
        self.base_url = base_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.token = get_token(token_url, client_id, client_secret)

    def _renouveler(self):
        print("    [token] 401 reçu -> renouvellement du token PISTE...", file=sys.stderr)
        self.token = get_token(self.token_url, self.client_id, self.client_secret)

    def call(self, path, body, _reessai=True):
        req = urllib.request.Request(
            self.base_url + path, data=json.dumps(body).encode("utf-8"), method="POST",
            headers={"Authorization": f"Bearer {self.token}",
                     "Content-Type": "application/json", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code == 401 and _reessai:
                # Token probablement expiré : on en reprend un et on rejoue UNE fois.
                self._renouveler()
                return self.call(path, body, _reessai=False)
            return {"_error": e.code, "_detail": e.read().decode(errors="replace")}
        except Exception as e:
            return {"_error": "exception", "_detail": str(e)}


# Compat : les fonctions existantes prennent un "token" en 2e argument. On leur
# passe désormais le client, et call_api délègue. Ainsi le reste du script ne
# change pas de forme.
def call_api(client, token_ignore, path, body):
    return client.call(path, body)


def date_dix_ans_glissante():
    """Aujourd'hui moins 10 ans, recalculé à chaque run. Ne borne que
    l'énumération, ne supprime jamais l'existant."""
    aujourdhui = date.today()
    try:
        return aujourdhui.replace(year=aujourdhui.year - 10)
    except ValueError:
        return aujourdhui.replace(year=aujourdhui.year - 10, day=28)


# Motif RH appliqué au TITRE de chaque texte énuméré -- large exprès, un
# arrêté d'extension de CCN, une revalorisation SMIC, un décret cotisations,
# doivent tous passer. Insensible à la casse et aux accents (normalisés avant).
MOTIF_RH = re.compile(
    r"extension|avenant|convention collective|accord|salair|smic|"
    r"plafond.*s[ée]curit[ée] sociale|cotisation|activit[ée] partielle|"
    r"temps de travail|t[ée]l[ée]travail|forfait|[ée]galit[ée] professionnelle|"
    r"[ée]pargne salariale|participation|int[ée]ressement|pr[ée]voyance|"
    r"retraite compl[ée]mentaire|apprentissage|formation professionnelle",
    re.IGNORECASE)


def titre_est_rh(titre):
    return bool(MOTIF_RH.search(titre or ""))


def rechercher_jorf_par_dates(client, debut, fin, page=1, page_size=100):
    """Recherche /search sur le fonds JORF, bornée par dates de publication.

    C'EST LA MÉTHODE QUI REMPLACE l'énumération conteneur-par-conteneur
    (01/08) : jorfCont ignorait le textCid demandé et renvoyait toujours le
    même JO (erreur "mismatch" en boucle). /search par tranche de dates,
    lui, ne demande jamais un JO précis -- donc pas de mismatch possible --
    et renvoie directement les titres. On découpe la fenêtre de 10 ans en
    petites tranches (un mois) pour rester sous le plafond de résultats de
    /search qui plombait la 1re version.

    typeChamp=ALL : cherche dans tout le texte (pas juste le titre), pour ne
    rater aucun texte RH.
    """
    body = {
        "fond": "JORF",
        "recherche": {
            "champs": [{
                "typeChamp": "ALL",
                "operateur": "ET",
                "criteres": [{
                    "valeur": "travail",   # amorce large ; le vrai tri RH se
                                            # fait ensuite sur le titre via MOTIF_RH
                    "typeRecherche": "UN_DES_MOTS",
                    "operateur": "ET",
                }],
            }],
            "filtres": [{
                "facette": "DATE_PUBLICATION",
                "dates": {
                    "start": debut,   # "AAAA-MM-JJ"
                    "end": fin,
                },
            }],
            "sort": "PUBLICATION_DATE_DESC",
            "fromAdvancedRecherche": False,
            "pageNumber": page,
            "pageSize": page_size,
            "typePagination": "DEFAUT",
            "operateur": "ET",
        },
    }
    return client.call("/search", body)


def extraire_textes_recherche(resultat):
    """Renvoie [(id, titre), ...] depuis une réponse /search JORF.
    L'id du texte est un JORFTEXT ; on retire un éventuel suffixe _date."""
    out = []
    results = resultat.get("results") or resultat.get("resultats") or []
    for r in results:
        titre = r.get("titre") or r.get("title") or ""
        # L'id peut être au niveau du résultat ou dans 'titles'
        tid = None
        for t in (r.get("titles") or r.get("titres") or []):
            if t.get("id"):
                tid = t["id"]
                if not titre:
                    titre = t.get("titre") or t.get("title") or ""
                break
        if not tid:
            tid = r.get("id")
        if tid and str(tid).startswith("JORFTEXT"):
            out.append((str(tid).split("_")[0], titre))
    return out


def mois_glissants(depuis, jusqu_a):
    """Génère les bornes (debut, fin) mois par mois entre deux dates, en
    'AAAA-MM-JJ'. Découper en mois garde chaque recherche sous le plafond."""
    from datetime import date, timedelta
    cur = date(depuis.year, depuis.month, 1)
    fin_totale = jusqu_a
    tranches = []
    while cur <= fin_totale:
        # 1er du mois suivant
        if cur.month == 12:
            suivant = date(cur.year + 1, 1, 1)
        else:
            suivant = date(cur.year, cur.month + 1, 1)
        fin_tranche = min(suivant - timedelta(days=1), fin_totale)
        tranches.append((cur.isoformat(), fin_tranche.isoformat()))
        cur = suivant
    return tranches


def fetch_un_texte(base_url, token, text_id):
    """Étape 3 : contenu intégral. Endpoint déjà fonctionnel depuis le
    correctif CID du 31/07."""
    return call_api(base_url, token, "/consult/jorf", {"textCid": text_id})


import subprocess


def commit_partiel(dossier, n_fait, total):
    """Commit + push ce qui est déjà récupéré, PENDANT la boucle -- comme ça
    si le run plante ou dépasse le temps limite plus loin, ce qui est déjà là
    est sauvé sur le dépôt, pas perdu. Idée de Chauvel (31/07/2026), reprise
    du principe des tranches du Code du travail : mieux vaut plusieurs petits
    commits sûrs qu'un seul gros commit final qui peut échouer d'un coup.

    Tolérant à l'échec : si le commit/push échoue (ex. rien à committer, ou
    conflit réseau ponctuel), on continue la récupération -- le prochain
    checkpoint ou le commit final rattrapera. On ne fait JAMAIS échouer le run
    juste parce qu'un checkpoint intermédiaire n'est pas passé.
    """
    try:
        subprocess.run(["git", "add", dossier], check=False, capture_output=True)
        # Rien de nouveau à committer -> git diff --cached --quiet renvoie 0.
        rien = subprocess.run(["git", "diff", "--cached", "--quiet"], capture_output=True).returncode == 0
        if rien:
            return
        subprocess.run(["git", "commit", "-m",
                        f"JORF: lot intermédiaire ({n_fait}/{total} textes)"],
                       check=False, capture_output=True)
        r = subprocess.run(["git", "push"], capture_output=True, text=True)
        if r.returncode == 0:
            print(f"    [checkpoint] {n_fait}/{total} textes committés et poussés.")
            return
        # Un seul rattrapage doux, puis on laisse tomber ce checkpoint.
        subprocess.run(["git", "pull", "--rebase", "--autostash", "origin", "main"],
                       check=False, capture_output=True)
        r2 = subprocess.run(["git", "push"], capture_output=True, text=True)
        if r2.returncode == 0:
            print(f"    [checkpoint] {n_fait}/{total} textes poussés (après rattrapage).")
        else:
            print(f"    [checkpoint] push différé (sera rattrapé au prochain lot ou à la fin).",
                  file=sys.stderr)
    except Exception as e:
        print(f"    [checkpoint] échec non bloquant : {e}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="output/jorf")
    ap.add_argument("--depuis", default=None,
                     help="Date de début (JJJJ-MM-JJ). Défaut : 10 ans glissants.")
    ap.add_argument("--delay", type=float, default=0.6, help="Délai entre appels (s)")
    ap.add_argument("--only-missing", action="store_true",
                     help="Ne récupère le CONTENU que des textes RH pas encore acquis. "
                          "C'est CE mode qui permet de reprendre là où le run précédent "
                          "s'est arrêté : les textes déjà récupérés sont sautés, on avance "
                          "dans la pile à chaque run successif.")
    ap.add_argument("--max", type=int, default=0,
                     help="Plafond de CONTENUS récupérés ce run (0 = pas de plafond -- on "
                          "s'arrête sur le temps, pas sur un nombre). L'énumération est "
                          "toujours complète.")
    ap.add_argument("--lot", type=int, default=700,
                     help="Commit + push tous les N textes (défaut 700, selon la stratégie "
                          "retenue : plusieurs petits lots sûrs plutôt qu'un gros commit final).")
    ap.add_argument("--minutes-max", type=int, default=330,
                     help="Temps maximal de la phase de récupération, en minutes (défaut 330 "
                          "= 5h30). GitHub tue un job à 6h ; on s'arrête AVANT, proprement, "
                          "en committant ce qui est fait -- le run suivant (--only-missing) "
                          "reprend la suite. C'est la clé pour couvrir 10 ans sur plusieurs runs.")
    args = ap.parse_args()

    depuis = date.fromisoformat(args.depuis) if args.depuis else date_dix_ans_glissante()

    client_id = os.environ.get("PISTE_CLIENT_ID")
    client_secret = os.environ.get("PISTE_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("ERREUR: identifiants PISTE manquants.", file=sys.stderr)
        sys.exit(1)

    token_url, base_url = get_urls()
    print(f"Environnement: {'production' if 'sandbox' not in base_url else 'SANDBOX'}")
    client = PisteClient(token_url, base_url, client_id, client_secret)
    token = None  # le token vit désormais dans le client, renouvelé tout seul
    print(f"Token OK. Énumération du JO depuis {depuis.isoformat()} (fenêtre glissante 10 ans).")

    os.makedirs(args.out, exist_ok=True)
    summary_path = os.path.join(args.out, "_summary.json")

    existing = {}
    if os.path.exists(summary_path):
        try:
            for e in json.load(open(summary_path, encoding="utf-8")):
                if e.get("id"):
                    existing[e["id"]] = e
        except Exception:
            existing = {}
    preserved_ok = {k: v for k, v in existing.items() if v.get("status") == "ok"}

    # ── Recherche des textes RH par tranches de dates mensuelles ──
    # Plus d'énumération conteneur-par-conteneur (jorfCont buguait). On balaie
    # la fenêtre de 10 ans mois par mois via /search, en paginant chaque mois.
    tranches = mois_glissants(depuis, date.today())
    print(f"Recherche JORF sur {len(tranches)} tranches mensuelles "
          f"(de {tranches[0][0]} à {tranches[-1][1]})...")

    candidats_rh = {}  # id -> titre
    for idx, (deb, fin) in enumerate(tranches, 1):
        page = 1
        total_mois = 0
        while True:
            resultat = rechercher_jorf_par_dates(client, deb, fin, page=page, page_size=100)
            if "_error" in resultat:
                print(f"  [{idx}/{len(tranches)}] {deb[:7]} : échec "
                      f"({resultat['_error']}) {str(resultat.get('_detail',''))[:120]}", file=sys.stderr)
                break
            textes = extraire_textes_recherche(resultat)
            if not textes:
                break
            rh = [(tid, titre) for tid, titre in textes if titre_est_rh(titre)]
            for tid, titre in rh:
                candidats_rh[tid] = titre
            total_mois += len(rh)
            # Pagination : s'il y a moins que page_size, c'était la dernière page.
            if len(textes) < 100:
                break
            page += 1
            if page > 50:  # garde-fou anti-boucle
                break
            time.sleep(args.delay)
        if total_mois or idx % 12 == 0:
            print(f"  [{idx}/{len(tranches)}] {deb[:7]} : +{total_mois} RH "
                  f"(cumul {len(candidats_rh)})")
        time.sleep(args.delay)

    print(f"\n{len(candidats_rh)} texte(s) RH trouvé(s) au total sur la période.")

    # ── Étape 3 : récupération du contenu, par lots, sous garde-temps ──
    a_traiter = list(candidats_rh.keys())
    if args.only_missing:
        avant = len(a_traiter)
        a_traiter = [t for t in a_traiter if t not in preserved_ok]
        print(f"Mode --only-missing : {avant - len(a_traiter)} déjà acquis, {len(a_traiter)} restant à récupérer.")
    if args.max and len(a_traiter) > args.max:
        print(f"Plafond --max {args.max} : le reste au prochain run.")
        a_traiter = a_traiter[:args.max]

    import time as _time
    debut = _time.monotonic()
    limite_secondes = args.minutes_max * 60

    summary = list(preserved_ok.values())
    n_ok, n_echec = 0, 0
    arrete_par_temps = False

    print(f"Récupération de {len(a_traiter)} texte(s), par lots de {args.lot}, "
          f"limite {args.minutes_max} min (~{args.minutes_max/60:.1f}h) avant arrêt propre.")

    for i, tid in enumerate(a_traiter, 1):
        # Garde-temps : avant chaque texte, on regarde si on approche la limite.
        # Si oui, on s'arrête NET et on committe ce qui est fait -- surtout pas
        # se faire tuer par GitHub à 6h en plein milieu, ce qui perdrait le lot
        # en cours et laisserait le dépôt dans un état de rebase bancal.
        if _time.monotonic() - debut > limite_secondes:
            print(f"\n[garde-temps] {args.minutes_max} min atteintes -- arrêt propre à "
                  f"{i-1}/{len(a_traiter)}. Le prochain run (--only-missing) reprend la suite.")
            arrete_par_temps = True
            break

        titre = candidats_rh[tid]
        print(f"[{i}/{len(a_traiter)}] {titre[:55]}...", end=" ")
        result = fetch_un_texte(client, None, tid)
        if "_error" in result:
            print(f"ÉCHEC ({result['_error']})")
            summary.append({"id": tid, "titre": titre, "status": "erreur"})
            n_echec += 1
        else:
            with open(os.path.join(args.out, f"{tid}.json"), "w", encoding="utf-8") as f:
                json.dump({"titre": titre, "text": result}, f, ensure_ascii=False, indent=2)
            summary.append({"id": tid, "titre": titre, "status": "ok"})
            print("ok")
            n_ok += 1

        # Fin de lot : on sauve le summary à jour PUIS on commit+push le lot.
        # Ainsi, même si le run est tué juste après, ce lot est déjà sur le
        # dépôt -- on ne reperd jamais plus qu'un lot en cours.
        if i % args.lot == 0:
            json.dump(summary, open(summary_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
            commit_partiel(args.out, i, len(a_traiter))
        time.sleep(args.delay)

    # Sauvegarde + commit final de ce qui reste (dernier lot incomplet, ou arrêt
    # par le temps).
    json.dump(summary, open(summary_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    commit_partiel(args.out, n_ok, len(a_traiter))

    reste = len(a_traiter) - (n_ok + n_echec)
    print(f"\n{n_ok} récupéré(s), {n_echec} échec(s), {len(preserved_ok)} déjà acquis avant ce run.")
    if arrete_par_temps or reste > 0:
        print(f"Il reste ~{reste} texte(s) à récupérer -- relancer le run "
              f"(--only-missing) pour continuer là où on s'est arrêté.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
