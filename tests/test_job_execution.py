"""Local execution safety: no adapters, accounts, network or browser side effects."""
import importlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scraper_framework.job_workflow.repository import Repository


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'workflow.sqlite3'
        self.repo = Repository(self.path)
        self.addCleanup(self.repo.close)
        self.job = {'source_url': 'https://example.test/jobs/1', 'job_title': 'Engineer'}
        self.jid = self.repo.upsert_job(self.job, raw_jd='JD', decision={'category': 'recommend'})['id']
        self.material = {'message': '  Exact\r\nmessage 原文', 'resume': {'skills': ['Python']}}

    def execution(self):
        try:
            return importlib.import_module('scraper_framework.job_workflow.execution')
        except ModuleNotFoundError:
            self.fail('The local execution module must exist')

    def ready(self):
        self.repo.save_material(self.jid, self.material)
        return self.repo.approve(self.jid)

    def test_handoff_and_dry_run_return_exact_approved_snapshot_without_sending(self):
        execution = self.execution()
        approval = self.ready()
        before = self.repo.list_logs(self.jid)
        with patch('socket.socket', side_effect=AssertionError('No network')), \
             patch('webbrowser.open', side_effect=AssertionError('No browser')), \
             patch('subprocess.Popen', side_effect=AssertionError('No external process')):
            handoff = execution.prepare_handoff(self.repo, self.jid)
            self.assertEqual(handoff['material'], self.material)
            self.assertEqual(handoff['url'], self.job['source_url'])
            self.assertEqual(handoff['approval_id'], approval['id'])
            self.assertEqual(handoff['revision'], approval['revision'])
            self.assertEqual(handoff['action'], 'manual_contact')
            self.assertFalse(handoff['sent'])
            self.assertEqual(execution.execute(self.repo, self.jid, dry_run=True), handoff)
            for kwargs in ({}, {'enabled': True}, {'adapter': lambda: self.fail('Adapter invoked')}):
                with self.assertRaises(ValueError):
                    execution.execute(self.repo, self.jid, **kwargs)
        self.assertEqual(self.repo.get_job(self.jid)['status'], 'APPROVED')
        self.assertEqual(self.repo.list_logs(self.jid), before)
    def test_missing_stale_and_expired_authorizations_fail_closed(self):
        execution = self.execution()
        with self.assertRaises(ValueError):
            execution.prepare_handoff(self.repo, self.jid)
        approval = self.ready()
        with patch('scraper_framework.job_workflow.repository.time.time', return_value=approval['expires_at']):
            with self.assertRaises(ValueError):
                execution.prepare_handoff(self.repo, self.jid)
            with self.assertRaises(ValueError):
                self.repo.record_manual_submission(self.jid, evidence='Too late')
        self.repo.save_material(self.jid, {'message': 'Changed'})
        with self.assertRaises(ValueError):
            execution.prepare_handoff(self.repo, self.jid)
        self.repo.approve(self.jid)
        self.repo.upsert_job(self.job, raw_jd='JD changed')
        with self.assertRaises(ValueError):
            execution.prepare_handoff(self.repo, self.jid)
        self.assertEqual(self.repo.get_job(self.jid)['status'], 'READY_FOR_REVIEW')

    def test_claim_is_atomic_and_duplicate_claims_are_blocked(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        approval = self.ready()
        barrier = threading.Barrier(2)

        def claim():
            repo = Repository(self.path)
            try:
                barrier.wait(timeout=5)
                try:
                    return repo.claim_execution(self.jid)
                except ValueError:
                    return None
            finally:
                repo.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: claim(), range(2)))
        winners = [r for r in results if r is not None]
        self.assertEqual(len(winners), 1)
        self.assertEqual(winners[0]['approval_id'], approval['id'])
        self.assertEqual(self.repo.get_job(self.jid)['status'], 'EXECUTING')
        self.assertEqual(len(self.repo.list_executions(self.jid)), 1)
        self.repo.close()
        self.repo = Repository(self.path)
        self.addCleanup(self.repo.close)
        for action in (lambda: self.repo.claim_execution(self.jid),
                       lambda: self.repo.approve(self.jid),
                       lambda: self.repo.record_manual_submission(self.jid, evidence='Duplicate'),
                       lambda: self.execution().prepare_handoff(self.repo, self.jid)):
            with self.assertRaises(ValueError):
                action()
    def test_ambiguous_result_never_retries_even_after_restart_or_edit(self):
        self.ready()
        claim = self.repo.claim_execution(self.jid)
        result = self.repo.finish_execution(claim['id'], result='unknown', evidence='Timeout; outcome unclear')
        self.assertEqual(result['status'], 'RESULT_UNKNOWN')
        self.repo.close()
        self.repo = Repository(self.path)
        self.addCleanup(self.repo.close)
        self.repo.upsert_job(self.job, raw_jd='Changed')
        self.assertEqual(self.repo.get_job(self.jid)['status'], 'RESULT_UNKNOWN')
        for action in (lambda: self.repo.claim_execution(self.jid),
                       lambda: self.repo.approve(self.jid),
                       lambda: self.repo.record_manual_submission(self.jid, evidence='Try again'),
                       lambda: self.repo.finish_execution(claim['id'], result='submitted', evidence='Late receipt'),
                       lambda: self.repo.set_followup(self.jid, status='replied')):
            with self.assertRaises(ValueError):
                action()
        self.assertEqual(len(self.repo.list_executions(self.jid)), 1)

    def test_claim_result_requires_evidence_and_cannot_be_overwritten(self):
        self.ready()
        claim = self.repo.claim_execution(self.jid)
        with self.assertRaises(ValueError):
            self.repo.finish_execution(claim['id'], result='submitted')
        with self.assertRaises(ValueError):
            self.repo.finish_execution(claim['id'], result='retry')
        self.assertEqual(self.repo.get_job(self.jid)['status'], 'EXECUTING')
        result = self.repo.finish_execution(claim['id'], result='submitted', evidence='Human receipt')
        self.assertEqual(result['status'], 'SUBMITTED')
        self.assertEqual(self.repo.get_job(self.jid)['status'], 'SUBMITTED')
        with self.assertRaises(ValueError):
            self.repo.finish_execution(claim['id'])


if __name__ == '__main__':
    unittest.main()
