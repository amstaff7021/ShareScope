@echo off
setlocal EnableExtensions EnableDelayedExpansion

cd /d "%~dp0"

git rev-parse --is-inside-work-tree >nul 2>&1
if errorlevel 1 (
  echo Ce dossier n'est pas un depot Git.
  pause
  exit /b 1
)

if exist ".git\rebase-merge" goto blocked
if exist ".git\rebase-apply" goto blocked
if exist ".git\MERGE_HEAD" goto blocked

set "COMMIT_MSG=%*"
if not defined COMMIT_MSG (
  for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format ''yyyy-MM-dd HH:mm:ss''"') do set "STAMP=%%i"
  set "COMMIT_MSG=Auto update !STAMP!"
)

echo [1/4] Ajout des changements...
git add -A
if errorlevel 1 goto error

echo [2/4] Verification des changements...
git diff --cached --quiet
if errorlevel 1 (
  echo [3/4] Commit...
  git commit -m "%COMMIT_MSG%"
  if errorlevel 1 goto error
) else (
  echo Aucun changement local a commit.
)

echo [4/4] Synchronisation avec GitHub...
git pull --rebase origin main
if errorlevel 1 goto error

git push origin main
if errorlevel 1 goto error

echo.
echo Push termine avec succes.
pause
exit /b 0

:blocked
echo Un rebase ou un merge est encore en cours.
echo Termine-le avant d'utiliser ce script.
pause
exit /b 1

:error
echo.
echo Echec pendant le push automatique.
pause
exit /b 1
