import argparse
import json
from pathlib import Path
from .core import APIModel, DemoModel, Store, Workspace, run
from .config import load_config
from .evaluation import run_evaluated
from uuid import uuid4
from .benchmark import evaluate
from .execution import Executor
from .comparison import compare
from .importer import import_task
from .resume import inspect_resume, resume_task
from .delivery import deliver
import sys
from .budget import validate
from .dashboard import generate


def _main():
    parser = argparse.ArgumentParser(description="FixLab: trusted local code repair MVP")
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo")
    demo.add_argument("--output", default=".fixlab/demo")
    repair = commands.add_parser("run")
    repair.add_argument("workspace")
    repair.add_argument("--task", required=True)
    repair.add_argument("--model")
    repair.add_argument("--config", default="fixlab.local.toml")
    repair.add_argument("--state", help="Existing state to resume, or a new state path")
    repair.add_argument("--max-steps", type=int, default=12)
    report = commands.add_parser("report")
    report.add_argument("state")
    dashboard = commands.add_parser("dashboard", help="Generate an offline read-only HTML report")
    dashboard.add_argument("source", nargs="?", default=".fixlab")
    dashboard.add_argument("--output", default=".fixlab/reports/index.html")
    batch = commands.add_parser("evaluate")
    batch.add_argument("suite", nargs="?", default="benchmarks")
    batch.add_argument("--output")
    batch.add_argument("--task-id")
    batch.add_argument("--config", default="fixlab.local.toml")
    batch.add_argument("--model")
    batch.add_argument("--max-steps", type=int, default=12)
    comparison = commands.add_parser("compare")
    comparison.add_argument("suite", nargs="?", default="benchmarks_advanced")
    comparison.add_argument("--output")
    comparison.add_argument("--task-id")
    comparison.add_argument("--config", default="fixlab.local.toml")
    comparison.add_argument("--model")
    comparison.add_argument("--max-steps", type=int, default=12)
    comparison.add_argument("--repeats", type=int, default=3)
    for command in (repair, batch):
        command.add_argument("--self-check", choices=["on", "off"], default="on")
    for command in (repair, batch, comparison):
        command.add_argument("--backend", choices=["local", "docker"], default="local")
        command.add_argument("--image", default="python:3.11-slim")
    importer = commands.add_parser("import-task", help="Export a local Git commit as a benchmark task")
    importer.add_argument("repository")
    importer.add_argument("--commit", required=True)
    importer.add_argument("--output", required=True)
    importer.add_argument("--description-file", required=True)
    importer.add_argument("--public-tests", required=True)
    importer.add_argument("--hidden-tests", required=True)
    resume = commands.add_parser("resume", help="Resume a saved evaluated task")
    resume.add_argument("state")
    resume.add_argument("--config", default="fixlab.local.toml")
    resume.add_argument("--max-steps", type=int)
    resume.add_argument("--inspect", action="store_true", help="Show saved settings without calling the model")
    delivery = commands.add_parser("deliver", help="Review or apply an accepted patch to a new worktree")
    delivery.add_argument("state")
    delivery.add_argument("repository")
    delivery.add_argument("--commit", required=True)
    delivery.add_argument("--branch")
    delivery.add_argument("--output")
    delivery.add_argument("--apply", action="store_true")
    for command in (repair, batch, comparison, resume):
        command.add_argument('--max-tokens', type=int, help='Cumulative per-task reported token limit')
        command.add_argument('--max-seconds', type=float, help='Cumulative cooperative agent runtime limit')
        command.add_argument('--input-price', type=float, help='Input price per million tokens')
        command.add_argument('--output-price', type=float, help='Output price per million tokens')
        command.add_argument('--currency', help='Currency label for user-supplied prices')
    args = parser.parse_args()
    budget_options = {key: getattr(args, key) for key in
                      ('max_tokens', 'max_seconds', 'input_price', 'output_price', 'currency')
                      if getattr(args, key, None) is not None}
    try:
        validate(budget_options)
    except ValueError as error:
        parser.error(str(error))
    if args.command == "dashboard":
        try:
            result = generate(args.source, args.output)
        except (ValueError, OSError) as error:
            parser.error(str(error))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if args.command == "deliver":
        try:
            result = deliver(args.state,args.repository,args.commit,args.branch,args.output,args.apply)
        except (ValueError,OSError,RuntimeError) as error:
            parser.error(str(error))
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return
    if args.command == "resume":
        try:
            result = inspect_resume(args.state,args.max_steps) if args.inspect else resume_task(args.state,args.config,args.max_steps,budget_options=budget_options)
        except Exception as error:
            if isinstance(error,(ValueError,FileNotFoundError)):
                parser.error(str(error))
            parser.error(f"Resume failed: {type(error).__name__}; inspect report and retry events")
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return
    if args.command == "import-task":
        try:
            result = import_task(args.repository, args.commit, args.output, args.description_file,
                                 args.public_tests, args.hidden_tests)
        except (ValueError, OSError) as error:
            parser.error(str(error))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if args.command == "report":
        if not Path(args.state).is_file():
            parser.error("State file does not exist")
        print(json.dumps(Store(args.state).events(), ensure_ascii=False, indent=2))
        return
    if args.command == "demo":
        root = Path(args.output).resolve()
        root.mkdir(parents=True, exist_ok=False)
        repo = root / "repo"
        repo.mkdir()
        (repo / "calculator.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
        (repo / "test_calculator.py").write_text(
            "import unittest\nfrom calculator import add\n\nclass Tests(unittest.TestCase):\n"
            "    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n", encoding="utf-8")
        workspace = Workspace(repo)
        baseline = workspace.execute("run_tests", {})
        status = run(Store(root / "state.sqlite"), workspace, DemoModel(), "Fix add")
        acceptance = workspace.execute("run_tests", {})
        result = {"mode": "scripted-demo", "status": status,
                  "baseline": json.loads(baseline), "acceptance": json.loads(acceptance)}
        (root / "report.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, indent=2))
        return
    if args.max_steps < 1:
        parser.error("--max-steps must be positive")
    if args.command == "compare" and args.repeats < 1:
        parser.error("--repeats must be positive")
    if args.command == "run" and not Path(args.workspace).is_dir():
        parser.error("Workspace must be an existing directory")
    try:
        config = load_config(args.config, args.model)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    if args.command == "compare":
        output = args.output or str(Path(".fixlab/comparisons") / uuid4().hex[:12])
        print(f"Comparison output: {Path(output).resolve()}", flush=True)
        try:
            result = compare(args.suite, output, lambda enabled: APIModel(**config, self_check=enabled),
                             args.repeats, args.max_steps, args.task_id, Executor(args.backend, args.image), budget_options=budget_options or None)
        except (ValueError, OSError, RuntimeError) as error:
            parser.error(str(error))
        print(json.dumps(result["groups"], ensure_ascii=False, indent=2))
        return
    if args.command == "evaluate":
        output = args.output or str(Path(".fixlab/evals") / uuid4().hex[:12])
        print(f"Evaluation output: {Path(output).resolve()}", flush=True)
        try:
            result = evaluate(args.suite, output, lambda: APIModel(**config, self_check=args.self_check == "on"),
                              args.max_steps, args.task_id, Executor(args.backend, args.image), budget_options=budget_options or None)
        except (ValueError, OSError, RuntimeError) as error:
            parser.error(str(error))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    state = args.state or str(Path(".fixlab/runs") / uuid4().hex[:12] / "state.sqlite")
    print(f"Task state: {Path(state).resolve()}", flush=True)
    try:
        result = run_evaluated(Workspace(args.workspace, Executor(args.backend, args.image)), APIModel(**config, self_check=args.self_check == "on"), args.task,
                               state, args.max_steps, budget_options=budget_options or None)
    except (ValueError, RuntimeError) as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main():
    try:
        _main()
    except KeyboardInterrupt:
        print("\nInterrupted. Saved task records are retained. Use resume --inspect before continuing; an interrupted tool may require manual inspection.", file=sys.stderr)
        raise SystemExit(130)
