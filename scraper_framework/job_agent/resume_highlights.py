"""简历亮点库 —— 填空模板

用法说明:
- projects: 每个项目一条,tags 尽量用招聘JD里常见的技术词(方便和 tech_stack 做重合匹配)
  one_liner 控制在30字以内,给LLM当"可直接引用的一句话",不是完整项目介绍
- skills: 平铺的技能关键词列表,越贴近JD原文用词越好(比如JD写"LLM应用开发"就别只写"Python")
- background: 1-2句自我定位,给LLM做整体语气参照,不是完整简历

只填内容,不用改结构。tags留空的先留空,不确定的项目可以先删掉,不用凑数。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Union

DEFAULT_RESUME_HIGHLIGHTS: Dict[str, Any] = {
    "projects": [
        {
            "name": "agentic-web-scraper",
            "one_liner": "基于docling为上下文的自主导航Agent框架，支持结构化数据抽取",
            "tags": ["Agent", "FunctionTool", "schema", "camel-ai"],
        },
        {
            "name": "cookie_handler",
            "one_liner": "四层降级式Cookie同意弹窗处理器,含shadow DOM递归遍历",
            "tags": ["工程鲁棒性", "反爬", "DOM"],
        },
        {
            "name": "NYU学费抓取项目",
            "one_liner": "解决AWS WAF反爬拦截,PDF解析从LLM方案切换为pdfplumber提速",
            "tags": ["反爬", "PDF解析", "性能优化"],
        },
        {
            "name": "CrawlAgent(ReAct架构)研究与调试",
            "one_liner": "研究并调试基于LangGraph的ReAct Agent,理解fetch/extract工具设计",
            "tags": ["LangGraph", "ReAct", "Agent架构"],
        },
    ],
    "skills": [
        "Python",
        "LangChain",
        "LangGraph",
        "RAG",
        "AI Agent",
        "MCP",
        "Prompt Engineering",
        "DrissionPage",
        "多模态",
        "向量检索",
    ],
    "background": (
        "2027应届本科生,4个月数据采集/爬虫岗实习经验,"
        "擅长独立设计Agent工程方案并落地"
    ),
}


def load_resume_highlights(path: Union[str, Path, None] = None) -> Dict[str, Any]:
    """加载简历亮点库。

    path 为 None 时返回 DEFAULT_RESUME_HIGHLIGHTS 的拷贝。
    path 指向 JSON 时以其内容为准（需为对象）。
    """
    if path is None:
        return json.loads(json.dumps(DEFAULT_RESUME_HIGHLIGHTS))

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"resume_highlights JSON 必须是对象: {path}")
    return data


__all__ = [
    "DEFAULT_RESUME_HIGHLIGHTS",
    "load_resume_highlights",
]
