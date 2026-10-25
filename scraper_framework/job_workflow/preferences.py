"""个人偏好校准：不加匹配分、不改原始证据、不推算月薪或入职日期。"""
from __future__ import annotations

import copy
import re

def _daily_cny(value):
    """只接受完整的人民币日薪表达；未知、附加条件和其他币种留待复核。"""
    text = str(value or '').strip().lower()
    if re.search(r'\d\s+\d', text):
        return None  # 不把两个未明确连接的数字拼成一个报价。
    text = re.sub(r'\s+', '', text)
    number = r'(\d+(?:\.\d+)?)'
    amount = number + r'(?:元?[-~～至到–]' + number + r')?'
    currency = r'(?:人民币|cny|rmb|元)'
    day = r'(?:/|每|per)(?:天|日|day)'
    match = re.fullmatch(currency + amount + r'元?' + day, text)
    if not match:
        match = re.fullmatch(amount + currency + day, text)
    if not match:
        match = re.fullmatch(r'(?:日薪|每天|每日)' + amount + currency, text)
    if not match:
        return None
    low = float(match.group(1))
    high = float(match.group(2) or match.group(1))
    return (low, high) if 0 <= low <= high < float('inf') else None


def calibrate(job, profile, decision):
    """在既有决策上仅施加偏好约束；返回独立副本。"""
    result = copy.deepcopy(decision)
    prefs = profile.get('personal_preferences') or {}
    tiers = (prefs.get('location') or {}).get('preferred_tiers', [])
    if tiers:
        # 只用地点原文；浙江是省级偏好，不擅自改成杭州或推断所属省份。
        location = str(job.get('location') or '')
        result['location_priority'] = next((i for i, places in enumerate(tiers)
                                            if any(place in location for place in places)), len(tiers))
    if prefs.get('fallback_policy') == 'only_if_no_suitable_main_roles':
        title = str(job.get('job_title') or '')
        patterns = {'testing': r'测试|\b(?:qa|sdet|test|testing)\b',
                    'data_engineering': r'数据工程|数据开发|\bdata[ -]engineer(?:ing)?\b'}
        # 复合标题中的主方向词可能只是业务领域，不能覆盖明确的后备职责。
        fallback = any(re.search(patterns[role], title, re.I)
                       for role in prefs.get('fallback_roles', []) if role in patterns)
        result['fallback_only'] = fallback
        if fallback:
            if result.get('category') != 'reject':
                result['category'] = 'review'
            result['recommend'] = False
            result.setdefault('warnings', []).append(
                '后备方向：仅在没有合适主方向岗位时考虑，需人工确认；不代表资格不符。')
    salary = prefs.get('salary') or {}
    if salary.get('currency') == 'CNY' and salary.get('period') == 'day':
        offered = _daily_cny(job.get('salary_range'))
        minimum = salary['minimum']
        result['salary_check'] = {
            'field': 'salary_range', 'text': job.get('salary_range'),
            'daily_cny_range': list(offered) if offered else None,
            'minimum': minimum, 'target': salary['target'],
            'target_guaranteed': offered[0] >= salary['target'] if offered else None,
        }
        if offered and offered[1] < minimum:
            result['category'] = 'reject'
            result['recommend'] = False
            result.setdefault('reasons', []).append(
                f"明确人民币日薪全部低于硬性下限 {minimum:g}元/天：{job.get('salary_range')}")
        elif offered is None or offered[0] < minimum:
            if result.get('category') != 'reject':
                result['category'] = 'review'
            result['recommend'] = False
            warning = (f'薪资范围跨越 {minimum:g}元/天底线，需确认实际报价。' if offered else
                       '薪资缺失、非明确人民币日薪或含歧义，需人工复核；不换算月薪或外币。')
            result.setdefault('warnings', []).append(warning)
    return result


def preference_sort_key(row):
    """类别优先；同类后备置后，其他岗位仍先比较实际匹配分。"""
    decision = row['decision']
    role = decision.get('role_priority')
    return ({'priority': 0, 'review': 1, 'reject': 2}.get(decision.get('category'), 1),
            bool(decision.get('fallback_only')), -(decision.get('score') or 0),
            role if role is not None else 999, decision.get('location_priority', 999), row['id'])
