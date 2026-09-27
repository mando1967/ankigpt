@echo off
setlocal EnableExtensions EnableDelayedExpansion

cd /d "%~dp0"

set "GITHUB_REPOSITORY=%~1"
if not defined GITHUB_REPOSITORY set "GITHUB_REPOSITORY=mando1967/ankigpt"

where gh >nul 2>nul
if errorlevel 1 (
    echo Error: GitHub CLI ^(gh^) is not installed or is not on PATH.
    echo Install it from https://cli.github.com/ and run: gh auth login
    exit /b 1
)

gh auth status >nul 2>nul
if errorlevel 1 (
    echo Error: GitHub CLI is not authenticated.
    echo Run: gh auth login
    exit /b 1
)

where curl.exe >nul 2>nul
if errorlevel 1 (
    echo Error: curl.exe is not installed or is not on PATH.
    exit /b 1
)

if not exist ".version" (
    echo Error: .version was not found.
    exit /b 1
)
set /p ANKIGPT_RELEASE_VERSION=<.version
set "LATEST_MSI=%CD%\release\anki-!ANKIGPT_RELEASE_VERSION!-win-x64.msi"
set "RELEASE_TAG=ankigpt-v!ANKIGPT_RELEASE_VERSION!"
if not exist "!LATEST_MSI!" (
    echo Error: No installer matching .version was found: !LATEST_MSI!
    echo Run build-windows-installer.bat upload=0 first.
    exit /b 1
)
for %%F in ("%LATEST_MSI%") do echo Selected MSI: %%~nxF ^(%%~zF bytes^)

echo Uploading %LATEST_MSI% to release %RELEASE_TAG% in %GITHUB_REPOSITORY%...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0upload-release-asset.ps1"

if errorlevel 1 (
    echo Error: GitHub release upload failed.
    exit /b 1
)

echo.
echo Upload complete:
gh release view "%RELEASE_TAG%" --repo "%GITHUB_REPOSITORY%" --json url --jq ".url"

endlocal
