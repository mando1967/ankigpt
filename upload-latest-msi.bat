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

set "LATEST_MSI="
for /f "delims=" %%F in ('dir /b /a-d /o-d "release\*.msi" 2^>nul') do if not defined LATEST_MSI set "LATEST_MSI=%CD%\release\%%F"

if not defined LATEST_MSI (
    echo Error: No MSI was found in release.
    echo Run build-windows-installer.bat upload=0 first.
    exit /b 1
)

set "RELEASE_TAG="
for /f "delims=" %%T in ('gh release view --repo "%GITHUB_REPOSITORY%" --json tagName --jq ".tagName" 2^>nul') do set "RELEASE_TAG=%%T"

if not defined RELEASE_TAG (
    if not exist ".version" (
        echo Error: No GitHub release exists and .version was not found.
        exit /b 1
    )
    set /p ANKIGPT_RELEASE_VERSION=<.version
    if not defined ANKIGPT_RELEASE_VERSION (
        echo Error: .version is empty.
        exit /b 1
    )
    set "RELEASE_TAG=v!ANKIGPT_RELEASE_VERSION!"
    echo No existing release found. Creating !RELEASE_TAG! in %GITHUB_REPOSITORY%...
    gh release create "!RELEASE_TAG!" "%LATEST_MSI%" --repo "%GITHUB_REPOSITORY%" --title "AnkiGPT !ANKIGPT_RELEASE_VERSION!" --generate-notes
) else (
    echo Uploading %LATEST_MSI% to release %RELEASE_TAG% in %GITHUB_REPOSITORY%...
    gh release upload "%RELEASE_TAG%" "%LATEST_MSI%" --repo "%GITHUB_REPOSITORY%" --clobber
)

if errorlevel 1 (
    echo Error: GitHub release upload failed.
    exit /b 1
)

echo.
echo Upload complete:
gh release view "%RELEASE_TAG%" --repo "%GITHUB_REPOSITORY%" --json url --jq ".url"

endlocal
