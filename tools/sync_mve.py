"""Emit a guarded cloud upload script; pipe to coder.ps1 exec python -.

Existing cloud bytes must match a previously observed hash or the incoming
bytes. This tool never reads secrets, production ledgers or simulation data.
Updates stay in the canonical source tree; no automatic version copies.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected", type=Path)
    args = parser.parse_args()
    expected = json.loads(args.expected.read_text(encoding="utf-8")) if args.expected else {}
    # Verified cloud source before this implementation, not a blanket overwrite.
    expected.setdefault("tools/smoke_budget.py", "091c7ea9f7a9015c7338ff320e4a6e618eab9b73e707a584fcccc1918e5d399b")
    payload = []
    folders = ["policy_mve", "custom", "research/mve_20260909"]
    paths = [p for name in folders for p in (root / name).rglob("*") if p.is_file() and p.suffix in {".py", ".json", ".md"}]
    paths += [p for p in (root / "tools").glob("*.py") if "mve" in p.name or p.name == "smoke_budget.py"]
    paths += [p for p in (root / "tests").glob("test_*.py") if "mve" in p.name or "policy" in p.name]
    for path in sorted(set(paths)):
        rel = path.relative_to(root).as_posix()
        data = path.read_bytes()
        payload.append({"path": rel, "data": base64.b64encode(data).decode(), "sha256": hashlib.sha256(data).hexdigest(), "expected": expected.get(rel)})
    print("from pathlib import Path\nimport base64,hashlib,json,os")
    print("root=Path('/home/coder/policy-mix').resolve()")
    print("payload=json.loads(" + repr(json.dumps(payload)) + ")")
    print("""
for row in payload:
    path=(root/row['path']).resolve()
    if not path.is_relative_to(root): raise RuntimeError('Path outside project')
    if path.exists():
        current=hashlib.sha256(path.read_bytes()).hexdigest()
        if current not in (row['sha256'],row['expected']):
            raise RuntimeError('Unreviewed cloud change: '+row['path']+' '+current)
for row in payload:
    path=root/row['path']; data=base64.b64decode(row['data'])
    if hashlib.sha256(data).hexdigest()!=row['sha256']: raise RuntimeError('Payload hash mismatch')
    if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest()==row['sha256']: continue
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.upload.tmp'); temp.write_bytes(data); temp.replace(path)
print(json.dumps({'uploaded':len(payload),'hashes':{r['path']:hashlib.sha256((root/r['path']).read_bytes()).hexdigest() for r in payload}}))
""")


if __name__ == "__main__":
    main()
