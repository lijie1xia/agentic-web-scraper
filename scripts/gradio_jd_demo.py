"""本地 Gradio Demo：粘贴 JD → 抽取 → 评分 → 三版开场白。本地演示，不爬取、不发送

用法: python scripts/gradio_jd_demo.py
"""
from __future__ import annotations
import sys
from pathlib import Path
from typing import Tuple

from scraper_framework.job_agent.decision import score
from scraper_framework.job_agent.extract import extract_jd_from_text
from scraper_framework.job_agent.generate import generate_greeting
from scraper_framework.job_agent.resume_highlights import load_resume_highlights
from scraper_framework.job_agent.skill_profile import default_skill_profile_path, load_skill_profile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_PROFILE_PATH = default_skill_profile_path()
_RESUME_PATH = ROOT / "data" / "resume_highlights.json"

_PROFILE = load_skill_profile(_PROFILE_PATH if _PROFILE_PATH.exists() else None)
_RESUME = load_resume_highlights(_RESUME_PATH if _RESUME_PATH.exists() else None)


def _fmt_list(values) -> str:
    if not values:
        return "（无）"
    if isinstance(values, list):
        return "、".join(str(v) for v in values if str(v).strip()) or "（无）"
    return str(values)


def run_pipeline(jd_text: str) -> Tuple[str, str, str]:
    """返回 (抽取摘要, 评分摘要, 开场白)。"""
    try:
        text = (jd_text or "").strip()
        if not text:
            return "请先粘贴 JD 文本。", "", ""

        job = extract_jd_from_text(text)
        company = str(job.get("company") or "").strip() or "未知公司"
        title = str(job.get("job_title") or "").strip() or "未知职位"
        extract_md = (
            f"**{company} / {title}**\n\n"
            f"- 技术栈: {_fmt_list(job.get('tech_stack'))}\n"
            f"- 硬性要求: {_fmt_list(job.get('required_skills'))}\n"
            f"- 加分项: {_fmt_list(job.get('preferred_skills'))}\n"
        )
        if job.get("error"):
            extract_md += f"\n抽取标记: `{job.get('error')}`\n"

        decision = score(job, _PROFILE)
        score_val = decision.get("score")
        recommend = bool(decision.get("recommend"))
        reasons = decision.get("reasons") or []
        reasons_block = "\n".join(f"- {r}" for r in reasons) if reasons else "- （无）"
        score_md = (
            f"**分数**: {score_val if score_val is not None else 'N/A'}\n\n"
            f"**推荐**: {'是' if recommend else '否'}\n\n"
            f"**理由**:\n{reasons_block}\n"
        )

        if not recommend:
            greet_md = "未达推荐阈值，跳过开场白生成。"  # 与 CLI 行为一致
            return extract_md, score_md, greet_md

        greetings = generate_greeting(job, decision, _RESUME)
        if not greetings:
            return extract_md, score_md, "生成失败或返回空结果。"

        parts = []
        for g in greetings:
            style = str(g.get("style") or "").strip() or "未命名"
            body = str(g.get("text") or "").strip()
            parts.append(f"### {style}\n\n{body}\n")
        return extract_md, score_md, "\n".join(parts)
    except Exception as e:
        err = f"**出错**: `{type(e).__name__}: {e}`\n\n完整堆栈在启动 Demo 的终端里。"
        return err, "", ""


def main():
    import os
    # 针对本机环境，代理略过本机回环地址
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        os.environ.pop(key, None)
    for key in ("NO_PROXY", "no_proxy"):
        existing = os.environ.get(key, "")
        extra = "127.0.0.1,localhost"
        os.environ[key] = f"{existing},{extra}" if existing else extra

    import gradio as gr

    with gr.Blocks(title="求职 Agent Demo") as demo:
        gr.Markdown(
            "## 求职 Agent Demo\n"
            "粘贴 JD 文本 → 抽取 → 评分 → 生成三版求职开场白。"
        )
        jd_in = gr.Textbox(
            label="JD 原文",
            lines=18,
            placeholder="把岗位描述整段粘贴到这里…",
        )
        btn = gr.Button("生成", variant="primary")
        with gr.Row():
            out_extract = gr.Markdown(label="抽取")
            out_score = gr.Markdown(label="评分")
        out_greet = gr.Markdown(label="开场白")
        btn.click(run_pipeline, inputs=[jd_in], outputs=[out_extract, out_score, out_greet])

    demo.launch(server_name="127.0.0.1")

if __name__ == "__main__":
    main()
