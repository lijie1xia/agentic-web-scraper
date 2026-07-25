"""页面来源抽象层 - 为未来 Browser DOM 模式预留扩展点

当前实现: DocumentPageSource (HTML → Markdown 文档驱动)
未来扩展: BrowserPageSource (DOM 浏览器交互模式)
"""

from abc import ABC, abstractmethod
from urllib.parse import urljoin, urlparse

from .models import Document, Link
from ...tools.page_fetcher import html_to_markdown
from ...logger import get_spider_logger

logger = get_spider_logger(__name__)


class PageSource(ABC):
    """页面来源抽象基类

    定义统一的页面获取接口。当前实现文档驱动模式，
    未来可扩展 BrowserPageSource 实现浏览器 DOM 交互模式。
    """

    @abstractmethod
    def get_page(self, target: str) -> Document:
        """获取目标页面并转换为 Document

        Args:
            target: URL 字符串

        Returns:
            Document 包含页面内容和关联链接
        """
        ...


class DocumentPageSource(PageSource):
    """文档驱动的页面来源

    使用 DrissionPage 获取 HTML，通过 crawl4ai 转换为 Markdown，
    同时提取页面中的关联链接。
    """

    def __init__(self, tab, timeout: int = 30):
        """初始化

        Args:
            tab: DrissionPage 的 MixTab 实例
            timeout: 页面加载超时时间 (秒)
        """
        self.tab = tab
        self.timeout = timeout

    def get_page(self, target: str) -> Document:
        """获取页面并转换为 Document

        Args:
            target: 要访问的 URL

        Returns:
            Document 包含 Markdown 内容和结构化链接列表
        """
        logger.info(f"DocumentPageSource: fetching {target}")

        self.tab.get(target)
        try:
            self.tab.scroll.to_bottom()
        except Exception:
            pass
        self.tab.wait(1)

        body = self.tab.ele("tag:body")
        html_content = body.html
        title = self._extract_title()

        import asyncio
        markdown_content = asyncio.run(html_to_markdown(html_content))

        links = self._extract_links(target)

        document = Document(
            url=target,
            title=title,
            content=markdown_content,
            links=links,
        )

        logger.info(
            f"DocumentPageSource: fetched {target}, "
            f"content_len={len(markdown_content)}, links={len(links)}"
        )
        return document

    def _extract_title(self) -> str:
        """提取页面标题"""
        try:
            title_ele = self.tab.ele("tag:title")
            if title_ele:
                return title_ele.text.strip()
        except Exception:
            pass
        return ""

    def _extract_links(self, base_url: str) -> list:
        """从当前页面提取同域名关联链接

        Args:
            base_url: 基础 URL，用于解析相对路径和过滤同域名

        Returns:
            Link 列表
        """
        base_domain = urlparse(base_url).netloc
        seen = set()
        links = []

        try:
            anchor_elements = self.tab.eles("tag:a")
            for anchor in anchor_elements:
                try:
                    href = anchor.attr("href")
                    text = anchor.text.strip()
                    if not href or not text:
                        continue

                    absolute_url = urljoin(base_url, href)
                    parsed = urlparse(absolute_url)

                    if parsed.netloc != base_domain:
                        continue
                    if absolute_url in seen:
                        continue
                    if absolute_url.endswith((".pdf", ".jpg", ".png", ".css", ".js")):
                        continue

                    seen.add(absolute_url)
                    links.append(Link(text=text, url=absolute_url))
                except Exception:
                    continue
        except Exception as e:
            logger.warning(f"DocumentPageSource: failed to extract links from {base_url}: {e}")

        return links
