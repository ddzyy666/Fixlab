"""Model-authored diagnostic tests; no hidden acceptance data is used."""
import base64
from .evaluation import acceptance, snapshot


def check(workspace, code):
    files = snapshot(workspace.root)
    name = "test_fixlab_self_check.py"
    files.pop(name, None)
    tests = {name: base64.b64encode(code.encode("utf-8")).decode()}
    return acceptance(tests, files, workspace.executor)
