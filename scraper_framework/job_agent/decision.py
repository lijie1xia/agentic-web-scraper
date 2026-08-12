"""模块2：岗位评分 / 决策

输入模块1 产出的 Job dict + skill_profile，输出可解释的 decision。
不调用 LLM、不访问网页、不修改原始 job。
"""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .skill_profile import DEFAULT_SKILL_PROFILE, load_skill_profile

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
            if norm == p or norm in p or p in norm:
                # 过短 token 避免误匹配（如 "go" in "golang" 已 alias；防 "c" 误伤）
                if min(len(norm), len(p)) <= 1 and norm != p:
                    continue
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

    if _is_fresh_grad_text(text):
        return 0.0

    # 排除纯届别数字被当成年限（如误写 "2027"）
    if re.fullmatch(r"20\d{2}", text):
        return 0.0

    tl = text.lower().replace(" ", "")

    # 明确 0 / 无
    if re.search(r"(没有|无需|不需要).{0,4}(经验|工作)", text):
        return 0.0
    if tl in {"0", "0年", "0years", "0yr", "0yrs"}:
        return 0.0

    # 区间：1-3年 / 1～3年 / 1到3年 → 取下限
    m = re.search(
        r"(\d+(?:\.\d+)?)\s*[-~～到至]\s*(\d+(?:\.\d+)?)\s*(年|years?|yrs?)?",
        tl,
        re.I,
    )
    if m:
        return float(m.group(1))

    # N年以上 / N+ years / at least N
    m = re.search(
        r"(\d+(?:\.\d+)?)\s*\+?\s*(年|years?|yrs?)?\s*(以上|及以上|\+|plus)?",
        tl,
        re.I,
    )
    if m:
        # 避免把 "2027届" 类已处理；再挡一下四位年份
        val = float(m.group(1))
        if val >= 1900:
            return 0.0
        return val

    m = re.search(r"(atleast|over|morethan)\s*(\d+(?:\.\d+)?)", tl)
    if m:
        return float(m.group(2))

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
        {"score": int|float|None, "recommend": bool, "reasons": list[str]}
    """
    if not isinstance(job, dict):
        return {
            "score": None,
            "recommend": False,
            "reasons": ["JD无效或提取失败"],
        }

    if _is_invalid_job(job):
        return {
            "score": None,
            "recommend": False,
            "reasons": ["JD无效或提取失败"],
        }

    reasons: List[str] = []
    deal_breaker = False
    score_val = 0.0

    # —— 技术栈（核心）——
    job_techs = _tech_list(job.get("tech_stack"))
    # tech_stack 为空时，用 required_skills 作软回退，便于空栈 JD 仍可测
    used_fallback = False
    if not job_techs:
        job_techs = _tech_list(job.get("required_skills"))
        used_fallback = bool(job_techs)

    profile_techs = _tech_list(profile.get("tech_stack"))
    matched_n, matched_names, _unmatched = _match_tech_stacks(job_techs, profile_techs)

    if not job_techs:
        tech_score = _TECH_SCORE_MAX * 0.4  # 未知：中性偏弱，不直接否决
        reasons.append("技术栈未知，按中性分处理")
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
        if used_fallback:
            reasons.append("tech_stack 为空，已用 required_skills 回退匹配")

    score_val += tech_score

    # —— 学历 ——
    # 规则：岗位要求等级 ≤ 候选人等级 → 符合；更高 → 硬性不符。
    # 空/无法识别 → 未知，不否决。"本科在读" 按本科计。
    deal = profile.get("deal_breakers") or {}
    job_edu = str(job.get("education") or "").strip()
    job_rank = _detect_edu_rank(job_edu)
    candidate_rank = _detect_edu_rank(str(profile.get("education") or ""))
    if candidate_rank is None:
        candidate_rank = _detect_edu_rank(str(deal.get("min_education") or ""))

    if not job_edu or job_rank is None:
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
    if min_exp is None and _is_fresh_grad_text(target):
        min_exp = 0.0
        reasons.append("target_candidate 指向应届/在读，按 0 年经验要求处理")

    profile_exp = profile.get("experience_years")
    try:
        profile_exp_f = float(profile_exp) if profile_exp is not None else 0.0
    except (TypeError, ValueError):
        profile_exp_f = 0.0

    max_exp_allowed = deal.get("max_experience_required")
    try:
        max_exp_allowed_f = (
            float(max_exp_allowed) if max_exp_allowed is not None else None
        )
    except (TypeError, ValueError):
        max_exp_allowed_f = None

    if min_exp is None:
        reasons.append("经验要求未知，不作为否决条件")
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

    score_val = max(0.0, min(100.0, round(score_val, 2)))

    recommend = (not deal_breaker) and (score_val >= _RECOMMEND_THRESHOLD)
    if deal_breaker:
        recommend = False

    return {
        "score": score_val,
        "recommend": recommend,
        "reasons": reasons,
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
    """
    if profile is None:
        profile = DEFAULT_SKILL_PROFILE

    results: List[dict] = []
    for job in jobs:
        job_copy = copy.deepcopy(job) if isinstance(job, dict) else job
        decision = score(job if isinstance(job, dict) else {}, profile)
        results.append({"job": job_copy, "decision": decision})

    if sort_by_score:

        def _sort_key(item: dict):
            s = item.get("decision", {}).get("score")
            if s is None:
                return (0, float("-inf"))
            return (1, float(s))

        results.sort(key=_sort_key, reverse=True)

    return results


__all__ = [
    "score",
    "score_jobs",
    "DEFAULT_SKILL_PROFILE",
    "load_skill_profile",
]
