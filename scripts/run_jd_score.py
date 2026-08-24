"""仅对已有 JD JSON 跑模块2 评分（不重新爬取）。

用法:
  python scripts/run_jd_score.py output/extract/jd_extract_20260101_120000.json
  python scripts/run_jd_score.py output/extract/jd_extract_20260101_120000.json --profile data/skill_profile.json
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scraper_framework.job_agent.decision import score_jobs
from scraper_framework.job_agent.skill_profile import load_skill_profile


def main():
    parser = argparse.ArgumentParser(description="对已有 JD JSON 重新评分")
    parser.add_argument("input", help="模块1 产出的 jd_extract_*.json 路径")
    parser.add_argument(
        "--profile",
        default=None,
        help="skill_profile JSON 路径；默认用 data/skill_profile.json 或内置默认画像",
    )
    parser.add_argument(
        "--no-sort",
        action="store_true",
        help="不按 score 降序排序",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="输出路径；默认 output/scored/jd_scored_{timestamp}.json",
    )
    args = parser.parse_args()

    in_path = Path(args.input)
    if not in_path.is_file():
        print(f"找不到输入文件: {in_path}")
        sys.exit(1)

    jobs = json.loads(in_path.read_text(encoding="utf-8"))
    if not isinstance(jobs, list):
        print("输入 JSON 必须是 Job 对象数组（模块1 的 jd_extract 格式）")
        sys.exit(1)

    if args.profile:
        profile = load_skill_profile(args.profile)
    else:
        default_path = ROOT / "data" / "skill_profile.json"
        profile = load_skill_profile(default_path if default_path.exists() else None)

    scored = score_jobs(jobs, profile, sort_by_score=not args.no_sort)

    out_dir = ROOT / "output" / "scored"
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.output:
        out_path = Path(args.output)
    else:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = out_dir / f"jd_scored_{stamp}.json"

    out_path.write_text(
        json.dumps(scored, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    recommended = sum(1 for x in scored if x.get("decision", {}).get("recommend"))
    print(f"评分完成 {len(scored)} 条（推荐 {recommended}）→ {out_path}")


if __name__ == "__main__":
    main()
