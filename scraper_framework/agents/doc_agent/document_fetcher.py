"""DocumentFetcher - URL → Document 抓取器

负责获取页面并转换为 Agent 可理解的文档格式。
不负责判断哪个链接最相关、任务是否完成等决策 —— 这些属于 Agent。
"""

from typing import Optional

from .models import Document
from .page_source import PageSource, DocumentPageSource
from ...logger import get_spider_logger

logger = get_spider_logger(__name__)


class DocumentFetcher:
    """文档抓取器

    将 URL 转换为 Document，内部可替换不同的 PageSource 实现。
    当前默认使用 DocumentPageSource (文档驱动模式)。

    未来可扩展:
        - BrowserPageSource (DOM 浏览器交互模式)

    Usage:
        fetcher = DocumentFetcher(tab)
        doc = fetcher.fetch("https://example.com")
        print(doc.content)   # Markdown 正文
        print(doc.links)     # [Link(text="...", url="..."), ...]
    """

    def __init__(self, tab=None, page_source: Optional[PageSource] = None, timeout: int = 30):
        """初始化

        Args:
            tab: DrissionPage 的 MixTab 实例 (page_source 为 None 时使用)
            page_source: 自定义 PageSource 实现 (可选，优先于 tab)
            timeout: 页面加载超时时间
        """
        if page_source is not None:
            self._page_source = page_source
        elif tab is not None:
            self._page_source = DocumentPageSource(tab, timeout=timeout)
        else:
            raise ValueError("Either tab or page_source must be provided")

    def fetch(self, url: str) -> Document:
        """抓取 URL 并返回 Document

        Args:
            url: 要抓取的页面 URL

        Returns:
            Document 包含 Markdown 内容和关联链接

        Raises:
            Exception: 页面抓取失败时抛出异常
        """
        return self._page_source.get_page(url)

    @property
    def page_source(self) -> PageSource:
        """获取当前的 PageSource 实例（便于调试和检查）"""
        return self._page_source
