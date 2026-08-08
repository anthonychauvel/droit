#!/usr/bin/env python3
"""
Compresse en brotli les gros index JSON, pour que le Worker Cloudflare les
serve avec l'en-tête « Content-Encoding: br ». Le navigateur décompresse de
façon transparente : côté application, rien ne change (on continue d'appeler
fetch('output/search-index.json')), mais l'octet transféré passe d'environ
159 Mo à 16,5 Mo au total (mesuré) — l'appli devient utilisable en mobilité.

Pourquoi pré-compresser plutôt que laisser Cloudflare faire ?
  * Cloudflare ne compresse PAS à la volée les réponses au-delà d'environ 10 Mo.
    Un search-index.json de 78 Mo serait donc servi BRUT malgré la compression
    automatique. Il faut le compresser en amont.
  * Un Worker gratuit n'a pas le budget CPU (10 ms) pour compresser 78 Mo à la
    volée : impossible côté worker non plus. Donc on le fait ici, une fois par
    run, sur le serveur GitHub Actions.

Le JSON brut reste généré et commité : lecteur.html et le repli GitHub Pages le
lisent directement (eux ne passent pas par le worker). On AJOUTE simplement le
.br à côté.

Usage :
    python3 scripts/compress_index.py --dir output --quality 9

Qualité brotli : 9 = quasi-optimal et rapide (recommandé pour ne pas ralentir
le push « live »). 11 gagne quelques % de plus mais est nettement plus lent sur
un fichier de 78 Mo.
"""
import argparse
import os
import sys

try:
    import brotli
except ImportError:
    sys.exit("Le module 'brotli' est absent. Dans le workflow :\n"
             "    pip install brotli --break-system-packages")

# Seuls les fichiers réellement volumineux et chargés par le front. Les petits
# (counts, ccn-liste, search-trends) ne valent pas un aller-retour .br en plus.
CIBLES = [
    "search-index.json",
    "clauses-index.json",
    "manifest.json",
    "classification-source.json",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="output",
                    help="Dossier contenant les index JSON (défaut: output)")
    ap.add_argument("--quality", type=int, default=9,
                    help="Qualité brotli 0-11 (défaut: 9)")
    args = ap.parse_args()

    total_raw = total_br = 0
    faits = 0
    for name in CIBLES:
        src = os.path.join(args.dir, name)
        if not os.path.exists(src):
            print(f"  (absent, ignoré) {name}")
            continue
        raw = open(src, "rb").read()
        comp = brotli.compress(raw, quality=args.quality)
        with open(src + ".br", "wb") as f:
            f.write(comp)
        total_raw += len(raw)
        total_br += len(comp)
        faits += 1
        ratio = len(raw) / len(comp) if comp else 0
        print(f"  {name}: {len(raw)/1e6:.1f} Mo -> {len(comp)/1e6:.1f} Mo "
              f"(br q{args.quality}, {ratio:.1f}x)")

    if faits:
        ratio = total_raw / total_br if total_br else 0
        print(f"Total: {total_raw/1e6:.1f} Mo -> {total_br/1e6:.1f} Mo ({ratio:.1f}x) "
              f"sur {faits} fichier(s).")
    else:
        print("Aucun fichier à compresser (aucune cible présente dans "
              f"{args.dir}).")


if __name__ == "__main__":
    main()
