"""模块1：JD 结构化抽取

流程：先用 DrissionPage 打开 URL -> HTML->Markdown -> 再让 LLM 抽 JSON。
（不用 ReAct 工具调用：已知 URL 时没必要等模型决定是否打开页面。）
"""

import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from camel.agents import ChatAgent
from DrissionPage.items import MixTab

from ..agents.llm_agent.llm_scraper import extract_json
from ..logger import get_spider_logger
from ..tools.model_factory import (
    NO_PROXY_TARGETS,
    enable_no_proxy_for_aliyun,
    get_model,
)
from ..tools.page_fetcher import fetch_page_as_markdown_sync
from .schema import (
    JD_EXTRACT_USER_PROMPT,
    JD_OUTPUT_FIELDS,
    empty_jd_fields,
    normalize_jd_result,
)

logger = get_spider_logger(__name__)

# 防止超长 JD 撑爆上下文
_MAX_MARKDOWN_CHARS = 24000


def _build_extract_prompt() -> str:
    schema_lines = []
    for name, desc in JD_OUTPUT_FIELDS.items():
        if name in ("responsibilities", "required_skills", "preferred_skills", "tech_stack"):
            schema_lines.append(f'  "{name}": [],')
        else:
            schema_lines.append(f'  "{name}": "",')
    schema = "{\n" + "\n".join(schema_lines) + "\n}"

    field_desc = "\n".join(
        f"  - {name}: {desc}" for name, desc in JD_OUTPUT_FIELDS.items()
    )

    return f"""你是招聘 JD 结构化抽取助手。用户会提供已抓取的页面 Markdown，请据此抽取字段。

规则：
1. 只使用提供的 Markdown，禁止臆造
2. 找不到的字符串填 ""，找不到的数组填 []
3. 只输出一个 JSON 对象，不要 markdown 代码块，不要其它说明文字

输出 schema：
{schema}

字段说明：
{field_desc}

{JD_EXTRACT_USER_PROMPT}
"""


def _llm_extract_from_markdown(
    markdown: str,
    url: str,
    model_name: str,
    max_retries: int,
) -> Optional[Dict[str, Any]]:
    """纯 LLM 抽取（无工具），输入已是页面内容。"""
    content = markdown
    if len(content) > _MAX_MARKDOWN_CHARS:
        content = content[:_MAX_MARKDOWN_CHARS] + "\n\n[内容已截断]"

    agent = ChatAgent(
        _build_extract_prompt(),
        model=get_model(model_name),
        output_language="zh",
        step_timeout=60 * 5,
    )
    user_msg = (
        f"source_url（仅供参考，不要写入 JSON）: {url}\n\n"
        f"页面 Markdown：\n{content}"
    )

    for attempt in range(1, max_retries + 1):
        try:
            print(f"  -> LLM 抽取中 (attempt {attempt}/{max_retries}, model={model_name})...")
            with enable_no_proxy_for_aliyun(NO_PROXY_TARGETS):
                response = agent.step(user_msg)
        except Exception as e:
            logger.error(f"LLM extract error on attempt {attempt}: {e}")
            print(f"  [x] LLM 调用失败: {e}")
            response = None

        text = None
        if (
            response
            and getattr(response, "msg", None)
            and getattr(response.msg, "content", None)
        ):
            text = response.msg.content

        json_obj = extract_json(text) if text else None
        if isinstance(json_obj, list) and len(json_obj) == 1:
            json_obj = json_obj[0]
        if isinstance(json_obj, dict):
            return json_obj

        logger.warning(f"JD extract: failed to parse JSON on attempt {attempt}")
        print("  [x] 未能解析出 JSON，重试...")
        if attempt < max_retries:
            time.sleep(2 ** attempt)

    return None


def extract_jd(
    tab: MixTab,
    url: str,
    model: Optional[str] = None,
    max_retries: int = 3,
) -> Dict[str, Any]:
    """从单个 JD URL 抽取结构化字段。

    Returns:
        含 schema 字段 + source_url / data_source_* 的 dict；抽取失败时字段多为空，但仍含 source_url。
    """
    if not model:
        model = os.getenv("CRAWL_MODEL", "deepseek")

    print(f"  -> 打开页面: {url}")
    logger.info(f"fetching page: {url}")
    markdown = fetch_page_as_markdown_sync(tab, url)
    if not markdown.strip():
        logger.error(f"empty markdown for {url}")
        print("  [x] 页面内容为空（可能加载失败或被拦截）")
        return normalize_jd_result({"source_url": url, **empty_jd_fields()})

    print(f"  -> 已抓取 Markdown，长度={len(markdown)}")
    if len(markdown) < 100:
        logger.error(f"Markdown almost empty: {url}")
    elif len(markdown) < 300:
        logger.warning(
            f"Markdown unusually short ({len(markdown)} chars): {url}"
        )
        logger.debug(f"Markdown preview:\n{markdown[:1000]}")

    extracted = _llm_extract_from_markdown(markdown, url, model, max_retries)

    result: Dict[str, Any] = {"source_url": url, **empty_jd_fields()}
    if isinstance(extracted, dict):
        for k, v in extracted.items():
            if k == "source_url":
                continue
            if k in JD_OUTPUT_FIELDS and v not in (None, ""):
                result[k] = v
        result["data_source_type"] = "jd_extract"
        result["data_source_model"] = model
        print("  [ok] 抽取完成")
    else:
        result["error"] = "llm_extract_failed"
        print("  [x] 抽取失败")

    return normalize_jd_result(result)


def extract_jd_from_text(
    text: str,
    model: Optional[str] = None,
    max_retries: int = 3,
    *,
    source_url: str = "paste://demo",
) -> Dict[str, Any]:
    """从粘贴的 JD 文本抽取结构化字段（不打开浏览器）。用于适配Gradio做的演示demo

    复用与 extract_jd 相同的 LLM 抽取与 normalize；仅跳过页面抓取。
    """
    if not model:
        model = os.getenv("CRAWL_MODEL", "deepseek")

    markdown = (text or "").strip()
    if not markdown:
        logger.error("empty pasted JD text")
        print("  [x] 粘贴内容为空")
        return normalize_jd_result({"source_url": source_url, **empty_jd_fields()})

    print(f"  -> 粘贴文本长度={len(markdown)}")
    extracted = _llm_extract_from_markdown(markdown, source_url, model, max_retries)

    result: Dict[str, Any] = {"source_url": source_url, **empty_jd_fields()}
    if isinstance(extracted, dict):
        for k, v in extracted.items():
            if k == "source_url":
                continue
            if k in JD_OUTPUT_FIELDS and v not in (None, ""):
                result[k] = v
        result["data_source_type"] = "jd_extract"
        result["data_source_model"] = model
        print("  [ok] 抽取完成")
    else:
        result["error"] = "llm_extract_failed"
        print("  [x] 抽取失败")

    return normalize_jd_result(result)


def extract_jd_batch(
    tab: MixTab,
    urls: List[str],
    model: Optional[str] = None,
    max_retries: int = 3,
) -> List[Dict[str, Any]]:
    """批量抽取；单条失败不中断整批。"""
    results: List[Dict[str, Any]] = []
    total = len(urls)
    for i, url in enumerate(urls, 1):
        url = url.strip()
        if not url or url.startswith("#"):
            continue
        print(f"\n[{i}/{total}] {url}")
        logger.info(f"[{i}/{total}] extracting JD: {url}")
        try:
            item = extract_jd(tab, url, model=model, max_retries=max_retries)
            results.append(item)
        except Exception as e:
            logger.error(f"extract failed for {url}: {e}")
            print(f"  [x] 异常: {e}")
            results.append(
                {
                    "source_url": url,
                    "error": str(e),
                    **empty_jd_fields(),
                }
            )
    return results


def load_urls(path: Union[str, Path]) -> List[str]:
    """从文本文件加载 URL，每行一条；支持 # 注释与空行。"""
    text = Path(path).read_text(encoding="utf-8")
    urls = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        urls.append(line)
    return urls
