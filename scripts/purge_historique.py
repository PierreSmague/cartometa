# Purge l'historique git : viewer/data/ partout, et les revisions de
# data/geo/ anterieures a la recompaction (commit 1fee70c), qui pesaient
# 4x leur poids utile en pretty-print.
#
# Le contenu de HEAD est strictement inchange (verifie par l'empreinte
# d'arbre apres coup) : seules les vieilles versions disparaissent. Les
# commits qui ne touchaient QUE data/geo deviennent vides et sont elagues.
#
# Sauvegarde prealable : bundle cree dans le scratchpad de la session, et
# origin porte encore l'ancien historique jusqu'au push force.
#
# Usage :  .venv\Scripts\python.exe scripts\purge_historique.py
import git_filter_repo as fr

# Le commit de recompaction : seul commit dont les data/geo sont conserves.
GARDE_GEO = {b"1fee70cc1c42d7efec6649a1d1a9e854c639848f"}

# Empreinte de l'arbre de HEAD avant purge — le contenu final doit etre
# bit-a-bit identique.
ARBRE_ATTENDU = "aeb6eeac29ed9bb13330ffd07340bb40d8296133"


def nettoyer(commit, metadata):
    def garder(change):
        if change.filename.startswith(b"viewer/data/"):
            return False
        if change.filename.startswith(b"data/geo/") and commit.original_id not in GARDE_GEO:
            return False
        return True

    commit.file_changes = [c for c in commit.file_changes if garder(c)]


args = fr.FilteringOptions.parse_args(["--force"])
fr.RepoFilter(args, commit_callback=nettoyer).run()

import subprocess

arbre = subprocess.run(
    ["git", "rev-parse", "HEAD^{tree}"], capture_output=True, text=True
).stdout.strip()
if arbre == ARBRE_ATTENDU:
    print(f"\nOK : l'arbre de HEAD est inchange ({arbre})")
else:
    print(f"\nATTENTION : arbre de HEAD {arbre} != attendu {ARBRE_ATTENDU}")
    print("Ne pas pousser — restaurer depuis le bundle de sauvegarde.")
