"""Read-only source adapters: local exports and the public Greenhouse GET API."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class SourceTests(unittest.TestCase):
    def test_local_export_accepts_existing_ranked_shape_without_trusting_decisions(self):
        from scraper_framework.job_workflow.sources import load_export
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'jobs.json'
            path.write_text(json.dumps([{'job': {'job_title': 'Python intern', 'source_url': 'https://example.org/1'}, 'decision': {'recommend': True}}]), encoding='utf-8')
            items = load_export(path)
        self.assertEqual(items[0]['job']['job_title'], 'Python intern')
        self.assertNotIn('decision', items[0])

    def test_invalid_export_is_rejected_before_import(self):
        from scraper_framework.job_workflow.sources import load_export
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'jobs.json'
            path.write_text('[{}, 12]', encoding='utf-8')
            with self.assertRaises(ValueError):
                load_export(path)

    def test_greenhouse_maps_ids_and_preserves_text_without_script(self):
        from scraper_framework.job_workflow.sources import parse_greenhouse
        payload = {'jobs': [{'id': 12, 'title': 'Python Intern', 'absolute_url': 'https://boards.greenhouse.io/demo/jobs/12', 'location': {'name': 'Remote'}, 'content': '&lt;p&gt;Required: Python&lt;/p&gt;<script>steal()</script>', 'updated_at': '2026-01-01'}], 'meta': {'total': 1}}
        rows = parse_greenhouse(payload, 'demo')
        self.assertEqual(rows[0]['job']['external_id'], '12')
        self.assertIn('Required: Python', rows[0]['raw_jd'])
        self.assertNotIn('steal', rows[0]['raw_jd'])
        self.assertEqual(rows[0]['source'], 'greenhouse:demo')
        self.assertEqual(rows[0]['job']['company'], '')

    def test_greenhouse_rejects_incomplete_snapshot(self):
        from scraper_framework.job_workflow.sources import parse_greenhouse
        with self.assertRaises(ValueError):
            parse_greenhouse({'jobs': [], 'meta': {'total': 4}}, 'demo')

    def test_network_disabled_without_explicit_opt_in(self):
        from scraper_framework.job_workflow.sources import fetch_greenhouse
        with patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('network called')):
            with self.assertRaises(PermissionError):
                fetch_greenhouse('demo')

    def test_malformed_metadata_is_reported_as_invalid_source(self):
        from scraper_framework.job_workflow.sources import parse_greenhouse
        for meta in ['unexpected', [1], 7, False, []]:
            with self.subTest(meta=meta), self.assertRaises(ValueError):
                parse_greenhouse({'jobs': [], 'meta': meta}, 'demo')

    def test_malformed_location_is_reported_as_invalid_source(self):
        from scraper_framework.job_workflow.sources import parse_greenhouse
        for location in ['Remote', [1], 7, False, []]:
            post = {'id': 1, 'title': 'Python Intern',
                    'absolute_url': 'https://example.org/jobs/1', 'location': location}
            with self.subTest(location=location), self.assertRaises(ValueError):
                parse_greenhouse({'jobs': [post]}, 'demo')

    def test_board_token_cannot_change_host_or_endpoint(self):
        from scraper_framework.job_workflow.sources import greenhouse_url
        for value in ['../jobs', 'https://evil.test', 'demo?x=y', '', 'demo/../test']:
            with self.assertRaises(ValueError):
                greenhouse_url(value)
        self.assertEqual(greenhouse_url('example'), 'https://boards-api.greenhouse.io/v1/boards/example/jobs?content=true')


if __name__ == '__main__':
    unittest.main()
