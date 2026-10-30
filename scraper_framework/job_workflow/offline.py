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
# 手机复制的另一种头部：日期、「正在招聘」、斜杠分隔的城市/日薪/学历。
# 出勤和实习月数沿用已有字段，不塞进薪资或学历。
_DATE_LINE = re.compile(
    r"^(?:"
    r"\d{4}[./\-年]\d{1,2}(?:[./\-月]\d{1,2}日?)?"
    r"|\d{1,2}[./\-]\d{1,2}[./\-]\d{2,4}"
    r"|\d{1,2}\s*(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|0ct)\.?(?:[\s.]*\d{4})"
    r")$",
    re.I,
)
_RECRUITING_LINE = re.compile(r"^(.{2,40}?)(?:正在招聘|招聘中)$")
_ZONE_STOP = re.compile(r"^(?:【|职位详情|岗位职责|任职要求|职位要求|职位描述|工作内容)")
_AL_AGENT = re.compile(r"(?<![A-Za-z])Al(?=\s+Agent\b)")
_AI_AGENT = re.compile(r"(?<![A-Za-z])AI\s+Agent\b")
_SLASH_EDU = re.compile(r"本科|硕士|博士|大专|学历不限")
_SLASH_EXP = re.compile(r"经验不限|\d+-\d+年|\d+年以[上内]")
_INTERN_DAYS = re.compile(r"每周(?:实习)?至少\s*(\d)\s*天|(\d)\s*天/周")
_INTERN_MONTHS = re.compile(r"连续(?:实习)?\s*(\d+)\s*个月")
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


def _set_header(result, field, value, raw, number, layout=None):
    """头部信息只补空字段，显式标签优先。"""
    if not result.get(field) or result[field] == "unknown":
        result[field] = value
        item = {"field": field, "value": value, "quote": raw, "line": number, "status": "header"}
        if layout:
            item["layout"] = layout
        result["evidence"].append(item)


def _header_zone(text):
    """职位详情之前的几行才是头部，避免正文里的斜杠被当成字段。"""
    zone = []
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if zone and _ZONE_STOP.match(line):
            break
        zone.append((number, raw, line))
        if len(zone) >= 8:
            break
    return zone


def _slash_fields(line):
    """只接受带字段分隔符、且能同时对上城市或薪资和其他已知字段的一行。"""
    if not re.search(r"[/／|｜]", line):
        return None
    protected = (line.replace("元/天", "\u0001").replace("元/日", "\u0002").replace("天/周", "\u0003")
                 .replace("元／天", "\u0001").replace("元／日", "\u0002").replace("天／周", "\u0003"))
    if not re.search(r"[/／|｜]", protected):
        return None
    parts = []
    for part in re.split(r"\s*[/／|｜]\s*", protected):
        part = part.strip().replace("\u0001", "元/天").replace("\u0002", "元/日").replace("\u0003", "天/周")
        if part:
            parts.append(part)
    fields = {"city": "", "salary": "", "education": "", "candidates": [], "experience": "",
              "days": None, "months": None}
    known = 0
    for part in parts:
        # 学历、在校/应届也是两三个汉字，必须先于城市判断，避免整行被当成多个城市。
        if re.fullmatch(_HEADER_SALARY, part):
            if fields["salary"]:
                return None
            fields["salary"] = part
            known += 1
            continue
        if _SLASH_EDU.fullmatch(part):
            if fields["education"]:
                return None
            fields["education"] = part
            known += 1
            continue
        if part in {"在校", "应届", "在校生", "应届生"}:
            fields["candidates"].append(part)
            known += 1
            continue
        if _SLASH_EXP.fullmatch(part):
            if fields["experience"]:
                return None
            fields["experience"] = part
            known += 1
            continue
        day = re.fullmatch(r"(\d)\s*天/周|每周(?:实习)?至少\s*(\d)\s*天", part)
        if day:
            fields["days"] = int(next(group for group in day.groups() if group))
            known += 1
            continue
        month = re.fullmatch(r"(?:连续(?:实习)?)?\s*(\d+)\s*个月", part)
        if month:
            fields["months"] = int(month.group(1))
            known += 1
            continue
        if _HEADER_CITY.fullmatch(part):
            if fields["city"]:
                return None
            fields["city"] = part
            known += 1
            continue
    if known < 2 or not (fields["city"] or fields["salary"]):
        return None
    return fields


def _candidate_value(parts):
    ordered = []
    for part in parts:
        value = "在校" if part in {"在校", "在校生"} else "应届"
        if value not in ordered:
            ordered.append(value)
    if set(ordered) == {"在校", "应届"}:
        return "在校/应届"
    if len(ordered) == 1:
        return ordered[0]
    return ""


def _normalize_copied_title(title, text):
    """正文已写 AI Agent 时，才把标题里单独的 Al Agent 规范为 AI。不改 raw_text，也不改其他词。"""
    if _AL_AGENT.search(title) and _AI_AGENT.search(text):
        return _AL_AGENT.sub("AI", title, count=1), True
    return title, False


def _apply_experience(result, experience, text, raw, number, layout=None):
    if experience == "在校/应届":
        _set_header(result, "target_candidate", experience, raw, number, layout)
    elif re.search(r"\d", experience) and _FRESH_ALTERNATIVE.search(text):
        result["warnings"].append(f"头部要求{experience}经验，但正文接受应届，需人工核实。")
    elif experience:
        _set_header(result, "experience_years", experience, raw, number, layout)


def _apply_employment(result, *, title, salary, days, months, raw, number, layout=None):
    internship = bool(days or months or "实习" in (title or "") or re.search(r"元/[天日]", salary or ""))
    monthly = bool(re.search(r"[kK]", salary or ""))
    if internship or monthly:
        _set_header(result, "employment_type", "internship" if internship else "full_time", raw, number, layout)


def _read_internship_requirement(result, text):
    """只读「实习要求」标题本身或紧随的一行，不从职责正文里猜月数。"""
    lines = text.splitlines()
    clause, number, raw = "", None, ""
    for index, line in enumerate(lines):
        stripped = line.strip()
        inline = re.fullmatch(r"【实习要求】\s*(.+)", stripped)
        if inline:
            number, raw, clause = index + 1, line, inline.group(1)
            break
        if stripped in {"【实习要求】", "实习要求"}:
            number, raw = index + 1, line
            for follow in lines[index + 1:index + 3]:
                if follow.strip():
                    number = lines.index(follow, index + 1) + 1
                    raw, clause = follow, follow.strip().lstrip("-• ").strip()
                    break
            break
    if number is None:
        return
    day, month = _INTERN_DAYS.search(clause), _INTERN_MONTHS.search(clause)
    if day:
        _set_header(result, "days_per_week", int(next(group for group in day.groups() if group)), raw, number)
    if month:
        _set_header(result, "internship_months", int(month.group(1)), raw, number)
    if not day and not month:
        result["warnings"].append("实习要求原文无法识别出勤或时长，未猜测。")


def _read_slash_header(result, text):
    """日期和招聘状态不当作职位名；斜杠行只填空字段。"""
    zone = _header_zone(text)
    meta = None
    for index, (number, raw, line) in enumerate(zone):
        fields = _slash_fields(line)
        if fields:
            meta = (index, number, raw, fields)
            break
    if not meta:
        return
    index, number, raw, fields = meta
    title = ""
    for prev_number, prev_raw, line in reversed(zone[:index]):
        if _DATE_LINE.fullmatch(line) or _RECRUITING_LINE.fullmatch(line):
            continue
        if re.fullmatch(r"BOSS\s*ZHIPIN|BOSS直聘.*", line, re.I) or line in _OTHER_HEADINGS or line == "职位详情":
            continue
        if len(line) > 40 or re.search(r"[:：]", line) or re.fullmatch(_HEADER_SALARY, line):
            break
        stored, normalized = _normalize_copied_title(line, text)
        _set_header(result, "job_title", stored, prev_raw, prev_number, "slash")
        if normalized:
            result["warnings"].append('标题中的 "Al Agent" 已按正文 "AI Agent" 规范为 AI，原文仍保留在 raw_text。')
        elif _AL_AGENT.search(line):
            result["warnings"].append('标题保留原文 "Al Agent"；正文没有可对照的 "AI Agent"，未替换字符。')
        title = stored
        break
    for prev_number, prev_raw, line in zone:
        match = _RECRUITING_LINE.fullmatch(line)
        if not match:
            continue
        _set_header(result, "company", match.group(1).strip(), prev_raw, prev_number, "slash")
        break
    if fields["city"]:
        _set_header(result, "location", fields["city"], raw, number, "slash")
    if fields["salary"]:
        _set_header(result, "salary_range", fields["salary"], raw, number, "slash")
    if fields["education"]:
        _set_header(result, "education", fields["education"], raw, number, "slash")
    candidate = _candidate_value(fields["candidates"])
    if candidate:
        _set_header(result, "target_candidate", candidate, raw, number, "slash")
    if fields["days"] is not None:
        _set_header(result, "days_per_week", fields["days"], raw, number, "slash")
    if fields["months"] is not None:
        _set_header(result, "internship_months", fields["months"], raw, number, "slash")
    if fields["experience"]:
        _apply_experience(result, fields["experience"], text, raw, number, "slash")
    _apply_employment(result, title=title or result.get("job_title", ""), salary=fields["salary"],
                      days=fields["days"] or result.get("days_per_week"),
                      months=fields["months"] or result.get("internship_months"),
                      raw=raw, number=number, layout="slash")


def _mark_header_gaps(result, text):
    """区分原文没写和解析器没认出。认不出关键字段时不把它当成普通匹配。"""
    if result.get("extraction_status") == "empty":
        return
    slash = any(item.get("layout") == "slash" for item in result["evidence"])
    if slash:
        if not result.get("salary_range"):
            result["warnings"].append("薪资原文未写，未猜测。")
        if not result.get("education"):
            result["warnings"].append("学历原文未写，未猜测。")
        intern_failed = any("实习要求原文无法识别" in warning for warning in result["warnings"])
        if not result.get("days_per_week") and not intern_failed:
            result["warnings"].append("每周出勤原文未写，未猜测。")
        if not result.get("internship_months") and not intern_failed:
            result["warnings"].append("实习时长原文未写，未猜测。")
        if not result.get("job_title"):
            result["extraction_status"] = "header_unparsed"
            result["warnings"].append("解析器未识别职位名称，未按技术匹配作正常推荐。")
        return
    head = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    boss_copy = bool(re.search(r"正在招聘|职位详情", "\n".join(head.splitlines()[:8]))
                     or re.search(r"BOSS\s*ZHIPIN|BOSS直聘", text))
    if boss_copy and not result.get("job_title"):
        result["extraction_status"] = "header_unparsed"
        result["warnings"].append("识别到招聘复制文本，但头部关键字段未解析；原文已保留，未按技术匹配作正常推荐。")


def _read_header(result, text):
    lines = [(number, raw) for number, raw in enumerate(text.splitlines(), 1) if raw.strip()][:4]
    if not lines:
        return
    number, raw = lines[0]
    title, salary = raw.strip(), ""
    # 日期或「正在招聘」开头的是另一种复制版式，留给斜杠头部解析。
    if _DATE_LINE.fullmatch(title) or _RECRUITING_LINE.fullmatch(title):
        return
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
    _read_internship_requirement(result, text)
    _read_slash_header(result, text)
    _read_header(result, text)
    _mark_header_gaps(result, text)
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
