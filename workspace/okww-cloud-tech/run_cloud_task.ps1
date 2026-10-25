param(
    [Parameter(Mandatory=$true)]
    [ValidateSet('daily','nightmare','echo','tacet','forgery','simulation')]
    [string]$Task
)
$ErrorActionPreference = 'Stop'
$sessionDir = Join-Path (Split-Path $PSScriptRoot -Parent) 'okww-cloud-session\background'
$settings = Get-Content -LiteralPath (Join-Path $sessionDir 'autorun-config.json') -Raw | ConvertFrom-Json
$entryPath = Join-Path $PSScriptRoot 'main_cloud_autodaily.py'
# Same lock, validation, solvent policy and failure notification as daily.
Start-Process -FilePath $settings.python -ArgumentList @(('"{0}"' -f $entryPath),'--task',$Task) -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
