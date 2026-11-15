"""Lever 公开职位接口：只读解析与显式联网开关。"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

POST = {
    'id': 'ad208490-4052-4f91-a57e-433f2d1e484b',
    'text': 'AI Application Engineer Intern',
    'hostedUrl': 'https://jobs.lever.co/demo/ad208490-4052-4f91-a57e-433f2d1e484b',
    'categories': {'location': 'Shenzhen', 'team': 'AI', 'commitment': 'Intern'},
    'descriptionPlain': 'Build agents. Required: Python.',
    'description': '<div>Build agents. Required: Python.<script>track()</script></div>',
    'createdAt': 1788199939703,
}


class LeverTests(unittest.TestCase):
    def test_parse_maps_official_fields_and_strips_scripts(self):
        from scraper_framework.job_workflow.sources import parse_lever
        rows = parse_lever([POST], 'demo')
        self.assertEqual(rows[0]['job']['external_id'], POST['id'])
        self.assertEqual(rows[0]['job']['job_title'], 'AI Application Engineer Intern')
        self.assertEqual(rows[0]['job']['location'], 'Shenzhen')
        self.assertEqual(rows[0]['source'], 'lever:demo')
        self.assertIn('Required: Python', rows[0]['raw_jd'])
        self.assertNotIn('track()', rows[0]['raw_jd'])

    def test_falls_back_to_html_description_when_plain_missing(self):
        from scraper_framework.job_workflow.sources import parse_lever
        post = dict(POST)
        post.pop('descriptionPlain')
        rows = parse_lever([post], 'demo')
        self.assertIn('Build agents', rows[0]['raw_jd'])

    def test_rejects_invalid_payloads(self):
        from scraper_framework.job_workflow.sources import parse_lever
        cases = [
            {'not': 'a list'},
            [dict(POST, id='')],
            [dict(POST, text='')],
            [POST, POST],
            [dict(POST, hostedUrl='http://evil.example/job')],
            [dict(POST, hostedUrl='https://jobs.lever.co/demo/x', categories='Shenzhen')],
        ]
        for payload in cases:
            with self.subTest(payload=str(payload)[:60]), self.assertRaises(ValueError):
                parse_lever(payload, 'demo')

    def test_site_token_is_restricted(self):
        from scraper_framework.job_workflow.sources import lever_url
        self.assertTrue(lever_url('demo-co').endswith('/v0/postings/demo-co?mode=json'))
        for bad in ('', '../etc', 'a b', 'x' * 101, 7):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                lever_url(bad)

    def test_network_requires_explicit_opt_in(self):
        from scraper_framework.job_workflow.sources import fetch_lever
        with patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('network called')):
            with self.assertRaises(PermissionError):
                fetch_lever('demo')


class LeverCycleTests(unittest.TestCase):
    def test_cycle_imports_lever_rows_and_keeps_snapshot_partial(self):
        import contextlib
        import io
        import tempfile
        from unittest.mock import patch
        from scraper_framework.job_workflow import cli
        from scraper_framework.job_workflow.lifecycle import source_status
        from scraper_framework.job_workflow.repository import Repository

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'jobs.db'
            report = Path(tmp) / 'report.txt'
            with patch.object(cli, 'fetch_lever', return_value=parse_rows()) as fetch, \
                    contextlib.redirect_stdout(io.StringIO()):
                code = cli.main(['--db', str(db), 'cycle', '--lever', 'demo',
                                 '--allow-network', '--report', str(report)])
            self.assertEqual(code, 0)
            self.assertTrue(fetch.call_args.kwargs['allow_network'])
            self.assertIn('AI Application Engineer Intern', report.read_text(encoding='utf-8'))
            repo = Repository(db)
            try:
                status = next(item for item in source_status(repo) if item['source'] == 'lever:demo')
            finally:
                repo.close()
            self.assertFalse(status['complete'])


def parse_rows():
    from scraper_framework.job_workflow.sources import parse_lever
    return parse_lever([POST], 'demo')


if __name__ == '__main__':
    unittest.main()
