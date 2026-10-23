"""来源完整快照与岗位可用性；投递状态仍由 Repository 管理。"""
import time
from datetime import date


def _schema(db):
    # execute 不会像 executescript 一样提前提交调用方事务。
    db.execute('''CREATE TABLE IF NOT EXISTS source_runs (
        id INTEGER PRIMARY KEY, source TEXT NOT NULL, observed_at REAL NOT NULL,
        complete INTEGER NOT NULL, new INTEGER NOT NULL,
        returned INTEGER NOT NULL, missing INTEGER NOT NULL
    )''')
    db.execute('''CREATE TABLE IF NOT EXISTS job_availability (
        source TEXT NOT NULL, job_id INTEGER NOT NULL REFERENCES jobs(id),
        first_seen_at REAL NOT NULL, last_seen_at REAL NOT NULL, missing_since REAL,
        PRIMARY KEY(source, job_id)
    )''')


def record_snapshot(repository, source, job_ids, *, complete=True, now=None):
    """登记已完整导入、未经筛选的来源全量岗位 ID，返回变化计数及新鲜度。

    complete=False 用于失败或不完整抓取：只追加尝试记录，忽略岗位 ID。
    now 是快照的 Unix 秒时间；审批失效时间仍由 Repository 记录。
    new 表示首次出现在此来源，returned 表示缺席后重现；重复快照只刷新时间。
    """
    now = time.time() if now is None else now
    ids = set(job_ids)
    result = {'source': source, 'complete': complete, 'new': 0, 'returned': 0,
              'missing': 0, 'last_run_at': now, 'last_success_at': now}
    with repository._transaction():
        db = repository._db
        _schema(db)
        result['last_success_at'] = db.execute('''SELECT MAX(observed_at)
            FROM source_runs WHERE source=? AND complete=1''', (source,)).fetchone()[0]
        if complete:
            previous = {row['job_id']: row for row in db.execute(
                'SELECT * FROM job_availability WHERE source=?', (source,))}
            result['new'] = len(ids - previous.keys())
            result['returned'] = sum(previous[job_id]['missing_since'] is not None
                                     for job_id in ids & previous.keys())
            for job_id in ids:
                db.execute('''INSERT INTO job_availability
                    (source,job_id,first_seen_at,last_seen_at) VALUES (?,?,?,?)
                    ON CONFLICT(source,job_id) DO UPDATE
                    SET last_seen_at=excluded.last_seen_at, missing_since=NULL''',
                    (source, job_id, now, now))
            missing_ids = {job_id for job_id, row in previous.items()
                           if job_id not in ids and row['missing_since'] is None}
            result['missing'] = len(missing_ids)
            for job_id in missing_ids:
                db.execute('''UPDATE job_availability SET missing_since=?
                    WHERE source=? AND job_id=?''', (now, source, job_id))
                if repository.get_job(job_id)['status'] in {'READY_FOR_REVIEW', 'APPROVED'}:
                    repository._invalidate(job_id, 'source_missing')
            result['last_success_at'] = now
        db.execute('''INSERT INTO source_runs (source,observed_at,complete,new,returned,missing)
            VALUES (?,?,?,?,?,?)''',
            (source, now, int(complete), result['new'], result['returned'], result['missing']))
    return result


def unavailable_reason(repository, job):
    """供审批事务与只读展示共用；未接入来源跟踪的旧库不受影响。"""
    deadline = job['job'].get('deadline')
    if deadline:
        try:
            expired = date.fromisoformat(deadline) < date.today()
        except (ValueError, TypeError):
            return '截止日期格式待核验'
        if expired:
            return f'已超过来源标注的截止日期 {deadline}'
    with repository._lock:
        db = repository._db
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='job_availability'").fetchone():
            states = list(db.execute('SELECT missing_since FROM job_availability WHERE job_id=?', (job['id'],)))
            if states and all(row[0] is not None for row in states):
                return '来源完整快照中缺失，需重新核验岗位'
    return ''


def list_missing(repository, *, source=None):
    """缺席只表示完整快照中未出现，不能推断岗位已关闭。"""
    with repository._transaction():
        db = repository._db
        _schema(db)
        sql = 'SELECT * FROM job_availability WHERE missing_since IS NOT NULL'
        args = ()
        if source is not None:
            sql += ' AND source=?'
            args = (source,)
        return [dict(row) for row in db.execute(sql + ' ORDER BY source,job_id', args)]


def source_status(repository):
    """列出最近一次尝试、完整成功时间及各来源可用性计数。"""
    with repository._transaction():
        db = repository._db
        _schema(db)
        rows = db.execute('''SELECT r.source, r.observed_at AS last_run_at,
            (SELECT MAX(observed_at) FROM source_runs s
             WHERE s.source=r.source AND s.complete=1) AS last_success_at,
            r.complete,
            (SELECT COUNT(*) FROM job_availability a
             WHERE a.source=r.source AND a.missing_since IS NULL) AS present,
            (SELECT COUNT(*) FROM job_availability a
             WHERE a.source=r.source AND a.missing_since IS NOT NULL) AS missing
            FROM source_runs r WHERE r.id=(SELECT MAX(id) FROM source_runs s
                WHERE s.source=r.source) ORDER BY r.source''')
        return [dict(row, complete=bool(row['complete'])) for row in rows]
