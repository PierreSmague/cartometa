# Prototype carmeta — matériel de référence

Code jetable écrit pendant la conception (2026-11-18). **Ce n'est pas du code
produit** : pas de tests, pas de gestion d'erreurs, chemins passés à la main.
Il est conservé parce que c'est lui qui a produit les chiffres et les cartes
validés par le mainteneur ; la spec `../2026-11-18-carmeta-sync-design.md` s'y
réfère pour lever toute ambiguïté sur les algorithmes.

| Fichier | Rôle |
|---|---|
| `zones.py` | Par (fichier, pays, tag) : familles, tags parents, zones chaînées, gain régional. |
| `verdict2.py` | Choix du fichier source par (pays, famille) et verdict par tag. |
| `expected-verdicts.json` | Résultat sur le repo carmeta au commit du 2026-11-15 : 965 tags candidats. |
| `file_dates.json` | Date du dernier commit de chaque fichier carmeta à cette date. |
| `page_template.html` | Gabarit de la page d'exemples (cartes par tag) ; modèle pour le rapport. |

Lancement d'origine, depuis la racine du dépôt, avec un clone de carmeta :

```
.venv/bin/python -I zones.py data/cache/ne_10m_admin_0_countries.geojson <sortie>/ <fichiers carmeta…>
python3 -I verdict2.py <sortie>/ file_dates.json page_data.json -v
```
