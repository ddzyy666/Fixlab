"""Nonblocking OS locks, released on process exit; never unlink lock files."""
import os
import threading
from contextlib import contextmanager
from pathlib import Path

_local = threading.local()


class BusyError(RuntimeError):
    pass


def lock_path(target, kind):
    target = Path(target).resolve()
    return target.parent / ('.' + target.name + '.fixlab-' + kind + '.lock')


@contextmanager
def exclusive(target, kind):
    path = lock_path(target, kind)
    held = getattr(_local, 'held', None)
    if held is None or getattr(_local, 'pid', None) != os.getpid():
        held = _local.held = set()
        _local.pid = os.getpid()
    if path in held:
        yield
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        if stream.seek(0, 2) == 0:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise BusyError(f'{kind} is busy in another process: {Path(target).resolve()}') from None
        held.add(path)
        try:
            yield
        finally:
            held.remove(path)
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
