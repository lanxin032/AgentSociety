"""Update the canonical cloud source after hash checks, without version copies."""
import argparse
import base64
import hashlib
import json
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected", type=Path, required=True)
    args = parser.parse_args()
    expected = json.loads(args.expected.read_text(encoding="utf-8-sig"))
    expected = expected.get("hashes", expected)
    selected = [p for folder in ("policy_v3", "policy_mve", "policy_runtime", "custom", "research/v3_20260909")
                for p in (root / folder).rglob("*")
                if p.is_file() and p.suffix in {".py", ".md", ".json"}]
    # Match the runtime source manifest, including shared and MVE driver code.
    selected += list((root / "tools").rglob("*.py"))
    selected += list((root / "tests").glob("test_v3*.py"))
    selected += [p for p in (root / "tests").glob("*.py")
                 if p.name in {"test_checkpoints.py", "test_policy_runtime.py", "test_framework_adapters.py", "fixtures.py"}]
    selected += list((root / "tests" / "data").glob("*.json"))
    payload = []
    for path in sorted(set(selected)):
        rel = path.relative_to(root).as_posix()
        data = path.read_bytes()
        payload.append({"path": rel, "sha256": hashlib.sha256(data).hexdigest(),
                        "data": base64.b64encode(data).decode(), "expected": expected.get(rel)})
    print("from pathlib import Path\nimport base64,hashlib,json")
    print("root=Path('/home/coder/policy-mix').resolve()")
    print("payload=json.loads(" + repr(json.dumps(payload)) + ")")
    print('''
for row in payload:
    target=(root/row['path']).resolve()
    if not target.is_relative_to(root): raise RuntimeError('Upload path outside project')
    if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() not in (row['sha256'],row['expected']):
        raise RuntimeError('Unreviewed remote change: '+row['path'])
for row in payload:
    target=root/row['path']; data=base64.b64decode(row['data'])
    if hashlib.sha256(data).hexdigest()!=row['sha256']: raise RuntimeError('Corrupted upload data')
    if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest()==row['sha256']: continue
    target.parent.mkdir(parents=True,exist_ok=True)
    temporary=target.with_suffix(target.suffix+'.upload.tmp'); temporary.write_bytes(data); temporary.replace(target)
print(json.dumps({'files':len(payload),'hashes':{r['path']:hashlib.sha256((root/r['path']).read_bytes()).hexdigest() for r in payload}}))
''')


if __name__ == "__main__":
    main()
