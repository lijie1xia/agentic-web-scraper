"""求职 Agent 公开 Demo：默认零成本（规则抽取 + 评分 + 预置样例），实时生成需访客自带 Key。

不爬取、不发送、不保存访客输入；访客 Key 只透传给本次调用，不写入磁盘或日志。
"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path
from typing import Optional, Tuple

_HERE = Path(__file__).resolve().parent


def _find_repo_root() -> Path:
    for candidate in (_HERE, _HERE.parent.parent):
        if (candidate / "scraper_framework" / "job_agent").is_dir():
            return candidate
    return _HERE


_ROOT = _find_repo_root()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scraper_framework.job_agent.decision import score
from scraper_framework.job_agent.resume_highlights import load_resume_highlights
from scraper_framework.job_agent.skill_profile import load_skill_profile
from scraper_framework.job_workflow.offline import extract_text


def _resolve_data(name: str) -> Optional[Path]:
    for base in (_HERE / "data", _ROOT / "data"):
        path = base / name
        if path.is_file():
            return path
    return None


_PROFILE_PATH = _resolve_data("skill_profile.json")
_RESUME_PATH = _resolve_data("resume_highlights.json")
_PROFILE = load_skill_profile(_PROFILE_PATH)
_RESUME = load_resume_highlights(_RESUME_PATH)

_RATE_LIMIT = 5
_COOLDOWN_SEC = 60
_rate_lock = threading.Lock()
_rate_state: dict[str, dict] = {}

_EXAMPLE_JD_MATCH = """职位：AI 应用开发实习生
公司：某智能科技公司
地点：广州 / 可混合办公

岗位职责：
1. 参与企业内部 Agent 应用搭建，用 Python 做工具调用与流程编排
2. 根据业务文档做 JD / 页面信息的结构化抽取，输出固定 Schema
3. 协助把 RAG 问答接到现有后端服务

任职要求：
- 本科在读，计算机或相关专业
- 熟悉 Python，了解 LangChain / Agent / Prompt Engineering
- 了解 Docker 与基本 Linux 命令
- 有爬虫或数据采集项目经验优先
"""

_EXAMPLE_JD_SKIP = """职位：资深 Java 后端工程师
公司：某电商公司
地点：北京

任职要求：
- 本科及以上，5 年及以上 Java 后端经验
- 精通 Spring Cloud 微服务与高并发交易系统
- 有千万级 DAU 架构落地经验
"""

_SAMPLE_RESULT_MD = """
### 预置样例结果（打开即可看，不消耗任何额度）

**抽取**：某智能科技公司 / AI 应用开发实习生
- 技术栈: Python、LangChain、Agent、Prompt Engineering、Docker、Linux、RAG
- 硬性要求: 本科在读、Python、LangChain / Agent / Prompt Engineering
- 加分项: 爬虫或数据采集项目经验

**评分**：推荐（示例约 80+）
- 技术栈重合：Python、Agent、LangChain、Prompt Engineering、Docker、RAG
- 学历与在读状态符合实习岗位

**开场白（示例）**

**简洁直接版**

您好，看到贵司 AI 应用开发实习，想说明一下我这边相关的经历。我做过一个示例项目，把院校页面抽取从大模型方案改成 XPath 解析，用虚构数据跑通了 10 所院校。如果方便，想进一步了解团队目前最希望实习生接手的 Agent 流程。

**突出项目匹配版**

您好，贵司岗位里写到结构化抽取和 Agent 编排，和我最近做的示例项目比较接近。我把一份虚构课程表从手动整理改成规则读取，单页处理从大约 1 分钟降到 2 秒。另外我自己搭过 extract-decide-generate 的求职 Agent，用固定 Schema 约束 LLM 输出。

**突出学习意愿版**

您好，我是本科在读，最近在做 JD 抽取和岗位匹配的个人示例项目，也练过 Agent 与规则解析怎么配合。还没在贵司这种内部 Agent 平台上线过，但 Python、Prompt 和 Docker 这些我可以较快接上。若合适，希望能请教一下当前业务文档抽取最痛的点。
"""

_SAMPLE_GREETINGS_MD = """### 预置示例文案（未按你粘贴的 JD 生成）

**简洁直接版**

您好，看到贵司的岗位，想简单说明一下我这边相关的经历。我做过一个把页面抽取从大模型方案改成规则解析的示例项目，用虚构数据跑通了完整流程。如果方便，想进一步了解团队目前最希望实习生接手的工作。

**突出项目匹配版**

您好，贵司岗位里提到的工程实践，和我最近做的示例项目比较接近。我把一份虚构数据从手动整理改成规则读取，单页处理时间大幅下降。另外我自己搭过 extract-decide-generate 的求职 Agent，用固定 Schema 约束模型输出。

**突出学习意愿版**

您好，我是本科在读，最近在做信息抽取和结构化处理的个人示例项目，也练过模型与规则怎么配合。还没在真实业务平台上线过，但 Python、Prompt 和基础工程工具我可以较快接上。若合适，希望能请教一下当前最需要解决的问题。

> 想要按你粘贴的 JD 实时生成，请在页面底部「高级选项」填入自己的 DeepSeek API Key。
"""


def _fmt_list(values) -> str:
    if not values:
        return "（无）"
    if isinstance(values, list):
        return "、".join(str(v) for v in values if str(v).strip()) or "（无）"
    return str(values)


def _session_id(request) -> str:
    if request is None:
        return "global"
    return str(getattr(request, "session_hash", None) or getattr(request, "client", None) or "global")


def _rate_limit_message(session_id: str) -> Optional[str]:
    now = time.time()
    with _rate_lock:
        state = _rate_state.setdefault(session_id, {"count": 0, "cooldown_until": 0.0})
        cooldown_until = float(state["cooldown_until"])
        if now < cooldown_until:
            remain = max(1, int(cooldown_until - now) + 1)
            return f"连续调用已达 {_RATE_LIMIT} 次，请 {remain} 秒后再试。"
        if cooldown_until and now >= cooldown_until:
            state["count"] = 0
            state["cooldown_until"] = 0.0
        if int(state["count"]) >= _RATE_LIMIT:
            state["cooldown_until"] = now + _COOLDOWN_SEC
            state["count"] = 0
            return f"连续调用已达 {_RATE_LIMIT} 次，请 {_COOLDOWN_SEC} 秒后再试。"
        state["count"] = int(state["count"]) + 1
        return None


def _friendly_error(exc: Exception) -> str:
    msg = str(exc).lower()
    if any(word in msg for word in ("401", "unauthorized", "invalid api key", "authentication", "insufficient", "balance")):
        return "**出错**：API Key 无效或余额不足，请检查后重试。"
    return f"**出错**：生成失败（{type(exc).__name__}），请检查 Key 或换一段 JD。"


def _format_result(job: dict, decision: dict, *, method: str) -> Tuple[str, str]:
    company = str(job.get("company") or "").strip() or "未知公司"
    title = str(job.get("job_title") or "").strip() or "未知职位"
    extract_md = (
        f"**{company} / {title}**（{method}）\n\n"
        f"- 技术栈: {_fmt_list(job.get('tech_stack'))}\n"
        f"- 硬性要求: {_fmt_list(job.get('required_skills'))}\n"
        f"- 加分项: {_fmt_list(job.get('preferred_skills'))}\n"
    )
    warnings = job.get("warnings") or []
    if warnings:
        extract_md += "\n待核对：" + "；".join(str(w) for w in warnings[:3]) + "\n"
    reasons = decision.get("reasons") or []
    reasons_block = "\n".join(f"- {r}" for r in reasons) if reasons else "- （无）"
    score_md = (
        f"**分数**: {decision.get('score') if decision.get('score') is not None else 'N/A'}\n\n"
        f"**推荐**: {'是' if decision.get('recommend') else '否'}\n\n"
        f"**理由**:\n{reasons_block}\n"
    )
    return extract_md, score_md


def run_pipeline(jd_text: str, api_key: str = "", request=None) -> Tuple[str, str, str]:
    """免费路径只用规则抽取与评分；只有填了访客自己的 Key 才调用模型。"""
    try:
        text = (jd_text or "").strip()
        if not text:
            return "请先粘贴 JD 文本，或点击下方 Examples。", "", ""
        job = extract_text(text, source_url="paste://demo")
        decision = score(job, _PROFILE)
        extract_md, score_md = _format_result(job, decision, method="规则抽取，未调用模型")
        if not decision.get("recommend"):
            return extract_md, score_md, "未达推荐阈值，跳过开场白生成。"

        key = (api_key or "").strip()
        if not key:
            return extract_md, score_md, _SAMPLE_GREETINGS_MD

        limited = _rate_limit_message(_session_id(request))
        if limited:
            return extract_md, score_md, limited

        # 访客 Key 只用于本次调用：延迟导入，避免免费路径加载模型依赖。
        from scraper_framework.job_agent.extract import extract_jd_from_text
        from scraper_framework.job_agent.generate import generate_greeting

        llm_job = extract_jd_from_text(text, source_url="paste://demo", api_key=key)
        if not llm_job.get("error"):
            job = llm_job
            decision = score(job, _PROFILE)
            extract_md, score_md = _format_result(job, decision, method="模型抽取（你的 Key）")

        greetings = generate_greeting(job, decision, _RESUME, api_key=key)
        if not greetings:
            return extract_md, score_md, "生成失败或返回空结果，请检查 Key 或稍后重试。"
        parts = []
        for g in greetings:
            style = str(g.get("style") or "").strip() or "未命名"
            body = str(g.get("text") or "").strip()
            parts.append(f"### {style}\n\n{body}\n")
        return extract_md, score_md, "\n".join(parts)
    except Exception as e:
        return _friendly_error(e), "", ""


def build_demo():
    import gradio as gr

    with gr.Blocks(title="求职 Agent Demo") as demo:
        gr.Markdown(
            "## 求职 Agent Demo\n"
            "粘贴 JD 文本 → 抽取 → 评分 → 开场白。**不打开招聘网站，也不会代为投递。**\n\n"
            "公开版本默认跑本地规则，不消耗任何额度；"
            "需要按你粘贴的 JD 实时生成开场白时，在页面底部填入自己的 DeepSeek Key。"
        )
        with gr.Accordion("预置样例结果（不消耗额度）", open=True):
            gr.Markdown(_SAMPLE_RESULT_MD)
        jd_in = gr.Textbox(
            label="JD 原文",
            lines=16,
            placeholder="把岗位描述整段粘贴到这里…",
        )
        btn = gr.Button("分析（免费：规则抽取 + 评分）", variant="primary")
        with gr.Row():
            out_extract = gr.Markdown(label="抽取")
            out_score = gr.Markdown(label="评分")
        out_greet = gr.Markdown(label="开场白")
        with gr.Accordion("高级选项：用自己的 DeepSeek Key 实时生成开场白", open=False):
            key_in = gr.Textbox(
                label="DeepSeek API Key",
                type="password",
                placeholder="sk-...",
                info="只用于本次请求，不写入磁盘或日志。留空则只输出预置示例文案。",
            )
        btn.click(run_pipeline, inputs=[jd_in, key_in], outputs=[out_extract, out_score, out_greet])
        gr.Examples(
            examples=[
                [_EXAMPLE_JD_MATCH],
                [_EXAMPLE_JD_SKIP],
            ],
            inputs=[jd_in],
            label="Examples（点选后点分析）",
        )
    return demo


def main():
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        os.environ.pop(key, None)
    extra = "127.0.0.1,localhost,::1"
    for key in ("NO_PROXY", "no_proxy"):
        existing = os.environ.get(key, "")
        os.environ[key] = f"{existing},{extra}" if existing else extra

    demo = build_demo()
    hosted = bool(
        os.getenv("SPACE_ID")
        or os.getenv("SYSTEM") == "spaces"
        or os.getenv("MODELSCOPE_ENVIRONMENT")
        or os.getenv("GRADIO_SERVER_NAME")
    )
    launch_kwargs = {"server_name": os.getenv("GRADIO_SERVER_NAME", "0.0.0.0") if hosted else "127.0.0.1"}
    demo.launch(**launch_kwargs)


if __name__ == "__main__":
    main()
