#!/usr/bin/env python3
"""
pull_jorf.py — Module 2 (Journal Officiel, volet social) : ÉNUMÈRE tous les
textes parus au JO sur la fenêtre glissante de 10 ans, puis récupère et
filtre ceux qui touchent la RH.

CHANGEMENT MAJEUR du 31/07/2026 -- pourquoi cette réécriture :
La version précédente cherchait par mot-clé via /search, qui plafonnait à
~40 résultats quoi qu'on fasse (pagination bloquée côté API). La doc
officielle Légifrance décrit un flux d'ÉNUMÉRATION complète, bien plus fiable,
exactement le même principe que list_all_code_articles.py pour le Code du
travail (lister d'abord, remplir ensuite) :

  1. /consult/lastNJo   -> liste les N derniers Journaux Officiels (conteneurs
                           JORFCONT). Plafond documenté : N < 2500.
  2. /consult/jorfCont  -> pour chaque JO, la liste de tous les JORFTEXT qui y
                           ont été publiés.
  3. /consult/jorf      -> le contenu intégral d'un texte (déjà utilisé et
                           fonctionnel depuis le correctif CID).

On énumère donc TOUT le JO sur la période (des dizaines de milliers de textes),
puis on ne garde que ceux dont le titre matche un motif RH. C'est plus lourd
qu'une recherche, mais exhaustif -- l'inverse du compromis précédent.

Variables d'environnement (identiques au reste) :
    PISTE_CLIENT_ID / PISTE_CLIENT_SECRET / PISTE_ENV (défaut sandbox)

Fenêtre : 10 ans glissants, recalculée à chaque run. Ne supprime jamais
l'existant -- aucune ligne de suppression dans ce script.

À VALIDER au premier run réel (formes déduites de la doc, pas encore testées
ici, aucun identifiant PISTE dans ce bac à sable) :
  - /consult/lastNJo : corps {"nbElement": N} -- nom du champ à confirmer.
  - /consult/jorfCont : corps {"textCid": "JORFCONT..."} -- à confirmer.
  Si l'un des deux diffère, le message d'erreur complet (affiché intégralement
  ci-dessous) donnera la vraie forme.
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


def lister_jo_conteneurs(base_url, token, depuis):
    """Étape 1 : liste les JORFCONT (conteneurs de JO) sur la période.
    lastNJo renvoie les N derniers -- on demande large et on filtre par date
    ensuite. N < 2500 (limite documentée) -> pour 10 ans (~2600 JO quotidiens),
    on plafonne à 2499 et on prévient si la période n'est pas entièrement
    couverte."""
    resultat = call_api(base_url, token, "/consult/lastNJo", {"nbElement": 2499})
    # (Le dump de diagnostic de la réponse lastNJo a été retiré : il pesait
    #  ~200 Mo -- la liste des 2499 JO d'un coup -- et dépassait la limite de
    #  100 Mo de GitHub, faisant échouer le push. Sa seule utilité était de
    #  découvrir la structure de la réponse au premier run ; c'est fait.)
    if "_error" in resultat:
        return None, resultat

    conteneurs = []
    # La réponse liste des conteneurs ; on tolère plusieurs noms de champ
    # possibles puisque la forme exacte n'est pas encore confirmée.
    items = resultat.get("containers") or resultat.get("jo") or resultat.get("results") or []
    for it in items:
        cid = it.get("id") or it.get("cid") or it.get("jorfContId")
        d = it.get("date") or it.get("publicationDate") or ""
        if cid:
            conteneurs.append((cid, d))
    return conteneurs, None


def lister_textes_du_jo(base_url, token, jorf_cont_id):
    """Étape 2 : les JORFTEXT publiés dans un JO donné.

    CORRECTIF 01/08 (bug du cumul figé) : la réponse jorfCont contient TOUT
    l'arbre du conteneur, y compris des références à d'AUTRES JO (liens,
    sommaires croisés). Un walk() naïf sur tout l'arbre ramassait donc des
    JORFTEXT qui ne sont PAS de ce JO -- et comme c'étaient souvent les mêmes
    (le JO le plus récent, très lié), le cumul restait bloqué. On restreint
    l'extraction à la STRUCTURE du conteneur demandé : items[].joCont.structure,
    et on vérifie au passage que le joCont renvoyé est bien celui demandé.
    """
    resultat = call_api(base_url, token, "/consult/jorfCont", {"textCid": jorf_cont_id})
    if "_error" in resultat:
        return None, resultat
    textes = []

    def extraire_de_structure(node):
        """Ne descend QUE dans la structure/les sections d'articles du JO,
        pas dans les liens vers d'autres conteneurs."""
        if isinstance(node, dict):
            tid = node.get("id") or node.get("cid")
            titre = node.get("title") or node.get("titre") or ""
            if tid and str(tid).startswith("JORFTEXT"):
                textes.append((str(tid).split("_")[0], titre))
            # On ne suit que les branches de contenu, pas 'liens'/'joEA' etc.
            for cle in ("structure", "sections", "articles", "children", "items", "tms"):
                if cle in node:
                    extraire_de_structure(node[cle])
        elif isinstance(node, list):
            for v in node:
                extraire_de_structure(v)

    # La vraie charge est sous items[].joCont.structure (confirmé par le diag).
    items = resultat.get("items") or []
    for it in items:
        jocont = it.get("joCont") if isinstance(it, dict) else None
        if not jocont:
            continue
        # Vérif : ce joCont est-il bien celui qu'on a demandé ? Sinon, l'API a
        # renvoyé autre chose et on ne veut pas de ses textes.
        renvoye = jocont.get("id") or ""
        if renvoye and renvoye != jorf_cont_id:
            # On le signale mais on n'ajoute rien : pas de pollution croisée.
            return [], {"_error": "mismatch",
                        "_detail": f"demandé {jorf_cont_id}, renvoyé {renvoye}"}
        extraire_de_structure(jocont.get("structure", []))

    # Repli : si la structure attendue n'existe pas, on tente l'ancien walk
    # global (mieux que rien), mais ça ne devrait plus servir.
    if not textes:
        def walk(node):
            if isinstance(node, dict):
                tid = node.get("id") or node.get("cid")
                titre = node.get("title") or node.get("titre") or ""
                if tid and str(tid).startswith("JORFTEXT"):
                    textes.append((str(tid).split("_")[0], titre))
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)
        walk(resultat.get("items", []))

    return textes, None


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
    ap.add_argument("--max-jo", type=int, default=2499,
                     help="Plafond de JO à énumérer (garde-fou).")
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

    # ── Étape 1 : conteneurs de JO ──
    print("Étape 1 : liste des Journaux Officiels...")
    conteneurs, err = lister_jo_conteneurs(client, None, depuis)
    if err:
        print(f"ÉCHEC lastNJo ({err['_error']}) : {str(err.get('_detail',''))[:400]}", file=sys.stderr)
        print("Rien récupéré -- voir le message ci-dessus pour la vraie forme du endpoint.", file=sys.stderr)
        sys.exit(1)

    depuis_dt = datetime.combine(depuis, datetime.min.time())
    conteneurs_periode = []
    for cid, d in conteneurs:
        try:
            if d and datetime.fromisoformat(d[:10]) < depuis_dt:
                continue
        except ValueError:
            pass
        conteneurs_periode.append(cid)
    conteneurs_periode = conteneurs_periode[:args.max_jo]
    print(f"  {len(conteneurs)} JO listés, {len(conteneurs_periode)} dans la fenêtre de 10 ans.")
    if len(conteneurs) >= 2499:
        print("  ATTENTION : plafond de 2499 JO atteint -- la période de 10 ans n'est "
              "peut-être pas entièrement couverte (le JO paraît quotidiennement). "
              "Les JO les plus anciens de la fenêtre peuvent manquer.", file=sys.stderr)

    # ── Étape 2 : énumération des textes, filtrés RH sur le titre ──
    print("Étape 2 : énumération des textes RH dans chaque JO...")
    candidats_rh = {}  # id -> titre
    for i, cid in enumerate(conteneurs_periode, 1):
        textes, err = lister_textes_du_jo(client, None, cid)
        if err:
            print(f"  [{i}/{len(conteneurs_periode)}] JO {cid} : échec ({err['_error']})", file=sys.stderr)
            time.sleep(args.delay)
            continue
        rh = [(tid, titre) for tid, titre in textes if titre_est_rh(titre)]
        for tid, titre in rh:
            candidats_rh[tid] = titre
        if i % 25 == 0 or rh:
            print(f"  [{i}/{len(conteneurs_periode)}] JO {cid} : {len(textes)} textes, "
                  f"{len(rh)} RH (cumul {len(candidats_rh)})")
        time.sleep(args.delay)

    print(f"\n{len(candidats_rh)} texte(s) RH énuméré(s) au total sur la période.")

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
