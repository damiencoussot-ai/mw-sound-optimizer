# Construit dist\MW_Sound_Optimizer.exe (un seul fichier, sans console).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue

python -m PyInstaller `
    --onefile --noconsole `
    --name MW_Sound_Optimizer `
    --icon "$PSScriptRoot\assets\icon.ico" `
    --add-data "$PSScriptRoot\assets\icon64.png;." `
    --collect-data soundcard `
    --hidden-import _cffi_backend `
    --distpath dist --workpath build --specpath build `
    -y src\mw_sound_optimizer.py

if (-not (Test-Path dist\MW_Sound_Optimizer.exe)) { throw "Build echoue." }
Get-FileHash dist\MW_Sound_Optimizer.exe -Algorithm SHA256 |
    ForEach-Object { "$($_.Hash.ToLower())  MW_Sound_Optimizer.exe" } |
    Set-Content dist\MW_Sound_Optimizer.exe.sha256 -Encoding ascii
Write-Host "OK : dist\MW_Sound_Optimizer.exe"
