"""批量跑模块1 JD 抽取。

用法:
  1. 把 JD URL 写入 data/jd_urls.txt（每行一条）
  2. python scripts/run_jd_extract.py
  3. 结果写入 output/jd_extract_*.json，人工核对字段
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
from scraper_framework.job_agent.extract import load_urls


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
    print("（会先打开 JD 页面，再调用 LLM；浏览器地址栏应很快变成岗位 URL）")

    out_dir = ROOT / "output"
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"jd_extract_{stamp}.json"

    browser = Chromium()
    tab = browser.latest_tab
    try:
        results = extract_jd_batch(tab, urls)
    finally:
        try:
            browser.quit()
        except Exception:
            pass

    out_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"完成 {len(results)} 条 → {out_path}")
    print("下一步：打开 JSON，人工核对字段准确率，再调 schema/prompt。")


if __name__ == "__main__":
    main()
