"""Conservative, stdlib-only JD extraction. No model, fetching or filesystem IO.

Unknown strings remain empty (work_mode/job_level use ``unknown``). ``evidence``
contains field/quote/line records; ``raw_text`` is unchanged. Rules intentionally
under-extract: callers must review warnings, not treat ``ok`` as confidence.
"""
from __future__ import annotations

import re

_STRING_FIELDS = (
    "job_title", "company", "location", "work_mode", "job_level",
    "experience_years", "target_candidate", "education", "salary_range",
    "jd_summary", "extraction_status",
)
_LIST_FIELDS = ("responsibilities", "required_skills", "preferred_skills", "tech_stack")
_LABELS = {
    "job_title": ("岗位名称", "职位名称", "职位", "岗位", "job title", "title"),
    "company": ("公司名称", "公司", "company"),
    "location": ("工作地点", "办公地点", "location"),
    "job_level": ("职级", "job level", "level"),
    "experience_years": ("工作经验", "经验要求", "experience"),
    "target_candidate": ("招聘对象", "面向人群", "target candidate"),
    "education": ("学历要求", "学历", "education"),
    "salary_range": ("薪资范围", "薪资", "薪酬", "salary"),
}


_TECH = (
    "Python", "JavaScript", "TypeScript", "Java", "C++", "C#", "Go", "Rust",
    "SQL", "MySQL", "PostgreSQL", "Redis", "MongoDB", "Linux", "Git",
    "Docker", "Kubernetes", "Nginx", "Flask", "FastAPI", "Django", "Spring Boot",
    "LangChain", "LangGraph", "RAG", "AI Agent", "Agent", "MCP", "LLM",
    "Prompt Engineering", "Function Calling", "PyTorch", "TensorFlow",
    "React", "Vue", "Node.js", "Playwright", "DrissionPage", "XPath",
    "pdfplumber", "PDF", "RxJava", "SSE", "Hugging Face", "向量检索", "反爬",
)
_HEADINGS = {
    "required_skills": ("任职要求", "岗位要求", "职位要求", "必备条件", "基本要求", "requirements", "required", "qualifications", "required skills"),
    "preferred_skills": ("加分项", "优先条件", "加分条件", "preferred", "preferred skills", "nice to have", "bonus"),
    "responsibilities": ("岗位职责", "工作职责", "职位描述", "职责", "responsibilities"),
}
_OPTIONAL = re.compile(r"优先|加分|优选|preferred|nice[- ]to[- ]have|optional|bonus", re.I)
_AMBIGUOUS = re.compile(r"无需|不要求|不需要|不限|至少一种|之一|或|\bor\b|not required|no experience", re.I)
_OTHER_HEADINGS = {"福利待遇", "公司介绍", "关于我们", "招聘流程", "面试流程", "联系方式", "benefits", "about us", "about company", "interview process"}


def _terms(text):
    matches = []
    for term in _TECH:
        match = re.search(r"(?<![A-Za-z0-9_])" + re.escape(term) + r"(?![A-Za-z0-9_+#])", text, re.I)
        if match:
            matches.append((match.start(), term))
    return [term for _, term in sorted(matches)]


def _record_value(result, candidates, field, value, raw, number):
    """Keep all evidence, but never choose among differing literal candidates."""
    result["evidence"].append({"field": field, "value": value, "quote": raw, "line": number})
    values = candidates.setdefault(field, [])
    if value not in values:
        values.append(value)
    if len(values) > 1:
        result[field] = "unknown" if field in {"job_level", "work_mode"} else ""
        warning = f"{field} 出现多个冲突值，未选择任何一个。"
        if warning not in result["warnings"]:
            result["warnings"].append(warning)
    else:
        result[field] = value


def extract_text(text: str, *, source_url: str = "") -> dict:
    """Extract explicit labels and sections; return schema-shaped data plus evidence."""
    if not isinstance(text, str) or not isinstance(source_url, str):
        raise TypeError("text and source_url must be strings")
    result = {field: "" for field in _STRING_FIELDS}
    result.update({field: [] for field in _LIST_FIELDS})
    result.update(work_mode="unknown", job_level="unknown", raw_text=text,
                  source_url=source_url, extraction_method="rules", evidence=[],
                  warnings=["规则抽取仅识别明确标签；未识别或缺失的资格条件须人工核对。"],
                  extraction_status="ok" if text.strip() else "empty",
                  required_conditions=[], preferred_conditions=[])
    section = None
    labeled_values = {}
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip().lstrip("# ")
        content = re.sub(r"^(?:[-*•]+|\d+[.)、])\s*", "", line)
        for field, headings in _HEADINGS.items():
            match = re.match(r"(?:" + "|".join(map(re.escape, headings)) + r")(?:\s*[:：]\s*(.*)|\s*)$", content, re.I)
            if match:
                section = field
                content = match.group(1) or ""
                break
        else:
            if content.endswith((":", "：")) or raw.lstrip().startswith("#") or content.casefold() in _OTHER_HEADINGS:
                section = None
        for term in _terms(content):
            if term not in result["tech_stack"]:
                result["tech_stack"].append(term)
                result["evidence"].append({"field": "tech_stack", "value": term, "quote": raw, "line": number})
        if section == "responsibilities" and content:
            result[section].append(content)
            result["evidence"].append({"field": section, "quote": raw, "line": number})
        elif section in {"required_skills", "preferred_skills"}:
            separator = r"[;；。，,]" if _OPTIONAL.search(content) else r"[;；。]"
            for clause in re.split(separator, content):
                target = "preferred_skills" if _OPTIONAL.search(clause) else section
                if clause.strip():
                    conditions = target.replace("skills", "conditions")
                    result[conditions].append(clause.strip())
                    result["evidence"].append({"field": conditions, "quote": raw, "line": number})
                if _AMBIGUOUS.search(clause):
                    result["warnings"].append(f"第{number}行有否定或可选关系歧义，未转换为必备技能或资格：{clause.strip()}")
                    continue
                if target == "required_skills" and not re.search(r"[:：]", clause):
                    patterns = {
                        "target_candidate": r"\d{4}\s*届|应届|在读|社招|graduates?",
                        "education": r"本科|硕士|博士|大专|bachelor|master|Ph\.?D",
                        "experience_years": r"\d[^。；]*年[^。；]*经验|\d[^.;]*years?[^.;]*experience",
                    }
                    for field, pattern in patterns.items():
                        if re.search(pattern, clause, re.I):
                            _record_value(result, labeled_values, field, clause.strip(), raw, number)
                for term in _terms(clause):
                    if term not in result[target]:
                        result[target].append(term)
                        result["evidence"].append({"field": target, "value": term, "quote": raw, "line": number})
        if re.match(r"(?:工作方式|办公方式|work mode)\s*[:：]", line, re.I):
            value = re.split(r"[:：]", line, maxsplit=1)[1].strip()
            modes = {"remote": r"远程办公|居家办公|remote|WFH", "hybrid": r"混合办公|hybrid", "onsite": r"现场办公|坐班|办公室办公|on[- ]?site"}
            found = [mode for mode, pattern in modes.items() if re.search(pattern, value, re.I)]
            if len(found) == 1 and not re.search(r"不|禁止|\bnot\b|\bno\b", value, re.I):
                _record_value(result, labeled_values, "work_mode", found[0], raw, number)
            else:
                result["warnings"].append("工作方式存在歧义或否定关系，未确认。")
        for field, labels in _LABELS.items():
            match = re.match(r"(?:" + "|".join(map(re.escape, labels)) + r")\s*[:：]\s*(.+)$", line, re.I)
            if match:
                value = match.group(1).strip()
                if field in {"education", "experience_years", "target_candidate"} and (section == "preferred_skills" or _OPTIONAL.search(value)):
                    result["evidence"].append({"field": field, "quote": raw, "line": number, "status": "preferred_only"})
                    result["warnings"].append(f"{field} 仅见于优先条件，未当作硬性要求。")
                    continue
                # 学历标签同样遵守条款的否定与替代关系检查，避免制造硬性门槛。
                if field == "education" and _AMBIGUOUS.search(value):
                    result["evidence"].append({"field": field, "quote": raw, "line": number, "status": "unresolved"})
                    result["warnings"].append(f"第{number}行有否定或可选关系歧义，未转换为必备技能或资格：{value}")
                    continue
                invalid = (field == "location" and re.search(r"面试|interview", value, re.I)) or (
                    field == "experience_years" and not re.search(r"\d.*(?:年|years?)", value, re.I))
                if invalid:
                    result["evidence"].append({"field": field, "quote": raw, "line": number, "status": "unresolved"})
                    result["warnings"].append(f"{field} 标签内容无法确认，保留原文待核对。")
                    continue
                _record_value(result, labeled_values, field, value, raw, number)
    return result
