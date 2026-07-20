#!/usr/bin/env python3
"""
Découvre des décisions de jurisprudence pertinentes pour l'app, PAR THÈME
(forfait jours, heures supplémentaires, temps partiel, licenciement...),
plutôt que par numéro de pourvoi déjà connu comme le fait pull_jurisprudence.py.

Il n'existe pas d'"univers complet" énumérable pour la jurisprudence (à la
différence des CCN ou des articles d'un code) -- la Cour de cassation rend
des milliers de décisions chaque année. Ce script ne prétend donc pas
"tout" récupérer : il cherche les décisions les plus récentes/pertinentes
sur une liste de thèmes fixée, et les propose à la validation humaine avant
tout ajout à arrets_list.txt -- cohérent avec l'avertissement déjà présent
dans pull_jurisprudence.py ("toute utilisation doit repasser par une
lecture humaine").

NE MODIFIE PAS arrets_list.txt automatiquement. Écrit les numéros trouvés,
avec leur titre, dans un fichier séparé à relire.

Usage:
    python3 discover_jurisprudence.py --out jurisprudence_decouverte.txt
    python3 discover_jurisprudence.py --themes "forfait jours" "temps partiel" --out /tmp/decouverte.txt
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# Thèmes par défaut : les sujets couverts par l'app (module HS, module cadres,
# module temps partiel). Modifiable via --themes.
THEMES_DEFAUT = [
    "forfait jours nullité",
    "forfait jours convention individuelle",
    "cadre dirigeant requalification",
    "heures supplémentaires preuve",
    "temps partiel requalification",
    "heures complémentaires",
    "contingent annuel heures supplémentaires",
    "rupture conventionnelle",
    "licenciement sans cause réelle et sérieuse",
    "droit à la déconnexion",
]


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
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())["access_token"]


def call_api(base_url, token, path, body):
    req = urllib.request.Request(
        base_url + path, data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                  "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"_error": e.code, "_detail": e.read().decode(errors="replace")}
    except Exception as e:
        return {"_error": "exception", "_detail": f"{type(e).__name__}: {e}"}


def chercher_theme(base_url, token, theme, max_resultats=10):
    """Cherche les décisions les plus récentes/pertinentes sur un thème donné.
    Même endpoint que pull_jurisprudence.py (fond JURI), mais typeChamp=ALL
    (texte libre) au lieu de NUM_AFFAIRE (numéro exact), et triée par date
    pour privilégier les décisions récentes."""
    body = {
        "fond": "JURI",
        "recherche": {
            "champs": [{
                "typeChamp": "ALL",
                "operateur": "ET",
                "criteres": [{"valeur": theme, "typeRecherche": "TOUS_LES_MOTS_DANS_UN_CHAMP", "operateur": "ET"}],
            }],
            "sort": "DATE_DESC",
            "pageNumber": 1,
            "pageSize": max_resultats,
        },
    }
    return call_api(base_url, token, "/search", body)


def extraire_decisions(result):
    """Le format exact de /search n'est pas garanti stable (même avertissement
    que pull_ccn.py) -- on essaie plusieurs chemins raisonnables."""
    items = result.get("results") or result.get("resultats") or []
    out = []
    for item in items:
        numero = item.get("numAffaire") or item.get("num_affaire") or item.get("numero")
        titres = item.get("titles") or item.get("titres") or []
        titre = ""
        for t in titres:
            titre = t.get("title") or t.get("titre") or ""
            if titre:
                break
        titre = titre or item.get("title") or item.get("titre") or ""
        if numero:
            out.append((numero, titre))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="jurisprudence_decouverte.txt")
    ap.add_argument("--themes", nargs="+", default=None,
                     help="Thèmes à chercher (défaut : liste fixe couvrant forfait jours/HS/temps partiel/rupture)")
    ap.add_argument("--par-theme", type=int, default=10, help="Nombre de résultats max par thème")
    ap.add_argument("--delay", type=float, default=1.2)
    args = ap.parse_args()

    client_id = os.environ.get("PISTE_CLIENT_ID")
    client_secret = os.environ.get("PISTE_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("ERREUR: PISTE_CLIENT_ID / PISTE_CLIENT_SECRET manquants.", file=sys.stderr)
        sys.exit(1)

    themes = args.themes or THEMES_DEFAUT
    token_url, base_url = get_urls()
    token = get_token(token_url, client_id, client_secret)
    print(f"Token OK. Recherche sur {len(themes)} thème(s).")

    # numéro -> (titre, liste des thèmes qui l'ont trouvé -- utile pour prioriser)
    trouvailles = {}
    deja_connus = set()
    if os.path.exists("arrets_list.txt"):
        with open("arrets_list.txt", encoding="utf-8") as f:
            deja_connus = set(l.strip() for l in f if l.strip())

    for theme in themes:
        result = chercher_theme(base_url, token, theme, args.par_theme)
        if "_error" in result:
            print(f"  '{theme}': ERREUR {result['_error']}")
            time.sleep(args.delay)
            continue
        decisions = extraire_decisions(result)
        nouveaux = [d for d in decisions if d[0] not in deja_connus]
        print(f"  '{theme}': {len(decisions)} trouvée(s), {len(nouveaux)} pas déjà dans arrets_list.txt")
        for numero, titre in decisions:
            if numero not in trouvailles:
                trouvailles[numero] = {"titre": titre, "themes": []}
            trouvailles[numero]["themes"].append(theme)
        time.sleep(args.delay)

    out_dir = os.path.dirname(args.out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write("# Découvertes par thème -- À RELIRE avant d'ajouter à arrets_list.txt\n")
        f.write("# Format : numéro_pourvoi | déjà connu ? | thème(s) | titre\n")
        for numero, info in sorted(trouvailles.items()):
            connu = "déjà connu" if numero in deja_connus else "NOUVEAU"
            f.write(f"{numero} | {connu} | {', '.join(info['themes'])} | {info['titre']}\n")

    n_nouveaux = sum(1 for n in trouvailles if n not in deja_connus)
    print(f"\n{len(trouvailles)} décision(s) unique(s) trouvée(s), {n_nouveaux} nouvelle(s) (pas déjà suivie(s)).")
    print(f"Écrit dans {args.out} -- à relire, puis ajouter à la main les numéros pertinents à arrets_list.txt.")


if __name__ == "__main__":
    main()
