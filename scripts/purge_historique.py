# Purge l'historique git : viewer/data/ partout, et toutes les revisions de
# data/geo/ dont le contenu n'est pas celui de HEAD. Contrairement a la
# premiere purge (calee sur le seul commit de recompaction 1fee70c), le critere
# est le BLOB et non le commit : l'etat courant est reparti sur plusieurs
# commits (migration d'elagage, tracages, merges de PR), et un commit de merge
# reintroduit les fichiers par rapport a son premier parent — garder le meme
# blob final a plusieurs endroits ne coute rien, git le stocke une seule fois.
#
# Le contenu de HEAD est strictement inchange (verifie par l'empreinte d'arbre
# capturee AVANT filtrage) : seules les vieilles versions disparaissent — dont
# les 108 Mo compacts gardes par la purge precedente, perimes depuis l'elagage.
# Les commits qui ne touchaient QUE data/geo deviennent vides et sont elagues.
#
# Sauvegarde prealable : bundle --all cree hors du depot, et origin porte
# encore l'ancien historique jusqu'au push force.
#
# Usage :  .venv\Scripts\python.exe scripts\purge_historique.py
import subprocess

import git_filter_repo as fr


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True).stdout


# Pour chaque fichier de data/geo, le blob de sa version courante : la seule
# revision a garder, ou qu'elle apparaisse. Tout chemin disparu de HEAD n'a
# pas d'entree et se purge donc entierement.
BLOBS_FINAUX: dict[bytes, bytes] = {}
for ligne in _git("ls-tree", "-r", "HEAD", "data/geo").splitlines():
    meta, chemin = ligne.split("\t", 1)
    BLOBS_FINAUX[chemin.encode()] = meta.split()[2].encode()

# Empreinte de l'arbre de HEAD avant purge — le contenu final doit etre
# bit-a-bit identique.
ARBRE_ATTENDU = _git("rev-parse", "HEAD^{tree}").strip()


def nettoyer(commit, metadata):
    def garder(change):
        if change.filename.startswith(b"viewer/data/"):
            return False
        if change.filename.startswith(b"data/geo/"):
            # Suppressions (pas de blob) : jamais utiles, les ajouts qui les
            # precedaient sont eux-memes purges.
            return getattr(change, "blob_id", None) == BLOBS_FINAUX.get(change.filename)
        return True

    commit.file_changes = [c for c in commit.file_changes if garder(c)]


args = fr.FilteringOptions.parse_args(["--force"])
fr.RepoFilter(args, commit_callback=nettoyer).run()

arbre = _git("rev-parse", "HEAD^{tree}").strip()
if arbre == ARBRE_ATTENDU:
    print(f"\nOK : l'arbre de HEAD est inchange ({arbre})")
else:
    print(f"\nATTENTION : arbre de HEAD {arbre} != attendu {ARBRE_ATTENDU}")
    print("Ne pas pousser — restaurer depuis le bundle de sauvegarde.")
