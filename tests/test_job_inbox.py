"""微信收件箱：拆分、增量导入、钩子和手机摘要。全程离线。"""
import importlib.util
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from scraper_framework.job_workflow.cli import import_inbox
from scraper_framework.job_workflow.offline import split_postings
from scraper_framework.job_workflow.service import Workflow, _fit_notice

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / 'output' / 'job_calibration' / 'samples.txt'
HOOK = ROOT / 'integrations' / 'hermes_job_inbox' / '__init__.py'


def load_hook():
    spec = importlib.util.spec_from_file_location('job_inbox_hook', HOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Event:
    def __init__(self, text='AI应用开发实习生\n180元/天\n广州 5天/周 6个月 本科\n任职要求\nPython',
                 message_id='m1', chat_type='dm', user_id='owner', kind='text'):
        self.text = text
        self.message_id = message_id
        self.message_type = kind
        self.timestamp = datetime(2026, 10, 26, tzinfo=timezone.utc)
        self.source = type('Source', (), {'chat_type': chat_type, 'user_id': user_id})()


class InboxTests(unittest.TestCase):
    def test_calibration_samples_split_without_changing_decisions(self):
        blocks = [block.split('\n', 1)[1] for block in SAMPLES.read_text(encoding='utf-8').split('##### ')[1:]]
        parts = split_postings('\n\n'.join(blocks))
        self.assertEqual(len(parts), len(blocks))
        flow = Workflow(':memory:')
        self.addCleanup(flow.close)
        for original, part in zip(blocks, parts):
            alone = flow.import_text(original)['decision']
            batch = flow.import_batch_text(part)['processed']
            joined = flow.repo.get_job(batch[0])['decision']
            self.assertEqual(joined['category'], alone['category'])
            self.assertEqual(joined['score'], alone['score'])

    def test_single_posting_is_unchanged(self):
        text = '没有招聘头部的一段说明'
        self.assertEqual(split_postings(text), [text])

    def test_inbox_advances_only_valid_messages_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'inbox.jsonl'
            path.write_text(
                '{"message_id":"ok","text":"AI应用开发实习生\\n180元/天\\n广州 5天/周 6个月 本科\\n任职要求\\nPython"}\n'
                '{broken\n'
                '{"message_id":"ok","text":"另一条"}\n',
                encoding='utf-8')
            flow = Workflow(':memory:')
            self.addCleanup(flow.close)
            first = import_inbox(flow, path)
            self.assertEqual(len(first['processed']), 1)
            self.assertEqual(len(first['errors']), 1)
            self.assertEqual(first['skipped'], 1)
            second = import_inbox(flow, path)
            self.assertEqual(second['processed'], [])
            self.assertEqual(second['skipped'], 2)
            self.assertEqual(len(second['errors']), 1)
            self.assertEqual(len(flow.rows()), 1)
            state = json.loads(path.with_name(path.name + '.state.json').read_text(encoding='utf-8'))
            self.assertEqual(state['ids'], ['ok'])

    def test_phone_summary_includes_priority_greeting_and_stays_bounded(self):
        flow = Workflow(':memory:')
        self.addCleanup(flow.close)
        text = '职位：AI应用开发实习生\n学历：本科\n招聘对象：应届\n工作方式：坐班\n任职要求：Python\n薪资：180元/天\n'
        row = flow.import_text(text)
        self.assertEqual(row['decision']['category'], 'priority')
        report = flow.report_text()
        self.assertLessEqual(len(report), 4000)
        self.assertIn('优先考虑', report)
        self.assertIn(flow.rows()[0]['material']['content']['message'], report)
        self.assertIn('明确不符合：0 条', report)
        self.assertLessEqual(len(_fit_notice('字' * 5000)), 4000)
        self.assertIn('审核台', _fit_notice('字' * 5000))

    def test_hook_captures_allowlisted_dm_and_leaves_everything_else(self):
        hook = load_hook()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'inbox.jsonl'
            env = {'JOB_INBOX_PATH': str(path), 'JOB_INBOX_USERS': 'owner'}
            with patch.dict(os.environ, env, clear=False):
                self.assertEqual(hook.capture(Event())['action'], 'skip')
                self.assertIsNone(hook.capture(Event(user_id='other', message_id='m2')))
                self.assertIsNone(hook.capture(Event(chat_type='group', message_id='m3')))
                self.assertIsNone(hook.capture(Event(kind='photo', message_id='m4')))
                self.assertIsNone(hook.capture(Event(text='超' * 100001, message_id='m5')))
                with patch('builtins.open', side_effect=OSError('disk')):
                    self.assertIsNone(hook.capture(Event(message_id='m6')))
            saved = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
            self.assertEqual([item['message_id'] for item in saved], ['m1'])

    def test_daily_imports_inbox_once(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            inbox = folder / 'inbox.jsonl'
            inbox.write_text(
                '{"message_id":"daily","text":"职位：AI应用开发实习生\\n学历：本科\\n招聘对象：应届\\n'
                '工作方式：坐班\\n任职要求：Python\\n薪资：180元/天\\n"}\n', encoding='utf-8')
            config = folder / 'sources.json'
            config.write_text(json.dumps({
                'database': str(folder / 'jobs.db'),
                'report': str(folder / 'report.txt'),
                'notice_state': str(folder / 'notice.txt'),
                'inputs': [], 'boards': [], 'allow_network': False,
                'inbox': str(inbox),
            }), encoding='utf-8')
            import subprocess
            import sys
            command = [sys.executable, '-S', str(ROOT / 'scripts/run_job_daily.py'), '--config', str(config)]
            first = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertIn('优先考虑', first.stdout)
            second = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(second.stdout, '')


if __name__ == '__main__':
    unittest.main()
