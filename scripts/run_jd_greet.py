"""仅对模块2 评分结果跑模块3 打招呼语（不重新爬取 / 不重新评分）。

用法: 改下面 INPUT 路径，点运行即可。
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

# ↓ 改这里：模块2 产出的 jd_scored_*.json（在 output/scored/ 下）
INPUT = "output/scored/jd_scored_20260812_231248.json"

# 可选。None 则自动写 output/greeted/jd_greeted_{timestamp}.json
OUTPUT = None

# 可选。None 走 CRAWL_MODEL，再回退 deepseek。想 A/B 换模型改这里，如 "local_qwen"
MODEL = None

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scraper_framework.job_agent.generate import generate_greetings
from scraper_framework.job_agent.resume_highlights import load_resume_highlights


def _resolve(path: str) -> Path:
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    return p


def main():
    in_path = _resolve(INPUT)
    if not in_path.is_file():
        print(f"找不到输入文件: {in_path}")
        print("请把脚本顶部的 INPUT 改成实际的 output/scored/jd_scored_xxxxxxxx.json 路径")
        sys.exit(1)

    ranked = json.loads(in_path.read_text(encoding="utf-8"))
    if not isinstance(ranked, list):
        print("输入 JSON 必须是数组（模块2 的 jd_scored 格式：[{job, decision}, ...]）")
        sys.exit(1)
    if ranked and not (
        isinstance(ranked[0], dict) and "job" in ranked[0] and "decision" in ranked[0]
    ):
        print("输入看起来不是模块2 输出（每条应含 job + decision）")
        sys.exit(1)

    resume_path = ROOT / "data" / "resume_highlights.json"
    resume = load_resume_highlights(resume_path if resume_path.exists() else None)

    greeted = generate_greetings(ranked, resume, model=MODEL)

    out_dir = ROOT / "output" / "greeted"
    out_dir.mkdir(parents=True, exist_ok=True)
    if OUTPUT:
        out_path = _resolve(OUTPUT)
        out_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = out_dir / f"jd_greeted_{stamp}.json"

    out_path.write_text(
        json.dumps(greeted, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    generated = sum(1 for x in greeted if x.get("greetings"))
    print(f"打招呼语完成 {len(greeted)} 条（生成 {generated}）→ {out_path}")


if __name__ == "__main__":
    main()
