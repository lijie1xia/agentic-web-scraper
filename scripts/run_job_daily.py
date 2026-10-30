"""每日导入并输出变化摘要，可选个人微信通知；全程不调用模型。"""
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
        notification = config.get('notification', {'enabled': False})
        if not isinstance(notification, dict) or not isinstance(notification.get('enabled'), bool):
            raise ValueError('通知配置必须包含布尔值 enabled')
        if notification['enabled']:
            notify_command = notification.get('command')
            if notification.get('target') != 'weixin':
                raise ValueError('通知配置 target 仅支持 weixin')
            if (not isinstance(notify_command, list) or not notify_command
                    or any(not isinstance(part, str) or not part.strip() for part in notify_command)):
                raise ValueError('通知配置 command 必须是非空字符串列表')
        inputs, boards = config.get('inputs', []), config.get('boards', [])
        campus = config.get('campus', {})
        inbox = config.get('inbox')
        if not inputs and not boards and campus.get('enabled') is not True and not inbox:
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
        inbox_errors = []
        if inbox:
            inbox_run = subprocess.run(
                [sys.executable, '-S', str(ROOT / 'scripts/run_job_workflow.py'), '--db', str(database),
                 'import-inbox', str(resolve_path(inbox))],
                cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=300)
            if not inbox_run.stdout.strip():
                inbox_errors.append(inbox_run.stderr.strip() or '收件箱导入未返回结果')
            else:
                inbox_outcome = json.loads(inbox_run.stdout)
                inbox_errors.extend(inbox_outcome.get('errors') or [])
        if not inputs and not boards and campus.get('enabled') is not True:
            command = [sys.executable, '-S', str(ROOT / 'scripts/run_job_workflow.py'), '--db', str(database),
                       'report', '--output', str(report)]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=300)
        if not result.stdout.strip():
            raise RuntimeError(result.stderr.strip() or '岗位任务未返回执行结果')
        outcome = json.loads(result.stdout)
        if result.returncode not in (0, 1) or ('errors' not in outcome and 'report_changed' not in outcome):
            raise RuntimeError(result.stderr.strip() or '岗位任务执行失败')
        notice = report.read_text(encoding='utf-8')
        errors = list(outcome.get('errors') or []) + inbox_errors
        if errors:
            notice += '\n来源异常（其他来源继续处理）：\n' + '\n'.join(errors) + '\n'
        previous = state.read_text(encoding='utf-8') if state.exists() else None
        if notice != previous:
            print(notice, end='', flush=True)
            # 先确认标准输出成功，再投递；不在本次运行中重试结果未知的发送。
            if notification['enabled']:
                delivery = subprocess.run(
                    notification['command'] + ['send', '--to', notification['target'], '--json'],
                    cwd=ROOT, input=notice, capture_output=True, text=True,
                    encoding='utf-8', timeout=30, shell=False,
                )
                if delivery.returncode != 0:
                    raise RuntimeError(f'通知命令失败（退出码 {delivery.returncode}）')
                accepted = json.loads(delivery.stdout)
                if not isinstance(accepted, dict) or accepted.get('success') is not True:
                    raise RuntimeError('通知未获 CLI 确认成功')
            # 启用通知时，只有 CLI 确认接受投递后才能推进状态。
            state.parent.mkdir(parents=True, exist_ok=True)
            state.write_text(notice, encoding='utf-8')
        # 单个来源失败属于摘要内容；脚本无法运行才作为调度器执行失败。
        return 0
    except (OSError, ValueError, TypeError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f'每日岗位任务失败：{exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
