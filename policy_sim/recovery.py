"""Read-only validation of current immutable checkpoints and explicit lineage."""
from pathlib import Path
from .io import read_json, digest
from .checkpoints import validate_commit
from .execution import ExecutionError, file_hash


def tree_hashes(directory):
    directory = Path(directory)
    result = {}
    for path in sorted(directory.rglob('*')):
        if path.is_symlink():
            raise ExecutionError('Recovery evidence must not contain symbolic links')
        if path.is_file():
            result[path.relative_to(directory).as_posix()] = file_hash(path)
    return result


def classify_failure(receipt, driver=None):
    driver = driver or {}
    details = receipt.get('proxy_failure') or receipt.get('failure') or driver.get('failure')
    if isinstance(details, dict) and details.get('error_type'):
        return {**details, 'retryable': False, 'global_stop': True}
    message = str(driver.get('error', '')) + str(receipt.get('error', ''))
    return {'error_type': 'turn_incomplete' if 'TurnIncomplete' in message else 'unclassified_failure',
            'retryable': False, 'global_stop': True}


def audit_recovery(run_output, registry=None):
    """Prove restored prefix and unchanged failed evidence without re-counting API."""
    run_output = Path(run_output)
    path = run_output / 'recovery_lineage.json'
    if not path.exists():
        return []
    lineage = read_json(path)
    if not isinstance(lineage, list) or not lineage:
        raise ExecutionError('Invalid recovery lineage')
    config = read_json(run_output / 'run_config.json')
    for entry in lineage:
        snapshot = Path(entry['snapshot_path'])
        marker = validate_commit(snapshot)
        if (entry['run_id'] != config['record']['run_id']
                or file_hash(snapshot / 'committed.json') != entry['snapshot_sha256']
                or marker['round'] != entry['restored_steps']
                or read_json(snapshot / 'run_config.json') != config):
            raise ExecutionError('Recovery checkpoint differs from frozen run')
        if digest(tree_hashes(entry['failed_output'])) != entry['failed_evidence_sha256']:
            raise ExecutionError('Failed original evidence changed after continuation')
        # The snapshot's append-only evidence must be a verbatim prefix of the
        # continuation's (marker['files'] now records a count, not paths).
        for relative in sorted(p.name for p in snapshot.glob('*.jsonl')):
            prefix = (snapshot / relative).read_bytes()
            with (run_output / relative).open('rb') as stream:
                if stream.read(len(prefix)) != prefix:
                    raise ExecutionError('Recovered JSONL prefix differs')
        if registry is not None:
            parent = registry.latest(entry['parent_attempt_id'])
            child = registry.latest(entry['attempt_id'])
            if (parent.get('kind') != 'technical_failure' or child.get('recovery_of') != entry['parent_attempt_id']
                    or child.get('checkpoint_sha256') != entry['snapshot_sha256']
                    or child.get('authorization_id') != entry['authorization_id']):
                raise ExecutionError('Recovery registry lineage differs')
    return lineage
