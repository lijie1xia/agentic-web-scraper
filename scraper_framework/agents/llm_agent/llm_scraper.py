"""LLM Agent 爬取 - 使用 CAMEL-AI ChatAgent + FunctionTool 进行 ReAct 爬取

这是最基础的 LLM 爬取模式：用户提供 URL，Agent 自动爬取页面并提取结构化数据。
"""

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

from camel.agents import ChatAgent
from camel.toolkits import FunctionTool
from DrissionPage import Chromium
from DrissionPage.items import MixTab

from ...tools.model_factory import get_model, enable_no_proxy_for_aliyun, NO_PROXY_TARGETS
from ...tools.page_fetcher import fetch_page_as_markdown_sync
from ...logger import get_spider_logger

logger = get_spider_logger(__name__)
logging.getLogger("camel").setLevel(logging.WARNING)
logging.getLogger("crawl4ai").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)


def extract_json(text: str) -> Optional[Any]:
    """从文本中提取 JSON 对象或数组"""
    if not isinstance(text, str):
        return None
    text = text.strip()
    if not text:
        return None

    array_start = text.find("[")
    array_end = text.rfind("]")
    if array_start != -1 and array_end > array_start:
        try:
            return json.loads(text[array_start : array_end + 1])
        except json.JSONDecodeError:
            pass

    obj_start = text.find("{")
    obj_end = text.rfind("}")
    if obj_start != -1 and obj_end > obj_start:
        try:
            return json.loads(text[obj_start : obj_end + 1])
        except json.JSONDecodeError:
            pass

    return None


class LLMAgentScraper:
    """LLM Agent 爬取器

    使用 CAMEL-AI ChatAgent + FunctionTool 实现 ReAct 模式的网页爬取。
    Agent 自动调用工具获取页面内容，然后提取结构化数据。

    Usage:
        tab = Chromium().new_tab()
        scraper = LLMAgentScraper(tab, model="qwen")
        result = scraper.crawl(
            msg="专业信息：https://example.com/program, 学费信息：https://example.com/fees",
            output_fields={"major_name": "专业名称", "fees": "学费"},
        )
    """

    DEFAULT_SYSTEM_PROMPT = """
角色：你是一个资深的网页数据爬虫专家
职责：根据用户提供的链接，从该链接中获取信息
处理流程：
    1. 根据用户提供链接使用爬虫工具获取该链接的内容
    2. 根据获取到的内容，进行分析整理，然后根据要求的JSON格式提取并返回
    3. 提取过程中要严格保证所有的信息必须是从用户提供的链接中获取的，如果没有获取到则空着，杜绝自我杜撰
    4. 所有的内容返回字符串，不允许返回bool或number
输出要求：
    - 严格使用JSON格式输出
    IMPORTANT: Output ONLY a single JSON object starting with { and ending with }.
    Do NOT output an array, do NOT output any other text, do NOT use code blocks.
"""

    def __init__(
        self,
        tab: MixTab,
        model: str = "qwen",
        system_prompt: str = None,
        max_retries: int = 3,
    ):
        """初始化 LLM Agent 爬取器

        Args:
            tab: DrissionPage 的 MixTab 实例
            model: 模型名称 ("qwen", "local_qwen", 或自定义)
            system_prompt: 自定义系统提示词，None 则使用默认
            max_retries: 最大重试次数
        """
        self.tab = tab
        self.model_name = model
        self.system_prompt = system_prompt or self.DEFAULT_SYSTEM_PROMPT
        self.max_retries = max_retries
        self.model = get_model(model)

    def _build_field_schema(self, output_fields: Dict[str, str]) -> str:
        """根据输出字段构建 JSON Schema 描述"""
        fields = []
        for name, desc in output_fields.items():
            fields.append(f'            "{name}": "",')
        schema = "{\n" + "\n".join(fields) + "\n        }"

        field_desc_lines = []
        for name, desc in output_fields.items():
            field_desc_lines.append(f"            {name}（{desc}）")
        field_desc = "\n".join(field_desc_lines)

        return f"""输出要求：
        - 严格使用JSON格式输出:
        {schema}
        字段解释:
{field_desc}
        """

    def crawl(
        self,
        msg: str,
        output_fields: Dict[str, str] = None,
        system_prompt: str = None,
        user_prompt: str = None,
    ) -> Optional[Dict[str, Any]]:
        """执行 LLM 爬取

        Args:
            msg: 传给 Agent 的消息，包含 URL 和描述
                如 "专业信息：https://example.com/program, 学费：https://example.com/fees"
            output_fields: 需要提取的字段，格式 {"field_name": "字段说明"}
                如 {"major_name": "专业名称", "fees": "学费"}
            system_prompt: 覆盖默认系统提示词
            user_prompt: 补充提示词，追加到系统提示词后面

        Returns:
            提取的结构化数据 dict，失败返回 None
        """
        prompt = system_prompt or self.system_prompt

        if output_fields:
            prompt += "\n" + self._build_field_schema(output_fields)

        if user_prompt:
            prompt += "\n 补充信息" + user_prompt

        def crawl_tool_with_tab(url: str) -> str:
            """获取指定url页面的html源码，返回markdown"""
            return fetch_page_as_markdown_sync(self.tab, url)

        craw_tool = FunctionTool(crawl_tool_with_tab)

        agent = ChatAgent(
            prompt,
            model=self.model,
            output_language="en",
            tools=[craw_tool],
            step_timeout=60 * 5,
        )

        for attempt in range(1, self.max_retries + 1):
            try:
                with enable_no_proxy_for_aliyun(NO_PROXY_TARGETS):
                    response = agent.step(msg)
            except Exception as e:
                logger.error(f"LLMAgentScraper error on attempt {attempt}: {e}")
                response = None

            content = None
            if (
                response
                and getattr(response, "msg", None)
                and getattr(response.msg, "content", None)
            ):
                content = response.msg.content
            else:
                logger.error(
                    f"LLMAgentScraper: no response on attempt {attempt}"
                )

            json_obj = extract_json(content) if content else None

            if json_obj:
                if isinstance(json_obj, list) and len(json_obj) == 1:
                    return json_obj[0]
                if isinstance(json_obj, dict):
                    return json_obj

            logger.warning(
                f"LLMAgentScraper: failed to extract json on attempt {attempt}"
            )
            if attempt < self.max_retries:
                delay = 2 ** attempt
                logger.info(f"Retrying after {delay}s (attempt {attempt + 1}/{self.max_retries})")
                time.sleep(delay)
            else:
                logger.error("LLMAgentScraper: max retries reached, giving up")

        return None


def llm_crawl(
    tab: MixTab,
    msg: str,
    existing_data: Dict[str, Any] = None,
    output_fields: Dict[str, str] = None,
    model: str = None,
    max_retries: int = 3,
    user_prompt: str = None,
) -> Dict[str, Any]:
    """便捷函数 - 使用 LLM 爬取并合并到已有数据

    Args:
        tab: DrissionPage 的 MixTab
        msg: URL 信息描述
        existing_data: 已有的数据，LLM 提取的结果会合并进去（不覆盖已有非空值）
        output_fields: 需要提取的字段描述
        model: 模型名称，None 则从环境变量 CRAWL_MODEL 读取
        max_retries: 最大重试次数
        user_prompt: 补充提示词

    Returns:
        合并后的数据 dict
    """
    if not model:
        model = os.getenv("CRAWL_MODEL", "qwen")

    logger.info(f"Using model: {model}")

    scraper = LLMAgentScraper(tab, model=model, max_retries=max_retries)
    result = scraper.crawl(
        msg=msg,
        output_fields=output_fields,
        user_prompt=user_prompt,
    )

    result_data = (existing_data or {}).copy()
    llm_crawl_field: List[str] = []

    if not isinstance(result, dict):
        logger.error(f"LLM returned non-dict result: {type(result)}")
        if isinstance(result, list):
            if len(result) == 0:
                return result_data
            elif len(result) > 1:
                logger.error(f"LLM returned {len(result)} items, skipping")
                return result_data
            else:
                result = result[0]

    if isinstance(result, dict):
        for k, v in result.items():
            if not result_data.get(k) and v:
                result_data[k] = v
                llm_crawl_field.append(k)

    result_data["data_source_type"] = "llm_crawl"
    result_data["data_source_model"] = model
    existing_fields = result_data.get("llm_crawl_field", [])
    result_data["llm_crawl_field"] = list(
        dict.fromkeys(existing_fields + llm_crawl_field)
    )

    return result_data
