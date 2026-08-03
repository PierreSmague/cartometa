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

**Personne n'a le droit d'écrire sur ce dépôt à part le mainteneur.** On
contribue en poussant sur son propre fork, jamais sur le dépôt d'origine :
un `git push origin` sera refusé (`403`).

1. **Forke** le dépôt, puis déclare ton fork dans ton clone :
   ```
   gh repo fork PierreSmague/cartometa --clone=false
   git remote add fork https://github.com/<ton-compte>/cartometa.git
   ```
2. `uv sync`
3. `uv run cartometa-review <CC>` — saisis tes métas (`N`) et trace leurs
   emprises. Aucune donnée préalable n'est nécessaire : un pays vide est un
   point de départ valide.
4. Pousse **sur ton fork**, puis ouvre la pull request :
   ```
   git switch -c metas-<cc>
   git add data/manual/<CC> data/geo/<CC>.geojson
   git commit -m "feat: metas manuelles pour <pays>"
   git push -u fork metas-<cc>
   gh pr create --repo PierreSmague/cartometa
   ```

Pour reprendre les textes Plonk It d'un pays entier plutôt que de saisir à la
main, `uv run cartometa-extract <pays>` les importe depuis une page
sauvegardée à la main — voir le README. **Ne jamais écrire de crawler pour
plonkit.net.**

Le guide détaillé, de l'installation à la pull request, est dans
[`docs/ajouter-une-meta-a-la-main.md`](docs/ajouter-une-meta-a-la-main.md).

La publication du site est faite séparément par le mainteneur : lui seul
possède les images sources, donc lui seul peut construire le site complet.
