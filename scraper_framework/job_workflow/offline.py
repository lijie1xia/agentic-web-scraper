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
    "Python", "JavaScript", "TypeScript", "Java", "C++", "C#", "Go", "Golang", "Rust",
    "SQL", "MySQL", "PostgreSQL", "Redis", "MongoDB", "Linux", "Git",
    "Docker", "Kubernetes", "Nginx", "Flask", "FastAPI", "Django", "Spring Boot", "SpringBoot", "Spring",
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
_OPTIONAL = re.compile(r"优先|加分|优选|更好|更佳|preferred|nice[- ]to[- ]have|optional|bonus", re.I)
_AMBIGUOUS = re.compile(r"无需|不要求|不需要|不限|至少一种|之一|任一|或|\bor\b|not required|no experience", re.I)
# 招聘 App 复制文本的头部：标题、薪资、"城市 5天/周 6个月 本科" 一类无标签信息行。
_HEADER_SALARY = r"\d+(?:\.\d+)?(?:\s*[-~～至到–]\s*\d+(?:\.\d+)?)?\s*(?:元/天|元/日|[kK](?:·\d+薪)?)"
_HEADER_CITY = re.compile(r"[\u4e00-\u9fa5]{2,6}(?:-[\u4e00-\u9fa5]{2,8})?")
_HEADER_TOKENS = {
    "days_per_week": re.compile(r"(\d)天/周"),
    "internship_months": re.compile(r"(\d+)个月"),
    "education": re.compile(r"(本科|硕士|博士|大专|学历不限)"),
    "experience_years": re.compile(r"(经验不限|在校/应届|\d+-\d+年|\d+年以[上内])"),
}
_FRESH_ALTERNATIVE = re.compile(r"应届[^。；\n]{0,20}(?:也可|均可|亦可|可考虑)")
_OTHER_HEADINGS = {"福利待遇", "公司介绍", "关于我们", "招聘流程", "面试流程", "联系方式", "benefits", "about us", "about company", "interview process"}


def _terms(text):
    matches = []
    for term in _TECH:
        for match in re.finditer(r"(?<![A-Za-z0-9_])" + re.escape(term) + r"(?![A-Za-z0-9_+#])", text, re.I):
            # ReAct 是 Agent 推理范式，不是前端框架 React。
            if match.group(0) != "ReAct":
                matches.append((match.start(), term))
                break
    return [term for _, term in sorted(matches)]


def _set_header(result, field, value, raw, number):
    """头部信息只补空字段，显式标签优先。"""
    if not result.get(field) or result[field] == "unknown":
        result[field] = value
        result["evidence"].append({"field": field, "value": value, "quote": raw, "line": number, "status": "header"})


def _read_header(result, text):
    lines = [(number, raw) for number, raw in enumerate(text.splitlines(), 1) if raw.strip()][:4]
    if not lines:
        return
    number, raw = lines[0]
    title, salary = raw.strip(), ""
    match = re.fullmatch(r"(.+?)\s*(" + _HEADER_SALARY + r")", title)
    if match:
        title, salary = match.group(1).strip(), match.group(2)
    elif len(lines) > 1 and re.fullmatch(_HEADER_SALARY, lines[1][1].strip()):
        salary = lines[1][1].strip()
    meta = None
    for meta_number, meta_raw in lines[1:]:
        tokens = meta_raw.split()
        if len(tokens) >= 2 and _HEADER_CITY.fullmatch(tokens[0]):
            found = {field: pattern.search(meta_raw) for field, pattern in _HEADER_TOKENS.items()}
            if any(found.values()):
                meta = (meta_number, meta_raw, tokens, found)
                break
    # 没有薪资或信息行佐证时，第一行不当作标题。
    if not salary and not meta:
        return
    headings = {heading.casefold() for values in _HEADINGS.values() for heading in values}
    if len(title) <= 40 and not re.search(r"[:：]", title) and title.casefold() not in headings:
        _set_header(result, "job_title", title, raw, number)
    else:
        title = ""
    if salary:
        _set_header(result, "salary_range", salary, raw, number)
    if meta:
        number, raw, tokens, found = meta
        _set_header(result, "location", tokens[0], raw, number)
        for field in ("days_per_week", "internship_months"):
            if found[field]:
                _set_header(result, field, int(found[field].group(1)), raw, number)
        if found["education"]:
            _set_header(result, "education", found["education"].group(1), raw, number)
        experience = found["experience_years"].group(1) if found["experience_years"] else ""
        if experience == "在校/应届":
            _set_header(result, "target_candidate", experience, raw, number)
        elif re.search(r"\d", experience) and _FRESH_ALTERNATIVE.search(text):
            result["warnings"].append(f"头部要求{experience}经验，但正文接受应届，需人工核实。")
        elif experience:
            _set_header(result, "experience_years", experience, raw, number)
        internship = bool(found["days_per_week"] or found["internship_months"] or "实习" in tokens
                          or "实习" in title or re.search(r"元/[天日]", salary))
        monthly = bool(re.search(r"[kK]", salary))
        if internship or monthly:
            _set_header(result, "employment_type", "internship" if internship else "full_time", raw, number)


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
        if line == "职位已关闭":
            result["posting_closed"] = True
            result["evidence"].append({"field": "posting_closed", "quote": raw, "line": number})
    _read_header(result, text)
    return result

def _header_at(lines, index):
    """只把空行后的「标题 + 薪资或城市信息」当作下一条岗位。"""
    if index > 0 and lines[index - 1].strip():
        return False
    title = lines[index].strip()
    if (not title or len(title) > 40 or re.search(r"[:：]", title)
            or re.fullmatch(_HEADER_SALARY, title)):
        return False
    following = [line.strip() for line in lines[index + 1:index + 6] if line.strip()][:3]
    # 标题行已经带薪资时，下一行必须是城市信息，避免正文里的重复标题被拆开。
    if re.search(_HEADER_SALARY, title):
        following = following[:1]
    elif following and re.fullmatch(_HEADER_SALARY, following[0]):
        return True
    for line in following:
        tokens = line.split()
        if (len(tokens) >= 2 and _HEADER_CITY.fullmatch(tokens[0])
                and any(pattern.search(line) for pattern in _HEADER_TOKENS.values())):
            return True
    return False


def split_postings(text: str) -> list[str]:
    """按招聘 App 头部把多条 JD 切开。没有第二个头部时原样返回。"""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("JD 必须是非空文本")
    lines = text.splitlines()
    starts = [index for index in range(len(lines)) if _header_at(lines, index)]
    if len(starts) <= 1:
        return [text]
    chunks = []
    for start, end in zip(starts, starts[1:] + [len(lines)]):
        chunk = "\n".join(lines[start:end]).strip()
        if chunk:
            chunks.append(chunk)
    return chunks or [text]
