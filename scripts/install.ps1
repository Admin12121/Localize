[CmdletBinding()]
param(
    [string] $Python = '3.12',
    [switch] $NoModifyPath
)
$ErrorActionPreference = 'Stop'
$release = 'https://github.com/Admin12121/Localize/releases/download/v3.2.3'
$wheel = 'localizeit-3.2.3-py3-none-any.whl'

function Find-LocalizeUv {
    $command = Get-Command uv -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    foreach ($directory in @($env:UV_UNMANAGED_INSTALL, $env:CARGO_DIST_FORCE_INSTALL_DIR, $env:UV_INSTALL_DIR, (Join-Path $HOME '.local\bin'))) {
        if ($directory -and (Test-Path -LiteralPath (Join-Path $directory 'uv.exe'))) {
            return (Join-Path $directory 'uv.exe')
        }
    }
    return $null
}

$uv = Find-LocalizeUv
if (-not $uv) {
    Write-Host 'Installing uv from its official installer (current user, no administrator access)...'
    $previousNoModify = $env:UV_NO_MODIFY_PATH
    $previousInstallDirectory = $env:UV_INSTALL_DIR
    try {
        if (-not $env:UV_INSTALL_DIR) { $env:UV_INSTALL_DIR = Join-Path $HOME '.local\bin' }
        if ($NoModifyPath) { $env:UV_NO_MODIFY_PATH = '1' }
        $bootstrapHost = if ($PSVersionTable.PSEdition -eq 'Core') { Join-Path $PSHOME 'pwsh.exe' } else { Join-Path $PSHOME 'powershell.exe' }
        & $bootstrapHost -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command 'irm https://astral.sh/uv/install.ps1 | iex'
        if ($LASTEXITCODE -ne 0) { throw 'The official uv installer failed.' }
    } finally {
        $env:UV_NO_MODIFY_PATH = $previousNoModify
        $env:UV_INSTALL_DIR = $previousInstallDirectory
    }
    $uv = Find-LocalizeUv
    if (-not $uv) { throw 'uv was not found after installation. See https://docs.astral.sh/uv/getting-started/installation/.' }
}

$temporary = Join-Path ([IO.Path]::GetTempPath()) ('localizeit-install-' + [guid]::NewGuid())
New-Item -ItemType Directory -Path $temporary | Out-Null
try {
    Write-Host 'Downloading Localize v3.2.3 from GitHub and checking SHA-256...'
    $wheelPath = Join-Path $temporary $wheel
    $sumPath = Join-Path $temporary 'SHA256SUMS'
    Invoke-WebRequest -UseBasicParsing -Uri "$release/SHA256SUMS" -OutFile $sumPath -TimeoutSec 60
    Invoke-WebRequest -UseBasicParsing -Uri "$release/$wheel" -OutFile $wheelPath -TimeoutSec 120
    $pattern = '^([a-f0-9]{64})  ' + [regex]::Escape($wheel) + '$'
    $matchesFound = @(Get-Content -LiteralPath $sumPath | Where-Object { $_ -cmatch $pattern })
    if ($matchesFound.Count -ne 1) { throw 'The release has no unique SHA-256 checksum for the wheel.' }
    $expected = ($matchesFound[0] -split '  ', 2)[0]
    $hasher = [Security.Cryptography.SHA256]::Create()
    try {
        $actual = [BitConverter]::ToString($hasher.ComputeHash([IO.File]::ReadAllBytes($wheelPath))).Replace('-', '').ToLowerInvariant()
    } finally { $hasher.Dispose() }
    if ($actual -cne $expected) { throw 'Localize checksum verification failed. Nothing was installed.' }

    Write-Host 'Installing the localizeit command in an isolated Python environment...'
    & $uv tool install --force --python $Python $wheelPath
    if ($LASTEXITCODE -ne 0) { throw 'Localize installation failed.' }
    $toolDirectory = (& $uv tool dir --bin | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) { throw 'Could not find the installed command directory.' }
    & (Join-Path $toolDirectory 'localizeit.exe') --about | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'The installed localizeit command failed its startup check.' }
    if (-not $NoModifyPath) {
        & $uv tool update-shell
        if ($LASTEXITCODE -ne 0) { throw 'Installed Localize, but could not update PATH. Run uv tool update-shell.' }
        if (($env:PATH -split ';') -notcontains $toolDirectory) { $env:PATH = "$toolDirectory;$env:PATH" }
    }
    Write-Host 'Localize is installed. Run: localizeit'
    Write-Host 'If an existing terminal cannot find it, open a new terminal once.'
} finally {
    $resolvedTemporary = (Resolve-Path -LiteralPath $temporary).Path
    $temporaryRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
    if (-not $resolvedTemporary.StartsWith($temporaryRoot, [StringComparison]::OrdinalIgnoreCase) -or
        ((Get-Item -LiteralPath $temporary).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'Refusing to clean an unexpected temporary directory.'
    }
    Remove-Item -LiteralPath $resolvedTemporary -Recurse -Force
}
