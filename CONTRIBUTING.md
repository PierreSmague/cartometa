# Contribuer à Cartometa

Les contributions portent sur les métas et le tracé de leurs emprises. Nul
besoin d'être développeur : le travail se fait à la souris, dans une
interface locale.

## Licence des contributions

En proposant une contribution, tu acceptes qu'elle soit publiée sous
**CC BY-NC-SA 4.0**, comme le reste des données du projet. C'est une
obligation de la licence de la source, pas un choix : Plonk It publie sous
partage à l'identique.

Le code, lui, reste sous licence MIT.

## Demander l'accès — première étape

Ce dépôt n'attend pas de toi que tu saches ce qu'est un *fork*. On te donne
directement le droit de travailler dessus.

**[Ouvre une issue](https://github.com/PierreSmague/cartometa/issues/new)**
en indiquant ton identifiant GitHub et le ou les pays qui t'intéressent.
Tu recevras une invitation par courriel : accepte-la, et tu pourras créer
des branches sur le dépôt.

Ce que cet accès te permet, et ce qu'il ne permet pas :

| | |
|---|---|
| Créer une branche et y pousser | oui |
| Ouvrir une pull request | oui |
| Pousser directement sur `master` | **non**, jamais |
| Fusionner ta propre pull request | **non** — seul le mainteneur approuve |

Rien de ce que tu fais sur ta branche ne peut abîmer le site en ligne ni le
travail des autres. C'est le but de ce découpage : tu peux te tromper sans
conséquence.

## Circuit

1. **Installe** — il faut git, Python ≥ 3.14 et [uv](https://docs.astral.sh/uv/) :
   ```
   git clone https://github.com/PierreSmague/cartometa.git
   cd cartometa
   uv sync
   ```

2. **Saisis et trace** — `uv run cartometa-review <CC>` (`FR`, `BE`, `JP`…)
   puis <http://127.0.0.1:8765>. `N` crée une méta, les touches `D` `C` `S`
   `E` `F` tracent son emprise, `A` l'enregistre. Aucune donnée préalable
   n'est nécessaire : un pays vide est un point de départ valide.

3. **Vérifie** — `uv run cartometa-build <CC>` puis
   `python -m http.server 8010 --directory dist`. **Le code du pays est
   obligatoire** : sans lui, la commande s'arrête sur le premier pays dont
   tu n'as pas les textes, et c'est normal.

4. **Propose** :
   ```
   git switch -c metas-<cc>
   git add data/manual/<CC> data/geo/<CC>.geojson
   git commit -m "feat: metas manuelles pour <pays>"
   git push -u origin metas-<cc>
   ```
   `git push` affiche une URL qui ouvre la pull request. Le mainteneur relit
   et fusionne.

Un commit ne doit contenir **que** `data/manual/**` et `data/geo/*.geojson`.
Si `git status` montre autre chose, quelque chose ne va pas.

Le guide détaillé, de l'installation à la pull request, avec toutes les
touches de tracé et les pannes courantes, est dans
[`docs/ajouter-une-meta-a-la-main.md`](docs/ajouter-une-meta-a-la-main.md).

## Deux règles absolues

**Ne jamais écrire de crawler pour plonkit.net.** Leur `robots.txt` interdit
tout accès automatisé et Cloudflare répond 403. Les pages sources se
capturent à la main, une par une, avec `Ctrl+S`.

**Ne verse aucune image dont tu n'as pas le droit de disposer.** Une capture
Street View que tu as prise toi-même, oui. Une image récupérée ailleurs sans
licence compatible, non.

## Publication

La mise en ligne est faite séparément par le mainteneur : lui seul possède
les images sources de l'ensemble du jeu, donc lui seul peut construire le
site complet.
