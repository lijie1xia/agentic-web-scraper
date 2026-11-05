"""Flatten spaces/job_demo and upload to a Hugging Face Space.

Usage:
    python spaces/job_demo/deploy.py --out ./space_build
    python spaces/job_demo/deploy.py          # needs `hf auth login`
"""
from __future__ import annotations

import argparse
import contextlib
import os
import shutil
import tempfile
from pathlib import Path

os.environ["HF_HUB_OFFLINE"] = "0"
os.environ["HF_ENDPOINT"] = "https://huggingface.co"

ROOT = Path(__file__).resolve().parents[2]
SPACE_DIR = Path(__file__).resolve().parent
SPACE_ID_DEFAULT = "job-agent-demo"
PROXY_ENV_KEYS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")


@contextlib.contextmanager
def proxy_environment(url: str | None):
    """仅在显式传入代理时临时设置环境变量，结束后原样恢复；不写死任何地址。"""
    if not url:
        yield
        return
    saved = {key: os.environ.get(key) for key in PROXY_ENV_KEYS}
    for key in PROXY_ENV_KEYS:
        os.environ[key] = url
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

_PKG_FILES = [
    "scraper_framework/__init__.py",
    "scraper_framework/logger.py",
    "scraper_framework/tools/__init__.py",
    "scraper_framework/tools/json_extract.py",
    "scraper_framework/tools/model_factory.py",
]

# Demo 的免费路径用规则抽取，需要整个 job_workflow 包（导入 __init__ 会连带 repository）。
_PKG_DIRS = ["scraper_framework/job_workflow"]


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
    for rel in _PKG_DIRS:
        out_dir = dest / rel
        out_dir.mkdir(parents=True, exist_ok=True)
        for path in (ROOT / rel).glob("*.py"):
            shutil.copy2(path, out_dir / path.name)


def upload_hf(proxy: str | None = None) -> None:
    from dotenv import load_dotenv
    from huggingface_hub import HfApi, create_repo, whoami

    load_dotenv(ROOT / ".env")
    try:
        user = whoami()["name"]
    except Exception as exc:
        raise SystemExit("未登录 Hugging Face：先执行 `hf auth login` 或设置 HF_TOKEN。") from exc
    repo_id = f"{user}/{os.getenv('HF_SPACE_NAME', SPACE_ID_DEFAULT)}"
    print(f"deploying Space {repo_id}（{'经代理' if proxy else '直连'}）")
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
        # 公开 Demo 默认只跑本地规则，不需要服务器密钥；实时生成由访客自带 Key。
        print("未上传 DEEPSEEK_API_KEY：公开 Demo 默认零成本，访客在页面底部自填 Key。")
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    print(f"https://huggingface.co/spaces/{repo_id}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        help="只导出可部署目录（HF Space / ModelScope Studio 都能用），不上传",
    )
    parser.add_argument(
        "--proxy",
        default=os.getenv("HF_PROXY"),
        help="可选：上传时使用的 HTTP(S) 代理（也可用环境变量 HF_PROXY）；不填则直连",
    )
    args = parser.parse_args()
    if args.out:
        dest = Path(args.out).resolve()
        if dest.exists():
            shutil.rmtree(dest)
        flatten(dest)
        print(dest)
        return
    with proxy_environment(args.proxy):
        upload_hf(proxy=args.proxy)


if __name__ == "__main__":
    main()
