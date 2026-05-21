# =============================================================
#  WINDOWS ONLY — autostart wrapper for cube-overlay-win-html.pyw.
#  PowerShell variant of cube-overlay-win-html.cmd.
#
#  Drop into Win+R -> shell:startup as either:
#    - the .ps1 itself (requires ExecutionPolicy != Restricted), or
#    - a .lnk shortcut to:
#        powershell.exe -ExecutionPolicy Bypass -WindowStyle Hidden
#                       -File "<path>\cube-overlay-win-html.ps1"
# =============================================================
#
# Requires: py -m pip install --user pywebview
#
# CUBE_OVERLAY_UNC_HTML override: set this env var to point at a
# non-default WSL distro/user path. Default assumes Ubuntu + Linux
# user == Windows user.

# Boot WSL distro if not already up (UNC access to \\wsl.localhost\
# needs a running WSL).
wsl.exe --exec true *> $null

# Resolve pythonw.exe dynamically via the py-launcher (works across
# Store / python.org / Python Install Manager).
# Pinned to 3.13 — pywebview's pythonnet dep has no wheels for 3.14 yet.
# Bump after pythonnet ships 3.14 wheels (or set $env:CUBE_OVERLAY_PY).
if (-not $env:CUBE_OVERLAY_PY) { $env:CUBE_OVERLAY_PY = "-3.13" }
$pyw = & py $env:CUBE_OVERLAY_PY -c "import sys, os; print(os.path.join(os.path.dirname(sys.executable), 'pythonw.exe'))"

# UNC path override, otherwise default to Ubuntu + matching username.
if (-not $env:CUBE_OVERLAY_UNC_HTML) {
    $env:CUBE_OVERLAY_UNC_HTML =
        "\\wsl.localhost\Ubuntu\home\$env:USERNAME\projects\cube\bin\win\cube-overlay-win-html.pyw"
}

# Start-Process detaches cleanly; pythonw.exe is GUI-subsystem so no
# console window stays attached.
Start-Process -FilePath $pyw -ArgumentList "`"$env:CUBE_OVERLAY_UNC_HTML`""
