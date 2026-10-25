$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$state = Join-Path (Split-Path $root -Parent) 'okww-cloud-session\background'
$configuration = Get-Content -Raw -LiteralPath (Join-Path $state 'autorun-config.json') | ConvertFrom-Json
& $configuration.python (Join-Path $root 'main_cloud_autodaily.py') --dry-run
if ($LASTEXITCODE -ne 0) { throw '后台验证或运行环境检查未通过，自启未安装。' }
$pythonWindowless = Join-Path (Split-Path $configuration.python -Parent) 'pythonw.exe'
if (!(Test-Path -LiteralPath $pythonWindowless)) { throw '没有找到无窗口 Python 入口。' }
$taskName = 'OKWW-Cloud-Daily-AtLogon'
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) { throw '同名任务已存在，请先核对现有任务。' }
$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute $pythonWindowless -Argument ('"' + (Join-Path $root 'main_cloud_autodaily.py') + '"') -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$trigger.Delay = 'PT2M'
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 25) -StartWhenAvailable -RunOnlyIfNetworkAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description '登录后延迟两分钟，无窗口执行云鸣潮每日；按 UTC+8 04:00 游戏日只尝试一次。异常停止，不自动重复消耗。' | Select-Object TaskName,State
