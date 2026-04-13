Param(
  [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (Test-Path "build/package") { Remove-Item "build/package" -Recurse -Force }
New-Item -ItemType Directory -Path "build/package" -Force | Out-Null

& $Python -m pip install --upgrade pip
& $Python -m pip install --target build/package -r app/requirements.txt
Copy-Item app/src/lambda_function.py build/package/

if (Test-Path "build/lambda.zip") { Remove-Item "build/lambda.zip" -Force }
Compress-Archive -Path build/package/* -DestinationPath build/lambda.zip
Write-Host "Created build/lambda.zip"
