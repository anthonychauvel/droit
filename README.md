# Aspirateur Légifrance — CCN + Code du travail

Récupère automatiquement les conventions collectives (IDCC/KALI) et des
articles du Code du travail depuis l'API PISTE, sans avoir besoin d'un
ordinateur — tout tourne sur les serveurs de GitHub.

## Installation (une seule fois, ~5 min)

1. **Crée le repo** sur GitHub (peut être privé) et mets-y tout le contenu
   de ce dossier tel quel (mêmes chemins : `.github/workflows/`, `scripts/`, etc.)

2. **Ajoute tes secrets PISTE** :
   Repo → Settings → Secrets and variables → Actions → "New repository secret"
   - `PISTE_CLIENT_ID` = ton Client ID (celui de ta capture d'écran)
   - `PISTE_CLIENT_SECRET` = ton Secret key
   (Ni moi ni personne d'autre ne peut voir ces valeurs une fois enregistrées.)

3. **Souscris à l'API Légifrance** dans ton dashboard PISTE si ce n'est pas
   déjà fait (ta dernière capture montrait "Aucune API souscrite" — c'est
   un bouton "Souscrire" à trouver sur la page de ton application).

## Utilisation (depuis iPhone, Safari ou l'app GitHub)

1. Va sur ton repo → onglet **Actions**
2. Clique sur **"Aspirateur Légifrance"** dans la liste à gauche
3. Clique sur **"Run workflow"**
4. Choisis :
   - **Cible** : `ccn` (grilles de salaires), `code-travail`, ou `les-deux`
   - **IDCC liste** : laisse vide pour utiliser `idcc_list.txt` (les 394 déjà dans ton fichier), ou tape des IDCC précis séparés par virgules pour tester sur 2-3 seulement
   - **Environnement** : `sandbox` pour tester, `production` une fois ta souscription validée
5. Clique le bouton vert "Run workflow"
6. Attends 1-2 minutes, rafraîchis la page — un ✅ vert apparaît quand c'est fini
7. Les résultats sont automatiquement commités dans `output/ccn/*.json` et `output/code-travail/*.json`

## Important : sandbox vs production

Le portail Légifrance confirme explicitement que **les données sandbox ne
sont pas identiques à la production** (souvent en retard, parfois
incomplètes). Pour du contenu réellement à jour, il faut demander une
appli **production** (validation supplémentaire par la DILA, ça peut
prendre quelques jours). Fais tes tests en sandbox, mais ne considère pas
les résultats sandbox comme fiables pour de la mise en production réelle.

## Comment je (Claude) récupère les résultats ensuite

Si le repo est **public**, dis-moi juste son nom (`utilisateur/nom-repo`)
et je peux lire directement `output/ccn/*.json` via GitHub — pas besoin
que tu m'envoies les fichiers à la main.

Si le repo est **privé**, il faudra que tu me partages les fichiers
générés (upload direct dans le chat, ou export en zip depuis GitHub).

## Structure des fichiers de sortie

- `output/ccn/<IDCC>.json` — contenu brut du conteneur KALI pour cette CCN
- `output/ccn/_summary.json` — résumé : quelles CCN ont marché, lesquelles
  ont des sections "salaire" détectées automatiquement
- `output/code-travail/<article>.json` — contenu de chaque article demandé
- `output/code-travail/_summary.json` — résumé des articles récupérés

Ces JSON sont **bruts** (structure telle que renvoyée par Légifrance,
avec du HTML imbriqué par endroits) — il faudra que je les reparse et les
restructure en JSON propre pour `ccn-data.json` et pour le guide, comme
j'ai fait pour les données kali-data plus tôt cette session.

## Fichiers de ce kit

- `scripts/pull_ccn.py` — récupère les CCN par IDCC (fonds KALI)
- `scripts/pull_code_travail.py` — récupère des articles précis (fonds LEGI)
- `.github/workflows/aspirateur.yml` — le workflow déclenché par bouton
- `idcc_list.txt` — les 394 IDCC actuellement dans ton `ccn-data.json`
- `articles_list.txt` — quelques articles de départ (à compléter selon ce
  que ton guide référence vraiment — dis-moi lesquels et je complète la liste)
