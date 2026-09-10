"""Seal the offline preparation only; performs no network or model call."""
from datetime import datetime, timezone
import json

import prepare_review as review


def main():
    from policy_v3.runtime import code_digest
    assert code_digest(review.ROOT) == review.FROZEN
    old_manifest = review.ROOT / 'research/v3_20260909/diagnostic_delivery_manifest.json'
    assert review.sha(old_manifest) == '9459ae27cbcee1bac44a72e4f2a217b5d1b6dd873e4a5028f834257f1914308f'
    cases = review.read(review.HERE / 'benchmark/cases.json')
    checks = review.validate_cases(cases, review.HERE / 'benchmark')
    plan = review.validate_plan(review.read(review.HERE / 'request_plan.json'), cases, review.HERE / 'benchmark')
    proposal = review.read(review.HERE / 'state_transition_proposal.json')
    assert proposal['status'] == 'proposal_not_implemented'
    assert len(proposal['acceptance_cases']) == 11
    report = {
        'status': 'offline_kit_completed_no_paid_execution',
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'case_count': len(checks), 'question_count': sum(x['questions'] for x in checks),
        'request_plan_checks': plan,
        'safeguard_tests': {'command': 'D:/miniconda1/python.exe -B research/v3_20260910_revision/test_prepare_review.py',
                            'final_passed': 8, 'final_failed': 0,
                            'basis': 'Observed process exit 0 and unittest OK in this preparation session.',
                            'initial_environment_issue': 'TemporaryDirectory ACL blocked the write-protection test. Test changed to assert refusal against existing request_plan without creating a temporary directory; all eight then passed. Empty temporary directory was removed.'},
        'independent_review': 'independent_review.md',
        'review_issue_closed': 'commission_not_reported now explicitly scopes communication mode, lawful delivery and observation boundary.',
        'runtime_sha256_unchanged': review.FROZEN,
        'old_diagnostic_delivery_manifest_sha256_unchanged': review.sha(old_manifest),
        'api_calls_in_this_preparation': 0,
        'model_understanding_tested': False,
        'new_mechanism_implemented': False,
        'candidate_acceptance_cases': 11,
        'candidate_acceptance_cases_executed': 0,
        'next_paid_stage_authorized': False,
    }
    review.write_new(review.HERE / 'final_validation.json', report)
    files = []
    for path in sorted(review.HERE.rglob('*')):
        if path.is_file() and '__pycache__' not in path.parts and path.name != 'delivery_manifest.json':
            files.append({'path': path.relative_to(review.HERE).as_posix(), 'bytes': path.stat().st_size,
                          'sha256': review.sha(path)})
    manifest = {'status': 'offline_review_delivery', 'files': files, 'file_count': len(files),
                'runtime_sha256': review.FROZEN, 'api_calls': 0}
    review.write_new(review.HERE / 'delivery_manifest.json', manifest)
    for entry in files:
        assert review.sha(review.HERE / entry['path']) == entry['sha256']
    print(json.dumps({'file_count': len(files), 'all_hashes_verified': True,
                      'manifest_sha256': review.sha(review.HERE / 'delivery_manifest.json'),
                      'runtime_unchanged': True, 'api_calls': 0}))


if __name__ == '__main__':
    main()
