@echo off
REM =============================================================
REM  WINDOWS ONLY — autostart wrapper for cube-overlay-win.pyw.
REM  Not meant to run inside WSL. Run it from a Windows shell or
REM  drop it into the Windows Startup folder:
REM    Win+R -> shell:startup -> paste this file
REM    (target: %APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\)
REM =============================================================
REM
REM Resolves pythonw.exe dynamically via the py-launcher so the file works
REM across Python install layouts (Store, python.org installer, Python
REM Install Manager / pythoncore). Survives Python minor upgrades.
REM
REM CUBE_OVERLAY_UNC override: set this env var to point at a non-default
REM WSL distro/user path. Default assumes Ubuntu + Linux user == Windows user.

wsl.exe --exec true >nul 2>&1

for /f "delims=" %%P in ('py -c "import sys,os; print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))"') do set PYW=%%P

if "%CUBE_OVERLAY_UNC%"=="" set CUBE_OVERLAY_UNC=\\wsl.localhost\Ubuntu\home\%USERNAME%\projects\cube\bin\win\cube-overlay-win.pyw

start "" "%PYW%" "%CUBE_OVERLAY_UNC%"
