param([ValidateSet('help','login','daily')][string]$Mode='help')
$ErrorActionPreference='Stop'
$taskRoot=Join-Path $PSScriptRoot 'workspace/okww-cloud-tech'
$runtimeRoot=Join-Path $PSScriptRoot 'workspace/okww-cloud-runtime-v367'
$taskPython=Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if(-not (Test-Path -LiteralPath $taskPython)){throw 'Create the Python 3.12 .venv and install requirements-windows.txt first.'}
$env:OKWW_INSTALLED_RUNTIME=$runtimeRoot
$env:PYTHONPATH="$taskRoot;$runtimeRoot"
if($Mode -eq 'help'){& $taskPython (Join-Path $taskRoot 'main_cloud_daily.py') --help}
elseif($Mode -eq 'login'){& $taskPython (Join-Path $taskRoot 'main_cloud_background.py') login --seconds 600 --keep-open}
else{& $taskPython (Join-Path $taskRoot 'main_cloud_daily.py') --connect --background --allow-game-tasks --once-daily}
exit $LASTEXITCODE
