"""PDF 视觉解析爬取器 - 使用视觉大模型从 PDF 图片中提取信息"""

import base64
import time
import requests
from typing import Any, Dict, List, Optional

from openai import OpenAI
from dotenv import load_dotenv
import os

from ..tools.model_factory import enable_no_proxy_for_aliyun, NO_PROXY_TARGETS
from ..logger import get_spider_logger

logger = get_spider_logger(__name__)
load_dotenv()

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None


def pdf_extract(url: str, target_keywords: Optional[List[str]] = None) -> List:
    """下载 PDF 并根据关键词过滤页面，转换为图片列表

    Args:
        url: PDF 文件 URL
        target_keywords: 用于筛选页面的关键词列表

    Returns:
        图片对象列表 (PyMuPDF Pixmap)
    """
    if fitz is None:
        raise ImportError("Please install PyMuPDF: pip install PyMuPDF")

    response = requests.get(url, timeout=30, verify=False)
    response.raise_for_status()

    doc = fitz.open(stream=response.content, filetype="pdf")
    images = []

    target_page_indices = []
    if target_keywords:
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            text = page.get_text("text").lower()
            if any(kw.lower() in text for kw in target_keywords):
                target_page_indices.append(page_num)
                if page_num + 1 < len(doc):
                    target_page_indices.append(page_num + 1)
        target_page_indices = sorted(list(set(target_page_indices)))

    if not target_page_indices:
        target_page_indices = list(range(len(doc)))

    for idx in target_page_indices:
        page = doc.load_page(idx)
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
        images.append(pix)

    doc.close()
    logger.info(f"Converted {len(images)} pages to images from PDF")
    return images


def extract_with_vl_model(images: List, pdf_crawl_field: Dict[str, str]) -> Optional[Dict]:
    """使用视觉模型从图片中提取信息

    Args:
        images: 图片对象列表
        pdf_crawl_field: 需要提取的字段及说明

    Returns:
        提取的信息字典
    """
    fields_json = ",\n    ".join([f'"{k}": ""' for k in pdf_crawl_field.keys()])
    fields_desc = "\n".join([f"- {k}: {v}" for k, v in pdf_crawl_field.items()])

    prompt = f'''
            角色：你是一个资深的数据解析专家
            职责：从PDF图片中提取相关信息

            处理流程：
                1. 仔细阅读所有PDF页面图片
                2. 提取详细信息
                3. 严格按照要求的JSON格式输出
                4. 所有信息必须来自PDF内容，如果没有找到则填空字符串''，禁止编造

            输出格式（严格JSON）：
            {{{fields_json}}}

            字段说明：
            {fields_desc}

            IMPORTANT: Output ONLY a single JSON object. Do NOT use code blocks.
            '''

    message_content = []
    for img_obj in images:
        img_data = img_obj.tobytes(output='png')
        base64_img = base64.b64encode(img_data).decode('utf-8')
        message_content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{base64_img}"}
        })
    message_content.append({"type": "text", "text": prompt})

    api_key = (
        os.getenv("VL_API_KEY")
        or os.getenv("DEEPSEEK_API_KEY")
        or os.getenv("OPENAI_API_KEY")
    )
    base_url = os.getenv("VL_BASE_URL", "https://api.deepseek.com")
    model_name = os.getenv("VL_MODEL", "deepseek-chat")

    client = OpenAI(base_url=base_url, api_key=api_key)

    with enable_no_proxy_for_aliyun(NO_PROXY_TARGETS):
        response = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": message_content}],
            stream=False,
        )

    result = response.choices[0].message.content
    logger.debug(f"VL model response: {result[:200]}...")

    from ..agents.llm_agent.llm_scraper import extract_json
    return extract_json(result)


class PDFAgentScraper:
    """PDF 视觉解析爬取器

    Usage:
        scraper = PDFAgentScraper()
        result = scraper.crawl(
            pdf_urls=["https://example.com/doc.pdf"],
            fields={"field_name": "字段说明"},
        )
    """

    def __init__(self, max_retries: int = 3):
        self.max_retries = max_retries

    def crawl(
        self,
        pdf_urls: List[str],
        fields: Dict[str, str],
        target_keywords: Optional[List[str]] = None,
    ) -> Optional[Dict]:
        """执行 PDF 爬取

        Args:
            pdf_urls: PDF URL 列表
            fields: 需要提取的字段及说明
            target_keywords: 用于筛选 PDF 页面的关键词

        Returns:
            提取的数据 dict，失败返回 None
        """
        if not pdf_urls:
            return None

        for attempt in range(1, self.max_retries + 1):
            try:
                all_images = []
                for url in pdf_urls:
                    images = pdf_extract(url, target_keywords)
                    all_images.extend(images)

                result = extract_with_vl_model(all_images, fields)
                if result and isinstance(result, dict):
                    return result

            except Exception as e:
                logger.error(f"PDF extraction attempt {attempt} failed: {e}")

            if attempt < self.max_retries:
                time.sleep(2 ** attempt)

        return None


def pdf_crawl(
    pdf_urls: List[str],
    existing_data: Dict[str, Any],
    pdf_crawl_field: Dict[str, str],
    target_keywords: Optional[List[str]] = None,
    max_retries: int = 3,
) -> Dict[str, Any]:
    """便捷函数 - 使用视觉大模型解析 PDF 并合并到已有数据

    Args:
        pdf_urls: PDF URL 列表
        existing_data: 已有的数据
        pdf_crawl_field: 需要提取的字段及说明
        target_keywords: 用于筛选 PDF 页面的关键词
        max_retries: 最大重试次数

    Returns:
        合并后的数据
    """
    scraper = PDFAgentScraper(max_retries=max_retries)
    result = scraper.crawl(pdf_urls, pdf_crawl_field, target_keywords)

    if not result:
        logger.warning("PDF extraction failed")
        return existing_data

    result_data = existing_data.copy()
    crawled_fields = []

    if isinstance(result, list) and len(result) > 0:
        result = result[0]

    if isinstance(result, dict):
        for k, v in result.items():
            if v and not result_data.get(k):
                result_data[k] = v
                crawled_fields.append(k)

    existing_fields = result_data.get("pdf_crawl_field", [])
    result_data["pdf_crawl_field"] = list(dict.fromkeys(existing_fields + crawled_fields))

    return result_data
