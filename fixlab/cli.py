import argparse
import json
from pathlib import Path
from .core import APIModel, DemoModel, Store, Workspace, run
from .config import load_config
from .evaluation import run_evaluated
from uuid import uuid4
from .benchmark import evaluate
from .execution import Executor


def main():
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
    batch = commands.add_parser("evaluate")
    batch.add_argument("suite", nargs="?", default="benchmarks")
    batch.add_argument("--output")
    batch.add_argument("--task-id")
    batch.add_argument("--config", default="fixlab.local.toml")
    batch.add_argument("--model")
    batch.add_argument("--max-steps", type=int, default=12)
    for command in (repair, batch):
        command.add_argument("--backend", choices=["local", "docker"], default="local")
        command.add_argument("--image", default="python:3.11-slim")
    args = parser.parse_args()
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
    if args.command == "run" and not Path(args.workspace).is_dir():
        parser.error("Workspace must be an existing directory")
    try:
        config = load_config(args.config, args.model)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    if args.command == "evaluate":
        output = args.output or str(Path(".fixlab/evals") / uuid4().hex[:12])
        print(f"Evaluation output: {Path(output).resolve()}", flush=True)
        try:
            result = evaluate(args.suite, output, lambda: APIModel(**config),
                              args.max_steps, args.task_id, Executor(args.backend, args.image))
        except (ValueError, OSError, RuntimeError) as error:
            parser.error(str(error))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    state = args.state or str(Path(".fixlab/runs") / uuid4().hex[:12] / "state.sqlite")
    print(f"Task state: {Path(state).resolve()}", flush=True)
    try:
        result = run_evaluated(Workspace(args.workspace, Executor(args.backend, args.image)), APIModel(**config), args.task,
                               state, args.max_steps)
    except (ValueError, RuntimeError) as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False, indent=2))
