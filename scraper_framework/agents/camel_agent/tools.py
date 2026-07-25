"""CAMEL Agent 工具 - 供 FunctionTool 调用"""

import asyncio
import logging
import os
from contextlib import contextmanager

from crawl4ai import AsyncWebCrawler, CacheMode, CrawlerRunConfig
from DrissionPage.items import MixTab

from ...tools.model_factory import (
    enable_no_proxy_for_aliyun,
    get_model,
    NO_PROXY_TARGETS,
)
from ...logger import get_spider_logger

logger = get_spider_logger(__name__)
logging.getLogger("crawl4ai").setLevel(logging.WARNING)


async def _filter_content(content: str) -> str:
    """将 HTML 转换为 Markdown"""
    raw_html_url = f"raw:{content}"
    config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        excluded_tags=["picture", "footer", "image", "img", "head", "header", "script"],
    )
    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun(url=raw_html_url, config=config)
        if result.success:
            return result.markdown
        else:
            logger.error(f"Failed to convert HTML to markdown: {result.error_message}")
            return ""


def fetch_page_as_markdown(tab: MixTab, url: str) -> str:
    """爬取指定 URL 页面并返回 Markdown 格式内容

    Args:
        tab: DrissionPage 的 MixTab 实例
        url: 要爬取的 URL

    Returns:
        页面内容的 Markdown 格式字符串
    """
    try:
        tab.get(url)
        try:
            tab.scroll.to_bottom()
        except Exception:
            pass
        tab.wait(1)
        content = tab.ele("tag:body").html
        return asyncio.run(_filter_content(content))
    except Exception as e:
        logger.error(f"Error fetching {url}: {e}")
        return ""


__all__ = [
    "fetch_page_as_markdown",
    "enable_no_proxy_for_aliyun",
    "get_model",
    "NO_PROXY_TARGETS",
]
