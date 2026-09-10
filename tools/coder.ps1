$ErrorActionPreference = 'Stop'
$CoderArguments = @($args)
$configDirectory = Join-Path $env:APPDATA 'Code\User\globalStorage\coder.coder-remote\coder.fiblab.net'
$coderBinary = Join-Path $configDirectory 'bin\coder-windows-amd64.exe'

if (-not (Test-Path -LiteralPath $coderBinary -PathType Leaf)) {
    throw 'Coder CLI not found in the existing VS Code extension storage.'
}
if (-not $CoderArguments) {
    $CoderArguments = @('list')
}

if ($CoderArguments[0] -eq 'exec') {
    if ($CoderArguments.Count -lt 2) {
        throw 'Usage: coder.ps1 exec <remote-command> [arguments]'
    }
    # PowerShell consumes a script-level --; insert it at the native CLI boundary.
    $CoderArguments = @('ssh', '--disable-autostart', 'lanxinl29-gmail-com/policy-mix.main', '--') + $CoderArguments[1..($CoderArguments.Count - 1)]
} elseif ($CoderArguments[0] -eq 'ssh') {
    throw 'Use coder.ps1 exec <command> [arguments] for this workspace.'
}

if ($MyInvocation.ExpectingInput) {
    $input | & $coderBinary --global-config $configDirectory --url 'https://coder.fiblab.net' @CoderArguments
} else {
    & $coderBinary --global-config $configDirectory --url 'https://coder.fiblab.net' @CoderArguments
}
if ($LASTEXITCODE -ne 0) {
    throw "Coder exited with status $LASTEXITCODE."
}
