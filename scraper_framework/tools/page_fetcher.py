"""页面抓取工具 - 支持 DrissionPage / Playwright + crawl4ai"""

import asyncio
import logging
from typing import Optional

from crawl4ai import AsyncWebCrawler, CacheMode, CrawlerRunConfig
from DrissionPage.items import MixTab

from ..logger import get_spider_logger

logger = get_spider_logger(__name__)
logging.getLogger("crawl4ai").setLevel(logging.WARNING)


async def html_to_markdown(html: str, excluded_tags: Optional[list] = None) -> str:
    """使用 crawl4ai 将 HTML 转换为 Markdown

    Args:
        html: 原始 HTML 内容
        excluded_tags: 需要排除的 HTML 标签列表

    Returns:
        Markdown 格式的文本
    """
    if excluded_tags is None:
        excluded_tags = ["picture", "footer", "image", "img", "head", "header", "script"]

    raw_html_url = f"raw:{html}"
    config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        excluded_tags=excluded_tags,
    )
    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun(url=raw_html_url, config=config)
        if result.success:
            return result.markdown
        logger.error(f"Failed to convert HTML to markdown: {result.error_message}")
        return ""


def fetch_page_as_markdown_sync(tab: MixTab, url: str) -> str:
    """使用 DrissionPage 爬取页面并返回 Markdown (同步)

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
        return asyncio.run(html_to_markdown(content))
    except Exception as e:
        logger.error(f"Error fetching {url}: {e}")
        return ""


async def fetch_page_as_markdown_async(browser, url: str, timeout: int = 90000) -> str:
    """使用 Playwright 爬取页面并返回 Markdown (异步)

    Args:
        browser: Playwright browser 实例
        url: 要爬取的 URL
        timeout: 页面加载超时时间 (ms)

    Returns:
        页面内容的 Markdown 格式字符串
    """
    page = await browser.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        await page.wait_for_timeout(1000)
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(500)
        html_content = await page.content()
        return await html_to_markdown(html_content)
    except Exception as e:
        logger.error(f"Error fetching {url}: {e}")
        return f"Error: {e}"
    finally:
        await page.close()


async def extract_page_links_async(browser, url: str, timeout: int = 30000) -> str:
    """使用 Playwright 提取页面中同域名下的所有链接

    Args:
        browser: Playwright browser 实例
        url: 要提取链接的页面 URL
        timeout: 页面加载超时时间 (ms)

    Returns:
        格式化的链接列表文本，每行一个 "- 链接文本: URL"
    """
    from urllib.parse import urlparse

    page = await browser.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        await page.wait_for_timeout(1000)

        base_domain = urlparse(url).netloc
        links = await page.evaluate("""
            () => {
                const anchors = document.querySelectorAll('a[href]');
                return Array.from(anchors).map(a => ({
                    href: a.href,
                    text: a.textContent.trim()
                })).filter(l => l.href && l.text);
            }
        """)

        result = []
        seen = set()
        for link in links:
            href = link["href"]
            text = link["text"]
            parsed = urlparse(href)
            if (
                parsed.netloc == base_domain
                and href not in seen
                and not href.endswith((".pdf", ".jpg", ".png", ".css", ".js"))
            ):
                seen.add(href)
                result.append(f"- {text}: {href}")

        return "\n".join(result) if result else "No links found"
    except Exception as e:
        logger.error(f"Error extracting links from {url}: {e}")
        return f"Error: {e}"
    finally:
        await page.close()
