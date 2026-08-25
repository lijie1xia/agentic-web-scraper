"""模块3：打招呼语生成

输入模块2 产出的 {job, decision} + resume_highlights，输出 3 个风格版本。
一次调用产出 3 版即结束，不提供「再来一版」接口，也不按文案质量循环重试。
不修改原始 ranked / job / decision。
"""

from __future__ import annotations

import copy
import os
from typing import Any, Dict, List, Optional

from ..logger import get_spider_logger
from .resume_highlights import DEFAULT_RESUME_HIGHLIGHTS

logger = get_spider_logger(__name__)

# JSON 解析失败才重试；不是为了打磨文案
_PARSE_RETRIES = 2

_GREETING_STYLES = ("简洁直接版", "突出项目匹配版", "突出学习意愿版")

# 太短会被压成电报体，太长在聊天框里没人读
_TEXT_MIN_CHARS = 120
_TEXT_MAX_CHARS = 180


def _as_str_list(values: Any) -> List[str]:
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


def _norm_tag(name: str) -> str:
    return str(name).strip().lower()


def select_relevant_highlights(
    job: dict, resume: dict, top_k: int = 2
) -> list:
    """从简历库里挑出和这条 JD 技术栈重合度最高的项目,不用 LLM,先用规则。"""
    job_tags = {_norm_tag(t) for t in _as_str_list(job.get("tech_stack")) if _norm_tag(t)}
    if not job_tags:
        job_tags = {
            _norm_tag(t) for t in _as_str_list(job.get("required_skills")) if _norm_tag(t)
        }

    projects = resume.get("projects") or []
    scored_projects = []
    for p in projects:
        if not isinstance(p, dict):
            continue
        if not str(p.get("one_liner") or "").strip():
            continue
        tags = {_norm_tag(t) for t in _as_str_list(p.get("tags")) if _norm_tag(t)}
        overlap = len(job_tags & tags)
        scored_projects.append((overlap, p))

    scored_projects.sort(key=lambda x: x[0], reverse=True)
    return [p for _, p in scored_projects[:top_k]]


def _matched_tech(job: dict, resume: dict) -> List[str]:
    """JD 技术栈与简历技能的交集，取 JD 原文用词。

    只给技术词本身，不给分数/比例——decision.reasons 那套打分话术喂进 prompt
    会被模型学去，写出"技术栈匹配核心要求"这类机器腔。
    """
    resume_norms = {
        _norm_tag(t) for t in _as_str_list(resume.get("skills")) if _norm_tag(t)
    }
    for p in resume.get("projects") or []:
        if isinstance(p, dict):
            resume_norms |= {
                _norm_tag(t) for t in _as_str_list(p.get("tags")) if _norm_tag(t)
            }

    job_techs = _as_str_list(job.get("tech_stack")) or _as_str_list(
        job.get("required_skills")
    )
    matched: List[str] = []
    for raw in job_techs:
        if _norm_tag(raw) in resume_norms and raw not in matched:
            matched.append(raw)
    return matched


def _build_greeting_prompt(job: dict, resume: dict, relevant: list) -> str:
    company = str(job.get("company") or "").strip() or "未知公司"
    title = str(job.get("job_title") or "").strip() or "未知职位"
    core_skills = _as_str_list(job.get("required_skills"))[:3]
    matched = _matched_tech(job, resume)
    background = str(resume.get("background") or "").strip()

    # 不给项目 name：那是仓库名，会被原样搬进正文
    project_lines = []
    for p in relevant:
        one_liner = str(p.get("one_liner") or "").strip()
        if not one_liner:
            continue
        outcome = str(p.get("outcome") or "").strip()
        if outcome:
            project_lines.append(f"- {one_liner}（做出的结果：{outcome}）")
        else:
            project_lines.append(f"- {one_liner}")
    projects_block = (
        "\n".join(project_lines)
        if project_lines
        else "- （暂无高度匹配项目，就从求职者定位和重合技术点写，不要编项目）"
    )

    return f"""你是求职者本人,要给下面这个岗位写一段打招呼语(用于投递平台的开场白)。

【求职者定位】
{background or "应届求职者"}

【岗位信息】
公司: {company}
职位: {title}
核心要求: {', '.join(core_skills) if core_skills else "未列出"}

【求职者会、且这个岗位要求的技术】
{'、'.join(matched) if matched else "无明显重合，别硬凑"}
(这是"他会用"的清单,不代表下面某个项目用过它)

【可用的项目经验】
{projects_block}

写法要求:
1. 只能用上面给出的事实。不许编造上面没有的经历、公司、职责或数字——这是要发给招聘方的,编了面试就穿帮
   上面没写的课程和证书尤其不许提,不许说"这门课我选修过""我学过这个"
2. 上面的技术清单不许硬安到项目描述里。项目描述本身没提到的技术,就不能说"这个项目是用它写的"
3. JD 要求里求职者没有的,要么不提,要么直说没接触过,不要含糊带过
4. 说人话。用完整句子,像给人发消息,不是填简历表格。不要用「+」「/」串联技术名,不要一句话里堆四五个名词
5. 每版只讲一个项目,并且带上它做出的结果。没有结果撑着的能力就别写
6. 不许写「技术栈匹配」「能快速上手」「符合贵司要求」这类自己给自己下的结论——把事实摆出来,让对方自己判断
7. 项目用中文口语描述。不要出现仓库名、英文包名、内部工具名(JD 自己提到的技术词除外)
8. 三个版本的开头必须不一样,不要三版都从自我介绍起手
9. 每版 4-6 句话,{_TEXT_MIN_CHARS}-{_TEXT_MAX_CHARS} 字。宁可短也不要超,写完自己数一遍
10. 空话套话一律不许出现(「我对贵公司非常感兴趣」「贵司平台广阔」这类)

语气示范(只学这种说话方式,内容是另一个领域的,不要照抄):
"看到岗位要做门店补货预测。我上半年在一家生鲜电商做过类似的事,把 30 家门店的日销预测接进了他们的订货系统,跑了两个月,人工改单量降了一半左右。用的是最朴素的时序加节假日修正,没上复杂模型,因为店长得能看懂为什么推荐这个数,看不懂就不会照着订。想问问你们现在补货这块主要卡在哪一环。"

只输出JSON数组,不要任何解释文字,格式: [{{"style": "...", "text": "..."}}]
style 必须分别是: {_GREETING_STYLES[0]}、{_GREETING_STYLES[1]}、{_GREETING_STYLES[2]}
"""


def _call_llm(prompt: str, model: str) -> Any:
    """单次 LLM 调用并解析 JSON。camel 依赖延迟导入，便于纯规则测试。"""
    from camel.agents import ChatAgent

    from ..agents.llm_agent.llm_scraper import extract_json
    from ..tools.model_factory import (
        NO_PROXY_TARGETS,
        enable_no_proxy_for_aliyun,
        get_model,
    )

    agent = ChatAgent(
        prompt,
        model=get_model(model),
        output_language="zh",
        step_timeout=60 * 5,
    )
    with enable_no_proxy_for_aliyun(NO_PROXY_TARGETS):
        response = agent.step("请按要求只输出 JSON 数组")

    text = None
    if (
        response
        and getattr(response, "msg", None)
        and getattr(response.msg, "content", None)
    ):
        text = response.msg.content
    return extract_json(text) if text else None


def _normalize_greetings(raw: Any) -> List[dict]:
    if not isinstance(raw, list):
        return []
    out: List[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        style = str(item.get("style") or "").strip()
        text = str(item.get("text") or "").strip()
        if style and text:
            if not _TEXT_MIN_CHARS <= len(text) <= _TEXT_MAX_CHARS:
                logger.warning(
                    f"greeting 字数 {len(text)} 超出 "
                    f"{_TEXT_MIN_CHARS}-{_TEXT_MAX_CHARS}（{style}）"
                )
            out.append({"style": style, "text": text})
    return out


def generate_greeting(
    job: dict,
    decision: dict,
    resume: dict,
    model: str = "deepseek",
) -> list:
    """为单条岗位生成打招呼语。不推荐的岗位直接返回 []，不调用 LLM。"""
    if not isinstance(decision, dict) or not decision.get("recommend"):
        return []

    relevant = select_relevant_highlights(job if isinstance(job, dict) else {}, resume)
    prompt = _build_greeting_prompt(
        job if isinstance(job, dict) else {},
        resume if isinstance(resume, dict) else {},
        relevant,
    )

    last_err = None
    for attempt in range(1, _PARSE_RETRIES + 1):
        try:
            raw = _call_llm(prompt, model=model)
            greetings = _normalize_greetings(raw)
            if greetings:
                return greetings
            logger.warning(f"greeting JSON parse empty on attempt {attempt}")
        except Exception as e:
            last_err = e
            logger.error(f"greeting LLM error on attempt {attempt}: {e}")

    if last_err:
        logger.error(f"generate_greeting failed: {last_err}")
    return []


def generate_greetings(
    ranked: List[dict],
    resume: Optional[dict] = None,
    *,
    model: Optional[str] = None,
) -> List[dict]:
    """批量生成打招呼语。

    - 输入模块2 的 [{"job": ..., "decision": ...}, ...]
    - 不修改原始 ranked
    - 返回 [{**item, "greetings": [...]}, ...]
    - 不推荐的岗位 greetings 为 []，不浪费 token
    """
    if resume is None:
        resume = DEFAULT_RESUME_HIGHLIGHTS
    if not model:
        model = os.getenv("CRAWL_MODEL", "deepseek")

    results: List[dict] = []
    total = len(ranked)
    for i, item in enumerate(ranked, 1):
        item_copy = copy.deepcopy(item) if isinstance(item, dict) else {"raw": item}
        job = item_copy.get("job") if isinstance(item_copy, dict) else {}
        decision = item_copy.get("decision") if isinstance(item_copy, dict) else {}
        if not isinstance(job, dict):
            job = {}
        if not isinstance(decision, dict):
            decision = {}

        company = str(job.get("company") or "").strip()
        title = str(job.get("job_title") or "").strip()
        label = " / ".join(x for x in (company, title) if x) or f"item {i}"

        if decision.get("recommend"):
            print(f"  [{i}/{total}] 生成打招呼语: {label}")
        else:
            print(f"  [{i}/{total}] 跳过（不推荐）: {label}")

        try:
            greetings = generate_greeting(job, decision, resume, model=model)
        except Exception as e:
            logger.error(f"generate_greeting failed for {label}: {e}")
            print(f"    ✗ 生成失败: {e}")
            greetings = []

        item_copy["greetings"] = greetings
        results.append(item_copy)

    return results


__all__ = [
    "select_relevant_highlights",
    "generate_greeting",
    "generate_greetings",
    "DEFAULT_RESUME_HIGHLIGHTS",
]
