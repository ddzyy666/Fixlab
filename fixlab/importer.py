"""Export a committed local Git snapshot into the existing benchmark format."""
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path, PurePosixPath


def git(repo, *args):
    env = {**os.environ, 'GIT_TERMINAL_PROMPT': '0'}
    try:
        return subprocess.run(['git', '-C', str(repo), *args], env=env,
                              capture_output=True, check=True, timeout=30).stdout
    except subprocess.CalledProcessError:
        raise ValueError('Git command failed; verify repository and commit') from None


def safe_name(name):
    parts = PurePosixPath(name).parts
    return bool(parts) and not PurePosixPath(name).is_absolute() and all(
        p not in ('.', '..') and not any(c in p for c in '\\:<>"|?*')
        and not p.endswith((' ', '.')) and p.split('.')[0].upper() not in
        {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1,10)), *(f'LPT{i}' for i in range(1,10))}
        for p in parts)


def excluded(name):
    parts = [p.lower() for p in PurePosixPath(name).parts]
    return any(p in {'.git', '.fixlab', '.venv', 'venv', '__pycache__', 'fixlab.local.toml'}
               or p == '.env' or p.startswith('.env.') for p in parts) or parts[-1].endswith(('.pem', '.key', '.pyc'))


def load_tests(directory, prefix):
    root = Path(directory).resolve()
    if not root.is_dir():
        raise ValueError('Test directory must exist')
    files = {}
    for p in sorted(root.iterdir()):
        if p.name == '__pycache__':
            continue
        if p.is_symlink() or not p.is_file() or not p.name.startswith(prefix) or p.suffix != '.py':
            raise ValueError(f'Tests must be flat {prefix}*.py files')
        if p.stat().st_size > 2_000_000:
            raise ValueError('Test file exceeds 2 MB')
        files[p.name] = p.read_bytes()
    if not files:
        raise ValueError('At least one test file is required')
    return files


def import_task(repository, commit, output, description_file, public_tests, hidden_tests):
    repo, output = Path(repository).resolve(), Path(output).resolve()
    if not repo.is_dir() or output.is_relative_to(repo):
        raise ValueError('Repository must exist and output must be outside it')
    if output.exists():
        raise ValueError('Output task directory already exists')
    description = Path(description_file).read_text(encoding='utf-8-sig').strip()
    if not description:
        raise ValueError('Task description cannot be empty')
    # Resolve once; every file comes from immutable Git object IDs, never the working tree.
    revision = git(repo, 'rev-parse', '--verify', '--end-of-options', commit + '^{commit}').decode().strip()
    if not re.fullmatch(r'[0-9a-f]{40,64}', revision):
        raise ValueError('Invalid resolved commit')
    public = load_tests(public_tests, 'test_public_')
    hidden = load_tests(hidden_tests, 'test_hidden_')
    files, skipped = {}, []
    total = 0
    for entry in git(repo, 'ls-tree', '-r', '-z', revision).split(b'\0'):
        if not entry:
            continue
        meta, raw_name = entry.split(b'\t', 1)
        mode, kind, oid = meta.decode().split()
        name = raw_name.decode('utf-8')
        if not safe_name(name):
            raise ValueError('Unsupported path in Git snapshot')
        if excluded(name):
            skipped.append(name)
            continue
        if kind != 'blob' or mode not in ('100644', '100755'):
            raise ValueError('Symlinks and submodules are unsupported; choose a self-contained repository')
        size = int(git(repo, 'cat-file', '-s', oid))
        total += size
        if size > 2_000_000 or total > 20_000_000:
            raise ValueError('Snapshot exceeds import limits (2 MB/file, 20 MB total)')
        files[name] = git(repo, 'cat-file', 'blob', oid)
    lowered = {n.casefold() for n in files}
    if len(lowered) != len(files):
        raise ValueError('Case-colliding paths are unsupported')
    if any(n.casefold() in lowered for n in public.keys() | hidden.keys()):
        raise ValueError('Regression test name conflicts with repository file')
    files.update(public)
    manifest = {'task': description, 'source': {'repository_name': repo.name, 'commit': revision,
                'skipped_paths': skipped, 'test_runner': 'unittest',
                'files_sha256': {k: hashlib.sha256(v).hexdigest() for k,v in sorted(files.items())},
                'hidden_sha256': {k: hashlib.sha256(v).hexdigest() for k,v in sorted(hidden.items())}}}
    # Validate everything before creating output; never change the source checkout.
    output.mkdir(parents=True, exist_ok=False)
    for subdir, mapping in [('repo', files), ('hidden', hidden)]:
        for name, content in mapping.items():
            path = output / subdir / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    (output / 'task.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return {'output': str(output), 'commit': revision, 'files': len(files),
            'public_tests': len(public), 'hidden_tests': len(hidden), 'skipped_paths': skipped}
