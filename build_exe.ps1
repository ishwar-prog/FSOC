# Builds dist\FSOC_Beacon_Tracker.exe (single file, no Python needed on the target PC).
#   powershell -ExecutionPolicy Bypass -File build_exe.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
python -m pip install -r requirements.txt
python benchmark.py --duration 20
python -m PyInstaller --noconfirm --clean FSOC_Beacon_Tracker.spec
Get-Item dist\FSOC_Beacon_Tracker.exe | Select-Object Name, @{n="Size (MB)"; e={[math]::Round($_.Length / 1MB, 1)}}, LastWriteTime
