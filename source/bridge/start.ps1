param([Parameter(ValueFromRemainingArguments=$true)][string[]]$BridgeArguments)
$ErrorActionPreference = 'Stop'
$BridgePython = Get-Command python -ErrorAction SilentlyContinue
if (-not $BridgePython) { throw 'Install Python 3.10 or later, then reopen this terminal.' }
& $BridgePython.Source (Join-Path $PSScriptRoot 'launch.py') @BridgeArguments
exit $LASTEXITCODE
