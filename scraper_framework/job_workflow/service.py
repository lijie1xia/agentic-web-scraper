"""Offline-first orchestration: every external effect remains a manual action."""
from __future__ import annotations

import copy
import hashlib
import json
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ..job_agent.decision import score
from ..job_agent.skill_profile import default_skill_profile_path
from .materials import build_material, validate_material
from .offline import extract_text, split_postings
from .repository import Repository
from .lifecycle import unavailable_reason
from .preferences import calibrate, preference_sort_key

ROOT = Path(__file__).resolve().parents[2]
OPEN = {'READY_FOR_REVIEW', 'APPROVED'}


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()


def _fit_notice(text, limit=4000):
    """微信单条上限内保留开头；超出时明确还有内容在审核台。"""
    note = '\n其余岗位请在本机审核台查看。\n'
    if len(text) <= limit:
        return text
    kept = text[:limit - len(note)].rstrip()
    return kept + note


def canonical_url(value):
    if not value or str(value).startswith('paste://'):
        return ''
    parsed = urlsplit(str(value).strip())
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('岗位链接必须是无凭据的 HTTP(S) 地址')
    query = [(key, val) for key, val in parse_qsl(parsed.query, keep_blank_values=True)
             if not key.lower().startswith('utm_') and key.lower() not in {'fbclid', 'gclid'}]
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or '/', urlencode(query), ''))


class Workflow:
    def __init__(self, db_path, *, profile=None, resume=None, channel='chat'):
        if channel not in {'chat', 'email'}:
            raise ValueError('channel 必须是 chat 或 email')
        if profile is None:
            profile = json.loads(default_skill_profile_path().read_text(encoding='utf-8-sig'))
        self.profile = copy.deepcopy(profile)
        self.resume = copy.deepcopy(resume) if resume is not None else json.loads((ROOT/'data/resume_highlights.json').read_text(encoding='utf-8-sig'))
        if not isinstance(self.profile, dict) or not isinstance(self.resume, dict):
            raise ValueError('求职画像与简历事实必须是 JSON 对象')
        self.profile.setdefault('target_roles', ['ai_application', 'backend'])
        self.channel = channel
        self.resume_hash = _digest(self.resume)
        if str(db_path) != ':memory:':
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.repo = Repository(db_path)

    def close(self):
        self.repo.close()

    def import_text(self, text, *, source_url=''):
        if not isinstance(text, str) or not text.strip() or len(text) > 100000:
            raise ValueError('JD 必须是非空文本且不超过 100000 字符')
        return self._ingest({'job': {}, 'raw_jd': text, 'source': 'manual'}, source_url=source_url)

    def import_batch_text(self, text, *, source_url=''):
        """按头部拆开后逐条导入；一条失败不影响其余条目。"""
        result = {'processed': [], 'errors': []}
        for index, part in enumerate(split_postings(text), 1):
            try:
                result['processed'].append(self.import_text(part, source_url=source_url)['id'])
            except (ValueError, TypeError, KeyError) as exc:
                result['errors'].append(f'第{index}条：{exc}')
        result['unique_jobs'] = len(set(result['processed']))
        return result

    def _ingest(self, item, *, source_url=None):
        if not isinstance(item, dict) or not isinstance(item.get('job'), dict):
            raise ValueError('导入条目必须包含 job 对象')
        supplied = copy.deepcopy(item['job'])
        raw = item.get('raw_jd') or supplied.get('raw_jd') or supplied.get('raw_text') or ''
        if not isinstance(raw, str) or len(raw) > 100000:
            raise ValueError('JD 原文格式或长度不符合限制')
        url = canonical_url(source_url if source_url is not None else supplied.get('source_url') or supplied.get('url'))
        job = extract_text(raw, source_url=url) if raw else {}
        job.update(supplied)
        job['source_url'] = url
        job.pop('url', None)
        if raw:
            job['raw_jd'] = raw
        if not url and not job.get('external_id') and not raw:
            # A structured export without original text is not fabricated into a JD.
            job['external_id'] = 'import-' + _digest(job)
        decision = calibrate(job, self.profile, score(job, self.profile))
        decision['profile_hash'] = _digest(self.profile)
        if not raw:
            decision.setdefault('warnings', []).append('没有原始 JD，当前判断基于导入字段；发送前请核验来源。')
        row = self.repo.upsert_job(job, source=str(item.get('source') or 'manual'), raw_jd=raw, decision=decision)
        if row['status'] in OPEN and decision.get('category') != 'reject':
            old = self.repo.latest_material(row['id'])
            if not old or old['revision'] != row['revision'] or old['content'].get('resume_hash') != self.resume_hash or old['content'].get('channel') != self.channel:
                material = build_material(job, decision, self.resume, channel=self.channel)
                material['resume_hash'] = self.resume_hash
                self._validate(material)
                self.repo.save_material(row['id'], material, expected_revision=row['revision'])
        return self.repo.get_job(row['id'])

    def import_rows(self, rows):
        """Per-job commits: one bad post does not discard prior successful imports."""
        if not isinstance(rows, list) or len(rows) > 10000:
            raise ValueError('岗位批次必须是数组且不超过10000条')
        result = {'processed': [], 'errors': []}
        for index, item in enumerate(rows, 1):
            try:
                row = self._ingest(item)
                result['processed'].append(row['id'])
            except (ValueError, TypeError, KeyError) as exc:
                result['errors'].append(f'第{index}条：{exc}')
        result['unique_jobs'] = len(set(result['processed']))
        return result

    def rows(self):
        result = self.repo.list_jobs()
        for row in result:
            material = self.repo.latest_material(row['id'])
            row['availability_warning'] = unavailable_reason(self.repo, row)
            if row['availability_warning'] and row['status'] in OPEN:
                material = None
            if row['status'] in OPEN and (row['decision'].get('category') == 'reject' or (material and material['revision'] != row['revision'])):
                material = None
            row['material'] = material
            row['approval_id'] = None
            if row['status'] == 'APPROVED' and material:
                try:
                    handoff = self.repo.prepare_handoff(row['id'])
                    # 只把与本卡片版本一致且仍有效的审批身份放入确认表单。
                    if handoff['revision'] == row['revision'] and handoff['material_id'] == material['id']:
                        row['approval_id'] = handoff['approval_id']
                except ValueError:
                    pass
        return sorted(result, key=preference_sort_key)

    def summary(self):
        result = self.repo.summary()
        return {'岗位总数': sum(result.values()), **result}

    @staticmethod
    def _validate(material):
        errors = [item for item in validate_material(material) if item.startswith('ERROR:')]
        if errors:
            raise ValueError('; '.join(errors))

    def approve_batch(self, selections, *, acknowledge_review=False):
        if not isinstance(selections, list) or len(selections) > 100:
            raise ValueError('每批最多审批100条岗位')
        result = {'approved': [], 'errors': []}
        seen = set()
        for selection in selections:
            job_id = selection.get('job_id')
            if job_id in seen:
                continue
            seen.add(job_id)
            try:
                if acknowledge_review is not True:
                    raise ValueError('请先逐项确认材料事实和待核实条件')
                if (not selection.get('expected_jd_hash') or not selection.get('expected_material_hash')
                        or type(selection.get('expected_revision')) is not int
                        or selection['expected_revision'] < 1):
                    raise ValueError('缺少已展示的 JD / 材料快照，请刷新审核页')
                material = self.repo.latest_material(job_id)
                if material is None:
                    raise ValueError('缺少可审核材料')
                self._validate(material['content'])
                self.repo.approve(job_id, expected_jd_hash=selection['expected_jd_hash'], expected_material_hash=selection['expected_material_hash'], expected_revision=selection['expected_revision'], acknowledge_review=True)
                result['approved'].append(job_id)
            except (ValueError, KeyError) as exc:
                result['errors'].append(f'#{job_id}：{exc}')
        return result

    def edit_message(self, job_id, message, *, expected_material_hash, expected_revision):
        if (not expected_material_hash or type(expected_revision) is not int or expected_revision < 1
                or not isinstance(message, str) or not message.strip() or len(message) > 4000):
            raise ValueError('需要材料快照及1到4000字的正文')
        material = self.repo.latest_material(job_id)
        if material is None:
            raise ValueError('岗位没有材料')
        content = copy.deepcopy(material['content'])
        if content['message'] != message:
            content['message'] = message
            warning = '正文经过人工编辑，请逐项核实新增事实、数字和承诺。'
            content['warnings'] = list(dict.fromkeys(content.get('warnings', []) + [warning]))
        self._validate(content)
        return self.repo.save_material(job_id, content, expected_material_hash=expected_material_hash,
                                       expected_revision=expected_revision)

    def manual_submission(self, job_id, *, evidence, expected_jd_hash, expected_material_hash,
                          expected_revision, expected_approval_id):
        if (not expected_jd_hash or not expected_material_hash
                or type(expected_revision) is not int or expected_revision < 1
                or type(expected_approval_id) is not int or expected_approval_id < 1):
            raise ValueError('需要你实际核对的材料和岗位快照')
        return self.repo.record_manual_submission(job_id, evidence=evidence,
            expected_jd_hash=expected_jd_hash, expected_material_hash=expected_material_hash,
            expected_revision=expected_revision, expected_approval_id=expected_approval_id)

    def followup(self, job_id, *, status, note=''):
        return self.repo.set_followup(job_id, status=status.lower(), note=note)

    def skip(self, job_id):
        self.repo.skip(job_id)

    def report_text(self):
        rows = self.rows()
        lines = ['本地求职进度摘要', '不调用 LLM；SUBMITTED 为人工确认记录，不是自动投递回执。', '无平台回复读取能力，回复与面试均为人工登记。', '']
        if any(row['source'] == 'cuhk' for row in rows):
            lines.append('港中大深圳来源为局部列表及指定详情监测，不覆盖全站；校外申请资格须另行核验。')
        lines.extend(f'{key}: {value}' for key, value in self.summary().items())
        grouped = {'priority': [], 'review': [], 'reject': []}
        for row in rows:
            grouped.setdefault(row['decision'].get('category') or 'review', []).append(row)
        lines.extend(['', '优先考虑'])
        if grouped['priority']:
            for row in grouped['priority']:
                lines.append(self._report_heading(row))
                message = (row.get('material') or {}).get('content', {}).get('message')
                if message:
                    lines.extend(['', message, ''])
        else:
            lines.append('无')
        lines.extend(['', '需要核实'])
        if grouped['review']:
            for row in grouped['review']:
                reason = next((item for item in row['decision'].get('warnings') or row['decision'].get('reasons') or [] if item), '需人工核实')
                lines.append(f"{self._report_heading(row)}：{reason}")
        else:
            lines.append('无')
        lines.extend(['', f"明确不符合：{len(grouped['reject'])} 条"])
        return _fit_notice('\n'.join(lines).strip() + '\n')

    @staticmethod
    def _report_heading(row):
        title = row['job'].get('job_title') or '职位待核实'
        reminder = '；已超过3天，可人工检查回复' if row['status'] == 'SUBMITTED' and time.time()-row['updated_at'] >= 3*86400 else ''
        availability = f"；{row['availability_warning']}" if row['availability_warning'] else ''
        return f"#{row['id']} {title} | {row['status']} | 版本{row['revision']}{reminder}{availability}"

    def write_report(self, path):
        """No duplicate notification on unchanged summaries; atomic local replacement."""
        path = Path(path)
        text = self.report_text()
        if path.exists() and path.read_text(encoding='utf-8') == text:
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        import os
        import tempfile
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, prefix=path.name+'.', suffix='.tmp', delete=False) as handle:
            handle.write(text)
            temporary = Path(handle.name)
        try:
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return True
