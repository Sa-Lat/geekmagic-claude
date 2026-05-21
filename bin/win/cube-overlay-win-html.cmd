@echo off
REM =============================================================
REM  WINDOWS ONLY — autostart wrapper for cube-overlay-win-html.pyw.
REM  Drop into Win+R -> shell:startup
REM    (%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\)
REM =============================================================
REM
REM HTML/pywebview variant. Requires:
REM   py -m pip install --user pywebview
REM
REM Resolves pythonw.exe dynamically via py-launcher (works across Store /
REM python.org / pythoncore installs).
REM
REM CUBE_OVERLAY_UNC_HTML override: point at a non-default WSL distro/user
REM path. Default assumes Ubuntu + Linux user == Windows user.

wsl.exe --exec true >nul 2>&1

REM Pinned to 3.13 — pywebview's pythonnet dep has no wheels for 3.14 yet.
REM Bump after pythonnet ships 3.14 wheels (or set CUBE_OVERLAY_PY to override).
if "%CUBE_OVERLAY_PY%"=="" set CUBE_OVERLAY_PY=-3.13
for /f "delims=" %%P in ('py %CUBE_OVERLAY_PY% -c "import sys,os; print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))"') do set PYW=%%P

if "%CUBE_OVERLAY_UNC_HTML%"=="" set CUBE_OVERLAY_UNC_HTML=\\wsl.localhost\Ubuntu\home\%USERNAME%\projects\cube\bin\win\cube-overlay-win-html.pyw

start "" "%PYW%" "%CUBE_OVERLAY_UNC_HTML%"
