"""Execution backends. Docker never falls back to host execution."""
import subprocess
import sys
from pathlib import Path
from uuid import uuid4


class Executor:
    def __init__(self, backend="local", image="python:3.11-slim"):
        if backend not in {"local", "docker"}:
            raise ValueError("Unknown execution backend")
        self.backend, self.image = backend, image

    def check(self):
        if self.backend == "docker":
            try:
                result = subprocess.run(["docker", "info", "--format", "{{.OSType}}"],
                    capture_output=True, text=True, timeout=15, check=True)
                if result.stdout.strip() != "linux":
                    raise RuntimeError("Docker must use Linux containers")
                subprocess.run(["docker", "image", "inspect", self.image],
                    capture_output=True, timeout=15, check=True)
            except (OSError, subprocess.SubprocessError) as error:
                raise RuntimeError(f"Docker unavailable or image missing; start Docker and pull {self.image}") from error

    def run(self, root, args, stdout, stderr, timeout=30):
        if self.backend == "local":
            return subprocess.run([sys.executable, *args], cwd=root, stdout=stdout,
                                  stderr=stderr, timeout=timeout)
        root = Path(root).resolve()
        if "," in str(root):
            raise ValueError("Docker mount paths cannot contain commas")
        name = "fixlab-" + uuid4().hex
        command = ["docker", "run", "--name", name, "--rm", "--pull=never",
            "--network=none", "--memory=256m", "--memory-swap=256m", "--cpus=1",
            "--pids-limit=64", "--cap-drop=ALL", "--security-opt=no-new-privileges",
            "--read-only", "--user=65534:65534", "--log-driver=none",
            "--tmpfs", "/tmp:rw,nosuid,nodev,size=128m,mode=1777",
            "--mount", f"type=bind,source={root},target=/source,readonly",
            "--entrypoint", "/bin/sh", self.image, "-c",
            'mkdir /tmp/work && cp -R /source/. /tmp/work/ && cd /tmp/work && exec python "$@"',
            "fixlab", *args]
        try:
            return subprocess.run(command, stdout=stdout, stderr=stderr, timeout=timeout)
        finally:
            # Killing docker's client does not kill container children. Remove by unique name.
            try:
                cleanup = subprocess.run(["docker", "rm", "-f", name],
                    capture_output=True, timeout=15)
                if cleanup.returncode and b"No such container" not in cleanup.stderr:
                    raise RuntimeError(f"Container cleanup failed: {name}")
            except (OSError, subprocess.SubprocessError) as error:
                raise RuntimeError(f"Cannot confirm container cleanup: {name}") from error
