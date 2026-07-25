"""BaseSpider - 爬虫基类

提供浏览器管理、多线程爬取、重试、数据保存等基础能力。
子类只需实现 get_list_urls() 和 scrape_detail_page() 即可完成一个爬虫。
"""

import json
import time
import threading
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional, Union
from pathlib import Path
from dataclasses import dataclass, field

from DrissionPage import Chromium, ChromiumOptions
from DrissionPage.items import MixTab

from ..models import ScrapeResult, ErrorInfo, CrawlerProgress
from ..logger import get_spider_logger

logger = get_spider_logger("base_spider")


@dataclass
class SpiderConfig:
    """爬虫配置"""
    school_name: str = ""
    max_workers: int = 10
    headless: bool = False
    chrome_profile_dir: Optional[str] = None
    verify_ssl: bool = True
    retry_count: int = 3
    retry_delay: int = 5
    output_dir: str = "output"


class BaseSpider(ABC):
    """爬虫基类

    子类必须实现：
    1. get_list_urls(tab) - 获取列表页 URL
    2. scrape_detail_page(tab, major_info) - 爬取详情页数据

    Usage:
        class MySpider(BaseSpider):
            def get_list_urls(self, tab):
                return [{"url": "https://..."}]

            def scrape_detail_page(self, tab, major_info):
                # 爬取逻辑
                return ScrapeResult(data={...})

        spider = MySpider(school_name="example", max_workers=5)
        result = spider.run()
    """

    def __init__(
        self,
        school_name: str = "",
        max_workers: int = 10,
        headless: bool = False,
        chrome_profile_dir: str = None,
        verify_ssl: bool = True,
        retry_count: int = 3,
        retry_delay: int = 5,
        output_dir: str = "output",
    ):
        self.school_name = school_name
        self.max_workers = max_workers
        self.headless = headless
        self.chrome_profile_dir = chrome_profile_dir
        self.verify_ssl = verify_ssl
        self.retry_count = retry_count
        self.retry_delay = retry_delay
        self.output_dir = Path(output_dir)

        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None
        self.browser: Optional[Chromium] = None

        self.total_count = 0
        self.scraped_data: List[Dict[str, Any]] = []
        self.failed_list: List[ErrorInfo] = []

        self._data_lock = threading.Lock()
        self._failed_lock = threading.Lock()
        self._browser_lock = threading.Lock()
        self._browser_ready = threading.Event()
        self._browser_ready.set()

        logger.info(f"Initialized spider: {self.school_name}")

    def _create_browser(self) -> Chromium:
        """创建 Chrome 浏览器实例"""
        try:
            co = ChromiumOptions()
            if self.chrome_profile_dir:
                co.set_user_data_path(self.chrome_profile_dir)
                co.set_argument("--profile-directory=Default")
            if self.headless:
                co.set_argument("--headless")
            if not self.verify_ssl:
                co.set_argument("--ignore-certificate-errors")
                co.set_argument("--ignore-ssl-errors")
            browser = Chromium(co)
            logger.info("Browser instance created successfully")
            return browser
        except Exception as e:
            logger.error(f"Failed to create browser: {e}")
            raise

    def _get_browser(self) -> Chromium:
        """获取浏览器实例（线程安全）"""
        if self.browser and self.browser.states.is_alive:
            return self.browser

        with self._browser_lock:
            if self.browser and self.browser.states.is_alive:
                return self.browser

            logger.warning("Browser instance lost, recreating...")
            self._browser_ready.clear()

            try:
                self.browser = self._create_browser()
            except Exception as e:
                logger.exception(f"Browser recreation failed: {e}")
                raise
            finally:
                self._browser_ready.set()

        self._browser_ready.wait()
        return self.browser

    def _cleanup_browsers(self):
        """关闭浏览器"""
        if not self.browser:
            return
        self.browser.quit()
        self.browser = None

    @abstractmethod
    def get_list_urls(self, tab: MixTab) -> Optional[List[Dict[str, Any]]]:
        """获取列表页 URL 列表

        Args:
            tab: DrissionPage 的 MixTab 对象

        Returns:
            URL 列表，每项必须包含一个 URL key（默认 "url"）
        """
        pass

    @abstractmethod
    def scrape_detail_page(
        self,
        tab: MixTab,
        item_info: Dict[str, Any],
        user_prompt: Optional[str] = None,
    ) -> ScrapeResult:
        """爬取详情页数据

        Args:
            tab: DrissionPage 的 Tab 对象
            item_info: 包含 URL 等信息的字典
            user_prompt: 可选的用户提示词

        Returns:
            ScrapeResult
        """
        pass

    def _scrape_single_url(
        self, item_info: Dict[str, Any], user_prompt: Optional[str] = None
    ) -> ScrapeResult:
        """爬取单个 URL"""
        tab = None
        url = item_info.get("url", item_info.get("major_url-href", ""))

        for attempt in range(self.retry_count):
            try:
                browser = self._get_browser()
                try:
                    tab = browser.new_tab()
                except Exception as e:
                    raise RuntimeError(f"Failed to create tab: {e}")

                if user_prompt is None:
                    res = self.scrape_detail_page(tab, item_info)
                else:
                    res = self.scrape_detail_page(tab, item_info, user_prompt=user_prompt)

                data = res.data if res else None
                err_info = res.err_info if res else None

                if data:
                    with self._data_lock:
                        if isinstance(data, list):
                            self.scraped_data.extend(data)
                        elif isinstance(data, dict):
                            self.scraped_data.append(data)

                if err_info and err_info.get("should_retry"):
                    if attempt == self.retry_count - 1:
                        logger.error(f"Max retries reached for {url}")
                    else:
                        logger.warning(f"Retrying {url} in {self.retry_delay}s...")
                        time.sleep(self.retry_delay)
                        continue

                logger.info(f"Scraped {url} successfully")
                return res

            except Exception as e:
                logger.error(f"Error scraping {url}: {e}")
                with self._failed_lock:
                    self._upsert_failed_list({"url": url, "err_list": [str(e)]})

                if attempt == self.retry_count - 1:
                    logger.error(f"Max retries reached for {url}")
                    return None

                logger.warning(f"Retrying {url} in {self.retry_delay}s...")
                time.sleep(self.retry_delay)

            finally:
                if tab:
                    try:
                        tab.close()
                    except Exception:
                        pass

    def initialize(self):
        """初始化逻辑，供子类覆盖"""
        pass

    def before_scrape(self, tab: MixTab, url_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """在爬取详情页之前执行，供子类覆盖"""
        return url_list

    def after_scrape(self):
        """爬取完成后调用，供子类覆盖"""
        pass

    def run(
        self,
        count: Optional[int] = None,
        urls: Optional[List[str]] = None,
        save_data: bool = True,
        cb: Optional[Callable[[CrawlerProgress], None]] = None,
        user_prompt: Optional[str] = None,
    ) -> CrawlerProgress:
        """执行爬虫

        Args:
            count: 随机爬取 count 条记录
            urls: 指定 URL 列表
            save_data: 是否保存爬取结果
            cb: 回调函数
            user_prompt: 可选的用户提示词

        Returns:
            CrawlerProgress
        """
        self.start_time = time.time()

        try:
            self.initialize()

            progress = CrawlerProgress(
                total_count=0,
                data=self.scraped_data,
                err_list=self.failed_list,
                remark="Starting...",
            )

            browser = self._get_browser()
            tab = browser.new_tab()

            try:
                url_list = self.get_list_urls(tab)
            finally:
                try:
                    tab.close()
                except Exception:
                    pass

            if not url_list:
                logger.error("Failed to get URL list")
                return progress

            logger.info(f"Got {len(url_list)} URLs from list page")

            scrape_urls = url_list
            if urls:
                url_map = {item.get("url", item.get("major_url-href", "")): item for item in url_list}
                scrape_urls = [url_map.get(u, {"url": u}) for u in urls]

            if count:
                import random
                scrape_urls = random.sample(scrape_urls, k=min(count, len(scrape_urls)))

            progress.total_count = len(scrape_urls)
            progress.remark = "URL list obtained"

            browser = self._get_browser()
            tab = browser.new_tab()
            try:
                scrape_urls = self.before_scrape(tab, scrape_urls)
            finally:
                try:
                    tab.close()
                except Exception:
                    pass

            self.total_count = len(scrape_urls)
            completed = 0

            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                future_to_info = {
                    executor.submit(self._scrape_single_url, info, user_prompt): info
                    for info in scrape_urls
                }
                progress.remark = "Scraping..."

                for future in as_completed(future_to_info):
                    info = future_to_info[future]
                    completed += 1
                    try:
                        _ = future.result()
                    except Exception as e:
                        logger.exception(f"Unhandled exception for {info}: {e}")
                    finally:
                        if cb:
                            cb(progress)
                        logger.info(f"Progress: {completed}/{self.total_count}")

            logger.info(f"Scraping complete: {len(self.scraped_data)} items")
            logger.info(f"Errors: {len(self.failed_list)} items")

            self.after_scrape()

            if save_data:
                self._save_data()

            progress.remark = "Done"
            if cb:
                cb(progress)

            return progress

        except KeyboardInterrupt:
            logger.warning("User interrupted, exiting safely...")
        finally:
            self._cleanup_browsers()
            logger.info("Browser closed, program exited safely.")

    def _save_data(self):
        """保存爬取的数据到 JSON 文件"""
        if not self.scraped_data:
            return

        output_dir = self.output_dir / self.school_name
        output_dir.mkdir(parents=True, exist_ok=True)

        data_path = output_dir / f"{self.school_name}_data.json"
        fail_path = output_dir / f"{self.school_name}_failed.json"

        with open(data_path, "w", encoding="utf-8") as f:
            json.dump(self.scraped_data, f, ensure_ascii=False, indent=2)
        logger.info(f"Data saved to: {data_path}")

        if self.failed_list:
            with open(fail_path, "w", encoding="utf-8") as f:
                json.dump(self.failed_list, f, ensure_ascii=False, indent=2)
            logger.info(f"Failed list saved to: {fail_path}")

    def _upsert_failed_list(self, err_info: ErrorInfo) -> bool:
        """插入或更新 failed_list"""
        try:
            for i, item in enumerate(self.failed_list):
                if item.get("url") == err_info.get("url"):
                    self.failed_list[i] = err_info
                    return True
            self.failed_list.append(err_info)
            return True
        except Exception as e:
            logger.error(f"Failed to update failed list: {e}")
            return False

    def get_json_data(self, file_path: Union[str, Path]) -> Optional[Union[Dict, List]]:
        """从本地 JSON 文件读取数据"""
        file_path = Path(file_path)
        if not file_path.exists():
            logger.error(f"JSON file not found: {file_path}")
            return None
        try:
            with file_path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to read JSON: {file_path}, error: {e}")
            return None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._cleanup_browsers()
