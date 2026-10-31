"""Build a reviewable source/sync archive; never upload or include run secrets."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from policy_sim.runtime import code_manifest, is_public_source


def build(output):
    output = Path(output).resolve()
    if output.exists() or not output.is_relative_to(ROOT / 'runs'):
        raise ValueError('Choose a new archive path under runs')
    files = {row['path'] for row in code_manifest(ROOT)}
    files.update(p.relative_to(ROOT).as_posix() for p in (ROOT / 'tests').rglob('*')
                 if p.suffix in ('.py', '.json') and is_public_source(p, ROOT))
    files.update(('README.md', 'ARCHITECTURE.md', 'CONTEXT.md', '.gitignore'))
    files.update(p.relative_to(ROOT).as_posix() for p in (ROOT / 'tools').glob('*.ps1'))
    # Every project import in the shipped Python must resolve within this archive.
    for name in sorted(files):
        if not is_public_source(ROOT / name, ROOT):
            raise ValueError('Unsafe source path: ' + name)
        if not name.endswith('.py'):
            continue
        for node in ast.walk(ast.parse((ROOT / name).read_text())):
            modules = ([node.module or ''] if isinstance(node, ast.ImportFrom)
                       else [a.name for a in node.names] if isinstance(node, ast.Import) else [])
            for module in modules:
                base = module.split('.')[0]
                if base in {'policy_v3', 'policy_mve', 'policy_runtime'}:
                    raise ValueError('Retired dependency in ' + name)
                if base in {'policy_sim', 'custom', 'tools'}:
                    path = module.replace('.', '/')
                    if path + '.py' not in files and path + '/__init__.py' not in files:
                        if not any(f.startswith(path + '/') for f in files):
                            raise ValueError('Missing bundled import: ' + module)
    manifest = [{'path': name, 'sha256': hashlib.sha256((ROOT / name).read_bytes()).hexdigest()}
                for name in sorted(files)]
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for row in manifest:
            archive.write(ROOT / row['path'], row['path'])
        archive.writestr('SOURCE_MANIFEST.json', json.dumps(manifest, indent=2))
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None:
            raise ValueError('Archive integrity check failed')
        for row in manifest:
            if hashlib.sha256(archive.read(row['path'])).hexdigest() != row['sha256']:
                raise ValueError('Bundled bytes differ: ' + row['path'])
    return {'path': str(output), 'files': len(manifest), 'sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
            'uploaded': False, 'runs_and_credentials_included': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    print(json.dumps(build(parser.parse_args().output), ensure_ascii=False, indent=2))
