"""Bounded literal source search with no shell or external dependency."""
import os
from pathlib import Path

SKIP_DIRS = {'.git', '.fixlab', '.venv', 'venv', '__pycache__', 'node_modules', 'build', 'dist'}
MAX_FILE_BYTES = 2_000_000
MAX_TOTAL_BYTES = 20_000_000
MAX_FILES = 2000


def protected(path):
    return any(p.lower() in SKIP_DIRS or p.lower() == 'fixlab.local.toml'
               or p.lower() == '.env' or p.lower().startswith('.env.') for p in path.parts) or path.suffix.lower() in {'.pem', '.key', '.pyc'}


def search_text(root, path, query, max_results):
    if not isinstance(query, str) or not query.strip() or len(query) > 1000 or '\n' in query or '\r' in query:
        raise ValueError('query must be a nonempty single-line string of at most 1000 characters')
    if type(max_results) is not int or not 1 <= max_results <= 100:
        raise ValueError('max_results must be an integer from 1 to 100')
    if not isinstance(path, str):
        raise ValueError('path must be a workspace-relative file or directory')
    root = Path(root).resolve()
    candidate = root/path
    target = candidate.resolve()
    if not target.is_relative_to(root):
        raise ValueError('Search path must stay inside workspace')
    if protected(candidate.relative_to(root)) or protected(target.relative_to(root)):
        raise ValueError('Protected search path')
    if candidate.is_symlink() or any(p.is_symlink() for p in candidate.parents if p != root and p.is_relative_to(root)):
        raise ValueError('Linked search paths are unsupported')
    if not target.exists():
        raise ValueError('Search path does not exist')

    def files():
        if target.is_file():
            yield target
            return
        for directory, dirs, names in os.walk(target, followlinks=False):
            dirs[:] = sorted(d for d in dirs if not protected(Path(d)) and not d.startswith('.')
                             and not Path(directory, d).is_symlink())
            for name in sorted(names):
                p = Path(directory, name)
                if not protected(p.relative_to(root)) and not p.is_symlink():
                    yield p

    result = {'matches': [], 'truncated': False, 'limit_reason': None, 'files_scanned': 0,
              'files_skipped': 0, 'case_sensitive': True}
    total = 0
    output_size = 0
    for index, file in enumerate(files()):
        if index >= MAX_FILES:
            result.update(truncated=True, limit_reason='file_count')
            break
        try:
            if not file.resolve().is_relative_to(root) or not file.is_file():
                result['files_skipped'] += 1
                continue
            if file.stat().st_size > MAX_FILE_BYTES:
                result['files_skipped'] += 1
                continue
            if total + file.stat().st_size > MAX_TOTAL_BYTES:
                result.update(truncated=True, limit_reason='total_bytes')
                break
            with file.open('rb') as stream:
                raw = stream.read(MAX_FILE_BYTES + 1)
            total += len(raw)
            if len(raw) > MAX_FILE_BYTES or b'\0' in raw:
                result['files_skipped'] += 1
                continue
            lines = raw.decode('utf-8-sig').splitlines()
        except (OSError, UnicodeError):
            result['files_skipped'] += 1
            continue
        result['files_scanned'] += 1
        for number, line in enumerate(lines, 1):
            position = line.find(query)
            if position < 0:
                continue
            if len(result['matches']) >= max_results:
                result.update(truncated=True, limit_reason='max_results')
                return result
            start = max(0, position - 100)
            snippet = line[start:start + max(500, len(query) + 100)]
            name = file.relative_to(root).as_posix()
            output_size += len(snippet) + len(name) + 100
            if output_size > 14000:
                result.update(truncated=True, limit_reason='output_size')
                return result
            result['matches'].append({'path': name, 'line': number, 'text': snippet,
                                      'line_truncated': start > 0 or len(snippet) < len(line)})
    return result
