"""投递结果状态与跟进提醒：按提交时间计算，不联网、不调用模型。"""
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PROFILE = {'tech_stack': ['Python', 'RAG'], 'education': '本科', 'graduate_year': 2027,
           'experience_years': 0, 'preferred_work_mode': ['onsite']}
RESUME = {'projects': [{'name': '项目', 'tags': ['Python'], 'one_liner': '开发 Python 服务。'}]}
JD = '职位：AI应用开发实习生\n公司：演示公司\n学历：本科\n招聘对象：2027届在读\n工作方式：坐班\n任职要求：Python、RAG'


class FollowupTests(unittest.TestCase):
    def setUp(self):
        from scraper_framework.job_workflow.service import Workflow
        self.tmp = tempfile.TemporaryDirectory()
        self.flow = Workflow(Path(self.tmp.name) / 'jobs.db', profile=PROFILE, resume=RESUME)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.flow.close)

    def submitted(self):
        self.flow.import_text(JD)
        row = self.flow.rows()[0]
        self.flow.approve_batch([{'job_id': row['id'], 'expected_revision': row['revision'],
                                  'expected_jd_hash': row['jd_hash'],
                                  'expected_material_hash': row['material']['content_hash']}],
                                acknowledge_review=True)
        row = self.flow.rows()[0]
        self.flow.manual_submission(row['id'], evidence='招聘 App 已显示发送成功',
                                    expected_jd_hash=row['jd_hash'],
                                    expected_material_hash=row['material']['content_hash'],
                                    expected_revision=row['revision'],
                                    expected_approval_id=row['approval_id'])
        return row['id']

    def backdate(self, days):
        self.flow.repo._db.execute('UPDATE executions SET finished_at=? WHERE status=\'SUBMITTED\'',
                                   (time.time() - days * 86400,))
        self.flow.repo._db.commit()

    def report(self):
        return self.flow.report_text()

    def test_submission_time_ignores_jobs_updated_at(self):
        job_id = self.submitted()
        self.backdate(4)
        self.flow.repo._db.execute('UPDATE jobs SET updated_at=? WHERE id=?', (time.time(), job_id))
        self.flow.repo._db.commit()
        self.assertIn('已投3天以上', self.report())

    def test_reminder_thresholds(self):
        self.submitted()
        for days, expected in ((2, ''), (3, '已投3天以上'), (7, '已投7天以上'), (14, '已投14天以上')):
            with self.subTest(days=days):
                self.backdate(days)
                text = self.report()
                if expected:
                    self.assertIn(expected, text)
                else:
                    self.assertNotIn('已投', text)

    def test_reply_stops_reminders(self):
        job_id = self.submitted()
        self.backdate(9)
        self.flow.followup(job_id, status='replied', note='HR 约了电话沟通')
        text = self.report()
        self.assertIn('REPLIED', text)
        self.assertNotIn('已投7天以上', text)

    def test_new_statuses_and_terminal_states(self):
        for status, expected in (('rejected', 'REJECTED'), ('withdrew', 'WITHDREW'),
                                 ('no_reply', 'NO_REPLY'), ('closed', 'WITHDREW')):
            with self.subTest(status=status):
                flow = self._fresh()
                job_id = self._submit(flow)
                self.assertEqual(flow.followup(job_id, status=status, note='人工记录')['status'], expected)
                with self.assertRaises(ValueError):
                    flow.followup(job_id, status='replied', note='不应允许回退')

    def test_non_terminal_progression(self):
        job_id = self.submitted()
        self.assertEqual(self.flow.followup(job_id, status='replied', note='HR 回复')['status'], 'REPLIED')
        self.assertEqual(self.flow.followup(job_id, status='interview', note='约一面')['status'], 'INTERVIEW')
        with self.assertRaises(ValueError):
            self.flow.followup(job_id, status='replied', note='不应允许回退')

    def test_missing_execution_time_is_reported_not_guessed(self):
        job_id = self.submitted()
        self.flow.repo._db.execute('DELETE FROM executions WHERE job_id=?', (job_id,))
        self.flow.repo._db.commit()
        self.assertIn('提交时间未知', self.report())

    def test_review_page_offers_explicit_outcomes(self):
        from scraper_framework.job_workflow.review_page import render_page
        job_id = self.submitted()
        html = render_page(self.flow.rows(), token='t')
        for value in ('REPLIED', 'INTERVIEW', 'REJECTED', 'WITHDREW', 'NO_REPLY'):
            self.assertIn(f'value="{value}"', html)
        self.assertNotIn('value="CLOSED"', html)
        self.assertIn(f'id="job-{job_id}"', html)

    def _fresh(self):
        from scraper_framework.job_workflow.service import Workflow
        flow = Workflow(Path(self.tmp.name) / f'jobs-{time.time_ns()}.db', profile=PROFILE, resume=RESUME)
        self.addCleanup(flow.close)
        return flow

    def _submit(self, flow):
        flow.import_text(JD)
        row = flow.rows()[0]
        flow.approve_batch([{'job_id': row['id'], 'expected_revision': row['revision'],
                             'expected_jd_hash': row['jd_hash'],
                             'expected_material_hash': row['material']['content_hash']}],
                           acknowledge_review=True)
        row = flow.rows()[0]
        flow.manual_submission(row['id'], evidence='招聘 App 已显示发送成功',
                               expected_jd_hash=row['jd_hash'],
                               expected_material_hash=row['material']['content_hash'],
                               expected_revision=row['revision'],
                               expected_approval_id=row['approval_id'])
        return row['id']


if __name__ == '__main__':
    unittest.main()
