# Contribuer à Cartometa

Les contributions portent aujourd'hui sur le tracé des emprises. Le circuit
est celui de la pull request : installe l'outil, trace, propose.

## Licence des contributions

En proposant une contribution, tu acceptes qu'elle soit publiée sous
**CC BY-NC-SA 4.0**, comme le reste des données du projet. C'est une
obligation de la licence de la source, pas un choix : Plonk It publie sous
partage à l'identique.

Le code, lui, reste sous licence MIT.

## Circuit

1. `uv sync`
2. `uv run cartometa-extract <pays>` — la page source se capture à la main,
   voir le README. **Ne jamais écrire de crawler pour plonkit.net.**
3. `uv run cartometa-review <CC>` — trace les emprises.
4. Propose une pull request avec le `data/geo/<CC>.geojson` modifié.

La publication du site est faite séparément par le mainteneur.
