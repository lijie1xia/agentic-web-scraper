"""JD 结构化抽取 schema（模块1）

面向后续 Decide（岗位匹配评分）：
- 技能相关字段使用字符串数组，便于匹配 / 去重
- job_level 与 experience_years 分离，禁止用年限推断职级
- target_candidate 与 experience_years 分离：前者是招聘对象，后者是工作年限
- jd_summary 仅为辅助字段，决策以结构化字段为准

source_url 由程序注入，不交给 LLM 抽取。
"""

from typing import Any, Dict, List, Set

# 必须输出为 JSON 字符串数组的字段
JD_LIST_FIELDS: Set[str] = {
    "responsibilities",
    "required_skills",
    "preferred_skills",
    "tech_stack",
}

# field_name -> 给 LLM 的字段说明（会拼进抽取 prompt 的 schema 段）
JD_OUTPUT_FIELDS: Dict[str, str] = {
    "job_title": "岗位名称，如 Software Engineer / 后端开发工程师",
    "company": "公司名称（官网招聘页通常能明确看到）",
    "location": (
        "实际工作地点城市/地区，如 北京、上海、深圳、Singapore；多地用逗号分隔；"
        "禁止填入远程面试/线上面试/视频面试等招聘流程信息"
    ),
    "work_mode": (
        "日常工作方式，只能是 remote / hybrid / onsite / unknown 之一；"
        "禁止根据远程面试、线上沟通、视频面试等招聘流程字样判断为 remote"
    ),
    "job_level": (
        "页面明确写出的职级原文（如 Senior / Staff / 高级工程师）；"
        "没有明确职级时填 unknown；禁止根据经验年限推断"
    ),
    "experience_years": (
        "明确的工作经验年限要求原文，如 1-3 years / 3年以上；"
        "没有明确年限则空字符串；不要把届别/应届/社招等招聘对象写到这里"
    ),
    "target_candidate": (
        "招聘对象/候选人范围原文，如 2027届本科及以上学历在读、应届毕业生、社招候选人；"
        "没有则空字符串；不要与 experience_years 混淆"
    ),
    "education": "学历要求原文，如 本科 / 硕士；没有明确要求则空字符串",
    "salary_range": "薪资范围原文；页面未写则空字符串，禁止猜测",
    "responsibilities": (
        "【必须是 JSON 字符串数组】JD 中明确写出的岗位职责条目；"
        "保留原意，不要编造；没有则 []"
    ),
    "required_skills": (
        "【必须是 JSON 字符串数组】硬性要求的技能/技术，如 Python、SQL；"
        "不要混入加分项；没有则 []"
    ),
    "preferred_skills": (
        "【必须是 JSON 字符串数组】加分项/优先条件中的技能，如 LangChain、大模型经验；"
        "不要与 required_skills 重复堆砌；没有则 []"
    ),
    "tech_stack": (
        "【必须是 JSON 字符串数组】文中出现的技术栈关键词汇总（工具/语言/框架）；"
        "只保留具体技术名，不要软技能；没有则 []"
    ),
    "jd_summary": (
        "【辅助字段】中文摘要 80-150 字：核心职责、技术方向、适合人群；"
        "不添加页面不存在的信息；决策请以结构化字段为准"
    ),
    "extraction_status": (
        "抽取状态，取值为 ok / empty / page_invalid"
        "如果页面内容为错误提示或空白,返回status=page_invalid, page_invalid状态下的 JD 会被丢弃,不参与后续决策"
    )
}

JD_EXTRACT_USER_PROMPT = """
这是一份公司官网的招聘 JD 页面。请只根据页面可见内容抽取字段。

【类型约定 — 覆盖默认「全部返回字符串」规则】
下列字段必须是 JSON 数组（数组元素为字符串），禁止写成逗号分隔的单个字符串：
- responsibilities
- required_skills
- preferred_skills
- tech_stack

其余字段为字符串。找不到的字符串字段填 ""；找不到的数组字段填 []。

【期望输出形状示例】
{
  "job_title": "AI应用开发实习生",
  "company": "Example Inc",
  "location": "北京",
  "work_mode": "unknown",
  "job_level": "unknown",
  "experience_years": "",
  "target_candidate": "2027届本科及以上学历在读",
  "education": "本科及以上",
  "salary_range": "",
  "responsibilities": [
    "负责后端服务开发与维护",
    "参与 AI 应用系统建设"
  ],
  "required_skills": ["Python", "SQL", "Linux"],
  "preferred_skills": ["LangChain", "LLM application experience"],
  "tech_stack": ["Python", "FastAPI", "Docker", "SQL"],
  "jd_summary": "该公司招聘 AI 应用开发实习生，面向2027届在读学生，工作地点北京，侧重服务开发与 AI 应用落地，要求具备 Python 与 SQL 等能力。"
  "extraction_status": "ok"
  }

【字段规则】
1. job_level：只提取页面明确出现的职级（标题或正文中的 Senior/Junior/Staff/P7/高级 等）。
   若无明确职级 → 填 "unknown"。严禁根据 experience_years 推断职级。
2. experience_years：只提取明确的工作经验年限原文（如 1-3年、3年以上、5+ years）。
   没有明确年限 → ""。禁止把「2027届」「应届」「社招」「在读」等招聘对象写进本字段。
3. target_candidate：提取招聘对象/候选人范围原文（如 2027届本科及以上学历在读、应届毕业生、社招候选人）。
   与 experience_years 严格分离；没有则 ""。
4. location：只提取实际工作地点（城市/地区）。多地用逗号分隔。
   禁止填入「远程面试」「线上面试」「视频面试」「线上面试/沟通」等招聘流程信息。
5. work_mode：只表示日常工作方式，取值只能是 remote / hybrid / onsite / unknown。
   - 明确写远程办公/居家办公/WFH → remote
   - 明确写混合办公/hybrid → hybrid
   - 明确写坐班/现场办公/onsite/办公室办公 → onsite
   - 无法判断 → unknown
   严禁因为出现「远程面试」「线上面试」「视频面试」「线上沟通」就判为 remote。
6. required_skills：仅硬性要求（必须/要求/required）；preferred_skills：仅加分/优先/nice to have。
   二者不要混在一起；同一技能不要同时塞进两边，除非原文两边都写了。
7. tech_stack：具体技术/工具名汇总，可与 required/preferred 有重叠，但不要写「沟通能力」等软技能。
8. responsibilities：逐条提取明确职责，保留原意，不要扩写页面没有的内容；不要把任职要求误当成职责。
9. salary_range / education / experience_years / target_candidate：页面没写就 ""，禁止根据公司名或行业惯例猜测。
10. jd_summary：中文 80-150 字辅助摘要，覆盖职责、技术方向、适合人群；不添加页面不存在的信息。
11. 不要输出 source_url（由程序注入）。
12. 只输出一个 JSON 对象，不要 markdown 代码块，不要数组包裹。
"""


def empty_jd_fields() -> Dict[str, Any]:
    """抽取失败时的空字段占位（不含 source_url）。"""
    out: Dict[str, Any] = {}
    for name in JD_OUTPUT_FIELDS:
        out[name] = [] if name in JD_LIST_FIELDS else ""
    return out


def normalize_jd_result(data: Dict[str, Any]) -> Dict[str, Any]:
    """将 LLM 结果规整到 Decide 友好的 schema（不改变抽取流程，仅做类型兜底）。"""
    result = dict(data)

    for name in JD_LIST_FIELDS:
        val = result.get(name, [])
        if val is None:
            result[name] = []
        elif isinstance(val, str):
            # 兜底：若仍返回逗号串，拆成数组
            parts = [p.strip() for p in val.replace("，", ",").split(",")]
            result[name] = [p for p in parts if p]
        elif isinstance(val, list):
            cleaned: List[str] = []
            for item in val:
                if item is None:
                    continue
                s = str(item).strip()
                if s:
                    cleaned.append(s)
            result[name] = cleaned
        else:
            result[name] = [str(val).strip()] if str(val).strip() else []

    # 字符串字段：None → ""；job_level 空 → unknown
    for name in JD_OUTPUT_FIELDS:
        if name in JD_LIST_FIELDS:
            continue
        val = result.get(name, "")
        if val is None:
            result[name] = ""
        else:
            result[name] = str(val).strip()

    level = result.get("job_level", "")
    if not level or level.lower() in {"null", "none", "n/a", "na"}:
        result["job_level"] = "unknown"

    return result
