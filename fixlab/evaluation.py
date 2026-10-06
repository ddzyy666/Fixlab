"""Host-side snapshots, patch generation and original-test acceptance."""
import base64
import difflib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .core import Store, run, APIModel
from .execution import Executor
from .budget import Budget, BudgetExceeded, validate, accounting

IGNORED = {".git", ".fixlab", ".venv", "venv", "__pycache__", ".env", "fixlab.local.toml"}


def snapshot(root):
    files = {}
    for directory, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if d not in IGNORED and not Path(directory, d).is_symlink()]
        for name in names:
            path = Path(directory, name)
            if name in IGNORED or path.is_symlink() or path.suffix == ".pyc":
                continue
            files[path.relative_to(root).as_posix()] = base64.b64encode(path.read_bytes()).decode()
    return files


def is_test(name):
    path = Path(name)
    return path.name.startswith("test") and path.suffix == ".py" or "tests" in path.parts


def save_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def acceptance(before, after, executor=None, hidden=None):
    # Reconstruct candidate code with original tests, outside the agent workspace.
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        candidate = {k: v for k, v in after.items() if not is_test(k)}
        candidate.update({k: v for k, v in before.items() if is_test(k)})
        if hidden:
            for name, value in hidden.items():
                if Path(name).name != name or not name.startswith("test_hidden_") or not name.endswith(".py"):
                    raise ValueError("Hidden tests must be flat test_hidden_*.py files")
                if name in before or name in after:
                    raise ValueError("Hidden test filename conflicts with workspace")
                candidate[name] = value
        for name, value in candidate.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(base64.b64decode(value))
        script = (
            "import unittest,json; "
            "s=unittest.defaultTestLoader.discover('.'); "
            "r=unittest.TextTestRunner(verbosity=2).run(s); "
            "print(json.dumps({'tests_run':r.testsRun,'failures':len(r.failures),"
            "'errors':len(r.errors),'skipped':len(r.skipped),'passed':r.wasSuccessful() "
            "and r.testsRun>len(r.skipped)}))"
        )
        with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
            try:
                process = (executor or Executor()).run(root, ["-B", "-c", script],
                                         stdout=output, stderr=errors, timeout=30)
            except subprocess.TimeoutExpired:
                return {"passed": False, "reason": "timeout"}
            output.seek(0)
            errors.seek(0)
            stdout = output.read(1024 * 1024).decode("utf-8", errors="replace")
            log = errors.read(16000).decode("utf-8", errors="replace")
            try:
                result = json.loads(stdout.strip().splitlines()[-1])
                if not isinstance(result, dict) or "tests_run" not in result:
                    raise ValueError("Invalid test result")
            except (ValueError, IndexError):
                result = {"passed": False, "reason": "test_runner_error"}
            result["passed"] = bool(result.get("passed")) and process.returncode == 0
            return {**result, "exit_code": process.returncode, "output": log}


def write_diff(path, before, after):
    parts = []
    for name in sorted(before.keys() | after.keys()):
        if before.get(name) == after.get(name):
            continue
        try:
            old = base64.b64decode(before.get(name, "")).decode("utf-8-sig")
            new = base64.b64decode(after.get(name, "")).decode("utf-8-sig")
            lines = difflib.unified_diff(old.splitlines(keepends=True), new.splitlines(keepends=True),
                fromfile=f"a/{name}" if name in before else "/dev/null",
                tofile=f"b/{name}" if name in after else "/dev/null")
            for line in lines:
                parts.append(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n")
        except UnicodeDecodeError:
            parts.append(f"Binary file changed: {name}\n")
    path.write_text("".join(parts), encoding="utf-8")


def run_evaluated(workspace, model, task, state, max_steps=12, hidden=None, budget_options=None):
    if budget_options is not None:
        validate(budget_options)
    workspace.executor.check()
    self_check_enabled = isinstance(model, APIModel) and model.self_check_enabled
    state = Path(state).resolve()
    if state.is_relative_to(workspace.root):
        raise ValueError("State and reports must be outside the target workspace")
    output = state.parent / (state.stem + "-artifacts")
    output.mkdir(parents=True, exist_ok=True)
    baseline_path = output / "baseline.json"
    store = Store(state)
    try:
        events = store.events()
        if events and events[0] != ("task", {"root": str(workspace.root), "task": task}):
            raise ValueError("Saved task/workspace does not match this run")
        if baseline_path.exists():
            baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
            if baseline.get("self_check_enabled", isinstance(model, APIModel)) != self_check_enabled:
                raise ValueError("Resume must use the original self-check mode")
            if hidden is not None and baseline.get("hidden", {}) != hidden:
                raise ValueError("Hidden tests changed since the original run")
            if baseline["root"] != str(workspace.root) or baseline["task"] != task:
                raise ValueError("Baseline belongs to another task")
            if baseline.get("backend", "local") != workspace.executor.backend or baseline.get("image") != (workspace.executor.image if workspace.executor.backend == "docker" else None):
                raise ValueError("Resume must use the original execution backend and image")
        else:
            if events:
                raise ValueError("Old task has no pre-repair snapshot; use a new --state file")
            before = snapshot(workspace.root)
            baseline = {"root": str(workspace.root), "task": task, "files": before,
                        "hidden": hidden or {}, "self_check_enabled": self_check_enabled,
                        "backend": workspace.executor.backend,
                        "image": workspace.executor.image if workspace.executor.backend == "docker" else None,
                        "acceptance": acceptance(before, before, workspace.executor, hidden)}
            save_json(baseline_path, baseline)
        baseline.setdefault("model", getattr(model, "model", "scripted-demo"))
        baseline["max_steps"] = max_steps
        baseline["budget"] = validate(budget_options if budget_options is not None else baseline.get("budget", {}))
        save_json(baseline_path, baseline)
        start = time.monotonic()
        budget = Budget(store, baseline["budget"])
        stop_reason = None
        status = "error"
        error_type = None
        def completion_check():
            current = snapshot(workspace.root)
            changed = any(baseline["files"].get(k) != current.get(k)
                          for k in baseline["files"].keys() | current.keys() if not is_test(k))
            public = acceptance(baseline["files"], current, workspace.executor)
            diagnostic = {"passed": True, "required": False}
            if self_check_enabled:
                diagnostic = {"passed": False, "reason": "Call self_check with requirement-based unittest cases before finishing"}
                calls = [p for k, p in store.events() if k == "tool_started" and p["function"]["name"] == "self_check"]
                if calls:
                    try:
                        from .selfcheck import check
                        args = json.loads(calls[-1]["function"]["arguments"])
                        if not args["requirements"].strip():
                            raise ValueError("Empty checklist")
                        diagnostic = check(workspace, args["test_code"])
                    except (ValueError, KeyError, TypeError):
                        diagnostic = {"passed": False, "reason": "Invalid self_check arguments"}
                store.add("self_check_final", diagnostic)
            return {"passed": changed and public["passed"] and diagnostic["passed"], "code_changed": changed,
                    "public_acceptance": public, "self_check": diagnostic}
        try:
            status = run(store, workspace, model, task, max_steps, completion_check, budget)
        except BudgetExceeded as error:
            status = "budget_exhausted"
            stop_reason = error.reason
            store.add("budget_exhausted", {"reason": stop_reason})
        except BaseException as error:
            error_type = type(error).__name__
            raise
        finally:
            store.add("execution_seconds", time.monotonic() - start)
            after = snapshot(workspace.root)
            before = baseline["files"]
            write_diff(output / "changes.diff", before, after)
            public = acceptance(before, after, workspace.executor)
            checked = acceptance(before, after, workspace.executor, baseline.get("hidden")) if baseline.get("hidden") else public
            events = store.events()
            usage = [p for k, p in events if k == "usage"]
            tokens = {key: sum(p.get(key, 0) or 0 for p in usage)
                      if any(key in p for p in usage) else None
                      for key in ("prompt_tokens", "completion_tokens", "total_tokens")}
            report = {
                "agent_status": status, "acceptance": checked,
                "error_type": error_type,
                "patch_status": "passed" if checked["passed"] else "failed",
                "execution_status": "completed" if status == "completed" else ("budget_exhausted" if status == "budget_exhausted" else "interrupted"),
                "self_check_status": "disabled" if not self_check_enabled else ("passed" if status == "completed" else "incomplete"),
                "max_steps": max_steps,
                "self_check_enabled": self_check_enabled,
                "public_acceptance": public, "has_hidden_tests": bool(baseline.get("hidden")),
                "backend": workspace.executor.backend, "image": baseline.get("image"),
                "baseline_acceptance": baseline["acceptance"],
                "repair_success": status == "completed" and checked["passed"]
                                  and not baseline["acceptance"]["passed"],
                "changed_files": sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k)),
                "changed_test_files": sorted(k for k in before.keys() | after.keys()
                                             if is_test(k) and before.get(k) != after.get(k)),
                "model": getattr(model, "model", "scripted-demo"),
                "tokens": tokens, "cost": accounting(events, baseline["budget"])["cost"],
                "budget": baseline["budget"],
                "budget_stop_reason": stop_reason or ("max_steps" if status == "budget_exhausted" else None),
                "self_check_calls": sum(k == "tool_started" and p["function"]["name"] == "self_check" for k, p in events),
                "self_check_final": next((p for k, p in reversed(events) if k == "self_check_final"), None),
                "api_retry_events": [p for k, p in events if k == "api_retry"],
                "usage_may_be_incomplete": any(k == "api_retry" for k, p in events),
                "completion_rejections": sum(k == "completion_check" and not p["passed"] for k, p in events),
                "execution_seconds": sum(p for k, p in events if k == "execution_seconds"),
                "state": str(state), "artifacts": str(output),
            }
            if report["cost"] is not None and error_type:
                report["cost"]["complete"] = False
            save_json(output / "report.json", report)
        return report
    finally:
        store.db.close()
