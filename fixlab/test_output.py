"""Keep complete tool logs on disk and return bounded diagnostics to the model."""
import shutil
from uuid import uuid4


def summarize(stream, exit_code, log_dir=None):
    log_file = None
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        path = log_dir / ('tests-' + uuid4().hex + '.log')
        stream.seek(0)
        with path.open('wb') as target:
            shutil.copyfileobj(stream, target)
        log_file = str(path)
    size = stream.seek(0, 2)
    limit = 1200 if exit_code == 0 else 6000
    stream.seek(max(0, size-limit))
    tail = stream.read(limit).decode('utf-8', errors='replace')
    # unittest -q retains the final count and failures without per-test success lines.
    if exit_code == 0:
        position = tail.rfind('Ran ')
        if position >= 0:
            tail = tail[position:]
    return {'exit_code': exit_code, 'output': tail, 'log_file': log_file,
            'output_truncated': size > limit}
