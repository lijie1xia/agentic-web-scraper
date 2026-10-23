"""SQLite persistence for a local, human-approved job workflow.

Connections use WAL, foreign keys, a busy timeout, and BEGIN IMMEDIATE for
per-job mutations. JSON hashes are deterministic; raw JD text is never stripped.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import math
import sqlite3
import threading
import time

from .lifecycle import unavailable_reason


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)


def _hash(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


class Repository:
    def __init__(self, path):
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(path), timeout=10, isolation_level=None,
                                   check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute('PRAGMA busy_timeout=10000')
        self._db.execute('PRAGMA foreign_keys=ON')
        self._db.execute('PRAGMA journal_mode=WAL')
        self._db.executescript('''
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY, identity TEXT NOT NULL UNIQUE,
                job TEXT NOT NULL, decision TEXT NOT NULL,
                source TEXT NOT NULL, raw_jd TEXT NOT NULL,
                jd_hash TEXT NOT NULL, status TEXT NOT NULL,
                revision INTEGER NOT NULL DEFAULT 1,
                created_at REAL NOT NULL, updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS identities (
                identity TEXT PRIMARY KEY, job_id INTEGER NOT NULL REFERENCES jobs(id)
            );
            CREATE TABLE IF NOT EXISTS revisions (
                id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL REFERENCES jobs(id),
                revision INTEGER NOT NULL, job TEXT NOT NULL, decision TEXT NOT NULL,
                raw_jd TEXT NOT NULL, jd_hash TEXT NOT NULL, created_at REAL NOT NULL,
                UNIQUE(job_id,revision)
            );
            CREATE TABLE IF NOT EXISTS materials (
                id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL REFERENCES jobs(id),
                revision INTEGER NOT NULL, jd_hash TEXT NOT NULL,
                content_hash TEXT NOT NULL, content TEXT NOT NULL, created_at REAL NOT NULL,
                UNIQUE(id,job_id)
            );
            CREATE TABLE IF NOT EXISTS approvals (
                id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL REFERENCES jobs(id),
                material_id INTEGER NOT NULL, revision INTEGER NOT NULL,
                jd_hash TEXT NOT NULL, content_hash TEXT NOT NULL, action TEXT NOT NULL,
                created_at REAL NOT NULL, expires_at REAL NOT NULL,
                invalidated_at REAL, consumed_at REAL, review_note TEXT NOT NULL,
                acknowledge_review INTEGER NOT NULL DEFAULT 0,
                UNIQUE(id,job_id),
                FOREIGN KEY(material_id,job_id) REFERENCES materials(id,job_id)
            );
            CREATE TABLE IF NOT EXISTS executions (
                id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL UNIQUE REFERENCES jobs(id),
                approval_id INTEGER NOT NULL UNIQUE, status TEXT NOT NULL,
                evidence TEXT NOT NULL, created_at REAL NOT NULL, finished_at REAL,
                FOREIGN KEY(approval_id,job_id) REFERENCES approvals(id,job_id)
            );
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL REFERENCES jobs(id),
                event TEXT NOT NULL, details TEXT NOT NULL, created_at REAL NOT NULL
            );
        ''')

    def close(self):
        with self._lock:
            self._db.close()

    @contextmanager
    def _transaction(self):
        with self._lock:
            self._db.execute('BEGIN IMMEDIATE')
            try:
                yield
                self._db.execute('COMMIT')
            except BaseException:
                self._db.execute('ROLLBACK')
                raise

    @staticmethod
    def _record(row):
        record = dict(row)
        for key in ('job', 'decision'):
            record[key] = json.loads(record[key])
        return record

    def get_job(self, job_id):
        with self._lock:
            row = self._db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
            if row is None:
                raise KeyError(job_id)
            return self._record(row)

    def list_jobs(self):
        with self._lock:
            return [self._record(row) for row in self._db.execute('SELECT * FROM jobs ORDER BY id')]

    def summary(self):
        with self._lock:
            return {row[0]: row[1] for row in self._db.execute(
                'SELECT status, COUNT(*) FROM jobs GROUP BY status')}

    def list_revisions(self, job_id):
        with self._lock:
            self.get_job(job_id)
            return [self._record(row) for row in self._db.execute(
                'SELECT * FROM revisions WHERE job_id=? ORDER BY revision', (job_id,))]

    def _log(self, job_id, event, details=None):
        self._db.execute('INSERT INTO logs (job_id,event,details,created_at) VALUES (?,?,?,?)',
                         (job_id, event, _json(details or {}), time.time()))

    def list_logs(self, job_id):
        with self._lock:
            self.get_job(job_id)
            records = [dict(row) for row in self._db.execute(
                'SELECT * FROM logs WHERE job_id=? ORDER BY id', (job_id,))]
            for record in records:
                record['details'] = json.loads(record['details'])
            return records

    def _invalidate(self, job_id, reason):
        now = time.time()
        self._db.execute('''UPDATE approvals SET invalidated_at=?
            WHERE job_id=? AND invalidated_at IS NULL AND consumed_at IS NULL''', (now, job_id))
        self._db.execute('''UPDATE jobs SET status='READY_FOR_REVIEW', updated_at=?
            WHERE id=? AND status='APPROVED' ''', (now, job_id))
        self._log(job_id, reason)

    def list_materials(self, job_id):
        with self._lock:
            self.get_job(job_id)
            records = [dict(row) for row in self._db.execute(
                'SELECT * FROM materials WHERE job_id=? ORDER BY id', (job_id,))]
            for record in records:
                record['content'] = json.loads(record['content'])
            return records

    def latest_material(self, job_id):
        """Return latest historical material; authorization also checks its revision."""
        materials = self.list_materials(job_id)
        return materials[-1] if materials else None

    def save_material(self, job_id, material: dict, *, expected_material_hash=None,
                      expected_revision=None):
        """编辑须提供展示版本与材料哈希；内部生成可不提供旧材料哈希。"""
        if not isinstance(material, dict) or not material:
            raise ValueError('Nonempty material dict required')
        encoded = _json(material)
        content_hash = _hash(encoded)
        with self._transaction():
            job = self.get_job(job_id)
            self._require_open(job)
            latest = self.latest_material(job_id)
            # 编辑必须携带展示版本；无材料哈希的调用保留内部新生成路径。
            if expected_material_hash is not None and expected_revision is None:
                raise ValueError('Displayed revision required for material editing')
            if expected_revision is not None and (
                    type(expected_revision) is not int or expected_revision != job['revision']):
                raise ValueError('Stale material editor: job revision changed')
            if expected_material_hash is not None and (
                    latest is None or latest['revision'] != job['revision']
                    or latest['content_hash'] != expected_material_hash):
                raise ValueError('Stale material editor; refresh before saving')
            if latest and latest['revision'] == job['revision'] and latest['content_hash'] == content_hash:
                return latest
            self._invalidate(job_id, 'material_changed')
            self._db.execute('''INSERT INTO materials
                (job_id,revision,jd_hash,content_hash,content,created_at) VALUES (?,?,?,?,?,?)''',
                (job_id, job['revision'], job['jd_hash'], content_hash, encoded, time.time()))
            return self.latest_material(job_id)

    def list_approvals(self, job_id=None):
        with self._lock:
            if job_id is None:
                rows = self._db.execute('SELECT * FROM approvals ORDER BY id')
            else:
                self.get_job(job_id)
                rows = self._db.execute('SELECT * FROM approvals WHERE job_id=? ORDER BY id', (job_id,))
            return [dict(row) for row in rows]

    @staticmethod
    def _check_policy(job, acknowledge_review):
        decision = job['decision']
        category = str(decision.get('category', '')).lower()
        if category == 'reject' or (not category and decision.get('recommend') is False):
            raise ValueError('Rejected jobs cannot be approved')
        if category not in {'priority', 'recommend', 'recommended', 'apply', 'accept'}:
            if acknowledge_review is not True:
                raise ValueError('Uncertain decision requires acknowledge_review=True before approval')

    def approve(self, job_id, *, action='manual_contact', ttl_hours=24, review_note='',
                expected_jd_hash=None, expected_material_hash=None, expected_revision=None,
                acknowledge_review=False):
        """Bind explicit approval to the exact revision and latest material.

        Review/unknown decisions require acknowledge_review=True. Reject is never
        overridable. Reapproving an unchanged, live grant preserves its expiry.
        UI 快照一旦提供哈希，必须同时提供展示时的岗位版本。
        """
        if action != 'manual_contact':
            raise ValueError('Only manual_contact approval is supported')
        if (type(ttl_hours) not in (int, float) or not math.isfinite(ttl_hours)
                or ttl_hours <= 0 or not math.isfinite(ttl_hours * 3600)):
            raise ValueError('ttl_hours must be a positive finite number')
        if not isinstance(review_note, str):
            raise ValueError('review_note must be text')
        with self._transaction():
            job = self.get_job(job_id)
            self._require_open(job)
            self._check_policy(job, acknowledge_review)
            reason = unavailable_reason(self, job)
            if reason:
                raise ValueError(reason)
            material = self.latest_material(job_id)
            if material is None or material['revision'] != job['revision']:
                raise ValueError('Current material is required; regenerate after a JD or decision edit')
            if (expected_jd_hash is not None or expected_material_hash is not None) and expected_revision is None:
                raise ValueError('Displayed revision required for review')
            if expected_revision is not None and (
                    type(expected_revision) is not int or expected_revision != job['revision']):
                raise ValueError('Stale review card: job revision changed')
            if expected_jd_hash is not None and expected_jd_hash != job['jd_hash']:
                raise ValueError('Stale review card: JD changed')
            if expected_material_hash is not None and expected_material_hash != material['content_hash']:
                raise ValueError('Stale review card: material changed')
            now = time.time()
            for approval in reversed(self.list_approvals(job_id)):
                if (approval['invalidated_at'] is None and approval['consumed_at'] is None
                        and approval['expires_at'] > now and approval['action'] == action):
                    return approval
            self._invalidate(job_id, 'approval_replaced')
            self._db.execute('''INSERT INTO approvals
                (job_id,material_id,revision,jd_hash,content_hash,action,created_at,expires_at,review_note,acknowledge_review)
                VALUES (?,?,?,?,?,?,?,?,?,?)''',
                (job_id, material['id'], job['revision'], job['jd_hash'], material['content_hash'],
                 action, now, now + ttl_hours * 3600, review_note, int(acknowledge_review is True)))
            self._db.execute("UPDATE jobs SET status='APPROVED',updated_at=? WHERE id=?", (now, job_id))
            self._log(job_id, 'approved', {'material_id': material['id'], 'action': action})
            return self.list_approvals(job_id)[-1]

    @staticmethod
    def _require_open(job):
        if job['status'] not in {'READY_FOR_REVIEW', 'APPROVED'}:
            raise ValueError('Job is not open for approval/execution: ' + job['status'])

    def _authorized(self, job_id):
        """Called only inside a transaction; no authorization/claim race window."""
        job = self.get_job(job_id)
        self._require_open(job)
        reason = unavailable_reason(self, job)
        if reason:
            raise ValueError(reason)
        if job['status'] != 'APPROVED':
            raise ValueError('Current manual_contact approval required')
        if self._db.execute('SELECT 1 FROM executions WHERE job_id=?', (job_id,)).fetchone():
            raise ValueError('Job already claimed; never retry automatically')
        material = self.latest_material(job_id)
        if material is None or material['revision'] != job['revision']:
            raise ValueError('Current material required')
        now = time.time()
        for approval in reversed(self.list_approvals(job_id)):
            if (approval['invalidated_at'] is None and approval['consumed_at'] is None
                    and approval['action'] == 'manual_contact'
                    and approval['expires_at'] > now
                    and approval['revision'] == job['revision']
                    and approval['jd_hash'] == job['jd_hash']
                    and approval['material_id'] == material['id']
                    and approval['content_hash'] == material['content_hash']):
                self._check_policy(job, bool(approval['acknowledge_review']))
                return job, material, approval
        raise ValueError('Approval missing, stale, consumed, or expired')

    def prepare_handoff(self, job_id):
        """Read an authorized snapshot atomically; does NOT claim or send.

        Repeated previews are harmless. A preview is not a durable permission:
        record_manual_submission/claim_execution revalidate inside their writes.
        """
        with self._transaction():
            job, material, approval = self._authorized(job_id)
            return {
                'job_id': job_id, 'job': job['job'], 'raw_jd': job['raw_jd'],
                'url': job['job'].get('source_url') or job['job'].get('url') or '',
                'material': material['content'], 'material_id': material['id'],
                'approval_id': approval['id'], 'action': approval['action'],
                'revision': job['revision'],
                'jd_hash': job['jd_hash'], 'content_hash': material['content_hash'],
                'expires_at': approval['expires_at'], 'sent': False, 'dry_run': True,
            }

    def list_executions(self, job_id):
        with self._lock:
            self.get_job(job_id)
            return [dict(row) for row in self._db.execute(
                'SELECT * FROM executions WHERE job_id=? ORDER BY id', (job_id,))]

    def claim_execution(self, job_id):
        """Reserve once, atomically, without contacting any external system.

        Claims never expire or auto-retry: a crash leaves EXECUTING and requires
        human reconciliation. Unique job_id is a second guard beyond the lock.
        """
        with self._transaction():
            job, material, approval = self._authorized(job_id)
            now = time.time()
            self._db.execute('''INSERT INTO executions
                (job_id,approval_id,status,evidence,created_at)
                VALUES (?,?,'CLAIMED','',?)''', (job_id, approval['id'], now))
            self._db.execute('UPDATE approvals SET consumed_at=? WHERE id=?', (now, approval['id']))
            self._db.execute("UPDATE jobs SET status='EXECUTING',updated_at=? WHERE id=?", (now, job_id))
            self._log(job_id, 'execution_claimed', {'approval_id': approval['id']})
            return self.list_executions(job_id)[-1]

    def finish_execution(self, claim_id, *, result='unknown', evidence=''):
        """Record an outcome once. Unknown is final and never schedules retries.

        Recording evidence does not send anything; even an expired claim may be
        finalized because this is a historical observation, not a new permission.
        """
        if result not in {'unknown', 'submitted'} or not isinstance(evidence, str):
            raise ValueError('Result must be unknown/submitted with text evidence')
        if result == 'submitted' and not evidence.strip():
            raise ValueError('Submitted result requires nonempty evidence')
        with self._transaction():
            row = self._db.execute('SELECT * FROM executions WHERE id=?', (claim_id,)).fetchone()
            if row is None:
                raise KeyError(claim_id)
            if row['status'] != 'CLAIMED':
                raise ValueError('Execution already finalized; no automatic retry or overwrite')
            status = 'SUBMITTED' if result == 'submitted' else 'RESULT_UNKNOWN'
            now = time.time()
            self._db.execute('UPDATE executions SET status=?,evidence=?,finished_at=? WHERE id=?',
                             (status, evidence, now, claim_id))
            self._db.execute('UPDATE jobs SET status=?,updated_at=? WHERE id=?', (status, now, row['job_id']))
            self._log(row['job_id'], 'execution_finished',
                      {'execution_id': claim_id, 'status': status, 'evidence': evidence})
            return self.list_executions(row['job_id'])[-1]

    def record_manual_submission(self, job_id, *, evidence: str,
                                 expected_jd_hash=None, expected_material_hash=None,
                                 expected_revision=None, expected_approval_id=None):
        """仅登记人工证据，不发送；缺失展示版本或审批身份时拒绝登记。"""
        if not isinstance(evidence, str) or not evidence.strip():
            raise ValueError('Nonempty manual submission evidence required')
        with self._transaction():
            job, material, approval = self._authorized(job_id)
            # 同内容的新审批不是旧页面的授权；版本和审批身份必须同时匹配。
            if type(expected_revision) is not int or job['revision'] != expected_revision:
                raise ValueError('Stale manual confirmation: displayed revision required')
            if type(expected_approval_id) is not int or approval['id'] != expected_approval_id:
                raise ValueError('Stale manual confirmation: displayed approval changed or missing')
            if expected_jd_hash is not None and job['jd_hash'] != expected_jd_hash:
                raise ValueError('Stale manual confirmation: JD changed')
            if expected_material_hash is not None and material['content_hash'] != expected_material_hash:
                raise ValueError('Stale manual confirmation: material changed')
            now = time.time()
            self._db.execute('''INSERT INTO executions
                (job_id,approval_id,status,evidence,created_at,finished_at)
                VALUES (?,?,'SUBMITTED',?,?,?)''', (job_id, approval['id'], evidence, now, now))
            self._db.execute('UPDATE approvals SET consumed_at=? WHERE id=?', (now, approval['id']))
            self._db.execute("UPDATE jobs SET status='SUBMITTED',updated_at=? WHERE id=?", (now, job_id))
            self._log(job_id, 'manual_submission', {'evidence': evidence, 'approval_id': approval['id']})
            return self.get_job(job_id)

    def set_followup(self, job_id, *, status: str, note: str = ''):
        if status not in {'replied', 'interview', 'closed'} or not isinstance(note, str):
            raise ValueError('Follow-up requires replied/interview/closed and a text note')
        with self._transaction():
            job = self.get_job(job_id)
            if job['status'] not in {'SUBMITTED', 'REPLIED', 'INTERVIEW'}:
                raise ValueError('Follow-up requires a submitted, non-closed job')
            self._db.execute('UPDATE jobs SET status=?,updated_at=? WHERE id=?',
                             (status.upper(), time.time(), job_id))
            self._log(job_id, 'followup', {'status': status, 'note': note})
            return self.get_job(job_id)

    def skip(self, job_id):
        with self._transaction():
            job = self.get_job(job_id)
            self._require_open(job)
            self._invalidate(job_id, 'skipped')
            self._db.execute("UPDATE jobs SET status='SKIPPED',updated_at=? WHERE id=?", (time.time(), job_id))

    @staticmethod
    def _identities(job, source, raw_jd):
        identities = []
        url = job.get('source_url') or job.get('url')
        if url:
            identities.append(_json(['url', url]))
        external_id = job.get('external_id')
        if external_id is not None and external_id != '':
            identities.append(_json(['external', source, str(external_id)]))
        if not identities:
            if not raw_jd.strip():
                raise ValueError('A source URL, external_id, or nonempty raw JD is required')
            identities.append(_json(['paste', _hash(raw_jd)]))
        return identities

    def upsert_job(self, job: dict, *, source='manual', raw_jd='', decision=None):
        if not isinstance(job, dict) or not isinstance(raw_jd, str):
            raise ValueError('job must be a dict and raw_jd must be text')
        if decision is not None and not isinstance(decision, dict):
            raise ValueError('decision must be a dict')
        identities = self._identities(job, source, raw_jd)
        encoded = _json(job)
        jd_hash = _hash(_json([job, raw_jd]))
        with self._transaction():
            ids = {row[0] for identity in identities for row in self._db.execute(
                'SELECT job_id FROM identities WHERE identity=?', (identity,))}
            if len(ids) > 1:
                raise ValueError('Conflicting job identities; explicit reconciliation required')
            now = time.time()
            changed = False
            if not ids:
                cursor = self._db.execute('''INSERT INTO jobs
                    (identity,job,decision,source,raw_jd,jd_hash,status,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,'READY_FOR_REVIEW',?,?)''',
                    (identities[0], encoded, _json(decision or {}), source, raw_jd, jd_hash, now, now))
                job_id = cursor.lastrowid
                changed = True
            else:
                job_id = ids.pop()
                old = self.get_job(job_id)
                next_decision = old['decision'] if decision is None else decision
                changed = old['jd_hash'] != jd_hash or old['decision'] != next_decision
                if changed:
                    self._invalidate(job_id, 'job_changed')
                    self._db.execute('''UPDATE jobs SET job=?,decision=?,raw_jd=?,jd_hash=?,
                        revision=revision+1,updated_at=? WHERE id=?''',
                        (encoded, _json(next_decision), raw_jd, jd_hash, now, job_id))
            for identity in identities:
                self._db.execute('INSERT OR IGNORE INTO identities VALUES (?,?)', (identity, job_id))
            if changed:
                self._db.execute('''INSERT INTO revisions
                    (job_id,revision,job,decision,raw_jd,jd_hash,created_at)
                    SELECT id,revision,job,decision,raw_jd,jd_hash,? FROM jobs WHERE id=?''', (now, job_id))
            return self.get_job(job_id)
