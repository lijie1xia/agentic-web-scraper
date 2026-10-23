"""过期和缺席在审批、审核页、摘要中保持一致。"""
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scraper_framework.job_workflow.lifecycle import record_snapshot
from scraper_framework.job_workflow.service import Workflow
from scraper_framework.job_workflow.review_page import render_page


class AvailabilityTests(unittest.TestCase):
    def setUp(self):
        self.flow = Workflow(':memory:')
        self.addCleanup(self.flow.close)
        self.item = {'source': 'test', 'job': {'external_id': 'one', 'job_title': 'Python后端实习生'},
                     'raw_jd': '职位：Python后端实习生\n学历：本科\n任职要求：熟悉Python'}

    def test_deadline_blocks_existing_approval_after_date_rollover(self):
        self.item['job']['deadline'] = date.today().isoformat()
        jid = self.flow.import_rows([self.item])['processed'][0]
        repo = self.flow.repo
        repo.approve(jid, acknowledge_review=True)
        with patch('scraper_framework.job_workflow.lifecycle.date', create=True) as clock:
            clock.today.return_value = date.today() + timedelta(days=1)
            clock.fromisoformat.side_effect = date.fromisoformat
            with self.assertRaisesRegex(ValueError, '截止'):
                repo.prepare_handoff(jid)
            with self.assertRaisesRegex(ValueError, '截止'):
                repo.approve(jid, acknowledge_review=True)
            rows = self.flow.rows()
            self.assertIsNone(rows[0]['material'])
            self.assertIn('截止', self.flow.report_text())
            self.assertIn('截止', render_page(rows, token='test'))
            self.assertEqual(repo.get_job(jid)['status'], 'APPROVED')

    def test_missing_is_visible_and_not_selectable(self):
        jid = self.flow.import_rows([self.item])['processed'][0]
        record_snapshot(self.flow.repo, 'test', [jid])
        record_snapshot(self.flow.repo, 'test', [])
        page = render_page(self.flow.rows(), token='test')
        self.assertIn('来源完整快照中缺失', page)
        self.assertNotIn('name="selected"', page)
        self.assertIn('来源完整快照中缺失', self.flow.report_text())

    def test_changed_jd_changes_report_even_with_same_title_and_category(self):
        self.flow.import_rows([self.item])
        before = self.flow.report_text()
        self.item['raw_jd'] += '\n工作时间：周一至周四'
        self.flow.import_rows([self.item])
        self.assertNotEqual(before, self.flow.report_text())


if __name__ == '__main__':
    unittest.main()
