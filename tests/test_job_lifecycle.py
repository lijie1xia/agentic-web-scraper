"""来源快照只更新可用性，不代替人工投递状态。"""
import importlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scraper_framework.job_workflow.repository import Repository


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'jobs.db'
        self.repo = Repository(self.path)
        self.addCleanup(lambda: self.repo.close())
        try:
            self.lifecycle = importlib.import_module('scraper_framework.job_workflow.lifecycle')
        except ModuleNotFoundError:
            self.fail('来源快照生命周期模块尚未实现')

    def job(self, name='one', source='board:a'):
        return self.repo.upsert_job({'external_id': name}, source=source,
                                    decision={'category': 'priority'})['id']

    def snapshot(self, ids, source='board:a', **kwargs):
        return self.lifecycle.record_snapshot(self.repo, source, ids, **kwargs)

    def test_repeated_snapshot_tracks_freshness_without_duplicate_changes(self):
        jid = self.job()
        self.assertEqual(self.lifecycle.source_status(self.repo), [])
        first = self.snapshot([jid, jid], now=100)
        self.assertEqual((first['new'], first['returned'], first['missing']), (1, 0, 0))
        repeat = self.snapshot([jid], now=200)
        self.assertEqual((repeat['new'], repeat['returned'], repeat['missing']), (0, 0, 0))
        self.assertEqual(repeat['last_success_at'], 200)
        self.assertEqual(self.lifecycle.source_status(self.repo), [{
            'source': 'board:a', 'last_run_at': 200, 'last_success_at': 200,
            'complete': True, 'present': 1, 'missing': 0,
        }])
        self.assertEqual(self.repo.get_job(jid)['status'], 'READY_FOR_REVIEW')
        self.assertEqual(len(self.repo.list_revisions(jid)), 1)
        self.assertEqual(self.repo.list_logs(jid), [])

    def test_missing_invalidates_approval_and_handoff_once(self):
        jid = self.job()
        self.repo.save_material(jid, {'message': '人工审核材料'})
        approval = self.repo.approve(jid)
        handoff = self.repo.prepare_handoff(jid)
        self.snapshot([jid], now=100)
        missing = self.snapshot([], now=200)
        self.assertEqual(missing['missing'], 1)
        self.assertEqual(self.repo.get_job(jid)['status'], 'READY_FOR_REVIEW')
        self.assertIsNotNone(self.repo.list_approvals(jid)[0]['invalidated_at'])
        self.assertEqual(self.repo.list_approvals(jid)[0]['id'], approval['id'])
        with self.assertRaises(ValueError):
            self.repo.prepare_handoff(jid)
        with self.assertRaises(ValueError):
            self.repo.record_manual_submission(jid, evidence='过时确认',
                expected_revision=handoff['revision'], expected_approval_id=handoff['approval_id'])
        self.assertEqual(self.lifecycle.list_missing(self.repo), [{
            'source': 'board:a', 'job_id': jid, 'first_seen_at': 100,
            'last_seen_at': 100, 'missing_since': 200,
        }])
        self.assertEqual(self.lifecycle.list_missing(self.repo, source='board:b'), [])
        logs = self.repo.list_logs(jid)
        self.assertEqual(self.snapshot([], now=300)['missing'], 0)
        self.assertEqual(self.repo.list_logs(jid), logs)
        self.assertEqual(self.lifecycle.list_missing(self.repo)[0]['missing_since'], 200)

    def test_missing_cannot_be_reapproved_until_seen_again(self):
        jid = self.job()
        self.repo.save_material(jid, {'message': '人工审核材料'})
        self.snapshot([jid])
        self.snapshot([])
        with self.assertRaisesRegex(ValueError, '来源.*缺失'):
            self.repo.approve(jid)
        self.snapshot([jid])
        self.assertIsNotNone(self.repo.approve(jid))

    def test_incomplete_or_failed_run_does_not_change_any_availability(self):
        first = self.job()
        second = self.job(source='board:b')
        unseen = self.job('unseen')
        self.snapshot([first], now=100)
        self.snapshot([second], source='board:b', now=150)
        for ids in ([], [unseen]):
            result = self.snapshot(ids, complete=False, now=200)
            self.assertEqual((result['new'], result['returned'], result['missing']), (0, 0, 0))
            self.assertEqual(result['last_success_at'], 100)
            self.assertFalse(result['complete'])
        self.assertEqual(self.lifecycle.list_missing(self.repo), [])
        self.assertEqual(self.lifecycle.source_status(self.repo), [
            {'source': 'board:a', 'last_run_at': 200, 'last_success_at': 100,
             'complete': False, 'present': 1, 'missing': 0},
            {'source': 'board:b', 'last_run_at': 150, 'last_success_at': 150,
             'complete': True, 'present': 1, 'missing': 0},
        ])
        failed = self.snapshot([], source='board:c', complete=False, now=300)
        self.assertIsNone(failed['last_success_at'])
        self.assertEqual(self.snapshot([first, unseen], now=400)['new'], 1)

    def test_reappearance_after_restart_requires_new_approval(self):
        jid = self.job()
        self.repo.save_material(jid, {'message': '人工审核材料'})
        old = self.repo.approve(jid)
        self.snapshot([jid], now=100)
        self.snapshot([], now=200)
        self.repo.close()
        self.repo = Repository(self.path)
        self.assertEqual(self.lifecycle.list_missing(self.repo)[0]['job_id'], jid)
        self.assertEqual(self.lifecycle.source_status(self.repo)[0]['last_success_at'], 200)
        result = self.snapshot([jid], now=300)
        self.assertEqual((result['new'], result['returned'], result['missing']), (0, 1, 0))
        self.assertEqual(self.lifecycle.list_missing(self.repo), [])
        self.assertEqual(self.repo.get_job(jid)['status'], 'READY_FOR_REVIEW')
        self.assertIsNotNone(self.repo.list_approvals(jid)[0]['invalidated_at'])
        with self.assertRaises(ValueError):
            self.repo.prepare_handoff(jid)
        fresh = self.repo.approve(jid)
        self.assertNotEqual(fresh['id'], old['id'])
        self.assertEqual(self.repo.prepare_handoff(jid)['approval_id'], fresh['id'])
        self.assertEqual(self.snapshot([jid], now=400)['returned'], 0)
        self.assertEqual(self.snapshot([], now=500)['missing'], 1)
        self.assertEqual(self.lifecycle.list_missing(self.repo)[0], {
            'source': 'board:a', 'job_id': jid, 'first_seen_at': 100,
            'last_seen_at': 400, 'missing_since': 500,
        })

    def test_missing_and_returned_preserve_terminal_status_and_history(self):
        for status in ('SUBMITTED', 'RESULT_UNKNOWN', 'EXECUTING', 'SKIPPED', 'CLOSED'):
            with self.subTest(status=status):
                source = 'board:' + status
                jid = self.job(source=source)
                self.repo.save_material(jid, {'message': '人工审核材料'})
                self.repo.approve(jid)
                if status == 'SKIPPED':
                    self.repo.skip(jid)
                else:
                    claim = self.repo.claim_execution(jid)
                    if status != 'EXECUTING':
                        result = 'unknown' if status == 'RESULT_UNKNOWN' else 'submitted'
                        self.repo.finish_execution(claim['id'], result=result, evidence='人工回执')
                    if status == 'CLOSED':
                        self.repo.set_followup(jid, status='closed')
                job = self.repo.get_job(jid)
                logs = self.repo.list_logs(jid)
                approvals = self.repo.list_approvals(jid)
                executions = self.repo.list_executions(jid)
                self.snapshot([jid], source=source, now=100)
                self.assertEqual(self.snapshot([], source=source, now=200)['missing'], 1)
                self.assertEqual(self.repo.get_job(jid), job)
                self.assertEqual(self.repo.list_logs(jid), logs)
                self.assertEqual(self.snapshot([jid], source=source, now=300)['returned'], 1)
                self.assertEqual(self.repo.get_job(jid)['status'], status)
                self.assertEqual(self.repo.list_approvals(jid), approvals)
                self.assertEqual(self.repo.list_executions(jid), executions)

    def test_run_insert_failure_rolls_back_missing_and_approval_invalidation(self):
        jid = self.job()
        self.repo.save_material(jid, {'message': '人工审核材料'})
        approval = self.repo.approve(jid)
        self.snapshot([jid], now=100)
        logs = self.repo.list_logs(jid)
        self.repo._db.execute('''CREATE TRIGGER fail_run BEFORE INSERT ON source_runs
            BEGIN SELECT RAISE(ABORT, '模拟写入失败'); END''')
        with self.assertRaises(sqlite3.IntegrityError):
            self.snapshot([], now=200)
        self.assertEqual(self.lifecycle.list_missing(self.repo), [])
        self.assertEqual(self.lifecycle.source_status(self.repo)[0]['last_success_at'], 100)
        self.assertEqual(self.repo.list_approvals(jid), [approval])
        self.assertEqual(self.repo.list_logs(jid), logs)
        self.assertEqual(self.repo.prepare_handoff(jid)['approval_id'], approval['id'])

    def test_failed_first_snapshot_rolls_back_lazy_schema(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.snapshot([-1], now=100)
        names = {row[0] for row in self.repo._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertNotIn('source_runs', names)
        self.assertNotIn('job_availability', names)
        self.assertEqual(self.lifecycle.list_missing(self.repo), [])
        self.assertEqual(self.lifecycle.source_status(self.repo), [])

    def test_each_attempt_appends_run_but_changes_stay_idempotent(self):
        jid = self.job()
        self.snapshot([jid], now=100)
        self.snapshot([], now=200)
        self.snapshot([jid], complete=False, now=300)
        self.snapshot([jid], now=400)
        self.snapshot([jid], now=500)
        runs = [tuple(row) for row in self.repo._db.execute(
            'SELECT complete,new,returned,missing FROM source_runs ORDER BY id')]
        self.assertEqual(runs, [(1, 1, 0, 0), (1, 0, 0, 1), (0, 0, 0, 0),
                                (1, 0, 1, 0), (1, 0, 0, 0)])


if __name__ == '__main__':
    unittest.main()
