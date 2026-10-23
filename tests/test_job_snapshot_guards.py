import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scraper_framework.job_workflow.repository import Repository


class SnapshotGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Repository(Path(self.tmp.name) / 'jobs.db')
        self.job = self.repo.upsert_job({'source_url':'https://example.org/1','job_title':'Developer'}, decision={'category':'priority'})
        self.material = self.repo.save_material(self.job['id'], {'message':'Version one'})

    def tearDown(self):
        self.repo.close()
        self.tmp.cleanup()

    def test_stale_material_editor_cannot_overwrite_newer_material(self):
        self.repo.save_material(self.job['id'], {'message':'Version two'})
        with self.assertRaises(ValueError):
            self.repo.save_material(self.job['id'], {'message':'Stale edit'}, expected_material_hash=self.material['content_hash'], expected_revision=self.job['revision'])
        self.assertEqual(self.repo.latest_material(self.job['id'])['content']['message'],'Version two')

    def test_old_hash_cannot_promote_historical_material_after_revision_change(self):
        for change in ('jd', 'decision'):
            with self.subTest(change=change):
                before = self.repo.list_materials(self.job['id'])
                self.repo.upsert_job(
                    self.job['job'], raw_jd='新 JD' if change == 'jd' else '',
                    decision={'category': 'priority', 'note': change})
                with self.assertRaises(ValueError):
                    self.repo.save_material(
                        self.job['id'], {'message': '旧页面编辑'},
                        expected_material_hash=self.material['content_hash'])
                self.assertEqual(self.repo.list_materials(self.job['id']), before)
                with self.assertRaises(ValueError):
                    self.repo.approve(self.job['id'])

    def test_manual_confirmation_is_bound_to_displayed_snapshot(self):
        approval = self.repo.approve(self.job['id'])
        with self.assertRaises(ValueError):
            self.repo.record_manual_submission(self.job['id'], evidence='Human checked sent log', expected_jd_hash=self.job['jd_hash'], expected_material_hash='old-hash', expected_revision=self.job['revision'], expected_approval_id=approval['id'])
        self.assertEqual(self.repo.get_job(self.job['id'])['status'],'APPROVED')
        self.repo.record_manual_submission(self.job['id'], evidence='Human checked sent log', expected_jd_hash=self.job['jd_hash'], expected_material_hash=self.material['content_hash'], expected_revision=self.job['revision'], expected_approval_id=approval['id'])
        self.assertEqual(self.repo.get_job(self.job['id'])['status'],'SUBMITTED')

    def test_old_hashes_without_approval_identity_cannot_consume_replacement(self):
        first = self.repo.approve(self.job['id'])
        with patch('scraper_framework.job_workflow.repository.time.time',
                   return_value=first['expires_at']):
            replacement = self.repo.approve(self.job['id'])
            self.assertNotEqual(first['id'], replacement['id'])
            with self.assertRaises(ValueError):
                self.repo.record_manual_submission(
                    self.job['id'], evidence='旧页面确认',
                    expected_jd_hash=self.job['jd_hash'],
                    expected_material_hash=self.material['content_hash'])
        self.assertEqual(self.repo.list_executions(self.job['id']), [])
        self.assertIsNone(self.repo.list_approvals(self.job['id'])[-1]['consumed_at'])

    def test_expired_replaced_approval_identity_cannot_authorize_old_form(self):
        first = self.repo.approve(self.job['id'])
        with patch('scraper_framework.job_workflow.repository.time.time', return_value=first['expires_at']):
            replacement = self.repo.approve(self.job['id'])
            logs = self.repo.list_logs(self.job['id'])
            with self.assertRaisesRegex(ValueError, 'approval'):
                self.repo.record_manual_submission(self.job['id'], evidence='旧确认',
                    expected_revision=self.job['revision'], expected_approval_id=first['id'],
                    expected_jd_hash=self.job['jd_hash'], expected_material_hash=self.material['content_hash'])
            self.assertEqual(self.repo.list_logs(self.job['id']), logs)
            self.assertEqual(self.repo.list_executions(self.job['id']), [])
            self.repo.record_manual_submission(self.job['id'], evidence='新确认',
                expected_revision=self.job['revision'], expected_approval_id=replacement['id'],
                expected_jd_hash=self.job['jd_hash'], expected_material_hash=self.material['content_hash'])

    def test_decision_revision_guards_approval_and_manual_confirmation_with_identical_hashes(self):
        first = self.repo.approve(self.job['id'])
        changed = self.repo.upsert_job(self.job['job'], decision={'category': 'priority', 'note': '新条件'})
        current = self.repo.save_material(self.job['id'], self.material['content'])
        self.assertEqual(current['content_hash'], self.material['content_hash'])
        self.assertEqual(changed['jd_hash'], self.job['jd_hash'])
        with self.assertRaisesRegex(ValueError, 'revision'):
            self.repo.approve(self.job['id'], expected_revision=self.job['revision'],
                expected_jd_hash=self.job['jd_hash'], expected_material_hash=current['content_hash'])
        approval = self.repo.approve(self.job['id'], expected_revision=changed['revision'],
            expected_jd_hash=changed['jd_hash'], expected_material_hash=current['content_hash'])
        self.assertNotEqual(first['id'], approval['id'])
        with self.assertRaisesRegex(ValueError, 'revision'):
            self.repo.record_manual_submission(self.job['id'], evidence='旧确认',
                expected_revision=self.job['revision'], expected_approval_id=approval['id'],
                expected_jd_hash=self.job['jd_hash'], expected_material_hash=current['content_hash'])
        self.assertEqual(self.repo.list_executions(self.job['id']), [])

    def test_displayed_revision_is_checked_inside_edit_write_transaction(self):
        transaction = self.repo._transaction
        snapshots = {}

        @contextmanager
        def interleaved_transaction():
            # 在保存函数进入后、写事务获取锁前，另一连接提交新版本。
            other = Repository(Path(self.tmp.name) / 'jobs.db')
            try:
                snapshots['changed'] = other.upsert_job(
                    self.job['job'], decision={'category': 'priority', 'note': '并发更新'})
                snapshots['logs'] = other.list_logs(self.job['id'])
            finally:
                other.close()
            with transaction():
                yield

        with patch.object(self.repo, '_transaction', interleaved_transaction):
            with self.assertRaisesRegex(ValueError, 'revision'):
                self.repo.save_material(self.job['id'], {'message': '旧编辑'},
                    expected_revision=self.job['revision'], expected_material_hash=self.material['content_hash'])
        self.assertEqual(self.repo.list_materials(self.job['id']), [self.material])
        self.assertEqual(self.repo.list_logs(self.job['id']), snapshots['logs'])
        changed = snapshots['changed']
        fresh = self.repo.save_material(self.job['id'], self.material['content'],
                                        expected_revision=changed['revision'])
        self.assertEqual(fresh['revision'], changed['revision'])
        self.assertEqual(self.repo.approve(self.job['id'])['material_id'], fresh['id'])


if __name__ == '__main__': unittest.main()
