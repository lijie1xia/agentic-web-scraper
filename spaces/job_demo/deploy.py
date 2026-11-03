"""Flatten spaces/job_demo and upload to a Hugging Face Space.

Usage:
    python spaces/job_demo/deploy.py --out ./space_build
    python spaces/job_demo/deploy.py          # needs `hf auth login`
"""
from __future__ import annotations

import argparse
import os
import shutil
import tempfile
from pathlib import Path

os.environ["HF_HUB_OFFLINE"] = "0"
os.environ["HF_ENDPOINT"] = "https://huggingface.co"

ROOT = Path(__file__).resolve().parents[2]
SPACE_DIR = Path(__file__).resolve().parent
SPACE_ID_DEFAULT = "job-agent-demo"

_PKG_FILES = [
    "scraper_framework/__init__.py",
    "scraper_framework/logger.py",
    "scraper_framework/tools/__init__.py",
    "scraper_framework/tools/json_extract.py",
    "scraper_framework/tools/model_factory.py",
]


def flatten(dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SPACE_DIR / "app.py", dest / "app.py")
    shutil.copy2(SPACE_DIR / "requirements.txt", dest / "requirements.txt")
    shutil.copy2(SPACE_DIR / "README.md", dest / "README.md")
    gif = SPACE_DIR / "preview.gif"
    if gif.is_file():
        shutil.copy2(gif, dest / "preview.gif")
    data_dest = dest / "data"
    data_dest.mkdir(exist_ok=True)
    shutil.copy2(SPACE_DIR / "data" / "skill_profile.json", data_dest / "skill_profile.json")
    shutil.copy2(SPACE_DIR / "data" / "resume_highlights.json", data_dest / "resume_highlights.json")
    for rel in _PKG_FILES:
        src = ROOT / rel
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, out)
    job_src = ROOT / "scraper_framework" / "job_agent"
    job_dest = dest / "scraper_framework" / "job_agent"
    job_dest.mkdir(parents=True, exist_ok=True)
    for path in job_src.glob("*.py"):
        shutil.copy2(path, job_dest / path.name)


def upload_hf() -> None:
    from dotenv import load_dotenv
    from huggingface_hub import HfApi, create_repo, whoami

    load_dotenv(ROOT / ".env")
    user = whoami()["name"]
    repo_id = f"{user}/{os.getenv('HF_SPACE_NAME', SPACE_ID_DEFAULT)}"
    print(f"deploying Space {repo_id}")
    create_repo(
        repo_id,
        repo_type="space",
        space_sdk="gradio",
        exist_ok=True,
        private=False,
    )
    staging = Path(tempfile.mkdtemp(prefix="job-demo-space-"))
    try:
        flatten(staging)
        api = HfApi()
        api.upload_folder(
            folder_path=str(staging),
            repo_id=repo_id,
            repo_type="space",
        )
        key = os.getenv("DEEPSEEK_API_KEY")
        if key:
            api.add_space_secret(repo_id, "DEEPSEEK_API_KEY", key)
            api.add_space_variable(repo_id, "CRAWL_MODEL", os.getenv("CRAWL_MODEL", "deepseek"))
            print("configured DEEPSEEK_API_KEY secret")
        else:
            print("DEEPSEEK_API_KEY missing; add it in Space Settings → Secrets")
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    print(f"https://huggingface.co/spaces/{repo_id}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        help="只导出可部署目录（HF Space / ModelScope Studio 都能用），不上传",
    )
    args = parser.parse_args()
    if args.out:
        dest = Path(args.out).resolve()
        if dest.exists():
            shutil.rmtree(dest)
        flatten(dest)
        print(dest)
        return
    upload_hf()


if __name__ == "__main__":
    main()
