"""每日导入并输出变化摘要；可由 Hermes 的 no_agent 定时任务直接运行。"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def resolve_path(value):
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='无模型调用的每日岗位导入与变化摘要')
    parser.add_argument('--config', default=str(ROOT / 'config/job_sources.json'))
    args = parser.parse_args(argv)
    try:
        config = json.loads(resolve_path(args.config).read_text(encoding='utf-8-sig'))
        inputs, boards = config.get('inputs', []), config.get('boards', [])
        campus = config.get('campus', {})
        if not inputs and not boards and campus.get('enabled') is not True:
            raise ValueError('请至少配置一个已核验的岗位来源')
        report = resolve_path(config.get('report', 'output/job_workflow/daily.txt'))
        state = resolve_path(config.get('notice_state', 'output/job_workflow/last_notice.txt'))
        database = resolve_path(config.get('database', 'output/job_workflow/jobs.sqlite3'))
        command = [sys.executable, '-S', str(ROOT / 'scripts/run_job_workflow.py'), '--db', str(database)]
        for field in ('profile', 'resume'):
            if config.get(field):
                command.extend(['--' + field, str(resolve_path(config[field]))])
        command.extend(['cycle', '--report', str(report)])
        for path in inputs:
            command.extend(['--input', str(resolve_path(path))])
        for board in boards:
            command.extend(['--board', board])
        if campus.get('enabled') is True:
            command.extend(['--campus', '--campus-pages', str(campus.get('pages', 1)), '--campus-limit', str(campus.get('max_jobs', 8))])
            for url in campus.get('known_urls', []):
                command.extend(['--campus-url', url])
        if config.get('allow_network') is True:
            command.append('--allow-network')
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=300)
        if not result.stdout.strip():
            raise RuntimeError(result.stderr.strip() or '岗位任务未返回执行结果')
        outcome = json.loads(result.stdout)
        if result.returncode not in (0, 1) or 'errors' not in outcome:
            raise RuntimeError(result.stderr.strip() or '岗位任务执行失败')
        notice = report.read_text(encoding='utf-8')
        if outcome['errors']:
            notice += '\n来源异常（其他来源继续处理）：\n' + '\n'.join(outcome['errors']) + '\n'
        previous = state.read_text(encoding='utf-8') if state.exists() else None
        if notice != previous:
            print(notice, end='', flush=True)
            state.parent.mkdir(parents=True, exist_ok=True)
            state.write_text(notice, encoding='utf-8')
        # 单个来源失败属于摘要内容；脚本无法运行才作为调度器执行失败。
        return 0
    except (OSError, ValueError, TypeError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f'每日岗位任务失败：{exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
