"""Local workflow CLI. No command invokes an LLM or submits applications."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .execution import prepare_handoff
from .service import ROOT, Workflow
from .sources import fetch_greenhouse, load_export


def _json(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='离线求职审核工作流：不调用LLM，不自动发送')
    parser.add_argument('--db', default=str(ROOT/'output/job_workflow/jobs.sqlite3'))
    parser.add_argument('--profile', help='可选：求职画像 JSON')
    parser.add_argument('--resume', help='可选：已核实的简历事实 JSON，不是自动上传附件')
    parser.add_argument('--channel', choices=['chat','email'], default='chat')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('init', help='建立本地 SQLite 数据库')
    importing = commands.add_parser('import-json', help='导入已有抽取/评分 JSON，离线重新评分')
    importing.add_argument('path')
    paste = commands.add_parser('paste', help='从 UTF-8 文件读取 JD 原文')
    paste.add_argument('path')
    paste.add_argument('--url', default='')
    discover = commands.add_parser('discover-greenhouse', help='读取指定公司的 Greenhouse 官方公开职位 API')
    discover.add_argument('board')
    discover.add_argument('--allow-network', action='store_true')
    report = commands.add_parser('report', help='查看本地摘要，不读取站内回复')
    report.add_argument('--output', help='可选：写入摘要文件，内容不变则不重复写')
    cycle = commands.add_parser('cycle', help='可重复的只读来源导入/分析/日报任务，不审批不发送')
    cycle.add_argument('--input', action='append', default=[], help='本地 JSON；可重复')
    cycle.add_argument('--board', action='append', default=[], help='Greenhouse board token；可重复')
    cycle.add_argument('--allow-network', action='store_true')
    cycle.add_argument('--report', default=str(ROOT/'output/job_workflow/daily.txt'))
    handoff = commands.add_parser('handoff', help='只预览已批准材料，绝不发送')
    handoff.add_argument('job_id', type=int)
    serving = commands.add_parser('serve', help='启动仅本机可访问的批量审核台')
    serving.add_argument('--port', type=int, default=8765)
    args = parser.parse_args(argv)
    try:
        profile = json.loads(Path(args.profile).read_text(encoding='utf-8-sig')) if args.profile else None
        resume = json.loads(Path(args.resume).read_text(encoding='utf-8-sig')) if args.resume else None
        factory = lambda: Workflow(args.db, profile=profile, resume=resume, channel=args.channel)
        if args.command == 'serve':
            from .server import create_server
            server = create_server(factory, port=args.port)
            print(f'本地审核台：http://127.0.0.1:{server.server_address[1]} （不调用LLM，不自动发送）', flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()
            return 0
        flow = factory()
        try:
            if args.command == 'init':
                _json({'database': str(Path(args.db).resolve()), 'summary': flow.summary()})
            elif args.command == 'import-json':
                result = flow.import_rows(load_export(args.path))
                _json(result)
                return 1 if result['errors'] else 0
            elif args.command == 'paste':
                row = flow.import_text(Path(args.path).read_text(encoding='utf-8-sig'), source_url=args.url)
                _json({'id': row['id'], 'decision': row['decision'], 'status': row['status']})
            elif args.command == 'discover-greenhouse':
                rows = fetch_greenhouse(args.board, allow_network=args.allow_network)
                result = flow.import_rows(rows)
                _json(result)
                return 1 if result['errors'] else 0
            elif args.command == 'report':
                if args.output:
                    _json({'report_changed': flow.write_report(args.output)})
                else:
                    print(flow.report_text(), end='')
            elif args.command == 'handoff':
                _json(prepare_handoff(flow.repo, args.job_id))
            elif args.command == 'cycle':
                result = {'processed': 0, 'errors': []}
                sources = [('file', value) for value in args.input] + [('greenhouse', value) for value in args.board]
                for kind, value in sources:
                    try:
                        rows = load_export(value) if kind == 'file' else fetch_greenhouse(value, allow_network=args.allow_network)
                        imported = flow.import_rows(rows)
                        result['processed'] += len(imported['processed'])
                        result['errors'].extend(imported['errors'])
                    except (OSError, ValueError, TypeError, KeyError) as exc:
                        result['errors'].append(f'{kind}: {value}: {type(exc).__name__}: {exc}')
                result['summary'] = flow.summary()
                result['report_changed'] = flow.write_report(args.report)
                _json(result)
                return 1 if result['errors'] else 0
        finally:
            flow.close()
        return 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f'操作未完成：{type(exc).__name__}: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
