param([Parameter(Mandatory=$true)][string]$RunName)
$ErrorActionPreference = 'Stop'
if ($RunName -notmatch '^mve-(scripted|llm|probe)-[0-9TZ.]+$') { throw 'Expected an exact MVE run directory name.' }
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$DestinationFile = Join-Path $ProjectRoot ".local\$RunName.transfer.json"
$DownloadScript = @'
from pathlib import Path
import base64,hashlib,json,sys
root=Path('/home/coder/policy-mix/runs')
name=sys.argv[1]
run=(root/name).resolve()
if not run.is_relative_to(root) or not run.is_dir():raise RuntimeError('Run not found')
rows=[]
for p in sorted(run.rglob('*')):
 if p.is_file() and p.suffix in ['.json','.jsonl','.log'] and not p.name.startswith('.env'):
  data=p.read_bytes()
  rows.append({'path':str(p.relative_to(root)),'sha256':hashlib.sha256(data).hexdigest(),'data':base64.b64encode(data).decode()})
for p in [root/'api-smoke-budget-20260909.json',root/'mve-authorization-20260909.json']:
 if p.exists():
  data=p.read_bytes();rows.append({'path':'mve-evidence/'+name+'/'+p.name,'sha256':hashlib.sha256(data).hexdigest(),'data':base64.b64encode(data).decode()})
print(json.dumps({'files':rows}))
'@
$TransferJson = $DownloadScript | & (Join-Path $PSScriptRoot 'coder.ps1') exec /usr/local/bin/python - $RunName
if ($LASTEXITCODE -ne 0) { throw 'Cloud retrieval failed' }
Set-Content -LiteralPath $DestinationFile -Value $TransferJson -Encoding utf8
@'
from pathlib import Path
import sys,json,base64,hashlib
root=Path.cwd().resolve()
payload=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8-sig'))
for row in payload['files']:
 path=(root/'runs'/row['path']).resolve()
 if not path.is_relative_to(root/'runs'):raise RuntimeError('Output outside runs')
 data=base64.b64decode(row['data'])
 if hashlib.sha256(data).hexdigest()!=row['sha256']:raise RuntimeError('Transfer hash mismatch')
 if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:raise RuntimeError('Existing local evidence differs: '+str(path))
for row in payload['files']:
 path=root/'runs'/row['path'];path.parent.mkdir(parents=True,exist_ok=True)
 if not path.exists():path.write_bytes(base64.b64decode(row['data']))
print(json.dumps({'verified_files':len(payload['files']),'run':sys.argv[2]}))
'@ | python -B - $DestinationFile $RunName
if ($LASTEXITCODE -ne 0) { throw 'Local evidence verification failed' }
