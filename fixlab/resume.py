"""Recover an evaluated task and update its containing batch without replaying tools."""
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4
from .core import APIModel, Workspace
from .config import load_config
from .execution import Executor
from .evaluation import run_evaluated, save_json


def inspect_resume(state, max_steps=None):
    state = Path(state).resolve()
    if not state.is_file():
        raise ValueError('State file does not exist')
    artifacts = state.parent / (state.stem + '-artifacts')
    baseline = json.loads((artifacts / 'baseline.json').read_text(encoding='utf-8'))
    report_path = artifacts / 'report.json'
    report = json.loads(report_path.read_text(encoding='utf-8')) if report_path.exists() else {}
    with closing(sqlite3.connect(state.as_uri() + '?mode=ro', uri=True)) as db:
        events = [(k,json.loads(p)) for k,p in db.execute('SELECT kind,payload FROM events ORDER BY id')]
    task = next((p for k,p in events if k=='task'), None)
    if task != {'root': baseline['root'], 'task': baseline['task']}:
        raise ValueError('State and baseline identity do not match')
    started = {p['id'] for k,p in events if k=='tool_started'}
    finished = {p['tool_call_id'] for k,p in events if k=='message' and p.get('role')=='tool'}
    if started-finished:
        raise ValueError('Uncertain tool execution; automatic replay blocked. Inspect workspace first.')
    if not Path(baseline['root']).is_dir():
        raise ValueError('Saved workspace no longer exists')
    summary_path = state.parent.parent / 'summary.json'
    summary = json.loads(summary_path.read_text(encoding='utf-8')) if summary_path.exists() else {}
    limit = max_steps if max_steps is not None else baseline.get('max_steps',report.get('max_steps',summary.get('max_steps',12)))
    if limit < 1:
        raise ValueError('max_steps must be positive')
    model = baseline.get('model',report.get('model'))
    if not model or model=='scripted-demo':
        raise ValueError('Cannot infer a real model for this task')
    steps = sum(k=='message' and p.get('role')=='assistant' for k,p in events)
    return {'state':str(state),'workspace':baseline['root'],'task':baseline['task'],
            'model':model,'backend':baseline.get('backend','local'),
            'image':baseline.get('image') or 'python:3.11-slim',
            'self_check':baseline.get('self_check_enabled',report.get('self_check_enabled',True)),
            'budget':baseline.get('budget', {}),
            'max_steps':limit,'used_steps':steps,'remaining_steps':max(0,limit-steps),
            'already_completed':any(k=='completed' for k,p in events)}


def refresh_batch(state, report):
    state=Path(state).resolve(); path=state.parent.parent/'summary.json'
    if not path.exists(): return
    summary=json.loads(path.read_text(encoding='utf-8'))
    matching=[i for i,r in enumerate(summary.get('results',[])) if r.get('state') and Path(r['state']).resolve()==state]
    if len(matching)!=1: return
    # Preserve initial experiment evidence before changing the aggregate.
    archive=path.parent/'resume-history';archive.mkdir(exist_ok=True)
    save_json(archive/(uuid4().hex+'.json'),summary)
    index=matching[0]; previous=summary['results'][index]
    outcome = ('execution_error' if report.get('error_type') else
               'baseline_already_passed' if report['baseline_acceptance']['passed'] else
               'repaired' if report['repair_success'] else
               'budget_exhausted' if report['agent_status']=='budget_exhausted' else 'acceptance_failed')
    summary['results'][index]={**previous,**report,'outcome':outcome,'resumed':True}
    rows=summary['results']
    summary['successes']=sum(bool(r.get('repair_success')) for r in rows)
    summary['tasks_finished']=len(rows)
    summary['success_rate']=summary['successes']/summary['tasks_total']
    known=[r.get('tokens',{}).get('total_tokens') for r in rows]
    summary['reported_total_tokens']=sum(v for v in known if v is not None)
    summary['token_usage_complete']=(len(rows)==summary['tasks_total'] and all(v is not None for v in known)
        and not any(r.get('usage_may_be_incomplete') or r.get('error_type') for r in rows))
    summary['contains_resumed_trials']=True
    save_json(path,summary)
    # Do not silently mix extra-budget resumed trials into an original comparison.
    comparison=path.parent.parent/'comparison.json'
    if comparison.exists():
        save_json(path.parent.parent/'resume-notice.json', {
            'comparison_unchanged':True, 'reason':'A child task was resumed. Original comparison is preserved; run a fresh paired experiment.',
            'updated_batch':str(path)})


def resume_task(state, config_path='fixlab.local.toml', max_steps=None, model_factory=None, budget_options=None):
    plan=inspect_resume(state,max_steps)
    state=Path(plan['state']);output=state.parent/(state.stem+'-artifacts');report_path=output/'report.json'
    if plan['already_completed']:
        if not report_path.exists(): raise ValueError('Completed state has no report')
        return json.loads(report_path.read_text(encoding='utf-8'))
    if plan['remaining_steps']==0:
        raise ValueError('No model steps remain; increase --max-steps (cumulative limit)')
    model=(model_factory(plan) if model_factory else
           APIModel(**load_config(config_path,plan['model']),self_check=plan['self_check']))
    if report_path.exists():
        history=output/'resume-history';history.mkdir(exist_ok=True)
        save_json(history/(uuid4().hex+'.json'),json.loads(report_path.read_text(encoding='utf-8')))
    try:
        return run_evaluated(Workspace(plan['workspace'],Executor(plan['backend'],plan['image'])),
                             model,plan['task'],state,plan['max_steps'], budget_options=({**plan['budget'], **budget_options} if budget_options else None))
    finally:
        if report_path.exists():
            report=json.loads(report_path.read_text(encoding='utf-8'))
            refresh_batch(state,report)
