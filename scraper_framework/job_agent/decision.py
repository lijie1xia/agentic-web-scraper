"""模块2：岗位评分 / 决策

输入模块1 产出的 Job dict + skill_profile，输出可解释的 decision。
不调用 LLM、不访问网页、不修改原始 job。
"""

from __future__ import annotations

import copy
import math
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .skill_profile import DEFAULT_SKILL_PROFILE, load_skill_profile
from .evaluation import duty_role, graduation_constraints, role_matches

# 技术栈满分；其余维度为加减分，总分钳制在 0–100
_TECH_SCORE_MAX = 70
_EDU_BONUS = 10
_EXP_BONUS = 10
_WORK_MODE_BONUS = 10
_WORK_MODE_PENALTY = 8
_RECOMMEND_THRESHOLD = 50

# 学历等级（越大越高）
_EDU_RANK = {
    "高中": 1,
    "中专": 1,
    "大专": 2,
    "专科": 2,
    "本科": 3,
    "学士": 3,
    "硕士": 4,
    "研究生": 4,
    "博士": 5,
}

# 常见技术别名 → 规范名（已 normalize 后的 key）
_TECH_ALIASES = {
    "golang": "go",
    "k8s": "kubernetes",
    "js": "javascript",
    "ts": "typescript",
    "py": "python",
    "postgres": "postgresql",
    "postgresql": "postgresql",
    "nodejs": "node",
    "node.js": "node",
    "reactjs": "react",
    "vuejs": "vue",
    "tf": "tensorflow",
    "pytorch": "pytorch",
    "llm": "llm",
    "llms": "llm",
    "aiagent": "agent",
    "agents": "agent",
    "springboot": "spring",
}


def _normalize_tech(name: str) -> str:
    s = str(name).strip().lower()
    s = s.replace("（", "(").replace("）", ")")
    # 去掉括号说明，如 "Python（熟练）"
    s = re.sub(r"\(.*?\)", "", s)
    s = s.replace("-", "").replace("_", "").replace(" ", "").replace(".", "")
    if not s:
        return ""
    return _TECH_ALIASES.get(s, s)


def _tech_list(values: Any) -> List[str]:
    if values is None:
        return []
    if isinstance(values, str):
        parts = [p.strip() for p in values.replace("，", ",").split(",")]
        return [p for p in parts if p]
    if isinstance(values, list):
        out: List[str] = []
        for item in values:
            if item is None:
                continue
            s = str(item).strip()
            if s:
                out.append(s)
        return out
    s = str(values).strip()
    return [s] if s else []


def _match_tech_stacks(
    job_techs: Sequence[str], profile_techs: Sequence[str]
) -> Tuple[int, List[str], List[str]]:
    """一对一匹配，避免同一技能重复计分。

    Returns:
        matched_count, matched_display_names, unmatched_job_techs
    """
    profile_norms = [_normalize_tech(t) for t in profile_techs]
    profile_norms = [t for t in profile_norms if t]
    used_profile: set = set()
    matched_names: List[str] = []
    unmatched: List[str] = []

    for raw in job_techs:
        norm = _normalize_tech(raw)
        if not norm:
            continue
        hit_idx = None
        for i, p in enumerate(profile_norms):
            if i in used_profile:
                continue
            if norm == p:
                hit_idx = i
                break
        if hit_idx is not None:
            used_profile.add(hit_idx)
            matched_names.append(raw)
        else:
            unmatched.append(raw)

    return len(matched_names), matched_names, unmatched


def _detect_edu_rank(text: str) -> Optional[int]:
    if not text or not str(text).strip():
        return None
    t = str(text).strip().lower()
    # 在读/应届仍按对应学历认定
    for key, rank in sorted(_EDU_RANK.items(), key=lambda x: -len(x[0])):
        if key.lower() in t or key in text:
            return rank
    if "bachelor" in t:
        return 3
    if "master" in t:
        return 4
    if "phd" in t or "doctor" in t:
        return 5
    return None


def _is_fresh_grad_text(text: str) -> bool:
    """判断文本是否表示应届/届别/无经验，而非 N 年工作经验。"""
    if not text or not str(text).strip():
        return False
    t = str(text).strip()
    # 届别：2026届 / 2027 届 — 不是工作年限
    if re.search(r"20\d{2}\s*届", t):
        return True
    fresh_keywords = [
        "应届",
        "校招",
        "校园招聘",
        "实习生",
        "实习",
        "在读",
        "无经验",
        "不限经验",
        "经验不限",
        "fresh graduate",
        "new graduate",
        "entry level",
        "entry-level",
        "no experience",
    ]
    tl = t.lower()
    return any(k.lower() in tl if k.isascii() else k in t for k in fresh_keywords)


def _parse_min_experience_required(experience_years: Any) -> Optional[float]:
    """从 job.experience_years 解析岗位要求的最低工作年限。

    Returns:
        None = 未知 / 无法判断
        0   = 明确可接受 0 年（应届、0-1 年的下限为 0 等）
        >0  = 最低要求年数
    """
    if experience_years is None:
        return None
    text = str(experience_years).strip()
    if not text:
        return None

    tl = re.sub(r"\s+", "", text.lower())
    if re.search(r"优先|加分|以内|以下|至多|不超过|个月|月|preferred|optional|upto|atmost|lessthan|months?", tl):
        return None
    numeric_years = re.search(r"\d\s*(?:\+|[-~～到至–]\s*\d+)?\s*(?:年|years?|yrs?)", text, re.I)
    if _is_fresh_grad_text(text):
        # Fresh-grad signals do not erase numeric/alternative requirements.
        return None if numeric_years else 0.0
    if re.search(r"(没有|无需|不需要).{0,4}(经验|工作)", text):
        return 0.0
    number = r"(\d+(?:\.\d+)?)"
    prefix = r"(?:至少|要求|必须|具备|需要|atleast|minimumof)?"
    suffix = r"(?:以上|及以上|\+|plus)?(?:相关)?(?:工作)?(?:经验|experience)?(?:required)?"
    unit = r"(?:年|years?|yrs?)"
    ranged = re.fullmatch(prefix + number + r"[-~～到至–]" + number + unit + suffix, tl)
    if ranged:
        low, high = map(float, ranged.groups())
        return low if 0 <= low <= high < 100 else None
    single = re.fullmatch(prefix + number + r"\+?" + unit + suffix, tl)
    if single:
        value = float(single.group(1))
        return value if 0 <= value < 100 else None
    if re.fullmatch(number, tl):
        value = float(tl)
        return value if 0 <= value < 100 else None
    return None


def _is_invalid_job(job: Dict[str, Any]) -> bool:
    status = str(job.get("extraction_status") or "").strip().lower()
    if status in {"page_invalid", "empty"}:
        return True
    if job.get("error"):
        return True
    return False


def score(job: dict, profile: dict) -> dict:
    """对单个 Job 打分。不修改 job。

    Returns:
        Original score/recommend/reasons plus category (priority/review/reject),
        warnings and missing_data (list[str]), missing_skills (required/preferred/
        unspecified lists), skill_evidence (field/skill/matched), graduation_evidence
        (field/text/years/optional/ambiguous), role_priority (zero-based preference or None).

        Missing evidence earns no matching points. Missing mandatory skills and
        ambiguous eligibility require review, not an assertion of ineligibility.
        A recommendation is always category=priority; reject needs a hard conflict
        or invalid input. Raw JD evidence is read only from supplied raw_jd,
        jd_text or raw_text fields, never synthesized from summaries.
    """
    if not isinstance(job, dict) or _is_invalid_job(job):
        return {
            "score": None,
            "recommend": False,
            "reasons": ["JD无效或提取失败"],
            "category": "reject",
            "warnings": ["JD无效，未执行评分"],
            "missing_data": [],
            "missing_skills": {"required": [], "preferred": [], "unspecified": []},
            "skill_evidence": [],
            "graduation_evidence": [],
            "role_priority": None,
        }
    if str(job.get("extraction_status") or "").strip().lower() == "header_unparsed":
        closed = job.get("posting_closed") is True
        return {
            "score": None,
            "recommend": False,
            "reasons": ["页面显示职位已关闭"] if closed else ["头部关键字段未识别，未按技术匹配评分"],
            "category": "reject" if closed else "review",
            "warnings": ["解析器未识别头部，原文已保留；这不是原文缺少薪资或学历。"],
            "missing_data": ["job.header"],
            "missing_skills": {"required": [], "preferred": [], "unspecified": []},
            "skill_evidence": [],
            "graduation_evidence": [],
            "role_priority": None,
        }

    reasons: List[str] = []
    warnings: List[str] = []
    missing_data: List[str] = []
    needs_review = False
    deal_breaker = False
    score_val = 0.0

    graduation_evidence = graduation_constraints(job)
    candidate_year = str(profile.get("graduate_year") or "").strip()
    for item in graduation_evidence:
        if item["ambiguous"]:
            needs_review = True
            warnings.append(f"届别条件含开放范围、否定、替代资格或无法识别，需人工复核：{item['text']}")
            continue
        if item["optional"]:
            continue
        if not re.fullmatch(r"20\d{2}", candidate_year):
            needs_review = True
            if "profile.graduate_year" not in missing_data:
                missing_data.append("profile.graduate_year")
                warnings.append("画像毕业年份缺失或无法识别，需复核届别资格")
        elif int(candidate_year) not in item["years"]:
            deal_breaker = True
            reasons.append(f"届别不符合（岗位证据：{item['text']}；画像：{candidate_year}届）")

    # Required requirements own 80% of technical points when secondary
    # evidence exists. Optional/unspecified evidence cannot swamp them.
    groups = {}
    seen = set()
    for group, field in (("required", "required_skills"), ("preferred", "preferred_skills"),
                         ("unspecified", "tech_stack")):
        groups[group] = []
        for skill in _tech_list(job.get(field)):
            normalized = _normalize_tech(skill)
            if normalized and normalized not in seen:
                groups[group].append(skill)
                seen.add(normalized)

    profile_techs = _tech_list(profile.get("tech_stack"))
    if not profile_techs:
        needs_review = True
        missing_data.append("profile.tech_stack")
        warnings.append("画像技术栈缺失，无法证明技能匹配")
    missing_skills = {}
    skill_evidence = []
    matched_names = []
    ratios = {}
    for group, field in (("required", "required_skills"), ("preferred", "preferred_skills"),
                         ("unspecified", "tech_stack")):
        skills = groups[group]
        count, matched, missing = _match_tech_stacks(skills, profile_techs)
        missing_skills[group] = missing
        ratios[group] = count / len(skills) if skills else 0.0
        matched_names.extend(matched)
        skill_evidence.extend({"field": field, "skill": skill, "matched": skill in matched}
                              for skill in skills)
    job_techs = [skill for skills in groups.values() for skill in skills]
    matched_n = len(matched_names)
    if missing_skills["required"]:
        needs_review = True
        warnings.append("画像未证明必需技能：" + "、".join(missing_skills["required"]))

    if not job_techs:
        tech_score = 0.0
        needs_review = True
        missing_data.append("job.technical_skills")
        warnings.append("缺少岗位技术证据，不能自动推荐")
        reasons.append("技术栈未知，不授予匹配分，需人工复核")
    else:
        secondary = groups["preferred"] + groups["unspecified"]
        secondary_matches = len(secondary) - len(missing_skills["preferred"]) - len(missing_skills["unspecified"])
        if groups["required"]:
            ratio = ratios["required"]
            if secondary:
                ratio = 0.8 * ratio + 0.2 * secondary_matches / len(secondary)
        else:
            ratio = matched_n / len(job_techs)
        tech_score = round(_TECH_SCORE_MAX * ratio, 2)
        if matched_n == 0:
            reasons.append("技术栈无匹配")
        elif matched_n == len(job_techs):
            label = "、".join(matched_names[:5])
            reasons.append(f"技术栈完全匹配（{label}）")
        else:
            label = "、".join(matched_names[:5])
            reasons.append(
                f"技术栈部分匹配 {matched_n}/{len(job_techs)}（{label}）"
            )
        if not _tech_list(job.get("tech_stack")) and groups["required"]:
            reasons.append("tech_stack 为空，已用 required_skills 回退匹配")

    score_val += tech_score

    # —— 学历 ——
    # 规则：岗位要求等级 ≤ 候选人等级 → 符合；更高 → 硬性不符。
    # 空/无法识别 → 未知，不否决。"本科在读" 按本科计。
    deal = profile.get("deal_breakers") or {}
    role_priority = None
    target_roles = _tech_list(profile.get("target_roles"))
    title = str(job.get("job_title") or "").strip()
    if target_roles:
        role_priority = next((i for i, role in enumerate(target_roles)
                              if role_matches(title, role)), None)
        inferred = duty_role(job) if role_priority is None else None
        if inferred in target_roles:
            role_priority = target_roles.index(inferred)
            reasons.append(f"标题为泛称，按职责原文判断方向：{inferred}")
        elif role_priority is None:
            if not title:
                missing_data.append("job.job_title")
            if title and deal.get("target_roles_only") is True:
                deal_breaker = True
                reasons.append("岗位方向不符合画像明确限定的 target_roles")
            else:
                needs_review = True
                warnings.append("岗位方向未匹配偏好，保留人工复核而非硬性拒绝")
        else:
            reasons.append(f"岗位方向匹配偏好：{target_roles[role_priority]}")
    job_edu = str(job.get("education") or "").strip()
    job_rank = _detect_edu_rank(job_edu)
    candidate_rank = _detect_edu_rank(str(profile.get("education") or ""))

    if candidate_rank is None:
        needs_review = True
        missing_data.append("profile.education")
        warnings.append("画像学历缺失或无法识别，需人工复核")

    if not job_edu or job_rank is None:
        missing_data.append("job.education")
        warnings.append("学历要求缺失或无法识别，不授予学历匹配分")
        reasons.append("学历要求未知，不作为否决条件")
    elif candidate_rank is None:
        reasons.append("画像学历未知，跳过学历判定")
    elif job_rank <= candidate_rank:
        score_val += _EDU_BONUS
        reasons.append("学历要求符合")
    else:
        deal_breaker = True
        reasons.append(f"学历明显不符合（岗位要求：{job_edu}）")
    # —— 工作经验 ——
    exp_text = job.get("experience_years")
    # target_candidate 仅作应届辅助信号，不把届别当成年限
    target = str(job.get("target_candidate") or "")
    min_exp = _parse_min_experience_required(exp_text)
    if (min_exp is None and not str(exp_text or "").strip()
            and _is_fresh_grad_text(target) and _parse_min_experience_required(target) == 0):
        min_exp = 0.0
        reasons.append("target_candidate 指向应届/在读，按 0 年经验要求处理")
    elif min_exp is None and not str(exp_text or "").strip() and job.get("employment_type") == "internship":
        min_exp = 0.0
        reasons.append("实习岗未写经验要求，按 0 年经验要求处理")

    profile_exp = profile.get("experience_years")
    try:
        profile_exp_f = float(profile_exp) if profile_exp is not None else None
        if profile_exp_f is not None and (not math.isfinite(profile_exp_f) or profile_exp_f < 0):
            profile_exp_f = None
    except (TypeError, ValueError):
        profile_exp_f = None

    max_exp_allowed = deal.get("max_experience_required")
    try:
        max_exp_allowed_f = (
            float(max_exp_allowed) if max_exp_allowed is not None else None
        )
    except (TypeError, ValueError):
        max_exp_allowed_f = None

    if profile_exp_f is None:
        needs_review = True
        missing_data.append("profile.experience_years")
        warnings.append("画像工作年限缺失或无法识别，不假定为零年")
    if min_exp is None:
        needs_review = True
        missing_data.append("job.experience_years")
        warnings.append("经验要求缺失或含糊，需人工复核")
        reasons.append("经验要求未知，不作为否决条件")
    elif profile_exp_f is None:
        reasons.append("画像经验未知，跳过经验判定")
    elif min_exp <= profile_exp_f:
        score_val += _EXP_BONUS
        reasons.append("经验要求符合")
    else:
        # 岗位要求高于候选人经验
        if max_exp_allowed_f is not None and min_exp > max_exp_allowed_f:
            deal_breaker = True
            reasons.append(
                f"经验要求过高（岗位约需 {min_exp:g} 年，硬性上限 {max_exp_allowed_f:g} 年）"
            )
        elif min_exp > profile_exp_f:
            deal_breaker = True
            reasons.append(
                f"经验要求不符合（岗位约需 {min_exp:g} 年，画像 {profile_exp_f:g} 年）"
            )

    # —— 工作方式 ——
    work_mode = str(job.get("work_mode") or "").strip().lower()
    preferred = [
        str(x).strip().lower()
        for x in _tech_list(profile.get("preferred_work_mode"))
    ]
    all_modes = {"remote", "hybrid", "onsite"}
    accepts_all = all_modes.issubset(set(preferred)) or not preferred

    if not work_mode or work_mode in {"unknown", "n/a", "na", "none"}:
        missing_data.append("job.work_mode")
        warnings.append("工作方式未提供，不授予工作方式匹配分")
        reasons.append("工作方式未知，不扣分")
    elif accepts_all:
        score_val += _WORK_MODE_BONUS
        reasons.append("工作方式匹配（画像接受全部模式）")
    elif work_mode in preferred:
        score_val += _WORK_MODE_BONUS
        reasons.append(f"工作方式匹配（{work_mode}）")
    else:
        score_val -= _WORK_MODE_PENALTY
        reasons.append(f"工作方式不太匹配（岗位 {work_mode}）")

    if job.get("posting_closed") is True:
        deal_breaker = True
        reasons.append("页面显示职位已关闭")

    score_val = max(0.0, min(100.0, round(score_val, 2)))

    recommend = (not deal_breaker) and (not needs_review) and (score_val >= _RECOMMEND_THRESHOLD)
    if deal_breaker:
        recommend = False

    return {
        "score": score_val,
        "recommend": recommend,
        "reasons": reasons,
        "category": "reject" if deal_breaker else ("priority" if recommend else "review"),
        "warnings": warnings,
        "missing_data": missing_data,
        "graduation_evidence": graduation_evidence,
        "missing_skills": missing_skills,
        "skill_evidence": skill_evidence,
        "role_priority": role_priority,
    }


def score_jobs(
    jobs: List[dict],
    profile: Optional[dict] = None,
    *,
    sort_by_score: bool = True,
) -> List[dict]:
    """批量评分。

    - 不修改原始 jobs 列表或其元素
    - 返回 [{"job": <深拷贝>, "decision": {...}}, ...]
    - sort_by_score=True（默认）时按 score 降序；None 分排最后
    - 同分时按可选 profile.target_roles 的顺序排列（例如 AI应用、后端）
    """
    if profile is None:
        profile = DEFAULT_SKILL_PROFILE

    results: List[dict] = []
    for job in jobs:
        job_copy = copy.deepcopy(job) if isinstance(job, dict) else job
        decision = score(job, profile)
        results.append({"job": job_copy, "decision": decision})

    if sort_by_score:

        def _sort_key(item: dict):
            s = item.get("decision", {}).get("score")
            if s is None:
                return (0, float("-inf"))
            role_priority = item.get("decision", {}).get("role_priority")
            preference = -role_priority if role_priority is not None else float("-inf")
            return (1, float(s), preference)

        results.sort(key=_sort_key, reverse=True)

    return results


__all__ = [
    "score",
    "score_jobs",
    "DEFAULT_SKILL_PROFILE",
    "load_skill_profile",
]
