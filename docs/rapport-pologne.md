# Rapport — verticale Pologne

## Chiffres mesurés

- Métas extraites : 35 (national 17, régional 12, ponctuel 6)
- Métas sans image : 0   sans lien Maps : 20 (15 métas ont des coordonnées Maps résolues : country 4, regional 7, spot 4)
- IoU de calibration PL : 0,9781, soit environ 1,30 km/pixel
- Taux de justesse automatique (point Maps dans le polygone) : 7 / 7 = 100 % — mesuré sur les 7 métas `regional` disposant de coordonnées Maps, confirmé par trois vérifications indépendantes (voir « Limites connues »)
- Métas validées sans retouche à la revue : en attente — la revue humaine (Task 11) n'a pas encore eu lieu ; les 35 métas sont toutes au statut `auto`. À mesurer par la personne qui effectue la revue au clavier (`cartometa-review`), une fois celle-ci terminée, comme `validées sans modification / total revu`.
- Temps moyen de revue par méta : en attente, même raison — à chronométrer par la personne qui effectue la revue (horodatage début/fin de session dans l'interface de revue, ou mesure manuelle), une fois la revue réalisée.
- Latence de requête du viewer : mesurée à 0,2–3,6 ms par clic (filtre bbox + test point-dans-polygone sur les 31 métas géométrisées), très en dessous du seuil de 100 ms

## Ce qui fonctionne

- L'extraction Plonk It couvre les 35 métas de la page Pologne sans manque d'image (0/35).
- L'aiguillage géométrique par tier (national = silhouette pays, régional = vectorisation de l'encart, ponctuel = tampon autour du point Maps) produit une géométrie valide pour 31 des 35 métas.
- Sur les 7 métas régionales disposant d'un point Maps de vérité terrain, le polygone vectorisé contient ce point dans 100 % des cas (7/7). Trois vérifications indépendantes (au moment de la construction Task 10, en revue Task 11, et en re-mesure directe lors de la rédaction de ce rapport) donnent le même résultat.
- Le viewer statique (Leaflet + JSON, sans build ni serveur applicatif) répond en quelques millisecondes : filtre bounding-box du côté JS, puis test point-dans-polygone gérant `Polygon` et `MultiPolygon` avec anneaux intérieurs (trous). Le tri par surface croissante fait remonter les métas ponctuelles avant les régionales, elles-mêmes avant les nationales — vérifié explicitement sur un clic dans les Tatras (méta ponctuelle `dx99` en tête, avant les 3 métas régionales et les 17 nationales couvrant le point).
- Un clic hors de toute géométrie (test effectué en plein Atlantique) affiche explicitement « Aucune méta pour ce point. », sans exception JavaScript.
- Le panneau de résultats passe sous la carte en dessous de 760px de large et reste utilisable (vérifié à 400px de large).

## Limites connues

- **Limite majeure : échantillon mince pour le taux de justesse.** La mesure de justesse automatique (7/7) ne couvre que les métas `regional` disposant d'un lien Maps, soit 7 des 12 métas régionales et 7 des 35 métas au total. Les métas `country` (justesse triviale, la géométrie est la silhouette du pays) et les métas `spot` sans encart à vectoriser ne sont pas concernées par cette mesure. Un taux de 100 % sur un échantillon de 7 est encourageant mais ne peut pas encore être généralisé ; il ne s'élargira qu'en ajoutant d'autres pays au corpus.
- 4 des 35 métas n'ont aucune géométrie, chacune avec un avertissement explicite et vérifié :
  - `JBtU`, `QKpM` : métas ponctuelles sans lien Maps, position inconnue.
  - `gxrJ` : encart cartographique détecté mais aucun pixel rouge trouvé dans la silhouette.
  - `hZvJ` : aucun encart cartographique détectable.
- Trois métas de tier `country` ou `regional` ont des dimensions d'image non standard, ce qui déclenche une détection d'encart aberrante ou absente sur ces images précises. Sans conséquence pratique : l'aiguillage par tier isole les métas `country` de la détection d'encart (elles reçoivent directement la silhouette du pays), donc ces dimensions atypiques n'affectent que des cas déjà couverts par un avertissement explicite plutôt que par une géométrie fausse silencieuse.
- Les deux chiffres de revue humaine (temps moyen par méta, taux de validation sans retouche) ne sont pas encore mesurables : aucune session de revue n'a eu lieu sur ce corpus. Ne pas les estimer par extrapolation — les mesurer réellement une fois la revue faite.

## Décision sur l'éditeur de sommets

La spec (§6.1) reportait la construction de l'éditeur de sommets jusqu'à connaître le taux de validation sans retouche à la revue. Ce taux ne peut pas encore être établi : la revue humaine n'a pas eu lieu sur ce corpus (35/35 métas au statut `auto`).

Décision : le report est maintenu. L'éditeur de sommets reste hors scope tant que ce taux n'est pas mesuré. Une fois une session de revue réalisée sur les 35 métas PL (via `cartometa-review`), recalculer `validées sans retouche / total revu` et rouvrir la décision sur cette base — pas avant.

## Pays problématiques et prochaine étape

- Aucun autre pays n'a encore été traité : la Pologne est la première et unique verticale complète du projet à ce stade, ce qui limite la portée de toute conclusion statistique (voir « Limites connues »).
- Prochaine étape recommandée : mener la revue humaine des 35 métas PL avec `cartometa-review`, pour (a) débloquer les deux chiffres de revue laissés en attente ci-dessus, (b) produire un premier jeu de données réellement publiable via `cartometa-export PL` (sans `--include-auto`), et (c) alimenter la décision sur l'éditeur de sommets avec une vraie mesure.
- Ajouter un second pays permettrait d'élargir l'échantillon de mesure de justesse au-delà des 7 métas actuelles et de tester l'aiguillage par tier sur un corpus d'images différent (autre style de carte source, autres dimensions d'encart).

## Note sur l'export du viewer

`cartometa-export` n'exporte par défaut que les métas de statut `validé` ou `corrigé` (comportement de la spec) : sur ce corpus, avant toute revue, cela produit un viewer vide (0 méta). Une option explicite `--include-auto`, désactivée par défaut, permet d'inclure aussi les métas `auto` pour faire fonctionner et vérifier le viewer avant la revue — elle a servi aux vérifications du Step 5 (31 métas géométrisées exportées, latence 0,2–3,6 ms). Quand elle est utilisée, l'outil affiche explicitement le nombre de métas non revues incluses, pour qu'une publication accidentelle de données non validées ne passe pas inaperçue. Les données livrées dans ce dépôt (`viewer/data/*.json`) correspondent au comportement par défaut — vides, en attente de revue.
