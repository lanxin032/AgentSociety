param([Parameter(Mandatory=$true)][string]$RunName)
$ErrorActionPreference = 'Stop'
if ($RunName -notmatch '^v3-[a-zA-Z0-9_-]+$') { throw 'Expected one exact v3 run directory name, without path separators.' }
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$DestinationFile = Join-Path $ProjectRoot ".local\$RunName.transfer.json"
$DownloadScript = @'
from pathlib import Path
import base64,gzip,hashlib,json,sys
root=Path('/home/coder/policy-mix/runs').resolve()
name=sys.argv[1]
run=(root/name).resolve()
if not run.is_relative_to(root) or not run.is_dir():raise RuntimeError('Run not found')
rows=[]
for p in sorted(run.rglob('*')):
 if p.is_file() and p.suffix in ['.json','.jsonl','.log','.md','.png','.pdf'] and not p.name.startswith('.env'):
  if not p.resolve().is_relative_to(run):raise RuntimeError('Symlink outside requested evidence')
  data=p.read_bytes()
  rows.append({'path':str(p.relative_to(root)),'sha256':hashlib.sha256(data).hexdigest(),'encoding':'gzip-base64','data':base64.b64encode(gzip.compress(data,mtime=0)).decode()})
print(json.dumps({'files':rows}))
'@
$TransferJson = $DownloadScript | & (Join-Path $PSScriptRoot 'coder.ps1') exec /usr/local/bin/python - $RunName
if ($LASTEXITCODE -ne 0) { throw 'Cloud retrieval failed' }
Set-Content -LiteralPath $DestinationFile -Value $TransferJson -Encoding utf8
@'
from pathlib import Path
import sys,json,base64,gzip,hashlib
root=(Path.cwd()/'runs').resolve()
payload=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8-sig'))
for row in payload['files']:
 path=(root/row['path']).resolve()
 if not path.is_relative_to(root):raise RuntimeError('Output outside runs')
 data=base64.b64decode(row['data'],validate=True)
 if row.get('encoding')=='gzip-base64':data=gzip.decompress(data)
 if hashlib.sha256(data).hexdigest()!=row['sha256']:raise RuntimeError('Transfer hash mismatch')
 if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:raise RuntimeError('Existing local evidence differs: '+str(path))
for row in payload['files']:
 path=root/row['path'];path.parent.mkdir(parents=True,exist_ok=True)
 if not path.exists():
  data=base64.b64decode(row['data'],validate=True)
  if row.get('encoding')=='gzip-base64':data=gzip.decompress(data)
  path.write_bytes(data)
print(json.dumps({'verified_files':len(payload['files']),'run':sys.argv[2]}))
'@ | D:/miniconda1/python.exe -B - $DestinationFile $RunName
if ($LASTEXITCODE -ne 0) { throw 'Local evidence verification failed' }
