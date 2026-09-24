"""Review and deliver an accepted repair into a new local Git worktree."""
import base64
import json
from pathlib import Path
from uuid import uuid4
from .importer import git, safe_name, excluded
from .evaluation import snapshot, acceptance, save_json, is_test
from .execution import Executor


def prepare(state, repository, commit):
    state, repo = Path(state).resolve(), Path(repository).resolve()
    if not state.is_file(): raise ValueError('State file does not exist')
    artifacts=state.parent/(state.stem+'-artifacts')
    baseline=json.loads((artifacts/'baseline.json').read_text(encoding='utf-8'))
    report=json.loads((artifacts/'report.json').read_text(encoding='utf-8'))
    if not report.get('repair_success'):
        raise ValueError('Delivery requires completed execution and successful acceptance; resume unfinished tasks first')
    if Path(report['state']).resolve()!=state:
        raise ValueError('Report belongs to another state')
    if git(repo,'status','--porcelain').strip():
        raise ValueError('Source repository must have a clean working tree')
    revision=git(repo,'rev-parse','--verify','--end-of-options',commit+'^{commit}').decode().strip()
    if git(repo,'rev-parse','HEAD').decode().strip()!=revision:
        raise ValueError('Source HEAD differs from requested baseline commit')
    before=baseline['files']
    tracked={}
    for entry in git(repo,'ls-tree','-r','-z',revision).split(b'\0'):
        if not entry: continue
        meta,name=entry.split(b'\t',1);name=name.decode('utf-8')
        mode,kind,oid=meta.decode().split()
        if not safe_name(name): raise ValueError('Unsupported source path')
        if excluded(name): continue
        if kind!='blob' or mode not in ('100644','100755'):
            raise ValueError('Linked files and submodules are unsupported')
        tracked[name]=base64.b64encode(git(repo,'cat-file','blob',oid)).decode()
    if any(before.get(name)!=content for name,content in tracked.items()):
        raise ValueError('Source commit content does not match the saved baseline')
    if any(name not in tracked and not is_test(name) for name in before):
        raise ValueError('Baseline contains business files absent from source commit')
    workspace=Path(baseline['root'])
    if not workspace.is_dir(): raise ValueError('Repair workspace is missing')
    after=snapshot(workspace)
    changed=sorted(k for k in before.keys() | after.keys() if before.get(k)!=after.get(k))
    if not changed: raise ValueError('No patch to deliver')
    if any(not safe_name(k) or excluded(k) or is_test(k) for k in changed):
        raise ValueError('Patch includes tests or protected/unsupported paths')
    return repo,revision,baseline,after,changed,artifacts


def deliver(state, repository, commit, branch=None, output=None, apply=False):
    repo,revision,baseline,after,changed,artifacts=prepare(state,repository,commit)
    plan={'source_commit':revision,'changed_files':changed,'source_repository':str(repo),
          'patch':str(artifacts/'changes.diff'),'applied':False}
    if not apply: return plan
    if not branch or not output: raise ValueError('--branch and --output are required with --apply')
    if branch.startswith('-'): raise ValueError('Invalid branch name')
    git(repo,'check-ref-format','--branch',branch)
    if git(repo,'branch','--list',branch).strip(): raise ValueError('Branch already exists')
    target=Path(output).resolve()
    if target.exists() or target.is_relative_to(repo) or target.is_relative_to(Path(baseline['root']).resolve()):
        raise ValueError('Output must be a new directory outside source and repair workspaces')
    executor=Executor(baseline.get('backend','local'),baseline.get('image') or 'python:3.11-slim')
    executor.check()
    checked=acceptance(baseline['files'],after,executor,baseline.get('hidden'))
    if not checked['passed']: raise ValueError('Current patch failed fresh acceptance; no worktree created')
    # Recheck immediately before mutation. No commit/merge/push is performed.
    if git(repo,'status','--porcelain').strip() or git(repo,'rev-parse','HEAD').decode().strip()!=revision:
        raise ValueError('Source repository changed during validation')
    git(repo,'worktree','add','-b',branch,str(target),revision)
    record={**plan,'worktree':str(target),'branch':branch,'status':'applying'}
    delivery_path=artifacts/('delivery-'+uuid4().hex+'.json')
    save_json(delivery_path,record)
    try:
        for name in changed:
            path=target/name
            if not path.resolve().is_relative_to(target): raise ValueError('Patch path escapes worktree')
            if name in after:
                path.parent.mkdir(parents=True,exist_ok=True)
                path.write_bytes(base64.b64decode(after[name]))
            else:
                path.unlink()
        final=acceptance(baseline['files'],snapshot(target),executor,baseline.get('hidden'))
        record.update(applied=True,status='ready_for_review' if final['passed'] else 'validation_failed',acceptance=final)
        if not final['passed']: raise ValueError('Delivered worktree failed acceptance; retained for inspection')
    except BaseException as error:
        record.update(status='failed',error_type=type(error).__name__)
        raise
    finally:
        # Preserve worktree on failure; do not delete files a user might inspect or edit.
        save_json(delivery_path,record)
    return {**record,'delivery_report':str(delivery_path)}
