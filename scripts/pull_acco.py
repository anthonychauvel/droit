#!/usr/bin/env python3
"""
pull_acco.py — Module 3 (Accords d'entreprise, benchmarking RH) : recherche
les accords du fonds ACCO sur la fenêtre glissante de 10 ans, puis récupère
leur contenu intégral.

MÊME MÉTHODE que pull_jorf.py (celle qui marche enfin) : /search par tranches
de dates mensuelles. L'ancienne version cherchait par thème avec typeChamp=ALL
et renvoyait une erreur 500 sur le fonds ACCO. En calquant exactement la
structure de recherche du JORF (qui fonctionne), on évite ce 500.

ANCIENNE VERSION (abandonnée) : cherchait par thème avec typeChamp=ALL et
renvoyait une erreur 500 sur le fonds ACCO. La version actuelle calque la
structure de recherche du JORF (qui marche) : /search par DATE_PUBLICATION,
découpé en tranches MENSUELLES (~121 sur 10 ans), chaque mois sous le plafond
de résultats. Le tri par thème RH se fait ensuite sur le titre (MOTIF_RH).

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


# ── Reglages de pagination / veille (ACCO) ───────────────────────────────────
# Fenetre de resultats Legifrance : ~10 000 par recherche (page 200 x 50). La
# page 201 renvoie 503 -- c'est le PLAFOND de la fenetre, pas une panne : on
# s'arrete avant, proprement.
MAX_PAGE = 200
# En veille (--only-missing), tri par date DESC : les nouveautes sont EN HAUT.
# Des qu'on a rattrape le deja-connu, tout le reste (plus ancien) est deja la.
# On scanne toujours un plancher de pages (accords parfois antidates de
# quelques jours), PUIS on stoppe le theme apres STOP_APRES_RIEN resultats
# consecutifs sans une seule nouveaute. Fait passer un run de veille de
# ~4 000 appels de recherche (20 themes x 200 pages) a quelques dizaines.
MIN_PAGES_VEILLE = 4
STOP_APRES_RIEN = 150          # 3 pages de 50 sans rien de neuf -> theme a jour
RETRY_5XX = 3                  # petites tentatives sur 5xx transitoire (backoff plafonne)


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
        import time as _t
        self._token_ts = _t.monotonic()   # heure d'obtention du token

    def _renouveler(self, prevention=False):
        import time as _t
        raison = "préventif (~50 min)" if prevention else "401 reçu"
        print(f"    [token] renouvellement {raison}...", file=sys.stderr)
        self.token = get_token(self.token_url, self.client_id, self.client_secret)
        self._token_ts = _t.monotonic()

    def call(self, path, body, _reessai=True, _n401=0):
        import time as _t
        # Renouvellement PRÉVENTIF : si le token a plus de 50 min, on le
        # renouvelle AVANT de l'utiliser, pour éviter le cycle coûteux
        # échec 401 -> renouvellement -> rejeu (qui doublait le temps de
        # certains appels et ralentissait tout le run).
        if _t.monotonic() - self._token_ts > 3000:  # 50 min
            self._renouveler(prevention=True)
        req = urllib.request.Request(
            self.base_url + path, data=json.dumps(body).encode("utf-8"), method="POST",
            headers={"Authorization": f"Bearer {self.token}",
                     "Content-Type": "application/json", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            token_frais = (_t.monotonic() - self._token_ts) < 60
            # 429, ou 401 sur un token FRAIS (< 60 s) = rate-limiting PISTE, PAS une
            # expiration. Renégocier un token ne sert à rien (le nouveau est limité
            # pareil) et coûte ~30 s : on TEMPORISE (backoff) puis on rejoue.
            if (e.code == 429 or (e.code == 401 and token_frais)) and _n401 < 4:
                pause = min(30, 3 * (2 ** _n401))     # 3, 6, 12, 24 s
                print(f"    [rate-limit] {e.code} sur token frais -> pause {pause}s "
                      f"(tentative {_n401 + 1})", file=sys.stderr)
                _t.sleep(pause)
                return self.call(path, body, _reessai, _n401 + 1)
            # 401 sur un token VIEUX (> 60 s) = vraie expiration -> un seul renew.
            if e.code == 401 and _reessai and not token_frais:
                self._renouveler()
                return self.call(path, body, _reessai=False, _n401=_n401)
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
# Thèmes RH ciblés du cahier des charges ACCO (Module 3) : on ne garde que
# les accords dont le titre touche ces sujets de benchmarking. Contrairement
# au JORF (qui contient de tout et où on filtre large), ici TOUT est déjà un
# accord d'entreprise -- ce motif sert donc à cibler les thèmes utiles, pas à
# écarter du non-RH.
MOTIF_RH = re.compile(
    r"t[ée]l[ée]travail|forfait.?jours?|forfait.?annuel|"
    r"prime|salaire|r[ée]mun[ée]ration|augmentation|pouvoir d.achat|"
    r"n[ée]gociation annuelle|\bnao\b|"
    r"partage de la valeur|\bppv\b|"
    r"int[ée]ressement|participation|[ée]pargne salariale|\bpee\b|\bperco\b|plan d.[ée]pargne|"
    r"compte [ée]pargne.?temps|\bcet\b|\bcetu\b|"
    r"[ée]galit[ée] (professionnelle|femmes?.hommes?|h.?/?.?f)|"
    r"qualit[ée] de vie|\bqvt\b|qvct|conditions de travail|"
    r"droit [àa] la d[ée]connexion|d[ée]connexion|"
    r"temps de travail|am[ée]nagement du temps|dur[ée]e du travail|"
    r"astreinte|cong[ée]s|classification|"
    r"pr[ée]voyance|compl[ée]mentaire sant[ée]|mutuelle|retraite",
    re.IGNORECASE)


def titre_est_rh(titre):
    return bool(MOTIF_RH.search(titre or ""))


# Thèmes de recherche envoyés à l'API ACCO (un /search par thème, sans date).
# Liste ÉLARGIE fondée sur les VRAIS thèmes de négociation collective 2024
# (sources DARES/INSEE), classés par fréquence réelle de négociation :
#   1. salaires/primes (10,3% des entreprises) -- le n°1
#   2. épargne salariale (6,8%, "la moitié des accords conclus")
#   3. temps de travail (5,4%)  4. conditions de travail (4,2%)
# On couvre ces gros volumes + les sujets structurels (télétravail, égalité,
# PPV, CETU...). Les premiers thèmes de la liste sont les plus négociés : comme
# on récupère par ordre de thème, ils remplissent le corpus en priorité.
THEMES_ACCO = [
    # --- Les plus négociés (gros volumes) ---
    "salaires augmentation",
    "prime pouvoir d'achat",
    "négociation annuelle obligatoire",
    "intéressement",
    "participation aux bénéfices",
    "épargne salariale plan",
    "prime de partage de la valeur",
    "temps de travail aménagement",
    "conditions de travail",
    # --- Sujets structurels forts ---
    "télétravail",
    "forfait jours",
    "compte épargne temps",
    "égalité professionnelle femmes hommes",
    "qualité de vie au travail",
    "droit à la déconnexion",
    "prévoyance complémentaire santé",
    "retraite supplémentaire",
    "classification rémunération",
    "astreinte",
    "congés",
]


def rechercher_acco_par_theme(client, theme, page=1, page_size=50):
    """Recherche /search sur le fonds ACCO, par THÈME, SANS filtre de date.

    DÉCOUVERTE du diagnostic (01/08) : le filtre DATE_PUBLICATION fait PLANTER
    le fonds ACCO (erreur 500 côté serveur Légifrance). Sans ce filtre, la
    recherche marche parfaitement (54 491 accords trouvés). On cherche donc par
    thème RH directement, sans borne de date. Si un filtrage par date devient
    nécessaire, il se fera côté nous, après récupération.

    Autre découverte : /consult/acco plante AUSSI en 500. Mais le résultat de
    recherche contient déjà un champ 'text' et des 'extracts' -- on s'en
    servira comme contenu, sans appeler /consult.
    """
    body = {
        "fond": "ACCO",
        "recherche": {
            "champs": [{
                "typeChamp": "ALL",
                "operateur": "ET",
                "criteres": [{
                    "valeur": theme,
                    "typeRecherche": "UN_DES_MOTS",
                    "operateur": "ET",
                }],
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


def extraire_accords_recherche(resultat):
    """Renvoie [(id, titre, texte, extraits), ...] depuis une réponse /search
    ACCO. On récupère le texte DIRECTEMENT du résultat (le /consult plante), en
    nettoyant les balises <mark> de surlignage."""
    def sans_marques(s):
        if not s:
            return ""
        return s.replace("<mark>", "").replace("</mark>", "")

    out = []
    results = resultat.get("results") or resultat.get("resultats") or []
    for r in results:
        titre = ""
        tid = None
        for t in (r.get("titles") or r.get("titres") or []):
            if t.get("id"):
                tid = t["id"]
                titre = t.get("title") or t.get("titre") or ""
                break
        if not tid:
            tid = r.get("id")
            titre = r.get("titre") or r.get("title") or ""
        if not (tid and str(tid).startswith("ACCOTEXT")):
            continue
        texte = sans_marques(r.get("text") or "")
        # Les extraits : liste de blocs, chacun avec 'values' (liste de chaînes).
        extraits = []
        for ex in (r.get("extracts") or []):
            if isinstance(ex, dict):
                vals = ex.get("values") or ex.get("value") or []
                if isinstance(vals, list):
                    extraits.extend(sans_marques(str(v)) for v in vals)
                elif vals:
                    extraits.append(sans_marques(str(vals)))
        out.append((str(tid).split("_")[0], sans_marques(titre), texte, extraits))
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


def fetch_texte_complet_acco(client, text_id):
    """Récupère le texte INTÉGRAL d'un accord.

    DÉCOUVERTE 01/08 (diagnostic) : /consult/acco plante en 500 avec le
    paramètre {"textCid": ...}, MAIS fonctionne avec {"id": ...} et renvoie
    le texte complet dans un champ 'acco'. C'est LA solution au 500.
    """
    return client.call("/consult/acco", {"id": text_id})


def extraire_texte_complet(reponse):
    """Extrait tout le texte d'une réponse /consult/acco {"id":...}.

    La réponse a la forme {executionTime, dereferenced, acco:{...}}. Le champ
    'acco' contient le texte, mais sa structure interne n'est pas certaine
    (articles ? sections ? contenu direct ?). On récupère donc TOUT le texte
    trouvé dans 'acco', de façon défensive, quelle que soit la forme.
    """
    acco = reponse.get("acco") or {}
    morceaux = []

    def sans_html(s):
        import re as _re
        return _re.sub(r"<[^>]+>", "", str(s)).replace("&nbsp;", " ").strip()

    def collecter(node, prof=0):
        if prof > 8:
            return
        if isinstance(node, dict):
            # Champs de contenu connus
            for cle in ("content", "contenu", "texte", "text", "corps"):
                v = node.get(cle)
                if isinstance(v, str) and len(v.strip()) > 10:
                    morceaux.append(sans_html(v))
            # Descendre dans les structures
            for cle in ("articles", "sections", "liens", "children", "elements", "items"):
                if cle in node:
                    collecter(node[cle], prof + 1)
            # Si rien trouvé aux clés connues, parcourir tout
            if not any(k in node for k in ("content", "contenu", "texte", "text",
                                            "articles", "sections")):
                for v in node.values():
                    collecter(v, prof + 1)
        elif isinstance(node, list):
            for v in node:
                collecter(v, prof + 1)

    collecter(acco)
    # Dédoublonner en gardant l'ordre
    vus = set()
    uniques = []
    for m in morceaux:
        if m and m not in vus:
            vus.add(m)
            uniques.append(m)
    return "\n\n".join(uniques)


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
            print(f"    [checkpoint] rien de nouveau à committer à {n_fait}.", file=sys.stderr)
            return
        rc = subprocess.run(["git", "commit", "-m",
                        f"ACCO: lot intermédiaire ({n_fait}/{total} textes)"],
                       capture_output=True, text=True)
        if rc.returncode != 0:
            # Ne PAS avaler : afficher pourquoi (souvent identité git non configurée).
            print(f"    [checkpoint] ÉCHEC git commit à {n_fait} : "
                  f"{(rc.stderr or rc.stdout)[:200]}", file=sys.stderr)
            return
        r = subprocess.run(["git", "push"], capture_output=True, text=True)
        if r.returncode == 0:
            print(f"    [checkpoint] {n_fait}/{total} accords committés et poussés.")
            return
        # Un seul rattrapage doux, puis on laisse tomber ce checkpoint.
        subprocess.run(["git", "pull", "--rebase", "--autostash", "origin", "main"],
                       check=False, capture_output=True)
        r2 = subprocess.run(["git", "push"], capture_output=True, text=True)
        if r2.returncode == 0:
            print(f"    [checkpoint] {n_fait}/{total} textes poussés (après rattrapage).")
        else:
            print(f"    [checkpoint] ÉCHEC push à {n_fait} : "
                  f"{(r2.stderr or r.stderr)[:200]}", file=sys.stderr)
    except Exception as e:
        print(f"    [checkpoint] exception non bloquante : {e}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="output/acco")
    ap.add_argument("--depuis", default=None,
                     help="Date de début (JJJJ-MM-JJ). Défaut : 10 ans glissants.")
    ap.add_argument("--delay", type=float, default=0.3, help="Délai entre appels (s). "
                    "0.3 est un bon compromis vitesse/prudence ; monter si l'API bloque.")
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
    ap.add_argument("--deadline-epoch", type=str, default="",
                     help="Échéance ABSOLUE partagée (timestamp Unix, secondes), fixée une "
                          "fois par le workflow pour TOUTE la phase de récupération. Empêche "
                          "JORF et ACCO (même job, plafond GitHub 355 min) de s'additionner "
                          "au-delà du plafond : on s'arrête au plus tôt entre --minutes-max "
                          "et cette échéance. Vide/absent = ignoré.")
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

    # ── Recherche par thème RH, SANS filtre de date, avec sauvegarde DIRECTE ──
    # Le diagnostic du 01/08 a montré : (1) le filtre de date fait planter ACCO
    # en 500, (2) /consult/acco plante AUSSI en 500. Mais la recherche sans date
    # marche et renvoie déjà le texte de chaque accord (champ 'text' + extraits).
    # On récupère donc tout depuis la recherche, sans jamais appeler /consult.
    import time as _time
    debut = _time.monotonic()
    limite_secondes = args.minutes_max * 60
    # Budget PARTAGÉ JORF+ACCO : si le workflow passe une échéance absolue
    # commune (--deadline-epoch), on s'arrête au plus tôt entre nos --minutes-max
    # et cette échéance. C'est ce qui empêche 330 (JORF) + 330 (ACCO) de dépasser
    # le plafond du job (cause de l'annulation à 355 min).
    deadline_epoch = None
    if (args.deadline_epoch or "").strip():
        try:
            deadline_epoch = float(args.deadline_epoch.strip())
        except ValueError:
            print(f"[budget partagé] --deadline-epoch illisible ({args.deadline_epoch!r}), ignoré.",
                  file=sys.stderr)
    if deadline_epoch is not None:
        reste = deadline_epoch - time.time()
        limite_secondes = max(0, min(limite_secondes, int(reste)))
        print(f"[budget partagé] échéance commune dans ~{int(reste // 60)} min "
              f"-> limite ACCO effective ~{limite_secondes // 60} min.", file=sys.stderr)

    summary = list(preserved_ok.values())
    n_ok = 0
    deja = set(preserved_ok.keys())
    arrete_par_temps = False
    depuis_iso = depuis.isoformat()
    _trace_faite = [False]      # pour n'afficher la structure qu'une fois
    _echecs_consult = [0]       # compteur d'échecs de consult (repli sur extrait)

    print(f"Recherche ACCO sur {len(THEMES_ACCO)} thèmes, récupération du TEXTE "
          f"COMPLET via consult (id), lots de {args.lot}, limite {args.minutes_max} min.")

    for t_idx, theme in enumerate(THEMES_ACCO, 1):
        if arrete_par_temps:
            break
        page = 1
        total_theme = 0
        rien_de_neuf = 0          # résultats consécutifs sans nouveauté (arrêt veille)
        while True:
            if _time.monotonic() - debut > limite_secondes:
                print(f"\n[garde-temps] limite de temps atteinte -- arrêt propre. "
                      f"Le prochain run (--only-missing) reprend la suite.")
                arrete_par_temps = True
                break
            if page > MAX_PAGE:
                print(f"  [{t_idx}/{len(THEMES_ACCO)}] '{theme}' : plafond de pagination "
                      f"(~{MAX_PAGE * 50} résultats) atteint, fin de la fenêtre accessible.")
                break

            # Recherche d'une page, avec petites tentatives sur 5xx TRANSITOIRE
            # (backoff plafonné : jamais de longue attente -> ne peut pas faire
            # déborder le run). Le 401 est déjà géré dans le client. Un 503 au
            # plafond de fenêtre est NORMAL -> on ne s'acharne pas.
            resultat = {"_error": "init"}
            for essai in range(1, RETRY_5XX + 1):
                resultat = rechercher_acco_par_theme(client, theme, page=page, page_size=50)
                err = resultat.get("_error") if isinstance(resultat, dict) else None
                if err is None:
                    break
                if err == 503 and page >= MAX_PAGE:
                    break
                transitoire = (err == "exception") or (isinstance(err, int) and 500 <= err < 600)
                if not transitoire or essai == RETRY_5XX:
                    break
                attente = min(2 ** essai, 8)
                print(f"    [retry] '{theme}' p{page} : {err}, nouvelle tentative "
                      f"dans {attente}s ({essai}/{RETRY_5XX})", file=sys.stderr)
                time.sleep(attente)

            if isinstance(resultat, dict) and "_error" in resultat:
                niveau = "fin de fenêtre" if resultat.get("_error") == 503 else "arrêt du thème"
                print(f"  [{t_idx}/{len(THEMES_ACCO)}] '{theme}' p{page} : {niveau} "
                      f"({resultat['_error']}) {str(resultat.get('_detail',''))[:80]}", file=sys.stderr)
                break

            accords = extraire_accords_recherche(resultat)
            if not accords:
                break
            for tid, titre, texte_court, extraits in accords:
                # Garde-temps FIN : vérifié à CHAQUE accord (et pas seulement en
                # tête de page de 50). Sinon, quand une page devient lente (rate-
                # limit -> backoffs), elle déborde l'échéance ET le timeout du job
                # avant la prochaine vérif -> annulation SIGTERM (exit 143).
                if _time.monotonic() - debut > limite_secondes:
                    print("\n[garde-temps] limite atteinte en cours de page -- arrêt propre. "
                          "Le prochain run (--only-missing) reprend la suite.")
                    arrete_par_temps = True
                    break
                # Filtre RH sur le titre + only-missing. Un item non-RH ou déjà
                # acquis = "rien de neuf" : il alimente le compteur d'arrêt veille.
                if not titre_est_rh(titre):
                    rien_de_neuf += 1
                    continue
                if tid in deja:
                    rien_de_neuf += 1
                    continue

                # Nouveauté RH -> TEXTE COMPLET via /consult/acco {"id": ...}
                # ("textCid" plante en 500). Repli sur l'extrait si échec.
                rien_de_neuf = 0
                texte_complet = ""
                rep = fetch_texte_complet_acco(client, tid)
                if "_error" not in rep:
                    texte_complet = extraire_texte_complet(rep)
                    # Trace : au tout premier accord récupéré, montrer la
                    # structure pour confirmer qu'on extrait bien le texte.
                    if not _trace_faite[0]:
                        acco_obj = rep.get("acco") or {}
                        print(f"    [trace] 1er accord {tid} : clés de 'acco' = "
                              f"{list(acco_obj.keys())[:12]}", file=sys.stderr)
                        print(f"    [trace] texte complet extrait : {len(texte_complet)} caractères "
                              f"(vs extrait recherche : {len(texte_court)})", file=sys.stderr)
                        _trace_faite[0] = True
                else:
                    _echecs_consult[0] += 1
                # Si le consult n'a rien donné, on garde au moins l'extrait.
                texte_final = texte_complet if texte_complet else texte_court

                contenu = {
                    "titre": titre,
                    "text": {
                        "titre": titre,
                        "articles": [{"content": texte_final}] if texte_final else [],
                        "extraits": extraits,
                        "source": "consult ACCO (id)" if texte_complet else "extrait recherche",
                    },
                }
                with open(os.path.join(args.out, f"{tid}.json"), "w", encoding="utf-8") as f:
                    json.dump(contenu, f, ensure_ascii=False, indent=2)
                summary.append({"id": tid, "titre": titre, "status": "ok"})
                deja.add(tid)
                n_ok += 1
                total_theme += 1
                if args.max and n_ok >= args.max:
                    break
                # Commit par lots.
                if n_ok % args.lot == 0:
                    json.dump(summary, open(summary_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
                    commit_partiel(args.out, n_ok, "?")
                time.sleep(args.delay)  # délai entre consult pour ménager l'API
            if arrete_par_temps:   # garde-temps déclenché en cours de page
                break
            if args.max and n_ok >= args.max:
                print(f"Plafond --max {args.max} atteint.")
                arrete_par_temps = True
                break

            # ── Arrêt anticipé VEILLE ──
            # En only-missing, dès qu'on enchaîne STOP_APRES_RIEN résultats sans
            # une seule nouveauté (après un plancher de pages), le thème est à
            # jour : le tri DESC garantit que tout le reste, plus ancien, est déjà
            # acquis. La rotation sur 5 semaines repasse de toute façon le fonds
            # en entier, donc un éventuel accord antidaté profond est rattrapé là.
            if (args.only_missing and page >= MIN_PAGES_VEILLE
                    and rien_de_neuf >= STOP_APRES_RIEN):
                print(f"  [{t_idx}/{len(THEMES_ACCO)}] '{theme}' : à jour "
                      f"({rien_de_neuf} résultats consécutifs déjà connus) -> arrêt du thème.")
                break

            if len(accords) < 50:
                break
            page += 1
            time.sleep(args.delay)
        print(f"  [{t_idx}/{len(THEMES_ACCO)}] '{theme}' : +{total_theme} accords (cumul {n_ok})")

    json.dump(summary, open(summary_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    commit_partiel(args.out, n_ok, "final")

    print(f"\n{n_ok} accord(s) récupéré(s) ce run, {len(preserved_ok)} déjà acquis avant.")
    if arrete_par_temps:
        print("Arrêt anticipé -- relancer (--only-missing) pour continuer.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
