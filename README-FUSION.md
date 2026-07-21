# Fusion lecteur + recherche — mise en place

On repart proprement. `index.html` **remplace à lui seul** `lecteur.html` **et**
`page-recherche/recherche.html` : un seul module qui fait recherche *et* lecture.

## Ce qui répond à chaque demande

| Demande | Où c'est traité |
|---|---|
| Fusionner lecteur + recherche | `index.html` (un seul fichier autonome) |
| Toutes les CCN, tous les articles Code du travail / Sécu, toute la jurisprudence, toutes les mises à jour, cliquables et consultables | `index.html` lit `output/manifest.json` (liste **intégrale**) et ouvre chaque fiche au clic |
| Sous-catégories avec la **totalité** des articles, pas quelques-uns | Navigation par source → sous-catégories (thèmes pour les CCN ; Partie L/R/D + Livres pour les codes) → **liste complète paginée** (bouton « Afficher plus ») |
| Recherche intuitive par **mots-clés combinés** (« convention commerce de gros heures supplémentaires ») | Barre de recherche : chaque mot devient un **filtre cumulatif** (chips retirables), ET entre une convention/un métier et un thème |
| Validé / abrogé **directement** à côté de chaque ligne, sans cliquer | Badge de validité sur chaque ligne (état lu dans `manifest.json` / `search-index.json`) |
| Fluide comme le guide | Même famille visuelle (Manrope + Source Sans, marine + violet), panneau de lecture qui glisse, listes virtualisées |
| Runs de vérif étalés sur 5 semaines, 2 par semaine, selon le volume total | `rotation_helper.py` (10 tranches) + `aspirateur.yml` (cron lundi **et** jeudi) |
| Chaque run pousse **en live** dès qu'il détecte un changement | Étape « PRIORITÉ nouveautés » (push immédiat après remplissage) **+** commit/push final : les changements partent sans attendre la fin du run |
| Chaque **lundi** recense **tous** les numéros (articles + CCN) ; un nouveau numéro est **injecté** et **rempli au run suivant** | Recensement lundi (`list_all_ccn.py` + `list_all_code_articles.py`) → un numéro sans fichier est « manquant » → passe prioritaire `--only-missing --max` à chaque run le remplit dès le run d'après |
| Chaque run n'écrase pas le précédent | Le manifeste et l'index sont **reconstruits en scannant les fichiers** (jamais le seul dernier run) ; les scripts ne remplacent **jamais** un bon fichier par une erreur ; les rapports d'audit restent datés |

## Fichiers à mettre sur GitHub

Remplacer / ajouter, en gardant l'arborescence :

```
index.html                              ← NOUVEAU (racine) — remplace lecteur.html + recherche.html
scripts/build_manifest.py               ← NOUVEAU
scripts/rotation_helper.py              ← REMPLACE (5 → 10 tranches, 2/semaine)
scripts/pull_code_travail.py            ← REMPLACE (capture l'état + n'écrase plus un bon fichier par une erreur + fusion du résumé)
scripts/pull_ccn.py                     ← REMPLACE (fusion du résumé même hors --only-missing)
scripts/build_search_index.py           ← REMPLACE (scanne tout le dossier + ajoute l'état par article)
.github/workflows/aspirateur.yml        ← REMPLACE (2 crons/semaine, période 10, étape manifeste)
```

Les autres scripts (`classify_source.py`, `export_ccn_liste.py`,
`generate_audit_report.py`, `fetch_*_details.py`, `list_all_*`, `detect_nouveaux.py`)
sont **inchangés** — ne pas y toucher.

Tu peux supprimer `lecteur.html` et `page-recherche/` une fois `index.html` en place
(ou les laisser, ils ne gênent pas). L'adresse devient
`https://anthonychauvel.github.io/droit/` (index.html est la page par défaut).

## Important : le premier affichage complet

`index.html` a besoin de `output/manifest.json` pour afficher la **liste
intégrale** et l'état validé/abrogé partout. Ce fichier est **produit par le
workflow** (nouvelle étape « Construire le manifeste complet »).

- **Avant** le premier run avec ces fichiers : la page fonctionne quand même,
  mais retombe sur les anciens `_summary.json` (donc listes potentiellement
  partielles, états seulement là où le search-index les connaît).
- **Après** un run (manuel depuis l'onglet *Actions* → *Run workflow*, ou le
  prochain lundi/jeudi automatique) : `manifest.json` est généré et committé, et
  la page affiche tout, avec validé/abrogé sur chaque ligne.

Rien à téléverser à la main : la page va chercher les données via des chemins
relatifs (`output/…`), et bascule automatiquement sur
`raw.githubusercontent.com/anthonychauvel/droit/main/…` si tu ouvres le fichier
hors du dépôt.

## Comment marche la rotation 2×/semaine sur 5 semaines

`rotation_helper.py` découpe la liste (univers complet des IDCC / articles) en
**10 tranches**. Le numéro de tranche est calculé depuis la date :
`(semaine_ISO × 2 + créneau) % 10`, créneau 0 le lundi, 1 le jeudi. Deux tranches
par semaine, donc après **5 semaines** tout le corpus est repassé une fois, puis
le cycle recommence — sans rien mémoriser, c'est déterministe.

Le volume total est respecté automatiquement : la taille d'une tranche = volume ÷ 10.

## Le rythme d'un run (lundi vs jeudi) + le push live

Chaque run (lundi et jeudi 6h UTC) fait, dans l'ordre :

1. **Lundi seulement — recensement complet** : `list_all_ccn.py` et
   `list_all_code_articles.py` relistent **tous** les IDCC et **tous** les
   numéros d'article existants sur Légifrance. `detect_nouveaux.py` écrit un
   rapport « X nouveaux détectés » (visible dans l'onglet *Mises à jour* et sur
   le tableau de bord d'accueil).
2. **Chaque run — remplissage prioritaire des nouveautés + PUSH LIVE** : tout
   numéro présent dans l'univers mais **sans fichier** (donc un numéro tout juste
   recensé) est récupéré en priorité (plafonné à 300 CCN / 800 articles par run
   pour tenir dans la limite de temps), l'index et le manifeste sont regénérés,
   puis **c'est poussé immédiatement** — les nouveautés sont en ligne sans
   attendre la suite. Un numéro découvert **lundi** est donc rempli et
   consultable dès **jeudi** ; s'il en reste (gros afflux), le reliquat part au
   run suivant, en boucle, jusqu'à épuisement.
3. **Chaque run — rotation** : une tranche (1/10ᵉ) de tout le corpus est
   re-vérifiée pour capter les **changements** des textes déjà présents (un
   article qui passe de *en vigueur* à *abrogé*, un avenant modifié…).
4. **Commit + push final** : si quoi que ce soit d'autre a changé, c'est committé
   et poussé. Deux pushes possibles par run (un « live » après l'étape 2, un en
   fin de run) — les changements réels apparaissent donc vite.

Ainsi : les **nouveaux numéros** sont injectés et remplis au run suivant (étapes
1–2), et les **modifications** des textes existants sont captées par la rotation
(étape 3), le tout poussé en live.

## « Ne pas écraser le précédent » — en détail

1. Les listes affichées viennent d'un **scan des fichiers réellement présents**
   (`build_manifest.py` et `build_search_index.py` font un `glob` du dossier),
   pas du résumé du dernier run. Un run tournant qui ne rafraîchit qu'1/10ᵉ du
   corpus **ne fait donc jamais disparaître** le reste.
2. Si un appel Légifrance échoue (réseau, quota), `pull_code_travail.py` et
   `pull_ccn.py` **conservent le fichier existant** au lieu de le remplacer par
   une erreur.
3. Les rapports d'audit restent datés (`AAAA-MM-JJ[-HHMM].md`) : chaque run ajoute
   le sien, aucun n'écrase l'autre.

## Jurisprudence via Judilibre (Cour de cassation)

`pull_judilibre.py` remplace l'ancienne brique jurisprudence. Judilibre est un
vrai moteur de recherche de la jurisprudence, exposé sur **PISTE** comme
l'API Légifrance — donc **avec les mêmes identifiants**.

**Action unique à faire une fois** (sinon les appels renverront une erreur
d'autorisation) : dans ta **même application PISTE**, abonne-toi à l'API
« Judilibre » et valide ses CGU (cherche « Judilibre » pour l'environnement
production, et/ou sandbox). Rien d'autre à changer : `PISTE_CLIENT_ID` /
`PISTE_CLIENT_SECRET` restent les mêmes.

Ce que fait le script :
- **Découverte thématique** (`GET /search`, chambre sociale `soc` par défaut) sur
  une liste de thèmes de droit du travail (forfait jours, heures sup, temps
  partiel, rupture conventionnelle, licenciement, inaptitude, harcèlement…).
- **Texte intégral** de chaque décision (`GET /decision`), écrit dans
  `output/jurisprudence/<numéro>.json` au format déjà lu par le lecteur,
  l'index et le manifeste — donc les décisions apparaissent dans l'onglet
  Jurisprudence **et** dans la recherche combinée, avec le reste.

Dans le workflow :
- **Runs planifiés** : découverte plafonnée en ne récupérant que les décisions
  **nouvelles** (`--only-missing --max-decisions 150`) → le corpus de
  jurisprudence s'enrichit à chaque run, sans tout re-télécharger.
- **Run manuel `cible = jurisprudence`** : version plus large (500 décisions).
- **Run manuel `cible = decouvrir-jurisprudence`** : très large, **toutes
  chambres** (800 décisions) — utile pour un gros remplissage ponctuel.

Réglages dans `pull_judilibre.py` / le workflow : `--chamber` (ex. `soc`, ou
vide = toutes), `--jurisdiction` (`cc` Cour de cassation, `ca` cours d'appel,
vide = toutes), `--themes "…" "…"`, `--per-theme`, `--max-decisions`.

Rappel prudence : le texte récupéré est la décision intégrale (pseudonymisée),
pas un résumé du principe — toute réutilisation demande une lecture humaine.
