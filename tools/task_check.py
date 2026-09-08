"""Print work packets or run checks; elapsed time is checks, not agent labor."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from datetime import datetime, timezone


def _repo():
    return Path(__file__).resolve().parents[1]


def _load(path):
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('schema_version') != 1 or not isinstance(data.get('tasks'), list):
        raise ValueError('invalid contract schema')
    tasks = data['tasks']
    ids = [t.get('id') for t in tasks if isinstance(t, dict)]
    if len(ids) != len(tasks) or any(not isinstance(x, str) for x in ids) or len(set(ids)) != len(ids):
        raise ValueError('task IDs must be unique strings')
    return tasks


def _safe(repo, value, required=True):
    if not isinstance(value, str) or not value or os.path.isabs(value):
        raise ValueError('paths must be nonempty relative strings')
    raw = value.split('#', 1)[0]
    if not raw:
        raise ValueError('read path must name a file')
    path = (repo / raw).resolve()
    if repo != path and repo not in path.parents:
        raise ValueError('path escapes repository')
    if required and not path.is_file():
        raise ValueError(f'missing file: {value}')
    return path


def _check(task, repo):
    for key in ('id', 'objective'):
        if not isinstance(task.get(key), str) or not task[key].strip():
            raise ValueError(f'{key} required')
    for key in ('files', 'reads', 'acceptance', 'evidence'):
        if not isinstance(task.get(key), list) or not task[key]:
            raise ValueError(f'{key} must be a nonempty list')
    for path in task['files']:
        _safe(repo, path, required=False)
    for path in task['reads']:
        _safe(repo, path)
    for item in task['evidence']:
        if not isinstance(item, str) or not item.strip():
            raise ValueError('evidence must contain nonempty strings')
    for command in task['acceptance']:
        if (not isinstance(command, list) or not command
                or any(not isinstance(arg, str) or not arg for arg in command)):
            raise ValueError('acceptance must be argv arrays of nonempty strings')


def _python(repo):
    windows = repo / '.venv/Scripts/python.exe'
    return str(windows if windows.exists() else repo / '.venv/bin/python')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task', required=True)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--contracts', default='docs/tasks.json')
    parser.add_argument('--log', default='~/reticle-store/notes/development.jsonl')
    parser.add_argument('--model')
    parser.add_argument('--review-corrections', type=int)
    parser.add_argument('--tokens', type=int)
    args = parser.parse_args(argv)
    for value in (args.review_corrections, args.tokens):
        if value is not None and value < 0:
            raise ValueError('telemetry counts must be nonnegative or omitted')
    repo = _repo()
    tasks = _load(repo / args.contracts)
    matches = [task for task in tasks if task['id'] == args.task]
    if len(matches) != 1:
        raise ValueError('task id must select exactly one contract')
    task = matches[0]
    _check(task, repo)
    if not args.run:
        print(json.dumps(task, indent=2))
        return 0
    checks = []
    for declared in task['acceptance']:
        command = [_python(repo) if arg == '{python}' else arg for arg in declared]
        started = time.monotonic()
        try:
            result = subprocess.run(command, cwd=repo, capture_output=True,
                                    text=True, shell=False)
            code, out, err = result.returncode, result.stdout, result.stderr
        except (OSError, subprocess.SubprocessError) as exc:
            code, out, err = 1, '', str(exc)
        checks.append(dict(command=command, exit=code, stdout=out, stderr=err,
                           elapsed_seconds=time.monotonic() - started))
    passed = all(check['exit'] == 0 for check in checks)
    row = dict(schema_version=1, time=datetime.now(timezone.utc).isoformat(),
               task=args.task, checks=checks, passed=passed,
               elapsed_check_seconds=sum(check['elapsed_seconds'] for check in checks),
               model=args.model, corrections=args.review_corrections, tokens=args.tokens,
               contract_sha256=hashlib.sha256(json.dumps(task, sort_keys=True).encode()).hexdigest())
    log = Path(args.log).expanduser()
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(row, separators=(',', ':')) + '\n')
    print(f"{args.task}: {'PASS' if passed else 'FAIL'} ({len(checks)} checks); evidence: {log}")
    for check in checks:
        if check['exit']:
            print(check['stdout'] + check['stderr'], file=sys.stderr)
    return 0 if passed else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError) as exc:
        print(f'task-check: {exc}', file=sys.stderr)
        raise SystemExit(2)
