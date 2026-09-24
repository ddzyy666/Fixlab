import tempfile
import unittest
from pathlib import Path
from fixlab.core import DemoModel, Store, Workspace, run


class HarnessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = Workspace(self.root)
        self.store = Store(self.root / "state.sqlite")
        self.addCleanup(self.store.db.close)
        (self.root / "calculator.py").write_text("def add(a,b): return a-b", encoding="utf-8")

    def test_path_escape(self):
        for path in ["../outside.py", ".git/config", ".env"]:
            with self.assertRaises(ValueError):
                self.workspace.path(path)

    def test_budget_and_resume(self):
        self.assertEqual(run(self.store, self.workspace, DemoModel(), "fix", 1), "budget_exhausted")
        self.assertEqual(run(self.store, self.workspace, DemoModel(), "fix", 5), "completed")
        self.assertIn("return a + b", (self.root / "calculator.py").read_text())
        before = len(self.store.events())
        self.assertEqual(run(self.store, self.workspace, DemoModel(), "fix", 5), "completed")
        self.assertEqual(len(self.store.events()), before)

    def test_uncertain_tool_is_not_replayed(self):
        run(self.store, self.workspace, DemoModel(), "fix", 1)
        self.store.add("tool_started", {"id": "interrupted-write"})
        with self.assertRaisesRegex(RuntimeError, "replay blocked"):
            run(self.store, self.workspace, DemoModel(), "fix", 5)

    def test_task_mismatch(self):
        run(self.store, self.workspace, DemoModel(), "fix", 1)
        with self.assertRaises(ValueError):
            run(self.store, self.workspace, DemoModel(), "different", 5)
