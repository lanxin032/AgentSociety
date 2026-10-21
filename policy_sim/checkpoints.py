"""Round-boundary snapshots with one digest marker.

The official workspace contract already guarantees atomic writes and a
defined save/restore order; this layer adds only what the research needs at
runtime — an immutable per-round copy and a world-digest marker strong
enough to detect divergence. Full per-file verification happens once, in the
offline independent audit, not on every round.
"""
import hashlib
import os
import shutil
from pathlib import Path
from .io import digest, read_json, write_json


def _checkpoint_files(run_dir):
    paths = [run_dir / name for name in (
        'SOCIETY.json', 'SOCIETY_STEP.json', 'world.json', 'metrics.json', 'run_config.json')]
    paths += list((run_dir / 'env').rglob('*.json'))
    paths += [p for p in (run_dir / 'agents').rglob('*') if p.is_file()]
    paths += list(run_dir.glob('*.jsonl'))
    return sorted(set(paths))


def _validate_round_state(run_dir, count):
    if type(count) is not int or count < 0:
        raise RuntimeError('Invalid checkpoint round')
    if read_json(run_dir / 'SOCIETY_STEP.json')['step_count'] != count:
        raise RuntimeError('Society step differs from the committed round')
    agents = sorted((run_dir / 'agents').glob('*/AGENT.json'))
    if len(agents) != 4:
        raise RuntimeError('Expected exactly four actor checkpoints')
    identifiers = set()
    for path in agents:
        meta = read_json(path)
        identifier = meta.get('agent_id', meta.get('id'))
        if type(identifier) is not int or identifier not in {1, 2, 3, 4} or identifier in identifiers or meta.get('step_count') != count:
            raise RuntimeError('Actor checkpoint identity or round mismatch')
        identifiers.add(identifier)


def commit_round(run_dir, count, snapshot, actor_results):
    run_dir = Path(run_dir)
    if (run_dir / 'partial_failure.json').exists():
        raise RuntimeError('Partial failure is not a clean commit')
    if snapshot.get('round') != count or digest(snapshot) != digest(read_json(run_dir / 'world.json')):
        raise RuntimeError('Persisted world does not match completed round')
    _validate_round_state(run_dir, count)
    marker = {'schema_version': 'official-checkpoint-1', 'round': count,
              'world_sha256': digest(snapshot), 'files': len(_checkpoint_files(run_dir)),
              'evidence_origin': str(run_dir.resolve())}
    write_json(run_dir / 'committed.json', marker)
    # Snapshot retains the complete official workspace and append-only
    # evidence at the exact commit boundary.
    parent = run_dir.parent / (run_dir.name + '-commits')
    destination = parent / f'round-{count:06d}'
    if destination.exists():
        raise RuntimeError('Immutable round snapshot already exists')
    parent.mkdir(parents=True, exist_ok=True)
    temporary = parent / (destination.name + '.pending')
    copy_checkpoint(run_dir, temporary)
    if read_json(temporary / 'committed.json')['round'] != count:
        raise RuntimeError('Snapshot marker mismatch')
    temporary.rename(destination)
    write_json(parent / 'latest.json', {'round': count, 'path': str(destination),
        'committed_sha256': hashlib.sha256((destination / 'committed.json').read_bytes()).hexdigest()})
    return marker


def validate_commit(snapshot):
    run_dir = Path(snapshot)
    marker = read_json(run_dir / 'committed.json')
    if marker.get('schema_version') != 'official-checkpoint-1':
        raise RuntimeError('Unknown checkpoint marker')
    if digest(read_json(run_dir / 'world.json')) != marker['world_sha256']:
        raise RuntimeError('Committed world diverged from its digest')
    _validate_round_state(run_dir, marker['round'])
    return marker


def copy_checkpoint(run_dir, destination):
    shutil.copytree(run_dir, destination, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('model_payloads'))


def restore_payload_links(snapshot, destination):
    run_dir, destination = Path(snapshot), Path(destination)
    # The evidence payloads live beside the commits directory, in the
    # originating attempt run (<attempt>-commits -> <attempt>/model_payloads).
    commits = run_dir.parent
    origin = commits.parent / commits.name[:-len('-commits')]
    payloads = origin / 'model_payloads'
    if payloads.is_dir():
        target = destination / 'model_payloads'
        if not target.exists():
            # Each attempt owns its directory; existing UUID files stay immutable.
            shutil.copytree(payloads, target, copy_function=os.link)
