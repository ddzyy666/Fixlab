"""Sequential benchmark execution with fresh workspaces and durable summaries."""
import base64
import hashlib
import json
from pathlib import Path

from .core import Workspace
from .budget import validate
from .evaluation import run_evaluated, save_json, snapshot
from .locking import exclusive


def evaluate(suite, output, model_factory, max_steps=12, task_id=None, executor=None, budget_options=None):
    with exclusive(output, 'batch'):
        return _evaluate(suite, output, model_factory, max_steps, task_id, executor, budget_options)


def _evaluate(suite, output, model_factory, max_steps=12, task_id=None, executor=None, budget_options=None):
    validate(budget_options)
    if executor:
        executor.check()
    suite, output = Path(suite).resolve(), Path(output).resolve()
    manifests = sorted(suite.glob("*/task.json"))
    if task_id:
        manifests = [p for p in manifests if p.parent.name == task_id]
    if not manifests:
        raise ValueError("No matching benchmark tasks found")
    tasks = []
    for manifest in manifests:
        task = json.loads(manifest.read_text(encoding="utf-8"))
        if not isinstance(task.get("task"), str) or not task["task"].strip():
            raise ValueError(f"Missing task description: {manifest}")
        repo = manifest.parent / "repo"
        if not repo.is_dir() or repo.is_symlink():
            raise ValueError(f"Missing or linked repository: {repo}")
        hidden_dir = manifest.parent / "hidden"
        if hidden_dir.is_symlink():
            raise ValueError("Hidden test directory cannot be linked")
        hidden = snapshot(hidden_dir) if hidden_dir.is_dir() else {}
        for name in hidden:
            if Path(name).name != name or not name.startswith("test_hidden_") or not name.endswith(".py"):
                raise ValueError("Hidden tests must be flat test_hidden_*.py files")
        tasks.append((manifest.parent.name, task["task"], snapshot(repo), hidden))
    if output.is_relative_to(suite):
        raise ValueError("Output must be outside benchmark sources")
    output.mkdir(parents=True, exist_ok=False)
    # Freeze all inputs and non-secret model settings before the first task starts.
    models = [model_factory() for _ in tasks]
    plan = {'version': 1, 'max_steps': max_steps, 'budget': budget_options or {},
            'backend': executor.backend if executor else 'local',
            'image': executor.image if executor else 'python:3.11-slim', 'tasks': []}
    for (name, description, files, hidden), model in zip(tasks, models):
        digest = hashlib.sha256(json.dumps([description, files, hidden], sort_keys=True).encode()).hexdigest()
        plan['tasks'].append({'task_id': name, 'task': description, 'files': files, 'hidden': hidden,
                              'source_sha256': digest, 'model': getattr(model, 'model', 'scripted-demo'),
                              'self_check': getattr(model, 'self_check_enabled', False)})
    save_json(output / 'batch-plan.json', plan)
    rows = []
    summary = {}
    def persist():
        summary.update({"tasks_total": len(tasks), "tasks_finished": len(rows),
                        "successes": sum(r.get("repair_success", False) for r in rows),
                        "results": rows, "max_steps": max_steps, "budget": budget_options or {}})
        summary["success_rate"] = summary["successes"] / len(tasks)
        known = [r.get("tokens", {}).get("total_tokens") for r in rows]
        summary["reported_total_tokens"] = sum(v for v in known if v is not None)
        summary["token_usage_complete"] = (len(rows) == len(tasks) and all(v is not None for v in known)
            and not any(r.get("usage_may_be_incomplete") or r.get("error_type") for r in rows))
        save_json(output / "summary.json", summary)
    persist()
    for (task_id, description, files, hidden), model in zip(tasks, models):
        print(f"[{len(rows)+1}/{len(tasks)}] {task_id}", flush=True)
        folder = output / task_id
        repo = folder / "workspace"
        repo.mkdir(parents=True)
        for name, content in files.items():
            path = repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(base64.b64decode(content))
        digest = hashlib.sha256(json.dumps([description, files, hidden], sort_keys=True).encode()).hexdigest()
        save_json(folder / "task.json", {"task": description, "source_sha256": digest})
        report = {}
        error_type = None
        try:
            report = run_evaluated(Workspace(repo, executor), model, description,
                                   folder / "state.sqlite", max_steps, hidden, budget_options)
        except Exception as error:
            # Do not persist provider error text, which may contain credentials.
            error_type = type(error).__name__
            report_path = folder / "state-artifacts/report.json"
            if report_path.exists():
                report = json.loads(report_path.read_text(encoding="utf-8"))
        if error_type:
            outcome = "execution_error"
        elif report.get("baseline_acceptance", {}).get("passed"):
            outcome = "baseline_already_passed"
        elif report.get("repair_success"):
            outcome = "repaired"
        elif report.get("agent_status") == "budget_exhausted":
            outcome = "budget_exhausted"
        else:
            outcome = "acceptance_failed"
        rows.append({**report, "task_id": task_id, "source_sha256": digest,
                     "outcome": outcome, "error_type": error_type,
                     "repair_success": bool(report.get("repair_success")) and not error_type})
        persist()
    return summary
