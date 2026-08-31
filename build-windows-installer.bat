@echo off
setlocal EnableExtensions EnableDelayedExpansion

cd /d "%~dp0"

set "UPLOAD=0"
set "GITHUB_REPOSITORY=%~2"
if not defined GITHUB_REPOSITORY set "GITHUB_REPOSITORY=mando1967/ankigpt"

if not "%~1"=="" (
    if /i "%~1"=="upload=0" set "UPLOAD=0"
    if /i "%~1"=="upload=1" set "UPLOAD=1"
    if /i not "%~1"=="upload=0" if /i not "%~1"=="upload=1" (
        echo Error: First argument must be upload=0 or upload=1.
        exit /b 2
    )
)

if not "!UPLOAD!"=="0" if not "!UPLOAD!"=="1" (
    echo Error: upload must be set to 0 or 1.
    echo Usage: build-windows-installer.bat upload=0^|1 [owner/repository]
    exit /b 2
)

if not exist ".version" (
    echo Error: .version was not found in %CD%.
    exit /b 1
)

set /p ANKIGPT_INSTALLER_VERSION=<.version
if not defined ANKIGPT_INSTALLER_VERSION (
    echo Error: .version is empty.
    exit /b 1
)

echo Building AnkiGPT %ANKIGPT_INSTALLER_VERSION% for Windows...
call tools\ninja installer:build
if errorlevel 1 exit /b %errorlevel%

echo Packaging MSI installer...
call out\pyenv\Scripts\python.exe qt\tools\build_installer.py --version %ANKIGPT_INSTALLER_VERSION% package
if errorlevel 1 exit /b %errorlevel%

set "BUILT_MSI="
for /f "delims=" %%F in ('dir /b /a-d /o-d "out\installer\dist\*.msi" 2^>nul') do if not defined BUILT_MSI set "BUILT_MSI=%%F"
if not defined BUILT_MSI (
    echo Error: Packaging completed, but no MSI was found in out\installer\dist.
    exit /b 1
)

if not exist "release" mkdir "release"
if errorlevel 1 exit /b %errorlevel%

echo Moving !BUILT_MSI! to the release directory...
move /Y "out\installer\dist\!BUILT_MSI!" "release\!BUILT_MSI!" >nul
if errorlevel 1 (
    echo Error: Could not move the MSI to %CD%\release.
    exit /b 1
)

echo.
echo Installer ready:
echo %CD%\release\!BUILT_MSI!

if "!UPLOAD!"=="1" (
    echo.
    echo Upload requested. Publishing the MSI to GitHub...
    call upload-latest-msi.bat "!GITHUB_REPOSITORY!"
    if errorlevel 1 exit /b !errorlevel!
) else (
    echo Upload skipped ^(upload=0^).
)

endlocal
