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


_PROVINCE_CITIES = {'浙江': ('杭州', '宁波', '温州', '嘉兴', '湖州', '绍兴', '金华', '衢州', '舟山', '台州', '丽水')}
# 标题含开发/研发/工程师时不排除，例如数据采集开发仍属于开发岗。
_EXCLUDED_ROLES = {
    'data_labeling': (r'标注|标记|采集', '数据标注/采集'),
    'aigc_content': (r'视频|剪辑|漫剧|绘图|运营', 'AIGC 内容制作'),
}
_ELITE_SCHOOL = re.compile(r'(985|211|双一流)[^。；\n]{0,6}(?:院校|高校|大学|学校)')


def _in_place(location, place):
    return place in location or any(city in location for city in _PROVINCE_CITIES.get(place, ()))


def calibrate(job, profile, decision):
    """在既有决策上仅施加偏好约束；返回独立副本。"""
    result = copy.deepcopy(decision)
    prefs = profile.get('personal_preferences') or {}
    tiers = (prefs.get('location') or {}).get('preferred_tiers', [])
    if tiers:
        # 只用地点原文；省级偏好只按该省地级市名匹配，不推断其他城市。
        location = str(job.get('location') or '')
        result['location_priority'] = next((i for i, places in enumerate(tiers)
                                            if any(_in_place(location, place) for place in places)), len(tiers))
    title = str(job.get('job_title') or '')
    if not re.search(r'开发|研发|工程师|engineer|developer', title, re.I):
        for role in prefs.get('excluded_roles', []):
            pattern, label = _EXCLUDED_ROLES.get(role, ('', ''))
            if pattern and re.search(pattern, title):
                result['category'] = 'reject'
                result['recommend'] = False
                result.setdefault('reasons', []).append(f'非开发方向（{label}），按个人偏好排除')
                break
    tier = prefs.get('school_tier')
    if tier:
        match = _ELITE_SCHOOL.search(str(job.get('raw_jd') or job.get('education') or ''))
        if match and match.group(1) not in tier:
            if result.get('category') != 'reject':
                result['category'] = 'review'
            result['recommend'] = False
            result.setdefault('warnings', []).append(f'岗位要求{match.group(0)}，画像为{tier}，需人工核实。')
    if job.get('employment_type'):
        result['employment_type'] = job['employment_type']
    if prefs.get('fallback_policy') == 'only_if_no_suitable_main_roles':
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
            if offered:
                warning = f'薪资范围跨越 {minimum:g}元/天底线，需确认实际报价。'
            elif job.get('employment_type') == 'full_time':
                warning = (f"应届全职岗（{job.get('salary_range')}），通常毕业取得证书后才能正式入职，"
                           '排在实习岗之后；不换算日薪。')
            else:
                warning = '薪资缺失、非明确人民币日薪或含歧义，需人工复核；不换算月薪或外币。'
            result.setdefault('warnings', []).append(warning)
    return result


def preference_sort_key(row):
    """类别优先；同类中后备置后、全职置于实习之后，再按方向偏好和匹配分排序。"""
    decision = row['decision']
    role = decision.get('role_priority')
    return ({'priority': 0, 'review': 1, 'reject': 2}.get(decision.get('category'), 1),
            bool(decision.get('fallback_only')), decision.get('employment_type') == 'full_time',
            role if role is not None else 999, -(decision.get('score') or 0),
            decision.get('location_priority', 999), row['id'])
