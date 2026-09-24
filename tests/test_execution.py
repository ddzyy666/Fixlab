import subprocess
import tempfile
import unittest
from unittest.mock import patch
from fixlab.execution import Executor


class ExecutorTests(unittest.TestCase):
    def test_timeout_removes_container(self):
        with tempfile.TemporaryDirectory() as root, patch('fixlab.execution.subprocess.run') as call:
            call.side_effect = [subprocess.TimeoutExpired('docker', 1),
                                subprocess.CompletedProcess([], 0, b'', b'')]
            with self.assertRaises(subprocess.TimeoutExpired):
                Executor('docker').run(root, ['-c', 'pass'], None, None, timeout=1)
            command = call.call_args_list[0].args[0]
            self.assertIn('--network=none', command)
            self.assertIn('--read-only', command)
            self.assertIn('--memory=256m', command)
            self.assertIn('--pids-limit=64', command)
            self.assertTrue(any('target=/source,readonly' in x for x in command))
            name = command[command.index('--name')+1]
            self.assertEqual(call.call_args_list[1].args[0], ['docker','rm','-f',name])

    def test_unavailable_docker_fails_closed(self):
        with patch('fixlab.execution.subprocess.run', side_effect=FileNotFoundError):
            with self.assertRaisesRegex(RuntimeError, 'Docker unavailable'):
                Executor('docker').check()

    def test_cleanup_failure_is_reported(self):
        with tempfile.TemporaryDirectory() as root, patch('fixlab.execution.subprocess.run') as call:
            call.side_effect = [subprocess.CompletedProcess([],0),
                                subprocess.CompletedProcess([],1,b'',b'daemon unavailable')]
            with self.assertRaisesRegex(RuntimeError, 'cleanup failed'):
                Executor('docker').run(root, ['-c','pass'], None, None)
