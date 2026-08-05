@echo off
REM Resumes the Cartometa plan implementation where it left off.
REM Triggered once by the Cartometa-Resume scheduled task.
cd /d "C:\Users\Smaguy\Documents\Scripts\Cartometa"
if not exist logs mkdir logs
set LOGFILE=logs\resume-%DATE:~-4%%DATE:~3,2%%DATE:~0,2%.log

"C:\Users\Smaguy\.local\bin\claude.exe" --permission-mode acceptEdits -p "Reprends l'implementation du plan docs/superpowers/plans/2026-07-28-cartometa-verticale-pologne.md. Lis d'abord le plan en entier, puis `git log --oneline` pour voir ce qui est deja fait. Les taches terminees ont leurs cases cochees dans le plan et un commit associe. Reprends a la premiere tache non terminee et continue en TDD, en cochant les cases au fur et a mesure et en commitant apres chaque tache. Ne recommence pas les taches deja committees. Si une commande echoue, diagnostique avant de contourner : ne desactive jamais un test pour le faire passer. Si tout le plan est termine, verifie que `uv run pytest -v` passe et arrete-toi." >> "%LOGFILE%" 2>&1

echo Termine le %DATE% a %TIME% >> "%LOGFILE%"
