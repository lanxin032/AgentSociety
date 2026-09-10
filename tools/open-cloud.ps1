$ErrorActionPreference = 'Stop'
$codeCommand = 'D:\Microsoft VS Code\bin\code.cmd'
$folderUri = 'vscode-remote://ssh-remote+coder-vscode.coder.fiblab.net--lanxinl29-gmail-com--policy-mix.main/home/coder/policy-mix'

if (-not (Test-Path -LiteralPath $codeCommand -PathType Leaf)) {
    throw 'VS Code CLI not found at its verified installation path.'
}

# The GPU option applies to this launch only; global VS Code settings are unchanged.
& $codeCommand --new-window --disable-gpu --folder-uri $folderUri
if ($LASTEXITCODE -ne 0) {
    throw "VS Code exited with status $LASTEXITCODE."
}
