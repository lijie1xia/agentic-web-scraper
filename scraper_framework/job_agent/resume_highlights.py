"""简历亮点库 —— 填空模板

用法说明:
- projects: 每个项目一条,tags 尽量用招聘JD里常见的技术词(方便和 tech_stack 做重合匹配)
  name 只用于内部识别,不会进 prompt——仓库名写进打招呼语里没人看得懂
  one_liner 是给对方看的一句话,写人话:不带仓库名、英文包名和内部工具名
  outcome 写这个项目做出的结果,能加数字就加数字(跑了多少站点、准确率、省了多少时间)。
    留空也行,空的项目 prompt 会自动跳过这一行——但没有结果撑着,生成出来的
    打招呼语只能靠"能快速上手"这类自证,读着就很像机器写的
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
            "one_liner": "做了一个能自己在网站里逐页找内容的采集框架，把页面整理成结构化字段",
            "outcome": "换个配置就能接新的采集任务，不用每个站点重写一遍爬虫",
            "tags": ["Agent", "FunctionTool", "schema", "camel-ai"],
        },
        {
            "name": "cookie_handler",
            "one_liner": "写了一套自动点掉网页 Cookie 同意弹窗的模块，分多层兜底",
            "outcome": "弹窗挡住页面导致的抓取失败不用再人工介入",
            "tags": ["工程鲁棒性", "反爬", "DOM"],
        },
        {
            "name": "NYU学费抓取项目",
            "one_liner": "抓一所美国大学的学费数据，页面有反爬拦截、关键数字埋在 PDF 里",
            "outcome": "把 PDF 解析从大模型方案换成直接读文本层，处理时间明显下降，也不再消耗模型调用额度",
            "tags": ["反爬", "PDF解析", "性能优化"],
        },
        {
            "name": "CrawlAgent(ReAct架构)研究与调试",
            "one_liner": "读并调通了一个 ReAct 结构的爬取 Agent，搞清楚它怎么在抓取和抽取之间做选择",
            "outcome": "",
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
