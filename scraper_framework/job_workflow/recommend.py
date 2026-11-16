"""每日推荐：在既有决策上做硬门槛过滤与去重，不改变决策类别。"""
from __future__ import annotations

from collections import Counter

_SKIP_STATUSES = {
    'SUBMITTED', 'REPLIED', 'INTERVIEW', 'REJECTED', 'NO_REPLY', 'WITHDREW',
    'SKIPPED', 'EXECUTING', 'RESULT_UNKNOWN',
}
_EXPIRED_HINTS = ('已过截止日期', '已过期')


def _missing_required(decision):
    """只看必需技能。score() 的 missing_skills 始终是三个分组的字典，空分组不能当真。"""
    missing = decision.get('missing_skills')
    if not isinstance(missing, dict):
        return False
    required = missing.get('required')
    return isinstance(required, list) and any(str(item).strip() for item in required)


def _exclusion_reason(row):
    """返回进不了推荐的原因；None 表示通过硬门槛。"""
    if row.get('status') in _SKIP_STATUSES:
        return '投递流程中或已结束'
    decision = row.get('decision') or {}
    if decision.get('category') == 'reject':
        return '明确不符合'
    if not decision.get('recommend'):
        return '仍需核实，未达优先'
    if _missing_required(decision):
        return '缺必需技能'
    if any(hint in str(row.get('availability_warning') or '') for hint in _EXPIRED_HINTS):
        return '已过截止日期'
    salary = decision.get('salary_check')
    if salary and not salary.get('daily_cny_range'):
        return '薪资未明确'
    return None


def _reasons(row):
    """最多三条、只引用已有事实，不给分数拆解。"""
    decision, job = row['decision'], row['job']
    reasons = []
    if decision.get('score') is not None:
        reasons.append(f"匹配分 {decision['score']:g}")
    offered = (decision.get('salary_check') or {}).get('daily_cny_range')
    if offered:
        target = (decision['salary_check'].get('target') or 0)
        reasons.append('薪资达目标' if offered[0] >= target else f'薪资 {offered[0]:g}-{offered[1]:g} 元/天')
    location = str(job.get('location') or '').strip()
    if location:
        reasons.append(location)
    return reasons[:3]


def exclusion_summary(rows):
    """统计被硬门槛拦下的原因，用于解释推荐为空。"""
    return dict(Counter(reason for reason in map(_exclusion_reason, rows) if reason))


def select_daily(rows, limit: int = 3):
    """返回 [{row, reasons}]：先过硬门槛，再排序，最后按公司去重。"""
    if not isinstance(limit, int) or limit < 1:
        raise ValueError('limit 必须是正整数')
    candidates = [row for row in rows if _exclusion_reason(row) is None]
    if any(not (row['decision'] or {}).get('fallback_only') for row in candidates):
        candidates = [row for row in candidates if not row['decision'].get('fallback_only')]

    def key(row):
        decision = row['decision']
        role = decision.get('role_priority')
        return (-(decision.get('score') or 0), role if role is not None else 999,
                decision.get('location_priority', 999), row['id'])

    picked, companies = [], set()
    for row in sorted(candidates, key=key):
        company = str(row['job'].get('company') or '').strip()
        if company and company in companies:
            continue
        if company:
            companies.add(company)
        picked.append({'row': row, 'reasons': _reasons(row)})
        if len(picked) >= limit:
            break
    return picked
