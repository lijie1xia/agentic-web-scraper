"""Persistence and authorization contract; standard-library unittest only."""
from contextlib import closing
import importlib
import sqlite3
import tempfile
import unittest
from pathlib import Path


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'workflow.sqlite3'

    def repository(self):
        try:
            module = importlib.import_module('scraper_framework.job_workflow.repository')
        except ModuleNotFoundError:
            self.fail('The local workflow repository must exist')
        repo = module.Repository(self.path)
        self.addCleanup(repo.close)
        return repo

    def test_persists_exact_raw_jd_and_deduplicates_after_restart(self):
        repo = self.repository()
        job = {'source_url': 'https://example.test/jobs/1', 'job_title': 'Engineer'}
        raw = '  原始 JD\nPython\r\n'
        saved = repo.upsert_job(job, source='site', raw_jd=raw,
                                decision={'category': 'recommend'})
        repo.close()
        repo = self.repository()
        duplicate = repo.upsert_job(job, source='site', raw_jd=raw,
                                    decision={'category': 'recommend'})
        self.assertEqual(saved['id'], duplicate['id'])
        self.assertEqual(repo.get_job(saved['id'])['raw_jd'], raw)
        self.assertEqual(duplicate['job'], job)
        self.assertEqual(duplicate['decision'], {'category': 'recommend'})
        self.assertEqual(duplicate['status'], 'READY_FOR_REVIEW')
        self.assertEqual(len(repo.list_jobs()), 1)
        self.assertEqual(repo.summary(), {'READY_FOR_REVIEW': 1})
        with closing(sqlite3.connect(self.path)) as conn:
            self.assertEqual(conn.execute('PRAGMA journal_mode').fetchone()[0], 'wal')
    def test_identity_aliases_and_incremental_revisions(self):
        repo = self.repository()
        first = repo.upsert_job({'external_id': '42'}, source='board', raw_jd='v1')
        changed = repo.upsert_job({'external_id': '42', 'source_url': 'https://x.test/42'},
                                  source='board', raw_jd='v2')
        via_url = repo.upsert_job(changed['job'], source='other', raw_jd='v2')
        self.assertEqual(first['id'], changed['id'])
        self.assertEqual(changed['id'], via_url['id'])
        self.assertNotEqual(first['jd_hash'], changed['jd_hash'])
        self.assertEqual(changed['revision'], 2)
        self.assertEqual(via_url['revision'], 2)
        self.assertEqual([r['raw_jd'] for r in repo.list_revisions(first['id'])], ['v1', 'v2'])
        paste = repo.upsert_job({}, source='paste', raw_jd='  Exact text\n')
        duplicate = repo.upsert_job({'job_title': 'extracted'}, source='paste', raw_jd='  Exact text\n')
        self.assertEqual(paste['id'], duplicate['id'])
        other = repo.upsert_job({'external_id': '42'}, source='another', raw_jd='v1')
        self.assertNotEqual(other['id'], first['id'])
        with self.assertRaises(ValueError):
            repo.upsert_job({})
    def test_material_approval_is_idempotent_but_edits_invalidate(self):
        repo = self.repository()
        job = {'source_url': 'https://example.test/approval'}
        saved = repo.upsert_job(job, raw_jd='JD', decision={'category': 'recommend'})
        jid = saved['id']
        self.assertIsNone(repo.latest_material(jid))
        material = repo.save_material(jid, {'message': 'Exact approved text'})
        approved = repo.approve(jid)
        self.assertEqual(repo.get_job(jid)['status'], 'APPROVED')
        self.assertEqual(approved['material_id'], material['id'])
        self.assertEqual(approved['jd_hash'], saved['jd_hash'])
        repo.upsert_job(job, raw_jd='JD')
        self.assertEqual(repo.save_material(jid, {'message': 'Exact approved text'})['id'], material['id'])
        self.assertEqual(repo.approve(jid)['id'], approved['id'])
        self.assertEqual(repo.get_job(jid)['status'], 'APPROVED')
        edited = repo.save_material(jid, {'message': 'Edited text'})
        self.assertNotEqual(edited['content_hash'], material['content_hash'])
        self.assertEqual(repo.get_job(jid)['status'], 'READY_FOR_REVIEW')
        self.assertIsNotNone(repo.list_approvals(jid)[0]['invalidated_at'])
        repo.approve(jid)
        repo.upsert_job(job, raw_jd='Changed JD')
        with self.assertRaises(ValueError):
            repo.approve(jid)
        repo.save_material(jid, {'message': 'Edited text'})
        repo.approve(jid)
        self.assertEqual(len(repo.list_materials(jid)), 3)
        self.assertEqual(len(repo.list_approvals()), 3)
        self.assertTrue(repo.list_logs(jid))
        self.assertEqual(repo.latest_material(jid)['content'], {'message': 'Edited text'})
    def test_approval_policy_blocks_reject_and_requires_review_note(self):
        repo = self.repository()
        for category in ('reject', 'review', 'unknown', ''):
            with self.subTest(category=category):
                job = repo.upsert_job({'external_id': category or 'empty'},
                                      decision={'category': category})
                jid = job['id']
                repo.save_material(jid, {'message': 'Hello'})
                with self.assertRaises(ValueError):
                    repo.approve(jid)
                if category == 'reject':
                    with self.assertRaises(ValueError):
                        repo.approve(jid, review_note='I checked')
                else:
                    approval = repo.approve(jid, acknowledge_review=True,
                                            review_note='I verified the uncertain requirements')
                    self.assertTrue(approval['review_note'])
        jid = repo.upsert_job({'external_id': 'safe'}, decision={'category': 'recommend'})['id']
        with self.assertRaises(ValueError):
            repo.approve(jid)
        repo.save_material(jid, {'message': 'Hello'})
        for ttl in (0, -1, float('inf'), float('nan'), True, '24'):
            with self.subTest(ttl=ttl), self.assertRaises(ValueError):
                repo.approve(jid, ttl_hours=ttl)
        with self.assertRaises(ValueError):
            repo.approve(jid, action='send')
        self.assertEqual(repo.get_job(jid)['status'], 'READY_FOR_REVIEW')
    def test_manual_submission_and_followup_are_single_use_and_terminal(self):
        repo = self.repository()
        job = {'source_url': 'https://example.test/submit'}
        jid = repo.upsert_job(job, raw_jd='JD', decision={'category': 'recommend'})['id']
        with self.assertRaises(ValueError):
            repo.record_manual_submission(jid, evidence='Receipt')
        with self.assertRaises(ValueError):
            repo.set_followup(jid, status='replied')
        repo.save_material(jid, {'message': 'Approved'})
        repo.approve(jid)
        with self.assertRaises(ValueError):
            repo.record_manual_submission(jid, evidence='  ')
        handoff = repo.prepare_handoff(jid)
        submitted = repo.record_manual_submission(jid, evidence='Receipt #123',
            expected_revision=handoff['revision'], expected_approval_id=handoff['approval_id'])
        self.assertEqual(submitted['status'], 'SUBMITTED')
        with self.assertRaises(ValueError):
            repo.record_manual_submission(jid, evidence='Duplicate')
        with self.assertRaises(ValueError):
            repo.approve(jid)
        repo.upsert_job(job, raw_jd='Changed JD', decision={'category': 'recommend'})
        self.assertEqual(repo.get_job(jid)['status'], 'SUBMITTED')
        for status in ('replied', 'interview', 'closed'):
            self.assertEqual(repo.set_followup(jid, status=status, note='Human update')['status'], status.upper())
        for action in (lambda: repo.approve(jid), lambda: repo.skip(jid),
                       lambda: repo.save_material(jid, {'message': 'new'}),
                       lambda: repo.set_followup(jid, status='replied')):
            with self.assertRaises(ValueError):
                action()
        self.assertEqual(repo.get_job(jid)['status'], 'CLOSED')
        self.assertEqual(repo.list_logs(jid)[-1]['details']['note'], 'Human update')
    def test_decision_categories_match_scoring_api(self):
        repo = self.repository()
        for category, recommend in (('priority', True), ('review', False)):
            jid = repo.upsert_job({'external_id': category},
                                  decision={'category': category, 'recommend': recommend})['id']
            repo.save_material(jid, {'message': 'Hello'})
            note = 'Checked uncertain eligibility' if category == 'review' else ''
            self.assertEqual(repo.approve(jid, review_note=note,
                                          acknowledge_review=category == 'review')['action'], 'manual_contact')

    def test_ui_hash_guards_and_review_acknowledgment(self):
        repo = self.repository()
        job = {'source_url': 'https://example.test/review'}
        record = repo.upsert_job(job, raw_jd='original', decision={'category': 'review'})
        jid = record['id']
        old = repo.save_material(jid, {'message': 'first'})
        with self.assertRaises(ValueError):
            repo.approve(jid, review_note='Note is not a checkbox')
        current = repo.save_material(jid, {'message': 'second'})
        with self.assertRaises(ValueError):
            repo.approve(jid, expected_jd_hash=record['jd_hash'],
                         expected_material_hash=old['content_hash'], expected_revision=record['revision'], acknowledge_review=True)
        changed = repo.upsert_job(job, raw_jd='changed', decision={'category': 'review'})
        repo.save_material(jid, current['content'])
        with self.assertRaises(ValueError):
            repo.approve(jid, expected_jd_hash=record['jd_hash'],
                         expected_material_hash=current['content_hash'], expected_revision=record['revision'], acknowledge_review=True)
        approval = repo.approve(jid, expected_jd_hash=changed['jd_hash'],
                                expected_material_hash=current['content_hash'], expected_revision=changed['revision'], acknowledge_review=True)
        self.assertTrue(approval['acknowledge_review'])
        self.assertEqual(len(repo.list_approvals(jid)), 1)
    def test_skip_and_decision_edits_do_not_reuse_approval(self):
        repo = self.repository()
        job = {'source_url': 'https://example.test/skipped'}
        jid = repo.upsert_job(job, raw_jd='JD', decision={'category': 'priority'})['id']
        repo.save_material(jid, {'message': 'One'})
        repo.approve(jid)
        repo.upsert_job(job, raw_jd='JD', decision={'category': 'reject'})
        self.assertEqual(repo.get_job(jid)['status'], 'READY_FOR_REVIEW')
        self.assertIsNotNone(repo.list_approvals(jid)[0]['invalidated_at'])
        self.assertIsNone(repo.skip(jid))
        repo.upsert_job(job, raw_jd='Updated', decision={'category': 'priority'})
        self.assertEqual(repo.get_job(jid)['status'], 'SKIPPED')
        with self.assertRaises(ValueError):
            repo.approve(jid)

    def test_failed_write_rolls_back_approval_and_history_and_enforces_foreign_keys(self):
        repo = self.repository()
        jid = repo.upsert_job({'external_id': 'tx'}, decision={'category': 'priority'})['id']
        repo.save_material(jid, {'message': 'Original'})
        approval = repo.approve(jid)
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute("""CREATE TRIGGER fail_material BEFORE INSERT ON materials
                BEGIN SELECT RAISE(ABORT, 'simulated disk write error'); END""")
        logs = repo.list_logs(jid)
        with self.assertRaises(sqlite3.IntegrityError):
            repo.save_material(jid, {'message': 'Must roll back'})
        self.assertEqual(repo.get_job(jid)['status'], 'APPROVED')
        self.assertEqual(repo.list_approvals(jid), [approval])
        self.assertEqual(repo.list_logs(jid), logs)
        self.assertEqual(len(repo.list_materials(jid)), 1)
        self.assertEqual(repo._db.execute('PRAGMA foreign_keys').fetchone()[0], 1)
        self.assertGreaterEqual(repo._db.execute('PRAGMA busy_timeout').fetchone()[0], 1000)
        with self.assertRaises(sqlite3.IntegrityError):
            repo._db.execute("INSERT INTO logs(job_id,event,details,created_at) VALUES(-1,'bad','{}',0)")
        with closing(sqlite3.connect(self.path)) as conn:
            self.assertEqual(conn.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_concurrent_upserts_deduplicate_and_identity_conflicts_roll_back(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        repo = self.repository()
        barrier = threading.Barrier(2)

        def upsert():
            other = type(repo)(self.path)
            try:
                barrier.wait(timeout=5)
                return other.upsert_job({'source_url': 'https://example.test/race'}, raw_jd='JD')['id']
            finally:
                other.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            ids = list(pool.map(lambda _: upsert(), range(2)))
        self.assertEqual(len(set(ids)), 1)
        separate = repo.upsert_job({'external_id': 'other'}, source='board')
        with self.assertRaises(ValueError):
            repo.upsert_job({'source_url': 'https://example.test/race', 'external_id': 'other'}, source='board')
        self.assertEqual(len(repo.list_jobs()), 2)
        self.assertEqual(repo.get_job(separate['id'])['revision'], 1)


if __name__ == '__main__':
    unittest.main()
