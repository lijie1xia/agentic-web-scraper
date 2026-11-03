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
            "name": "启德教育-海外院校数据采集迁移",
            "one_liner": "在启德实习期间，参与把海外院校数据采集从 LLM/Agent 方案迁移到 XPath 确定性解析，负责验证与落地",
            "outcome": "覆盖 23 所院校、7 国、1500+ 专业，核心字段完整率约 98%；单校处理周期从 5 天缩短到 2 天，字段一次性通过率约 90%",
            "tags": ["Python", "Agent", "AI Agent", "MCP", "XPath", "Prompt Engineering", "Function Calling"],
        },
        {
            "name": "启德教育-PDF表格规则化解析",
            "one_liner": "针对 LLM 解析非标准 PDF 表格易出错的问题，改用规则化读取替代大模型解析",
            "outcome": "处理率从约 10% 提升到 99%，单次解析耗时从 15 分钟以上降到 5 秒以内",
            "tags": ["Python", "PDF", "pdfplumber", "性能优化"],
        },
        {
            "name": "启德教育-采集异常与反爬处理",
            "one_liner": "开发多层 Cookie 弹窗处理工具，并梳理 WAF 与人机验证的识别和处理流程",
            "outcome": "减少页面异常污染采集结果，沉淀可复用排障方法，支撑团队周更 10 所院校的交付目标",
            "tags": ["反爬", "WAF", "DrissionPage", "DOM", "工程鲁棒性"],
        },
        {
            "name": "企业级多智能体编排平台",
            "one_liner": "参与 Spring Boot 多 Agent 协作平台后端，负责 Planner/Router/Executor 分层调度与事件驱动相关开发",
            "outcome": "修复 RxJava 流式响应并发问题，重构 Quartz 任务调度解决极端场景下线程池枯竭",
            "tags": ["Java", "Spring Boot", "Agent", "Agent架构", "Docker", "RxJava", "SSE"],
        },
        {
            "name": "RAG垂直领域问答后端",
            "one_liner": "搭建从爬虫抓取、文本清洗分块到向量检索的 RAG 全流程后端服务",
            "outcome": "完成 Flask 接入大模型到 Docker/Nginx 部署的全链路，支撑孕产场景基本问答",
            "tags": ["Python", "RAG", "Flask", "Docker", "LangChain", "向量检索", "Hugging Face"],
        },
        {
            "name": "求职情报Agent",
            "one_liner": "个人项目：设计 extract-decide-generate 三段式 Agent 流水线，做 JD 结构化抽取与岗位匹配评分",
            "outcome": "用固定 Schema 约束 LLM 输出，基于真实 JD 完成首轮抽取验证，并生成个性化邮件开场白",
            "tags": ["Agent", "Python", "Prompt Engineering", "schema", "Function Calling"],
        },
    ],
    "skills": [
        "Python",
        "Java",
        "Spring Boot",
        "Flask",
        "Docker",
        "Nginx",
        "Git",
        "Linux",
        "MySQL",
        "Redis",
        "LangChain",
        "RAG",
        "AI Agent",
        "Agent",
        "MCP",
        "Prompt Engineering",
        "Function Calling",
        "DrissionPage",
        "XPath",
        "pdfplumber",
        "RESTful API",
        "MyBatis",
        "JPA",
        "RxJava",
        "SSE",
        "Hugging Face",
        "向量检索",
        "反爬",
        "Schema约束",
    ],
    "background": (
        "区块链工程本科在读(2027届)，启德教育数据采集实习(AI辅助爬虫与流程优化)，"
        "专业排名前5%，华为云计算HCIP，通过CET-6，意向AI应用/工程研发实习"
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
