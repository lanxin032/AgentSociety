"""Prepare and verify an OFFLINE review package. No model or network calls.

Run from any directory with the existing Python. This module only reads the
frozen evidence and writes new review artifacts in this directory.
"""
from collections import Counter
from datetime import datetime, timezone
import argparse
import copy
import hashlib
import json
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
FROZEN = '8530b5271468bd93c8ee71cbde8b1206d6c926a22cf7e2948d00fa2f6ef87e9c'
MAX_BODY = 96 * 1024
MAX_TOKENS = 4096
SETTINGS = {'model': 'deepseek-v4-flash', 'max_tokens': MAX_TOKENS, 'stream': False,
            'temperature': 0.2, 'thinking': {'type': 'disabled'},
            'response_format': {'type': 'json_object'}, 'n': 1}
UNDERSTANDING_SYSTEM = '''你正在参加一次接口理解检验，不执行仿真动作。
依据给出的角色观察、其已有历史和公开规则回答问题。不得读取隐藏真实状态。
区分已知、未收到信息与不能判断；对每题选择一个现有选项。
只返回JSON对象，格式为 {"answers":{"题目ID":"选项key"}}。不解释、不选择业务行动。'''


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_new(path, value):
    text = json.dumps(value, ensure_ascii=False, indent=2)
    if path.exists():
        raise FileExistsError('Review output already exists; do not overwrite: ' + str(path))
    path.write_text(text, encoding='utf-8')


def scoped(base, relative):
    path = (base / relative).resolve()
    if not path.is_relative_to(base.resolve()):
        raise ValueError('Path leaves its declared evidence scope')
    return path


def pointer(document, expression):
    if expression == '':
        return document
    if not expression.startswith('/'):
        raise ValueError('Expected RFC6901 pointer')
    value = document
    for token in expression[1:].split('/'):
        token = token.replace('~1', '/').replace('~0', '~')
        value = value[int(token)] if isinstance(value, list) else value[token]
    return value


def validate_cases(document, benchmark):
    cases = document['cases']
    if len(cases) != 6 or {c['id'] for c in cases} != {f'C{i:02}' for i in range(1, 7)}:
        raise ValueError('Expected exactly six unique cases')
    summary = []
    for case in cases:
        src = case['source']
        original_path = scoped(ROOT, src['observations_path'])
        if sha(original_path) != src['sha256']:
            raise ValueError('Original observation file hash changed')
        rows = original_path.read_text(encoding='utf-8').splitlines()
        row = json.loads(rows[src['line'] - 1])
        observation = read(scoped(benchmark, case['observation_path']))
        history = read(scoped(benchmark, case['history_path']))
        if observation != row['observation']:
            raise ValueError('Extracted observation differs from the original')
        if (observation['round'], observation['actor_id']) != (src['round'], src['actor_id']):
            raise ValueError('Actor/round identity mismatch')
        decision_path = scoped(ROOT, src['decision_path'])
        if sha(decision_path) != src['decision_sha256']:
            raise ValueError('Decision trace hash changed')
        decision = json.loads(decision_path.read_text(encoding='utf-8').splitlines()[src['decision_line'] - 1])
        original_input = json.loads(decision['messages'][1]['content'])
        if original_input['observation'] != observation or original_input['recent_history'] != history:
            raise ValueError('Extraction differs from the actual decision input')
        if any(h['round'] >= src['round'] for h in history):
            raise ValueError('History must precede the case decision')
        question_ids = [q['id'] for q in case['questions']]
        if not question_ids or len(question_ids) != len(set(question_ids)):
            raise ValueError('Empty or duplicate questions')
        context = {'observation': observation, 'history': history}
        for q in case['questions']:
            if q['answer_key'] not in q['options']:
                raise ValueError('Answer does not name an existing option')
            if not q['evidence']:
                raise ValueError('Every answer needs lawful visible evidence')
            for evidence in q['evidence']:
                pointer(context, evidence['pointer'])
        summary.append({'case_id': case['id'], 'actor_id': src['actor_id'], 'round': src['round'],
                        'source_line': src['line'], 'questions': len(question_ids),
                        'observation_exact': True, 'history_exact': True, 'evidence_pointers_resolve': True})
    return summary


def make_plan(document, benchmark):
    old = (benchmark / 'choice_system_original.txt').read_text(encoding='utf-8')
    help_text = (benchmark / 'interface_clarification.txt').read_text(encoding='utf-8')
    rows = []
    for case in document['cases']:
        observation = read(scoped(benchmark, case['observation_path']))
        history = read(scoped(benchmark, case['history_path']))
        for variant in ('original', 'clarified'):
            for task in ('understanding', 'choice'):
                system = UNDERSTANDING_SYSTEM if task == 'understanding' else old
                if variant == 'clarified':
                    system += '\n\n以下为各案例通用的中性接口释义：\n' + help_text
                body = {'observation': observation, 'recent_history': history}
                if task == 'understanding':
                    # Deliberate allowlist. Never serialize answers or evidence locators.
                    body['questions'] = [{key: copy.deepcopy(q[key]) for key in ('id', 'prompt', 'options')}
                                         for q in case['questions']]
                for repeat in (1, 2):
                    messages = [{'role': 'system', 'content': system},
                                {'role': 'user', 'content': json.dumps(body, ensure_ascii=False, allow_nan=False)}]
                    request = {**copy.deepcopy(SETTINGS), 'messages': messages}
                    rows.append({'task_id': f"{case['id']}-{variant}-{task}-r{repeat}",
                                 'case_id': case['id'], 'variant': variant, 'task': task, 'repeat': repeat,
                                 'request': request})
    random.Random(20260910).shuffle(rows)
    return {'schema_version': 'interface-review-request-plan-1.0', 'status': 'prepared_not_executed',
            'authorized': False, 'primary_tasks': 48, 'max_format_repairs_per_task': 1,
            'max_api_requests': 96, 'order_seed': 20260910,
            'session_rule': 'Each task uses an independent stateless request; no test response or feedback is reused.',
            'tasks': rows}


def validate_plan(plan, cases_document, benchmark):
    expected = make_plan(cases_document, benchmark)
    if plan != expected:
        raise ValueError('Plan differs from its allowlisted source construction')
    rows = plan['tasks']
    if len({x['task_id'] for x in rows}) != 48:
        raise ValueError('Missing or duplicate planned task')
    sizes = []
    for row in rows:
        data = json.loads(row['request']['messages'][1]['content'])
        if row['task'] == 'choice' and set(data) != {'observation', 'recent_history'}:
            raise ValueError('Choice task contains test questions or answer feedback')
        if row['task'] == 'understanding':
            if any(set(q) != {'id', 'prompt', 'options'} for q in data['questions']):
                raise ValueError('An answer key or reviewer evidence leaked into a request')
        size = len(json.dumps(row['request'], ensure_ascii=False).encode('utf-8'))
        if size > MAX_BODY:
            raise ValueError('Planned request exceeds existing proxy byte cap')
        sizes.append(size)
    return {'tasks': 48, 'understanding_tasks': 24, 'choice_tasks': 24,
            'max_request_bytes': max(sizes), 'sum_primary_request_bytes': sum(sizes),
            'answer_keys_excluded': True, 'choice_tasks_isolated': True,
            'same_observation_history_and_candidates_between_variants': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--validate', action='store_true')
    args = parser.parse_args()
    if args.prepare == args.validate:
        parser.error('Select exactly one mode')
    from policy_v3.runtime import code_digest
    if code_digest(ROOT) != FROZEN:
        raise ValueError('Frozen runtime source changed; re-audit before using saved cases')
    benchmark = HERE / 'benchmark'
    cases = read(benchmark / 'cases.json')
    summaries = validate_cases(cases, benchmark)
    proposal = read(HERE / 'state_transition_proposal.json')
    if proposal['status'] != 'proposal_not_implemented' or len(proposal['acceptance_cases']) < 6:
        raise ValueError('State proposal must remain explicitly unimplemented with acceptance cases')
    if args.prepare:
        plan = make_plan(cases, benchmark)
        plan_checks = validate_plan(plan, cases, benchmark)
        # Rates come from the user screenshot, not a live price or billing query.
        price = {'model': 'deepseek-v4-flash', 'input_rmb_per_million': 1.2,
                 'output_rmb_per_million': 2.4, 'evidence': 'evidence/platform_model_prices_user.png',
                 'evidence_sha256': sha(HERE / 'evidence/platform_model_prices_user.png'),
                 'basis': 'User supplied platform screenshot; refresh before execution.', 'actual_bill_verified': False}
        bound = 96 * (((MAX_BODY + 4096) * 1.2 + MAX_TOKENS * 2.4) / 1_000_000)
        quote = {'status': 'proposal_not_authorized', 'api_requests_already_executed': 0,
                 'primary_tasks': 48, 'hard_request_cap_with_one_format_repair': 96,
                 'proxy_max_body_bytes': MAX_BODY, 'output_token_cap_per_request': MAX_TOKENS,
                 'max_proxy_reservation_total_rmb_at_screenshot_rates': bound,
                 'proposed_incremental_rmb_cap': 15, 'elapsed_time_estimate': None,
                 'rates': price, 'authorizes_execution': False,
                 'bound_note': 'All 96 requests are reserved at the existing proxy maximum body size plus its 4096-token padding. This is a conservative reservation calculation, not a measured bill or tokenizer guarantee.',
                 'execution_conditions': ['Explicit stage approval and current rates', 'Original API ledger retained; new stage baseline binds its current prefix without rewriting history',
                                          'Current cloud deadline checked', '96-request and 15-rmb limits enforced by one owner',
                                          'No automatic rerun after technical failure; no extra attempts to improve scores']}
        report = {'status': 'offline_preparation_validated', 'created_utc': datetime.now(timezone.utc).isoformat(),
                  'source_sha256': FROZEN, 'runtime_modified': False, 'api_calls': 0,
                  'model_understanding_tested': False, 'state_proposal_implemented': False,
                  'case_checks': summaries, 'request_plan_checks': plan_checks,
                  'script_sha256': sha(__file__), 'cases_sha256': sha(benchmark / 'cases.json')}
        for name, obj in [('request_plan.json', plan), ('interface_test_quote_UNAPPROVED.json', quote),
                          ('offline_validation.json', report)]:
            write_new(HERE / name, obj)
    else:
        plan_checks = validate_plan(read(HERE / 'request_plan.json'), cases, benchmark)
        report = {'status': 'offline_revalidated', 'cases': len(summaries), **plan_checks,
                  'runtime_modified': False, 'api_calls': 0, 'model_understanding_tested': False}
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
