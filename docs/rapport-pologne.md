# Rapport — verticale Pologne

## Chiffres mesurés

- Métas extraites : 37 (national 19, régional 12, ponctuel 6)
- Métas sans image : 0. 31 métas portent un lien Maps, et **les 31 se résolvent en coordonnées** (national 17, régional 8, ponctuel 6)
- IoU de calibration PL : 0,9781, soit environ 1,30 km/pixel
- Taux de justesse automatique (point Maps dans le polygone) : **8 / 8 = 100 %** — mesuré sur les 8 métas `regional` disposant de coordonnées Maps, confirmé par quatre vérifications indépendantes (voir « Limites connues »)
- Métas validées sans retouche à la revue : **27 / 37 = 73 %**, au-dessus du seuil de 70 % fixé par la spec (§7). Revue humaine effectuée le 2026-07-29 sur la totalité du corpus : 37/37 métas décidées, aucune laissée au statut `auto`. Détail : 27 `validé`, 6 `corrigé`, 4 `rejeté`.
- Temps moyen de revue par méta : **non mesuré**. L'interface de revue n'horodate pas les décisions — elle n'enregistre que `status` (et `geometry_before_correction` en cas de correction). Le chiffre n'est donc pas reconstituable a posteriori. Ne pas l'estimer : instrumenter l'interface avant la prochaine session de revue si le chiffre importe.
- Latence de requête du viewer : mesurée à 0,2–3,6 ms par clic (filtre bbox + test point-dans-polygone), très en dessous du seuil de 100 ms. Mesure faite dans Chromium *headless* piloté par Playwright — moteur de rendu réel, mais pas une session de navigateur de bureau.
- Suite de tests : 86 tests, tous verts, dont 5 sur données réelles.

## Ce qui fonctionne

- L'extraction Plonk It couvre les 37 métas de la page Pologne sans manque d'image (0/37).
- L'aiguillage géométrique par tier (national = silhouette pays, régional = vectorisation de l'encart, ponctuel = tampon autour du point Maps) produit une géométrie valide pour 35 des 37 métas.
- Sur les 8 métas régionales disposant d'un point Maps de vérité terrain, le polygone vectorisé contient ce point dans 100 % des cas (8/8). Quatre vérifications indépendantes donnent le même résultat, dont deux menées par des relecteurs ayant écrit leur propre script sans réutiliser les fonctions du projet.
- Le viewer statique (Leaflet + JSON, sans build ni serveur applicatif) répond en quelques millisecondes : filtre bounding-box du côté JS, puis test point-dans-polygone gérant `Polygon` et `MultiPolygon` avec anneaux intérieurs (trous). Le tri par surface croissante fait remonter les métas ponctuelles avant les régionales, elles-mêmes avant les nationales — vérifié explicitement sur un clic dans les Tatras (méta ponctuelle `dx99` en tête, avant les métas régionales puis les 19 nationales couvrant le point).
- Un clic hors de toute géométrie (test effectué en plein Atlantique) affiche explicitement « Aucune méta pour ce point. », sans exception JavaScript.
- Le panneau de résultats passe sous la carte en dessous de 760px de large et reste utilisable (vérifié à 400px de large).

## Limites connues

- **Limite majeure : échantillon mince pour le taux de justesse.** La mesure de justesse automatique (8/8) ne couvre que les métas `regional` disposant d'un lien Maps, soit 8 des 12 métas régionales et 8 des 37 métas au total. Les métas `country` (justesse triviale, la géométrie est la silhouette du pays) et les métas `spot` sans encart à vectoriser ne sont pas concernées par cette mesure. Un taux de 100 % sur un échantillon de 8 est encourageant mais ne peut pas encore être généralisé ; il ne s'élargira qu'en ajoutant d'autres pays au corpus.
- 2 des 37 métas n'ont aucune géométrie, chacune avec un avertissement explicite et vérifié :
  - `gxrJ` : encart cartographique détecté mais aucun pixel rouge trouvé dans la silhouette.
  - `hZvJ` : aucun encart cartographique détectable.
- **Un piège de résolution des liens Maps, découvert tardivement.** 14 des liens de l'ancien domaine `goo.gl/maps` étaient mémorisés comme irrésolvables. La cause n'était ni un throttling ni des liens périmés : ils redirigent vers un visualiseur de panorama Street View qui place les coordonnées dans un paramètre `viewpoint=lat,lon` au lieu du format `/@lat,lon` attendu. Un motif de repli les récupère tous, ce qui a fait passer l'échantillon de justesse de 7 à 8 et rendu leur géométrie à deux métas ponctuelles. Enseignement à retenir pour les prochains pays : un échec de résolution en masse doit être diagnostiqué, jamais accepté comme une fatalité.
- **Titres dérivés, et non copiés.** Le titre est le texte en gras lorsqu'il ouvre le paragraphe, sinon la première phrase de la description. La règle initiale, qui prenait le gras où qu'il soit, produisait des titres inutilisables comme « side », « on top » ou « -owo ». Effet de bord bénéfique : les blocs sans aucun gras ne sont plus écartés, ce qui a récupéré deux métas légitimes sur la génération et la couleur de la voiture Google.
- Trois métas de tier `country` ou `regional` ont des dimensions d'image non standard, ce qui déclenche une détection d'encart aberrante ou absente sur ces images précises. Sans conséquence pratique : l'aiguillage par tier isole les métas `country` de la détection d'encart (elles reçoivent directement la silhouette du pays), donc ces dimensions atypiques n'affectent que des cas déjà couverts par un avertissement explicite plutôt que par une géométrie fausse silencieuse.
- **L'interface de revue n'horodate pas les décisions.** Le temps par méta, objectif chiffré de la spec (§6.1, « moins de 10 secondes »), n'est donc pas vérifiable — ni maintenant ni rétroactivement. C'est un manque d'instrumentation, pas un échec : à corriger avant la prochaine session de revue si l'objectif doit être tenu pour atteint.

## Décision sur l'éditeur de sommets

La spec (§6.1) reportait la construction de l'éditeur de sommets jusqu'à connaître le taux de validation sans retouche à la revue. Ce taux est maintenant mesuré : **73 %** (27/37).

Décision : **le report devient un abandon pour la v1.** Le motif est plus fort que le seul taux. Aucune des 10 décisions non-`validé` n'aurait été résolue par un éditeur de sommets :

- Les 6 `corrigé` sont toutes de tier `spot` — leur géométrie est un cercle autour d'un point Maps. La correction porte sur le **rayon**, réglable par un champ numérique déjà présent dans l'interface de revue. Un éditeur de sommets n'a rien à y faire.
- Les 4 `rejeté` sont toutes de tier `regional`. Deux (`gxrJ`, `hZvJ`) n'avaient aucune géométrie à éditer — il n'y avait littéralement pas de polygone. Les deux autres (`OH23`, `dcsB`) portent sur des métas dont la zone rouge n'exprimait pas une emprise exploitable.

Autrement dit : sur les 10 polygones vectorisés soumis à un jugement de forme (tier `regional` avec géométrie), 8 sont passés tels quels et 2 ont été rejetés en bloc — **zéro cas où retoucher des sommets aurait sauvé une méta**. Rouvrir la décision seulement si un pays futur produit des rejets de type « polygone presque bon, bord mal placé ».

## Pays problématiques et prochaine étape

- Aucun autre pays n'a encore été traité : la Pologne est la première et unique verticale complète du projet à ce stade, ce qui limite la portée de toute conclusion statistique (voir « Limites connues »).
- La revue humaine des 37 métas PL est faite (2026-07-29) et l'export par défaut produit **33 métas publiables** dans `viewer/data/` (les 4 rejetées sont exclues). La verticale Pologne est close.
- Prochaine étape recommandée : **ajouter un second pays**, pour élargir l'échantillon de justesse au-delà de 8 métas et éprouver l'aiguillage par tier sur un autre corpus d'images.
- Ajouter un second pays permettrait d'élargir l'échantillon de mesure de justesse au-delà des 8 métas actuelles et de tester l'aiguillage par tier sur un corpus d'images différent (autre style de carte source, autres dimensions d'encart).

## Note sur l'export du viewer

`cartometa-export` n'exporte par défaut que les métas de statut `validé` ou `corrigé` (comportement de la spec) : sur ce corpus, avant toute revue, cela produit un viewer vide (0 méta). Une option explicite `--include-auto`, désactivée par défaut, permet d'inclure aussi les métas `auto` pour faire fonctionner et vérifier le viewer avant la revue — elle a servi aux vérifications du Step 5 (35 métas géométrisées exportées, latence 0,2–3,6 ms). Quand elle est utilisée, l'outil affiche explicitement le nombre de métas non revues incluses, pour qu'une publication accidentelle de données non validées ne passe pas inaperçue. Les données livrées dans ce dépôt (`viewer/data/*.json`) correspondent au comportement par défaut, après revue : **33 métas** (37 revues moins 4 rejetées).
