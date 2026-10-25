"""Offline eligibility evidence helpers; never fetch or synthesize JD text."""
from __future__ import annotations

import re


RAW_JD_FIELDS = ("raw_jd", "jd_text", "raw_text")
_OPTIONAL = re.compile(r"优先|加分|preferred|optional|nice.to.have", re.I)
_YEAR = r"20\d{2}"


def graduation_constraints(job: dict) -> list[dict]:
    """Return explicit cohort clauses, retaining their actual source text.

    Ordinary dates are not cohorts. Ranges/lists in a cohort clause are allowed;
    optional cohorts remain soft evidence. No summary is treated as raw JD.
    """
    constraints = []
    for field in ("graduate_year", "target_candidate", "experience_years", *RAW_JD_FIELDS):
        value = job.get(field)
        if value is None:
            continue
        # 逗号隔开的语气不互相传播；连续年份列表中的逗号仍作为连接符。
        for clause in re.split(
            r"[。；;\n]|(?<!20\d{2})(?<!20\d{2}届)[，,]|[，,](?!\s*20\d{2})",
            str(value),
        ):
            if not clause.strip():
                continue
            if field in RAW_JD_FIELDS and not re.search(
                r"仅限|面向|招收|招募|招聘|要求|毕业时间|毕业年份|must|require|seeking|class of|graduating", clause, re.I
            ):
                continue
            year_block = rf"{_YEAR}(?:\s*届?\s*(?:[/、,&和或]|[-~～到至–]|or|and)\s*{_YEAR})*"
            if field == "graduate_year":
                blocks = [clause]
            else:
                blocks = re.findall(rf"({year_block})\s*(?:届|年\s*毕业)", clause)
                blocks += re.findall(rf"(?:graduat\w*|class of)[^\d。;]{{0,30}}({year_block})", clause, re.I)
                blocks += re.findall(rf"({year_block})\s+graduates?", clause, re.I)
            years = set()
            ambiguous = bool(re.search(
                r"以前|以后|之前|之后|不限|不限制|也可|不(?:招收|招募|招聘|接受)|非\s*20\d{2}|除|before|after|earlier|later|\bnot\b", clause, re.I
            ))
            # 年份列表之外的“或”可能提供其他资格路径，不能当作单一届别门槛。
            alternative_text = re.sub(year_block, "", clause, flags=re.I)
            ambiguous = ambiguous or bool(re.search(r"或|\bor\b", alternative_text, re.I))
            for block in blocks:
                years.update(int(year) for year in re.findall(_YEAR, block))
                for start, end in re.findall(rf"({_YEAR})\s*届?\s*[-~～到至–]\s*({_YEAR})", block):
                    ambiguous = ambiguous or int(start) > int(end)
                    years.update(range(int(start), int(end) + 1))
            if years or field == "graduate_year":
                constraints.append({
                    "field": field,
                    "text": clause,
                    "years": sorted(years),
                    "optional": bool(_OPTIONAL.search(clause)),
                    "ambiguous": ambiguous or not years,
                })
    return constraints


def role_matches(title: str, preference: str) -> bool:
    """按标题中明确出现的方向匹配，复合标题可同时属于多个方向。"""
    def families(value: str) -> set[str]:
        text = re.sub(r"[\s_-]+", "", value.lower())
        matched = set()
        if re.search(r"ai应用|aiapplication|aiapps?|大模型|智能体|(?:(?<![a-z])|(?<=ai))(?:llm|agent(?!cy)|rag(?![a-z]))|(?<![a-z])ai(?:技术)?开发", text):
            matched.add("ai_application")
        if re.search(r"后端|服务端|backend|(?<![a-z])(?:java|python|golang|go)(?:开发|工程师|后端)", text):
            matched.add("backend")
        return matched

    title_families, preference_families = families(title), families(preference)
    if preference_families:
        return bool(title_families & preference_families)
    normalized_title = re.sub(r"[\s_-]+", "", title.lower())
    normalized_preference = re.sub(r"[\s_-]+", "", preference.lower())
    return bool(normalized_preference) and normalized_preference in normalized_title


_GENERIC_AI_TITLE = re.compile(r"^(?:ai|人工智能)(?:实习生?|工程师|开发)?(?:实习生?)?$", re.I)
_AI_DUTY = re.compile(r"agent|智能体|rag|大模型|llm|function\s*calling|mcp", re.I)


def duty_role(job: dict) -> str | None:
    """标题只写"AI实习生"这类泛称时，按职责原文判断是否为 AI 应用开发。"""
    title = re.sub(r"\s+", "", str(job.get("job_title") or ""))
    if not _GENERIC_AI_TITLE.match(title):
        return None
    duties = " ".join(str(item) for item in job.get("responsibilities") or [])
    return "ai_application" if _AI_DUTY.search(duties) and re.search(r"开发|编码|实现", duties) else None
