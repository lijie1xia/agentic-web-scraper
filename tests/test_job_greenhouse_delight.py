"""get-delight 公开招聘板的离线夹具。失败响应不得把历史岗位标为来源缺失。"""
import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from scraper_framework.job_workflow.cli import main
from scraper_framework.job_workflow.lifecycle import list_missing
from scraper_framework.job_workflow.service import Workflow
from scraper_framework.job_workflow.sources import _NoRedirect, fetch_greenhouse, parse_greenhouse

FIXTURE = Path(__file__).parent / 'fixtures' / 'greenhouse_get_delight.json'
BOARD = 'get-delight'


def payload():
    return json.loads(FIXTURE.read_text(encoding='utf-8'))


class Response(io.BytesIO):
    status = 200

    def __init__(self, body):
        super().__init__(body)

    def geturl(self):
        return 'https://boards-api.greenhouse.io/v1/boards/get-delight/jobs?content=true'


class DelightFixtureTests(unittest.TestCase):
    def test_fixture_maps_public_fields_without_html(self):
        rows = parse_greenhouse(payload(), BOARD)
        self.assertEqual(len(rows), 1)
        job = rows[0]['job']
        self.assertEqual(rows[0]['source'], 'greenhouse:get-delight')
        self.assertEqual(job['external_id'], '8639423002')
        self.assertEqual(job['job_title'], 'AI Agent Software Engineer, Intern')
        self.assertEqual(job['company'], 'delight.ai')
        self.assertEqual(job['location'], 'Seoul, South Korea')
        self.assertEqual(job['source_url'], 'https://job-boards.greenhouse.io/get-delight/jobs/8639423002')
        self.assertEqual(rows[0]['raw_jd'], 'Build AI agent features with Python.')

    def test_total_mismatch_is_rejected(self):
        broken = payload()
        broken['meta']['total'] = 2
        with self.assertRaises(ValueError) as caught:
            parse_greenhouse(broken, BOARD)
        self.assertIn('不完整', str(caught.exception))

    def test_network_disabled_does_not_open_connection(self):
        with patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('network called')):
            with self.assertRaises(PermissionError):
                fetch_greenhouse(BOARD)

    def test_redirect_is_refused(self):
        with self.assertRaises(ValueError) as caught:
            _NoRedirect().redirect_request(None, None, 302, 'Found', {}, 'https://example.test/login')
        self.assertIn('重定向', str(caught.exception))

    def test_http_404_and_timeout_raise_once(self):
        url = 'https://boards-api.greenhouse.io/v1/boards/get-delight/jobs?content=true'
        cases = [
            HTTPError(url, 404, 'Not Found', hdrs=None, fp=io.BytesIO(b'{"status":404,"error":"Job not found"}')),
            TimeoutError('timed out'),
        ]
        for error in cases:
            with self.subTest(error=type(error).__name__):
                with patch('urllib.request.OpenerDirector.open', side_effect=error) as opened:
                    with self.assertRaises(type(error)):
                        fetch_greenhouse(BOARD, allow_network=True)
                    self.assertEqual(opened.call_count, 1)

    def test_import_is_idempotent_and_failures_do_not_mark_history_missing(self):
        rows = parse_greenhouse(payload(), BOARD)
        with tempfile.TemporaryDirectory() as folder:
            db = str(Path(folder) / 'jobs.db')
            report = str(Path(folder) / 'daily.txt')
            def run(value):
                with patch('scraper_framework.job_workflow.cli.fetch_greenhouse', **value), contextlib.redirect_stdout(io.StringIO()):
                    return main(['--db', db, 'cycle', '--board', BOARD, '--report', report, '--allow-network'])

            self.assertEqual(run({'return_value': rows}), 0)
            self.assertEqual(run({'return_value': copy.deepcopy(rows)}), 0)
            flow = Workflow(db)
            try:
                self.assertEqual(len(flow.rows()), 1)
                self.assertEqual(flow.rows()[0]['job']['external_id'], '8639423002')
                self.assertEqual(list_missing(flow.repo), [])
                for failure in (
                    {'side_effect': HTTPError('https://boards-api.greenhouse.io/', 404, 'Not Found', hdrs=None, fp=io.BytesIO(b'{}'))},
                    {'side_effect': TimeoutError('timed out')},
                    {'side_effect': ValueError('来源发生重定向，需人工核验，未继续请求')},
                    {'side_effect': ValueError('岗位快照不完整：总数与返回条数不符，不可据此判定岗位下架')},
                ):
                    with self.subTest(failure=failure['side_effect']):
                        self.assertEqual(run(failure), 1)
                        self.assertEqual(list_missing(flow.repo), [])
                        self.assertEqual(len(flow.rows()), 1)
                        self.assertEqual(flow.rows()[0]['availability_warning'], '')
            finally:
                flow.close()

    def test_sanitized_post_stays_in_review(self):
        flow = Workflow(':memory:')
        self.addCleanup(flow.close)
        imported = flow.import_rows(parse_greenhouse(payload(), BOARD))
        self.assertEqual(imported['errors'], [])
        again = flow.import_rows(parse_greenhouse(payload(), BOARD))
        self.assertEqual(imported['processed'], again['processed'])
        row = flow.repo.get_job(imported['processed'][0])
        decision = row['decision']
        self.assertEqual(decision['role_priority'], 0)
        self.assertEqual(decision['location_priority'], 2)
        self.assertEqual(decision['category'], 'review')
        self.assertFalse(decision['recommend'])
        self.assertIsNone(decision['salary_check']['daily_cny_range'])


if __name__ == '__main__':
    unittest.main()
