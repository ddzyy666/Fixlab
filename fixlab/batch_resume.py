"""Resume one saved evaluation batch sequentially, without repeating completed tasks."""
import base64
import hashlib
import json
import sqlite3
from pathlib import Path
from uuid import uuid4

from .budget import validate
from .config import load_config
from .core import APIModel, Workspace
from .evaluation import run_evaluated, save_json
from .execution import Executor
from .importer import safe_name
from .locking import exclusive, BusyError
from .resume import inspect_resume, resume_task, refresh_batch


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def inspect_batch(directory, max_steps=None):
    root = Path(directory).resolve()
    summary = read_json(root/'summary.json')
    plan = read_json(root/'batch-plan.json') if (root/'batch-plan.json').exists() else None
    planned = {}
    if plan:
        if plan.get('version') != 1:
            raise ValueError('Unsupported batch plan version')
        for item in plan['tasks']:
            name = item['task_id']
            if not safe_name(name) or len(Path(name).parts) != 1 or name in planned:
                raise ValueError('Invalid or duplicate task ID in batch plan')
            planned[name] = item
    names = set(planned)
    for child in root.iterdir():
        if child.is_dir() and not child.is_symlink() and (child/'state.sqlite').exists():
            names.add(child.name)
    for row in summary.get('results', []):
        name = row.get('task_id')
        if not isinstance(name, str) or not safe_name(name) or len(Path(name).parts) != 1:
            raise ValueError('Invalid task ID in batch summary')
        names.add(name)
        if row.get('state') and Path(row['state']).resolve() != root/name/'state.sqlite':
            raise ValueError('Batch task state points outside its expected location')
    if len(names) > summary['tasks_total']:
        raise ValueError('Batch contains more task records than expected')
    result = {'directory': str(root), 'tasks_total': summary['tasks_total'],
              'unrecoverable_unstarted': max(0, summary['tasks_total']-len(names)), 'tasks': []}
    for name in sorted(names):
        folder = root/name
        state = folder/'state.sqlite'
        item = {'task_id': name, 'state': str(state)}
        try:
            if folder.is_symlink() or state.is_symlink():
                raise ValueError('Linked task directories or state files are unsupported')
            if state.exists():
                saved = inspect_resume(state, max_steps)
                item['action'] = 'skip_completed' if saved['already_completed'] else 'resume'
                item['remaining_steps'] = saved['remaining_steps']
                if not saved['already_completed'] and not saved['remaining_steps']:
                    raise ValueError('No model steps remain; increase --max-steps')
            elif name in planned and not folder.exists():
                item['action'] = 'start'
            else:
                raise ValueError('No resumable state; existing partial workspace requires inspection')
        except (ValueError, OSError, KeyError, sqlite3.Error) as error:
            item.update(action='blocked', reason=str(error) if isinstance(error, ValueError) else type(error).__name__)
        result['tasks'].append(item)
    return result, plan


def start_planned(root, plan, item, config_path, max_steps, budget_options, model_factory):
    # Check snapshot fingerprint and paths before creating any workspace.
    files, hidden = item['files'], item['hidden']
    digest = hashlib.sha256(json.dumps([item['task'], files, hidden], sort_keys=True).encode()).hexdigest()
    if digest != item['source_sha256']:
        raise ValueError('Frozen task fingerprint mismatch')
    for name in files:
        if not safe_name(name):
            raise ValueError('Unsafe frozen workspace path')
    for name in hidden:
        if not safe_name(name) or len(Path(name).parts) != 1 or not name.startswith('test_hidden_') or not name.endswith('.py'):
            raise ValueError('Unsafe hidden test path')
    settings = {**item, 'backend': plan['backend'], 'image': plan['image'],
                'max_steps': max_steps if max_steps is not None else plan['max_steps'],
                'budget': {**plan.get('budget', {}), **(budget_options or {})}}
    validate(settings['budget'])
    if settings['max_steps'] < 1:
        raise ValueError('max_steps must be positive')
    if not model_factory and item['model'] == 'scripted-demo':
        raise ValueError('Cannot resume scripted fixtures using a real model')
    model = (model_factory(settings) if model_factory else
             APIModel(**load_config(config_path, item['model']), self_check=item['self_check']))
    folder = root/item['task_id']
    repo = folder/'workspace'
    repo.mkdir(parents=True, exist_ok=False)
    for name, content in files.items():
        path = repo/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.b64decode(content, validate=True))
    save_json(folder/'task.json', {'task': item['task'], 'source_sha256': digest})
    state = folder/'state.sqlite'
    try:
        return run_evaluated(Workspace(repo, Executor(settings['backend'], settings['image'])),
                             model, item['task'], state, settings['max_steps'], hidden, settings['budget'])
    finally:
        path = folder/'state-artifacts/report.json'
        if path.exists():
            refresh_batch(state, read_json(path))


def resume_batch(directory, config_path='fixlab.local.toml', max_steps=None, budget_options=None,
                 model_factory=None, inspect=False):
    root = Path(directory).resolve()
    if not (root/'summary.json').is_file():
        raise ValueError('Choose an evaluation batch directory containing summary.json')
    validate(budget_options)
    if max_steps is not None and max_steps < 1:
        raise ValueError('max_steps must be positive')
    with exclusive(root, 'batch'):
        inventory, plan = inspect_batch(root, max_steps)
        if inspect:
            return inventory
        history = root/'resume-history'
        history.mkdir(exist_ok=True)
        log = history/('batch-'+uuid4().hex+'.json')
        result = {**inventory, 'tasks': [], 'status': 'running', 'log': str(log)}
        save_json(log, result)
        planned = {p['task_id']: p for p in plan['tasks']} if plan else {}
        try:
            for item in inventory['tasks']:
                record = dict(item)
                print(f"[resume-batch] {item['task_id']}: {item['action']}", flush=True)
                try:
                    if item['action'] == 'blocked':
                        record['status'] = 'blocked'
                    elif item['action'] in ('resume', 'skip_completed'):
                        report = resume_task(item['state'], config_path, max_steps, model_factory, budget_options)
                        record.update(status='skipped_completed' if item['action']=='skip_completed' else 'resumed',
                                      repair_success=report['repair_success'], agent_status=report['agent_status'])
                    else:
                        report = start_planned(root, plan, planned[item['task_id']], config_path,
                                               max_steps, budget_options, model_factory)
                        record.update(status='started', repair_success=report['repair_success'], agent_status=report['agent_status'])
                except (ValueError, BusyError) as error:
                    record.update(status='blocked', reason=str(error))
                except Exception as error:
                    record.update(status='error', error_type=type(error).__name__)
                except BaseException:
                    record['status'] = 'interrupted'
                    raise
                finally:
                    result['tasks'].append(record)
                    save_json(log, result)
            result['status'] = 'finished_with_pending' if (result['unrecoverable_unstarted'] or any(
                r.get('status') in ('blocked', 'error') or r.get('agent_status') == 'budget_exhausted'
                for r in result['tasks'])) else 'finished'
        except BaseException:
            result['status'] = 'interrupted'
            raise
        finally:
            save_json(log, result)
        return result
