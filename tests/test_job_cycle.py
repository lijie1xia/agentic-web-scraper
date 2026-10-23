"""完整快照必须经过整批导入，失败和局部来源不推断下架。"""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scraper_framework.job_workflow.cli import main
from scraper_framework.job_workflow.lifecycle import list_missing, source_status
from scraper_framework.job_workflow.service import Workflow


class CycleTests(unittest.TestCase):
    def test_campus_is_partial_and_does_not_mark_previous_jobs_missing(self):
        with tempfile.TemporaryDirectory() as folder, contextlib.ExitStack() as cleanup:
            db = str(Path(folder) / 'jobs.db')
            report = str(Path(folder) / 'daily.txt')
            row = {'source': 'cuhk', 'job': {'external_id': '1', 'job_title': 'AI实习生'}, 'raw_jd': 'Python开发'}
            with patch('scraper_framework.job_workflow.cli.fetch_campus', return_value=[row], create=True) as fetch:
                with contextlib.redirect_stdout(io.StringIO()):
                    code = main(['--db', db, 'cycle', '--campus', '--campus-url', 'https://career.cuhk.edu.cn/en/job/view/id/468767', '--report', report, '--allow-network'])
                self.assertEqual(code, 0)
                self.assertEqual(fetch.call_args.kwargs['known_urls'], ['https://career.cuhk.edu.cn/en/job/view/id/468767'])
                fetch.return_value = []
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(main(['--db', db, 'cycle', '--campus', '--report', report, '--allow-network']), 0)
            flow = Workflow(db)
            cleanup.callback(flow.close)
            self.assertEqual(len(flow.rows()), 1)
            self.assertEqual(list_missing(flow.repo), [])
            self.assertIn('局部列表', Path(report).read_text(encoding='utf-8'))

    def test_complete_feed_missing_failed_and_reappeared(self):
        with tempfile.TemporaryDirectory() as folder, contextlib.ExitStack() as cleanup:
            db = str(Path(folder) / 'jobs.db')
            report = str(Path(folder) / 'daily.txt')
            row = {'source': 'greenhouse:test', 'job': {'external_id': '1', 'job_title': 'Python后端实习'}, 'raw_jd': '熟悉Python'}
            def run(value):
                with patch('scraper_framework.job_workflow.cli.fetch_greenhouse', **value), contextlib.redirect_stdout(io.StringIO()) as out:
                    code = main(['--db', db, 'cycle', '--board', 'test', '--report', report, '--allow-network'])
                return code, json.loads(out.getvalue())
            self.assertEqual(run({'return_value': [row]})[0], 0)
            flow = Workflow(db)
            cleanup.callback(flow.close)
            sources = source_status(flow.repo)
            self.assertEqual(len(sources), 1)
            self.assertEqual(sources[0]['present'], 1)
            self.assertEqual(run({'side_effect': OSError('临时网络错误')})[0], 1)
            self.assertEqual(list_missing(flow.repo), [])
            self.assertEqual(run({'return_value': [row, {'job': None}]})[0], 1)
            self.assertEqual(list_missing(flow.repo), [])
            self.assertEqual(run({'return_value': []})[0], 0)
            self.assertEqual(len(list_missing(flow.repo)), 1)
            self.assertEqual(run({'return_value': [row]})[0], 0)
            self.assertEqual(list_missing(flow.repo), [])


if __name__ == '__main__':
    unittest.main()
