# Mode évolutif — MonLegiTexte

Le moteur **apprend** le vocabulaire à mesure que le corpus grandit. Tout est
**automatique** et **ne touche à aucune donnée personnelle** : on se base
uniquement sur les textes récupérés par les runs.

## Comment ça marche

À chaque run, juste après la construction de l'index, le workflow lance
`scripts/build_trends.py`. Ce script :

1. lit `output/search-index.json` (déjà produit) ;
2. compte les **mots et expressions les plus fréquents** dans les textes ;
3. écrit `output/search-trends.json` ;
4. affiche dans le journal du run la liste **« à classer en priorité »** :
   les termes fréquents qui **ne sont couverts par aucune catégorie**.

Le fichier produit ressemble à :

```json
{
  "generated": "2026-07-21",
  "terms":      [["contingent", 1234], ["teletravail", 980], ...],
  "phrases":    [["heures supplementaires", 456], ...],
  "to_classify":[["teletravail", 980], ["prime", 640], ["nuit", 610], ...]
}
```

## Ce que ça change, sans rien faire

`index.html` charge `search-trends.json` (et l'ignore proprement s'il est
absent). Les mots fréquents alimentent alors **l'autocomplétion** (catégorie
« Fréquent ») et la **tolérance aux fautes** (vocabulaire du correcteur). Donc,
run après run, la prédiction et la correction s'enrichissent **toutes seules**
du vocabulaire réel du corpus.

## Ce que ça vous fait gagner (classer plus vite)

La liste **`to_classify`** vous dit *exactement quoi classer ensuite*, trié par
fréquence. Pour classer un terme, ajoutez-le à la bonne catégorie dans
`scripts/build_search_index.py` (dictionnaire `KEYWORDS`). Exemple : si
`teletravail` revient beaucoup, créez/complétez une entrée :

```python
KEYWORDS = {
    ...
    "teletravail": ["télétravail", "travail à distance", "distanciel"],
}
```

Si vous voulez qu'un mot déclenche aussi ce thème côté moteur (sections
cliquables), ajoutez-le dans `index.html` (`CAT_KEYWORDS_RAW`). Au prochain run,
les sections qui en parlent seront étiquetées automatiquement.

> Le script **repère et priorise** pour vous ; il ne classe pas tout seul à
> votre place. Sur du droit, une catégorie posée automatiquement de travers
> ferait plus de mal que de bien : vous gardez la main sur la taxonomie, mais
> vous savez enfin *où regarder en premier*.

## Confidentialité

Aucune donnée personnelle n'est traitée : l'application ne fait que lire des
fichiers statiques sur le même domaine (pas de cookie, pas de traçage, aucune
requête d'utilisateur enregistrée). Les tendances proviennent **exclusivement**
des textes officiels récupérés par les runs.
