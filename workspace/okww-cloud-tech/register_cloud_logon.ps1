param([switch]$Enable)
$ErrorActionPreference = 'Stop'
$sourceRoot = $PSScriptRoot
$sessionDir = Join-Path (Split-Path $sourceRoot -Parent) 'okww-cloud-session\background'
$settings = Get-Content -LiteralPath (Join-Path $sessionDir 'autorun-config.json') -Raw | ConvertFrom-Json
$pythonPath = $settings.python
$windowlessPython = Join-Path (Split-Path $pythonPath -Parent) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $windowlessPython)) {
    throw 'pythonw.exe is required for a windowless login trigger.'
}
$entryPath = Join-Path $sourceRoot 'main_cloud_autodaily.py'
if ($Enable) {
    & $pythonPath $entryPath --dry-run
    if ($LASTEXITCODE -ne 0) { throw 'Startup validation failed; task was not enabled.' }
}
$action = New-ScheduledTaskAction -Execute $windowlessPython -Argument ('"{0}"' -f $entryPath) -WorkingDirectory $sourceRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name)
$trigger.Delay = 'PT2M'
$principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$options = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -RunOnlyIfNetworkAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -Hidden
$definition = New-ScheduledTask -Action $action -Trigger $trigger -Principal $principal -Settings $options
# Register disabled atomically: never briefly enable an unvalidated revision.
$definition.Settings.Enabled = [bool]$Enable
Register-ScheduledTask -TaskName 'OKWW-Cloud-Daily-AtLogon' -InputObject $definition -Force | Out-Null
Write-Output ('Registered. Enabled={0}. No game launched.' -f [bool]$Enable)
