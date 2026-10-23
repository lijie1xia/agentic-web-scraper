import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PROFILE = {'tech_stack':['Python','RAG'],'education':'本科在读','graduate_year':2027,'experience_years':0,'preferred_work_mode':['onsite'],'target_roles':['ai_application','backend']}
RESUME = {'projects':[{'name':'Project','tags':['Python','RAG'],'one_liner':'搭建过 Python RAG 后端服务。'}]}
JD = '职位：AI应用开发实习生\n公司：演示公司\n学历：本科\n招聘对象：2027届在读\n工作方式：坐班\n任职要求：Python、RAG'


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        from scraper_framework.job_workflow.service import Workflow
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name)/'nested'/'jobs.db'
        self.flow = Workflow(self.db, profile=PROFILE, resume=RESUME)

    def tearDown(self):
        self.flow.close()
        self.tmp.cleanup()

    def approve(self, job_id):
        row = next(x for x in self.flow.rows() if x['id']==job_id)
        return self.flow.approve_batch([{'job_id':job_id,'expected_revision':row['revision'],'expected_jd_hash':row['jd_hash'],'expected_material_hash':row['material']['content_hash']}], acknowledge_review=True)

    def test_offline_import_and_reimport_preserve_edited_material_and_approval(self):
        with patch('socket.socket.connect', side_effect=AssertionError('network forbidden')):
            row = self.flow.import_text(JD)
            original = self.flow.rows()[0]['material']
            self.flow.edit_message(row['id'],'您好，我想了解此岗位。',expected_material_hash=original['content_hash'],expected_revision=row['revision'])
            self.assertEqual(self.approve(row['id'])['approved'],[row['id']])
            self.flow.import_text(JD)
        self.assertEqual(len(self.flow.rows()),1)
        self.assertEqual(self.flow.rows()[0]['material']['content']['message'],'您好，我想了解此岗位。')
        self.assertEqual(self.flow.rows()[0]['status'],'APPROVED')

    def test_url_tracking_dedup_and_changed_jd_invalidate_approval(self):
        row = self.flow.import_text(JD,source_url='https://example.org/job/1?utm_source=a')
        self.approve(row['id'])
        self.flow.import_text(JD+'\n薪资：待议',source_url='https://example.org/job/1?utm_source=b#top')
        self.assertEqual(len(self.flow.rows()),1)
        self.assertEqual(self.flow.rows()[0]['status'],'READY_FOR_REVIEW')

    def test_reject_has_no_material_and_cannot_approve(self):
        row = self.flow.import_text(JD.replace('2027','2026'))
        self.assertEqual(row['decision']['category'],'reject')
        self.assertIsNone(self.flow.rows()[0]['material'])

    def test_manual_submission_and_followup_are_explicit(self):
        row = self.flow.import_text(JD)
        self.approve(row['id'])
        row = self.flow.rows()[0]
        with self.assertRaises(ValueError):
            self.flow.manual_submission(row['id'], evidence='', expected_jd_hash=row['jd_hash'],expected_material_hash=row['material']['content_hash'],expected_revision=row['revision'],expected_approval_id=row['approval_id'])
        self.flow.manual_submission(row['id'], evidence='演示：人工核对发送记录', expected_jd_hash=row['jd_hash'],expected_material_hash=row['material']['content_hash'],expected_revision=row['revision'],expected_approval_id=row['approval_id'])
        self.flow.followup(row['id'],status='REPLIED',note='演示回复')
        self.assertEqual(self.flow.rows()[0]['status'],'REPLIED')
        self.assertIn('人工',self.flow.report_text())

    def test_reimport_submitted_job_never_reopens_or_regenerates_material(self):
        row = self.flow.import_text(JD, source_url='https://example.org/job/1')
        self.approve(row['id'])
        card = self.flow.rows()[0]
        self.flow.manual_submission(row['id'],evidence='人工核对',expected_jd_hash=card['jd_hash'],expected_material_hash=card['material']['content_hash'],expected_revision=card['revision'],expected_approval_id=card['approval_id'])
        self.flow.import_text(JD+'\n新说明',source_url='https://example.org/job/1')
        self.assertEqual(self.flow.rows()[0]['status'],'SUBMITTED')

    def test_batch_requires_explicit_confirmation_and_snapshot(self):
        row = self.flow.import_text(JD)
        result = self.flow.approve_batch([{'job_id':row['id']}],acknowledge_review=True)
        self.assertEqual(result['approved'],[])
        self.assertEqual(len(result['errors']),1)

    def test_batch_rejects_old_decision_revision_even_when_both_hashes_match(self):
        self.flow.import_text(JD, source_url='https://example.org/revision')
        row = self.flow.rows()[0]
        selection = {'job_id': row['id'], 'expected_revision': row['revision'],
                     'expected_jd_hash': row['jd_hash'],
                     'expected_material_hash': row['material']['content_hash']}
        changed = self.flow.repo.upsert_job(
            row['job'], raw_jd=row['raw_jd'],
            decision={**row['decision'], 'warnings': ['新增待核实条件']})
        fresh = self.flow.repo.save_material(row['id'], row['material']['content'])
        self.assertEqual(changed['jd_hash'], row['jd_hash'])
        self.assertEqual(fresh['content_hash'], row['material']['content_hash'])
        result = self.flow.approve_batch([selection], acknowledge_review=True)
        self.assertEqual(result['approved'], [])
        self.assertEqual(len(result['errors']), 1)
        self.assertEqual(self.flow.repo.list_approvals(row['id']), [])

    def test_batch_requires_displayed_revision_in_addition_to_hashes(self):
        row = self.flow.import_text(JD)
        material = self.flow.repo.latest_material(row['id'])
        result = self.flow.approve_batch([{
            'job_id': row['id'], 'expected_jd_hash': row['jd_hash'],
            'expected_material_hash': material['content_hash']}], acknowledge_review=True)
        self.assertEqual(result['approved'], [])
        self.assertEqual(len(result['errors']), 1)

    def test_editor_rejects_old_revision_after_jd_or_decision_update(self):
        for change in ('jd', 'decision'):
            with self.subTest(change=change):
                row = self.flow.import_text(JD, source_url=f'https://example.org/{change}')
                material = self.flow.repo.latest_material(row['id'])
                self.flow.repo.upsert_job(
                    row['job'], raw_jd=row['raw_jd'] + ('新要求' if change == 'jd' else ''),
                    decision={**row['decision'], 'note': change})
                with self.assertRaises(ValueError):
                    self.flow.edit_message(row['id'], '旧编辑内容',
                        expected_material_hash=material['content_hash'],
                        expected_revision=row['revision'])
                self.assertEqual(self.flow.repo.list_materials(row['id']), [material])
                self.assertIsNone(next(x for x in self.flow.rows() if x['id'] == row['id'])['material'])

    def test_manual_confirmation_rejects_replaced_same_content_approval(self):
        row = self.flow.import_text(JD)
        self.approve(row['id'])
        card = self.flow.rows()[0]
        first = self.flow.repo.list_approvals(row['id'])[-1]
        with patch('scraper_framework.job_workflow.repository.time.time', return_value=first['expires_at']):
            self.assertIsNone(self.flow.rows()[0]['approval_id'])
            self.approve(row['id'])
            replacement = self.flow.rows()[0]
            self.assertNotEqual(card['approval_id'], replacement['approval_id'])
            with self.assertRaises(ValueError):
                self.flow.manual_submission(row['id'], evidence='旧页面确认',
                    expected_jd_hash=card['jd_hash'],
                    expected_material_hash=card['material']['content_hash'],
                    expected_revision=card['revision'], expected_approval_id=card['approval_id'])
        self.assertEqual(self.flow.repo.list_executions(row['id']), [])

    def test_internal_generation_cannot_stamp_material_from_an_older_revision(self):
        from scraper_framework.job_workflow.materials import build_material
        from scraper_framework.job_workflow.repository import Repository

        def generate_then_change(job, decision, resume, *, channel):
            material = build_material(job, decision, resume, channel=channel)
            other = Repository(self.db)
            try:
                other.upsert_job(job, raw_jd=job['raw_jd'],
                                 decision={**decision, 'note': '生成期间更新'})
            finally:
                other.close()
            return material

        with patch('scraper_framework.job_workflow.service.build_material', side_effect=generate_then_change):
            with self.assertRaisesRegex(ValueError, 'revision'):
                self.flow.import_text(JD, source_url='https://example.org/generation-race')
        self.assertEqual(self.flow.repo.list_materials(1), [])
        self.assertEqual(self.flow.repo.list_approvals(1), [])

    def test_two_pasted_demo_urls_do_not_collapse(self):
        from scraper_framework.job_workflow.service import Workflow
        rows=[{'job':{'job_title':'岗位一','source_url':'paste://demo'},'raw_jd':'一','source':'manual'}, {'job':{'job_title':'岗位二','source_url':'paste://demo'},'raw_jd':'二','source':'manual'}]
        self.flow.import_rows(rows)
        self.assertEqual(len(self.flow.rows()),2)


if __name__ == '__main__': unittest.main()
