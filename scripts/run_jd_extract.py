"""批量跑模块1 JD 抽取，并可选接通模块2 评分。

用法:
  1. 把 JD URL 写入 data/jd_urls.txt（每行一条）
  2. python scripts/run_jd_extract.py
  3. 原始结果 → output/jd_extract_*.json
     评分结果 → output/jd_scored_*.json
"""

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from DrissionPage import Chromium

from scraper_framework.job_agent import extract_jd_batch
from scraper_framework.job_agent.decision import score_jobs
from scraper_framework.job_agent.extract import load_urls
from scraper_framework.job_agent.skill_profile import load_skill_profile


def main():
    urls_path = ROOT / "data" / "jd_urls.txt"
    if not urls_path.exists():
        print(f"请先创建 {urls_path}，每行放一个 JD URL")
        sys.exit(1)

    urls = load_urls(urls_path)
    if not urls:
        print(f"{urls_path} 里没有有效 URL")
        sys.exit(1)

    print(f"加载 {len(urls)} 条 URL，开始抽取…")
    print("（先打开 JD 页面，再调用 LLM；浏览器地址栏应很快变成岗位 URL）")

    out_dir = ROOT / "output"
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    extract_path = out_dir / f"jd_extract_{stamp}.json"
    scored_path = out_dir / f"jd_scored_{stamp}.json"

    profile_path = ROOT / "data" / "skill_profile.json"
    profile = load_skill_profile(profile_path if profile_path.exists() else None)

    browser = Chromium()
    tab = browser.latest_tab
    try:
        jobs = extract_jd_batch(tab, urls)
    finally:
        try:
            browser.quit()
        except Exception:
            pass

    extract_path.write_text(
        json.dumps(jobs, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"模块1 完成 {len(jobs)} 条 → {extract_path}")

    scored = score_jobs(jobs, profile, sort_by_score=True)
    scored_path.write_text(
        json.dumps(scored, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    recommended = sum(1 for x in scored if x.get("decision", {}).get("recommend"))
    print(f"模块2 完成 {len(scored)} 条（推荐 {recommended}）→ {scored_path}")


if __name__ == "__main__":
    main()
