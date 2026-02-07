@echo off
setlocal EnableDelayedExpansion

:: ==========================================================
:: pull_all_apks.bat
:: Pulls ALL app APKs from device (system + user-installed)
:: Then extract_app_labels.ps1 reads them to get real names
:: ==========================================================

:: Output paths — update PROJDIR to your project root
set "PROJDIR=C:\Users\chira\OneDrive\Desktop\tablet_voice_agent_v1"
set "OUTDIR=%PROJDIR%\apks_all"
set "LIST=%PROJDIR%\packages_all.txt"

if not exist "%OUTDIR%" mkdir "%OUTDIR%"

echo ============================================
echo  Pulling ALL app packages from device
echo  (system + user-installed)
echo ============================================
echo.

echo Creating full package list...
echo (This file will show what Android returned) > "%LIST%"

:: ALL packages (no -3 flag = everything)
adb shell cmd package list packages -f 1>>"%LIST%" 2>>&1

:: If that produced nothing useful, fallback to pm
findstr /i "package:" "%LIST%" >nul
if errorlevel 1 (
  echo --- cmd package returned nothing, trying pm --- >> "%LIST%"
  adb shell pm list packages -f 1>>"%LIST%" 2>>&1
)

:: Count packages
set /a COUNT=0
for /f "usebackq" %%L in (`findstr /c:"package:" "%LIST%"`) do set /a COUNT+=1
echo Found %COUNT% packages.
echo.

echo Pulling APKs into: %OUTDIR%
echo This may take a while for first run...
echo.

set /a PULLED=0
set /a SKIPPED=0
set /a FAILED=0

for /f "usebackq delims=" %%L in ("%LIST%") do (
  echo %%L | findstr /b /c:"package:" >nul
  if not errorlevel 1 (
    for /f "tokens=1,2 delims==" %%A in ("%%L") do (
      set "APKPATH=%%A"
      set "PKG=%%B"
    )
    set "APKPATH=!APKPATH:package:=!"

    :: Skip if already pulled
    if exist "%OUTDIR%\!PKG!.apk" (
      set /a SKIPPED+=1
    ) else (
      echo Pulling: !PKG!
      adb pull "!APKPATH!" "%OUTDIR%\!PKG!.apk" >nul 2>&1
      if errorlevel 1 (
        echo   FAILED: !PKG!
        set /a FAILED+=1
      ) else (
        set /a PULLED+=1
      )
    )
  )
)

echo.
echo ============================================
echo  Done!
echo  Pulled:  %PULLED% new APKs
echo  Skipped: %SKIPPED% (already exist)
echo  Failed:  %FAILED%
echo ============================================
echo.
echo Next step: Run extract_app_labels.ps1
echo.
endlocal
