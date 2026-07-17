# Audit des erreurs CCN — 17/07/2026

## Contexte
386 IDCC sur les 696 de `idcc_list.txt` échouent actuellement (erreur 500)
lors de la récupération via l'API PISTE/Légifrance. Ce fichier documente
CE QU'ON SAIT sur chacune, pour permettre une correction méthodique plus
tard sans devoir tout re-vérifier depuis zéro.

## Fichier : `audit-ccn-erreurs.csv`

Colonnes :
- **idcc** : le numéro qui échoue actuellement
- **categorie** : voir ci-dessous
- **cible** : le numéro correct à utiliser à la place (si connu)
- **preuve** : d'où vient l'information
- **action_recommandee** : quoi faire concrètement

## Les 3 catégories

### 1. `agricole_absorbe` (164 lignes)
Anciens codes départementaux/régionaux agricoles (séries 9xxx et 8xxx).
Confirmé par la MSA et par le texte officiel de 7024/7025/7004 eux-mêmes
(qui citent explicitement "ex-IDCC 9301", etc.) : ces numéros ont **perdu
leur IDCC** depuis la fusion vers la CCN nationale unifiée (avril 2021).
Ce n'est pas un numéro périmé-avec-remplaçant classique — il n'y a
officiellement plus d'IDCC du tout pour ces anciens codes.

**Action recommandée** : retirer purement et simplement ces 164 numéros
de `idcc_list.txt`. Rien à récupérer individuellement, le contenu de
7024/7025/7004 (déjà dans le repo) couvre déjà tout.

### 2. `renumerotation_confirmee_dares` (43 lignes)
Confirmé directement par la base officielle DARES (le fichier
`Dares_Suivi_Historique_convention_collective_Juin2026.xlsx`) : chaque
ligne a un `NouvIDCC` renseigné, c'est-à-dire un numéro de remplacement
officiel et sourcé.

**Action recommandée** : pour chaque paire (idcc, cible), vérifier si
`cible` existe déjà dans `ccn-data.json` :
- Si NON : renommer la clé `idcc` -> `cible` directement
- Si OUI : comparer les deux contenus, garder le meilleur, supprimer le doublon
(C'est exactement la méthode déjà utilisée plus tôt cette session sur
un premier lot de renumérotations.)

### 3. `introuvable_non_resolu` (179 lignes)
Aucune piste trouvée : ni DARES, ni mention textuelle dans les CCN déjà
téléchargées avec succès. Soit ce sont des numéros véritablement
fantômes (jamais existé), soit l'information de remplacement n'est
simplement pas dans les sources qu'on a consultées.

**Action recommandée** : pas de correction automatique possible. Si l'un
de ces numéros s'avère important (beaucoup référencé dans le guide ou
l'appli), vaut le coup d'une recherche web dédiée au cas par cas. Sinon,
les laisser de côté / les retirer de `idcc_list.txt` pour ne plus
polluer les résultats de chaque run.

## Méthode utilisée pour construire cet audit
1. Liste des 386 IDCC en erreur 500 extraite de `output/ccn/_summary.json`
2. Séparation par motif numérique (9xxx = agricole probable)
3. Recherche du motif "ex-IDCC \d+" et "IDCC \d+" dans le texte de toutes
   les CCN déjà récupérées avec succès (310 fichiers) -- a révélé les
   correspondances agricoles en 8xxx et plusieurs cas non-agricoles
4. Croisement systématique avec la colonne NouvIDCC du fichier DARES
   officiel pour les 224 non-agricoles restants

## Prochaine étape suggérée
Traiter la catégorie 2 (43 lignes, la plus actionnable) en premier —
c'est un travail mécanique de renommage avec vérification de collision,
comme celui déjà fait sur le premier lot de renumérotations. Devrait
faire passer le taux de réussite de 45% à environ 51% (310+43 sur 696).
