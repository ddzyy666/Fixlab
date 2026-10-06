"""Offline, read-only HTML views of saved runs. No model or web server required."""
import html
import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


MARKER = '<!-- FixLab offline report v1 -->'
MAX_TEXT = 200_000
MAX_EVENTS = 500
MAX_TASKS = 500


def escaped(value):
    return html.escape(str(value), quote=True)


def read_text(path, limit=MAX_TEXT):
    if path.is_symlink():
        raise ValueError('Linked artifacts are not supported')
    with path.open(encoding='utf-8-sig', errors='replace') as stream:
        content = stream.read(limit + 1)
    return content[:limit], len(content) > limit


def discover(source):
    """Only discover SQLite task files; do not follow linked directories."""
    source = Path(source).absolute()
    if source.is_symlink():
        raise ValueError('Source cannot be a symbolic link')
    if not source.exists():
        raise ValueError('Report source does not exist')
    if source.is_file():
        if source.suffix != '.sqlite':
            raise ValueError('Source must be a task .sqlite file or a directory')
        return [source], False
    found = []
    for directory, dirs, names in os.walk(source, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in {'.git', 'workspace', 'repo', 'resume-history', '__pycache__'}
                         and not Path(directory, d).is_symlink())
        for name in sorted(names):
            path = Path(directory, name)
            if path.suffix == '.sqlite' and not path.is_symlink():
                found.append(path)
                if len(found) > MAX_TASKS:
                    return found[:MAX_TASKS], True
    return found, False


def load_task(state):
    state = Path(state)
    artifacts = state.parent / (state.stem + '-artifacts')
    row = {'state': str(state), 'report': {}, 'events': [], 'diff': '', 'warnings': []}
    if artifacts.is_symlink():
        row['warnings'].append('报告目录为链接，未读取。')
    else:
        report_path = artifacts / 'report.json'
        if report_path.exists():
            try:
                raw, truncated = read_text(report_path, 2_000_000)
                report = json.loads(raw) if not truncated else None
                if not isinstance(report, dict):
                    raise ValueError('Invalid report')
                row['report'] = report
            except (ValueError, OSError):
                row['warnings'].append('报告无法读取或超过大小限制。')
        else:
            row['warnings'].append('尚无报告：任务可能仍在运行或已中断。')
        diff_path = artifacts / 'changes.diff'
        if diff_path.exists():
            try:
                row['diff'], truncated = read_text(diff_path)
                if truncated:
                    row['warnings'].append('代码差异已截断为前 200,000 字符。')
            except (ValueError, OSError):
                row['warnings'].append('代码差异无法读取。')
    try:
        with closing(sqlite3.connect(state.resolve().as_uri() + '?mode=ro', uri=True, timeout=1)) as db:
            db.execute('PRAGMA query_only=ON')
            events = db.execute('SELECT id, kind, substr(payload,1,?) FROM events ORDER BY id LIMIT ?',
                                (MAX_TEXT + 1, MAX_EVENTS + 1)).fetchall()
        if len(events) > MAX_EVENTS:
            row['warnings'].append('轨迹已截断为前 500 条事件。')
        for event_id, kind, raw in events[:MAX_EVENTS]:
            try:
                payload = json.loads(raw) if len(raw) <= MAX_TEXT else '[事件内容超过大小限制]'
            except (ValueError, TypeError):
                payload = '[事件内容无法解析]'
            row['events'].append((event_id, kind, payload))
    except (sqlite3.Error, OSError, ValueError):
        row['warnings'].append('轨迹数据库不可读；其他任务仍可查看。')
    return row


def pretty(value):
    return escaped(json.dumps(value, ensure_ascii=False, indent=2))


def render_task(row, index, label):
    report = row['report']
    status = ('success' if report.get('repair_success') else
              'unknown' if not report else 'failed')
    status_text = {'success': '修复成功', 'unknown': '状态未知', 'failed': '未成功'}[status]
    tokens = report.get('tokens') or {}
    tokens = tokens if isinstance(tokens, dict) else {}
    seconds = report.get('execution_seconds')
    duration = f'{seconds:.1f} s' if isinstance(seconds, (int, float)) else '未知'
    task = next((p.get('task', '') for _, k, p in row['events'] if k == 'task' and isinstance(p, dict)), '')
    warnings = ''.join(f'<p class="warning">{escaped(w)}</p>' for w in row['warnings'])
    metrics = {'执行': report.get('execution_status', report.get('agent_status', '未知')),
               '补丁': report.get('patch_status', '未知'), '自检': report.get('self_check_status', '未知'),
               '后端': report.get('backend', '未知'), '停止原因': report.get('budget_stop_reason') or '无',
               '异常类型': report.get('error_type') or '无', '预算': report.get('budget', {}),
               '费用估算': report.get('cost'), '用量可能缺失': report.get('usage_may_be_incomplete', False)}
    tests = {key: report.get(key) for key in ('baseline_acceptance', 'public_acceptance', 'acceptance', 'self_check_final')}
    changes = ''.join('<span class="' + ('added' if line.startswith('+') else 'removed' if line.startswith('-') else 'context')
                      + '">' + escaped(line) + '</span>\n' for line in row['diff'].splitlines())
    events = []
    for event_id, kind, payload in row['events']:
        title = kind
        if isinstance(payload, dict):
            if kind == 'message':
                title += ' / ' + str(payload.get('role', ''))
            if kind == 'tool_started':
                function = payload.get('function')
                if isinstance(function, dict):
                    title += ' / ' + str(function.get('name', ''))
        events.append(f'<details class="event"><summary>#{escaped(event_id)} · {escaped(title)}</summary><pre>{pretty(payload)}</pre></details>')
    search = escaped(label + ' ' + str(task) + ' ' + str(report.get('model', '')))
    return f'''<article class="task" data-status="{status}" data-search="{search}">
<details id="task-{index}"><summary class="task-heading"><span><strong>{escaped(label)}</strong>
<small>{escaped(report.get('model', '模型未知'))}</small></span><span class="badge {status}">{status_text}</span>
<span>{escaped(tokens.get('total_tokens', '未知'))} tokens</span><span>{duration}</span></summary>
<div class="body">{warnings}<p class="task-description">{escaped(task)}</p><p class="path">{escaped(row['state'])}</p>
<details open><summary>运行状态与预算</summary><pre>{pretty(metrics)}</pre></details>
<details><summary>原始测试、最终验收与模型自检</summary><p>模型自检不等于独立验收。隐藏测试：{escaped(report.get('has_hidden_tests', '未知'))}</p><pre>{pretty(tests)}</pre></details>
<details><summary>代码差异 · {escaped(report.get('changed_files', []))}</summary><pre class="diff">{changes or '没有可显示的差异。'}</pre></details>
<details><summary>执行轨迹 · {len(row['events'])} 条记录</summary><div>{''.join(events) or '没有可显示的记录。'}</div></details>
</div></details></article>''', status


STYLE = '''
:root{font-family:Segoe UI,Microsoft YaHei,sans-serif;color:#1d3040;background:#f3f6f8;color-scheme:light}
*{box-sizing:border-box}body{margin:0}main{max-width:1180px;margin:auto;padding:40px 24px}
header{border-top:5px solid #137a71;padding:24px 0}h1{font-size:32px;margin:4px 0 12px}p{line-height:1.65}
.eyebrow{color:#137a71;font-size:13px;letter-spacing:2px;font-weight:700}.muted,small,.path{color:#607383}
.stats{display:flex;gap:16px;flex-wrap:wrap;margin:24px 0}.stat{background:white;border:1px solid #d7e1e7;border-radius:12px;padding:18px 24px;min-width:140px}.stat b{font-size:28px;display:block}
.controls{display:flex;gap:12px;margin-bottom:20px}input,select{font:inherit;padding:12px;border:1px solid #bdccd6;border-radius:8px;background:white}input{flex:1;min-width:0}
.task{background:white;border:1px solid #d7e1e7;border-radius:12px;margin:12px 0;overflow:hidden}summary{cursor:pointer;padding:14px;overflow-wrap:anywhere}
.task-heading{display:flex;align-items:center;gap:20px}.task-heading>span:first-child{flex:1;min-width:0}.task-heading small{display:block;margin-top:6px}.body{padding:0 20px 20px;border-top:1px solid #e3e9ee}
.badge{border-radius:20px;padding:6px 12px;font-size:13px;white-space:nowrap}.success{color:#12634e;background:#e4f4ec}.failed{color:#984a20;background:#fff0df}.unknown{background:#edf0f4;color:#526478}
pre{white-space:pre-wrap;overflow-wrap:anywhere;font-family:Consolas,monospace;font-size:13px;line-height:1.65;padding:16px;background:#f5f7f9;border-radius:8px;margin:0 0 14px;max-height:540px;overflow:auto}
.added{background:#ddf5e7;color:#175237}.removed{background:#ffe5e4;color:#8a302d}.diff span{display:block}.diff{white-space:pre-wrap}.event{margin-left:12px;border-left:2px solid #dce5eb}
.warning{background:#fff0df;padding:12px;border-radius:8px}.path{font-size:12px;overflow-wrap:anywhere}.task-description{white-space:pre-wrap}footer{margin-top:28px;font-size:13px;color:#607383}
[hidden]{display:none!important}summary:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid #137a71;outline-offset:2px}
@media(max-width:700px){main{padding:20px 12px}.task-heading{flex-wrap:wrap;gap:10px}.task-heading>span:first-child{flex-basis:100%}.controls{flex-direction:column}.stat{flex:1;min-width:110px;padding:14px}.body{padding:0 10px 12px}}
'''

SCRIPT = '''
const search=document.getElementById('search'),filter=document.getElementById('filter');
function update(){let count=0;for(const task of document.querySelectorAll('.task')){
const shown=task.dataset.search.toLowerCase().includes(search.value.toLowerCase()) && (filter.value==='all'||task.dataset.status===filter.value);
task.hidden=!shown;if(shown)count++;}document.getElementById('visible').textContent='显示 '+count+' 个任务';}
search.addEventListener('input',update);filter.addEventListener('change',update);update();
'''


def generate(source='.fixlab', output='.fixlab/reports/index.html'):
    states, truncated = discover(source)
    source = Path(source).resolve()
    output = Path(output).absolute()
    if output.suffix.lower() != '.html' or output.is_symlink():
        raise ValueError('Output must be an unlinked .html file')
    if output.exists():
        beginning, _ = read_text(output, len(MARKER))
        if beginning != MARKER:
            raise ValueError('Refusing to overwrite a file not generated by FixLab')
    cards, counts = [], {'success': 0, 'failed': 0, 'unknown': 0}
    base = source if source.is_dir() else source.parent
    for index, state in enumerate(states):
        row = load_task(state)
        card, status = render_task(row, index, state.relative_to(base).as_posix())
        cards.append(card)
        counts[status] += 1
    timestamp = datetime.now(timezone.utc).isoformat(timespec='seconds')
    stats = ''.join(f'<div class="stat"><b>{value}</b>{label}</div>' for label, value in
                    [('任务总数', len(cards)), ('修复成功', counts['success']), ('未成功', counts['failed']), ('状态未知', counts['unknown'])])
    document = f'''{MARKER}
<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>FixLab · 修复报告</title><style>{STYLE}</style></head><body><main>
<header><div class="eyebrow">FIXLAB / RUN REPORTS</div><h1>每一次修复，都有据可查。</h1>
<p class="muted">本地只读快照 · 展开任务查看验收、代码差异与执行轨迹</p>
<p class="path">来源：{escaped(source)}<br>生成时间（UTC）：{timestamp}</p></header>
<div class="stats">{stats}</div><div class="controls"><input id="search" aria-label="搜索任务" placeholder="搜索任务路径、描述或模型…">
<select id="filter" aria-label="筛选结果"><option value="all">全部结果</option><option value="success">修复成功</option><option value="failed">未成功</option><option value="unknown">状态未知</option></select></div>
<p id="visible" class="muted"></p>{'<p class="warning">仅展示前 500 个任务；请缩小源目录。</p>' if truncated else ''}
{''.join(cards) or '<p>没有发现任务记录。请指定包含 .sqlite 状态文件的目录。</p>'}
<footer>页面为生成时的快照，重新执行命令可刷新。报告包含代码、提示词及本地路径，未自动脱敏，请仅在本地查看。<br>缺失记录不代表成功；模型自检不能替代独立测试。</footer>
</main><script>{SCRIPT}</script></body></html>'''
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(document, encoding='utf-8')
    return {'output': str(output.resolve()), 'tasks': len(cards), **counts, 'truncated': truncated}
