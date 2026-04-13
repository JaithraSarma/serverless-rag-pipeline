$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location "$root/infra"

terraform init
terraform apply -auto-approve
