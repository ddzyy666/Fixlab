"""Repeated paired self-check ablation; independent task copies for every run."""
import base64
import hashlib
import json
from pathlib import Path
from statistics import mean

from .benchmark import evaluate
from .budget import validate
from .evaluation import snapshot, save_json


def aggregate(runs, expected):
    groups = {}
    for mode in ('off', 'on'):
        selected = [r for r in runs if r['mode'] == mode]
        rows = [row for r in selected for row in r['summary']['results']]
        successes = sum(bool(row.get('repair_success')) for row in rows)
        tokens = [row.get('tokens', {}).get('total_tokens') for row in rows]
        seconds = [row.get('execution_seconds') for row in rows]
        known_tokens = sum(v for v in tokens if v is not None)
        usage_complete = bool(rows) and all(v is not None for v in tokens) and all(
            r['summary']['token_usage_complete'] for r in selected)
        durations_complete = bool(rows) and all(v is not None for v in seconds)
        groups[mode] = {
            'completed_trials': len(rows), 'expected_trials': expected,
            'successes': successes, 'success_rate': successes / len(rows) if rows else None,
            'execution_errors': sum(bool(r.get('error_type')) for r in rows),
            'reported_total_tokens': known_tokens, 'token_usage_complete': usage_complete,
            'mean_tokens': known_tokens / len(rows) if usage_complete else None,
            'tokens_per_success': known_tokens / successes if usage_complete and successes else None,
            'mean_execution_seconds': mean(seconds) if durations_complete else None,
        }
    pairs = []
    indexed = {(r['repeat'], r['mode']): r for r in runs}
    for repeat in sorted({r['repeat'] for r in runs}):
        if (repeat, 'on') not in indexed or (repeat, 'off') not in indexed:
            continue
        on = {r['task_id']: r for r in indexed[repeat, 'on']['summary']['results']}
        off = {r['task_id']: r for r in indexed[repeat, 'off']['summary']['results']}
        if on.keys() != off.keys():
            raise ValueError('Compared task sets differ')
        for task in sorted(on):
            if on[task]['source_sha256'] != off[task]['source_sha256']:
                raise ValueError('Compared task fingerprints differ')
            pairs.append({'repeat': repeat, 'task_id': task,
                          'off_success': bool(off[task].get('repair_success')),
                          'on_success': bool(on[task].get('repair_success'))})
    return groups, pairs


def compare(suite, output, model_factory, repeats=3, max_steps=12, task_id=None, executor=None, budget_options=None):
    validate(budget_options)
    if repeats < 1 or max_steps < 1:
        raise ValueError('Repeats and max_steps must be positive')
    suite, output = Path(suite).resolve(), Path(output).resolve()
    if output.is_relative_to(suite):
        raise ValueError('Comparison output must be outside benchmark sources')
    manifests = sorted(suite.glob('*/task.json'))
    if task_id:
        manifests = [m for m in manifests if m.parent.name == task_id]
    if not manifests:
        raise ValueError('No matching benchmark tasks found')
    # Freeze only declared task fixtures, never credentials or prior execution logs.
    frozen = {}
    for manifest in manifests:
        if manifest.is_symlink() or manifest.parent.is_symlink():
            raise ValueError('Linked task manifests are not supported')
        metadata = json.loads(manifest.read_text(encoding='utf-8'))
        if not isinstance(metadata.get('task'), str) or not metadata['task'].strip():
            raise ValueError('Task description is required')
        name = manifest.parent.name
        frozen[f'{name}/task.json'] = base64.b64encode(json.dumps({'task': metadata['task'], **({'source': metadata['source']} if 'source' in metadata else {})}).encode()).decode()
        for subdir in ('repo', 'hidden'):
            source = manifest.parent / subdir
            if source.is_symlink() or (subdir == 'repo' and not source.is_dir()):
                raise ValueError('Missing or linked task directory')
            for relative, content in snapshot(source).items():
                if subdir == 'hidden' and (Path(relative).name != relative or not relative.startswith('test_hidden_') or not relative.endswith('.py')):
                    raise ValueError('Hidden tests must be flat test_hidden_*.py files')
                frozen[f'{name}/{subdir}/{relative}'] = content
    if executor:
        executor.check()
    probe = model_factory(False)
    model_name = getattr(probe, 'model', type(probe).__name__)
    api_base = getattr(probe, 'api_base', None)
    output.mkdir(parents=True, exist_ok=False)
    frozen_root = output / 'suite'
    for name, content in frozen.items():
        path = frozen_root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.b64decode(content))
    source_hash = hashlib.sha256(json.dumps(frozen, sort_keys=True).encode()).hexdigest()
    code_hash = hashlib.sha256(b''.join(p.name.encode() + p.read_bytes() for p in sorted(Path(__file__).parent.glob('*.py')))).hexdigest()
    result = {'model': model_name, 'suite_sha256': source_hash, 'harness_sha256': code_hash,
              'repeats': repeats, 'max_steps': max_steps, 'budget': budget_options or {},
              'backend': executor.backend if executor else 'local',
              'image': executor.image if executor and executor.backend == 'docker' else None,
              'status': 'running', 'runs': []}
    def persist():
        result['groups'], result['pairs'] = aggregate(result['runs'], repeats * len(manifests))
        save_json(output / 'comparison.json', result)
        lines = ['# Self-check comparison', '', f"Status: {result['status']}", '',
                 '| Mode | Finished | Successes | Success rate | Mean tokens | Mean seconds |',
                 '|---|---:|---:|---:|---:|---:|']
        for mode, row in result['groups'].items():
            fmt = lambda v: 'unknown' if v is None else f'{v:.2f}'
            lines.append(f"| {mode} | {row['completed_trials']}/{row['expected_trials']} | {row['successes']} | {fmt(row['success_rate'])} | {fmt(row['mean_tokens'])} | {fmt(row['mean_execution_seconds'])} |")
        lines += ['', 'Equal step limits are not equal token or cost limits. Model sampling defaults are unchanged.',
                  'Rates describe completed trials; inspect completion counts before interpreting partial results.',
                  'Small repeated development tasks do not establish general performance or statistical significance.',
                  'tokens_per_success includes tokens spent on failures; unknown usage is not treated as zero.']
        (output / 'comparison.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    persist()
    try:
        for repeat in range(1, repeats + 1):
            # Alternate order to reduce consistently favoring one mode by execution time.
            modes = ('off', 'on') if repeat % 2 else ('on', 'off')
            for mode in modes:
                def factory():
                    model = model_factory(mode == 'on')
                    if getattr(model, 'model', type(model).__name__) != model_name or getattr(model, 'api_base', None) != api_base:
                        raise ValueError('Model and provider must remain identical across runs')
                    if getattr(model, 'self_check_enabled', mode == 'on') != (mode == 'on'):
                        raise ValueError('Model factory ignored the self-check mode')
                    return model
                batch = output / f'repeat-{repeat:02d}-{mode}'
                print(f'Comparison repeat {repeat}/{repeats}, self-check {mode}', flush=True)
                summary = evaluate(frozen_root, batch, factory, max_steps, executor=executor, budget_options=budget_options)
                result['runs'].append({'repeat': repeat, 'mode': mode, 'path': str(batch), 'summary': summary})
                persist()
        result['status'] = 'completed'
    except BaseException:
        result['status'] = 'interrupted'
        raise
    finally:
        persist()
    return result
