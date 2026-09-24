import tempfile
import unittest
from pathlib import Path

from fixlab.core import DemoModel, Workspace
from fixlab.evaluation import acceptance, snapshot, run_evaluated


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        (self.repo / "calculator.py").write_text("def add(a,b): return a-b\n")
        (self.repo / "test_calculator.py").write_text(
            "import unittest\nfrom calculator import add\n"
            "class TestAdd(unittest.TestCase):\n"
            " def test_add(self): self.assertEqual(add(2,3),5)\n")

    def test_repair_report_and_resume(self):
        state = self.root / "state.sqlite"
        report = run_evaluated(Workspace(self.repo), DemoModel(), "fix", state)
        self.assertTrue(report["repair_success"])
        self.assertFalse(report["baseline_acceptance"]["passed"])
        self.assertEqual(report["acceptance"]["tests_run"], 1)
        self.assertIsNone(report["tokens"]["total_tokens"])
        diff = (self.root / "state-artifacts/changes.diff").read_text()
        self.assertIn("+    return a + b", diff)
        resumed = run_evaluated(Workspace(self.repo), DemoModel(), "fix", state)
        self.assertTrue(resumed["repair_success"])
        self.assertEqual(diff, (self.root / "state-artifacts/changes.diff").read_text())

    def test_modified_test_cannot_make_broken_code_pass(self):
        before = snapshot(self.repo)
        (self.repo / "test_calculator.py").write_text("# removed test\n")
        checked = acceptance(before, snapshot(self.repo))
        self.assertFalse(checked["passed"])
        self.assertEqual(checked["tests_run"], 1)

    def test_no_tests_is_not_success(self):
        self.assertFalse(acceptance({}, {})["passed"])

    def test_error_still_writes_report(self):
        class BrokenModel:
            def reply(self, messages):
                raise RuntimeError("offline")
        with self.assertRaisesRegex(RuntimeError, "offline"):
            run_evaluated(Workspace(self.repo), BrokenModel(), "fix", self.root / "error.sqlite")
        import json
        report = json.loads((self.root / "error-artifacts/report.json").read_text())
        self.assertEqual(report["agent_status"], "error")
        self.assertFalse(report["repair_success"])

    def test_state_inside_workspace_rejected(self):
        with self.assertRaisesRegex(ValueError, "outside"):
            run_evaluated(Workspace(self.repo), DemoModel(), "fix", self.repo / "state.sqlite")
