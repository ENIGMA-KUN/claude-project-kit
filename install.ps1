<#
.SYNOPSIS
Install or upgrade the project kit in a repository (Windows launcher for install.py).

.EXAMPLE
.\install.ps1 -Target R:\code\my-project
.\install.ps1 -Target . -Global
#>
param(
    [string]$Target = (Get-Location).Path,
    [switch]$Global,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$KitRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

function Test-Python([string]$Exe, [string[]]$Pre) {
    if (-not (Get-Command $Exe -ErrorAction SilentlyContinue)) { return $false }
    try {
        $out = & $Exe @Pre -c "import sys; print(sys.version_info[0]*100+sys.version_info[1])" 2>$null
        if ($LASTEXITCODE -ne 0) { return $false }
        return ([int]("$out".Trim()) -ge 308)
    } catch {
        return $false
    }
}

$candidates = @(
    @{ Exe = 'python';  Pre = @();     Cmd = 'python'  },
    @{ Exe = 'py';      Pre = @('-3'); Cmd = 'py -3'   },
    @{ Exe = 'python3'; Pre = @();     Cmd = 'python3' }
)
$py = $null
foreach ($c in $candidates) {
    if (Test-Python $c.Exe $c.Pre) { $py = $c; break }
}
if ($null -eq $py) {
    Write-Error "Python 3.8 or newer was not found on PATH. Install it from https://www.python.org/downloads/ and run this again."
    exit 1
}

$argsList = @()
$argsList += $py.Pre
$argsList += @((Join-Path $KitRoot 'install.py'), $Target, '--python-cmd', $py.Cmd)
if ($Global) { $argsList += '--global' }
if ($DryRun) { $argsList += '--dry-run' }

& $py.Exe @argsList
exit $LASTEXITCODE
