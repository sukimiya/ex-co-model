# Build ExCoModel (Windows). Run from repo root. Requires: py -3.14, PowerShell 5.1+.
# NOTE: written for the Windows build machine; not yet executed/tested there.
$ErrorActionPreference = "Stop"

$BlenderVersion = "5.2.1"
$BlenderZip = "blender-$BlenderVersion-windows-x64.zip"
$BlenderUrl = "https://download.blender.org/release/Blender5.2/$BlenderZip"
$Build = ".build-app"
$Venv = "$Build\venv"

if (Test-Path $Build) { Remove-Item -Recurse -Force $Build }
if (Test-Path "dist\ExCoModel") { Remove-Item -Recurse -Force "dist\ExCoModel" }
New-Item -ItemType Directory -Force -Path $Build | Out-Null

# 1. build venv with app deps
py -3.14 -m venv $Venv
& "$Venv\Scripts\pip.exe" install --quiet .\kernel .\orchestrator -r app\requirements-app.txt

# 2. fetch portable Blender
if (-not (Test-Path "$Build\$BlenderZip")) {
    Invoke-WebRequest -Uri $BlenderUrl -OutFile "$Build\$BlenderZip"
}
Expand-Archive "$Build\$BlenderZip" -DestinationPath "$Build\blender"

# 3. pyinstaller onedir bundle
& "$Venv\Scripts\pyinstaller.exe" --noconfirm --clean --onedir --windowed `
    --name ExCoModel `
    --add-data "orchestrator/orchestrator/static;orchestrator/static" `
    app/main.py

# 4. drop Blender where find_blender() looks: dist\ExCoModel\blender\blender.exe
Copy-Item -Recurse "$Build\blender\blender-$BlenderVersion-windows-x64" "dist\ExCoModel\blender"

# 5. third-party notices
Copy-Item app\THIRD_PARTY_NOTICES.md dist\ExCoModel\
# Blender <= 4.x ships LICENSE.txt at the root; 5.x ships text\license\license.md
$BlenderLicense = "dist\ExCoModel\blender\LICENSE.txt"
if (-not (Test-Path $BlenderLicense)) {
    $BlenderLicense = "dist\ExCoModel\blender\text\license\license.md"
}
if (Test-Path $BlenderLicense) {
    Copy-Item $BlenderLicense dist\ExCoModel\BLENDER-LICENSE.txt
}

Write-Host "built: dist\ExCoModel"
