"""CamelScraperAgent - CAMEL-AI 多 URL 爬取主调度器

接收 msg 文本（含多个 URL 及描述），先用解析 Agent 提取 URL 列表，
按顺序分发给 SubAgent 处理，最后用 MergeAgent 合并所有结果。
"""

import json
from typing import Any, Dict, List, Literal, Optional, Type

from camel.agents import ChatAgent
from DrissionPage.items import MixTab
from pydantic import BaseModel, Field

from .prompts import MERGE_AGENT_SYSTEM_PROMPT, build_merge_agent_prompt
from .sub_agent import SubAgent
from .tools import get_model, enable_no_proxy_for_aliyun, NO_PROXY_TARGETS
from ...logger import get_spider_logger

logger = get_spider_logger(__name__)


PARSE_MSG_PROMPT = """
角色：你是一个文本解析专家

职责：从用户输入的文本中提取所有URL及其对应的描述信息

输入：用户提供的包含多个链接的文本，格式如：
"信息A：https://xxx.com/page1, 信息B：https://xxx.com/page2"

输出要求：
- 每个元素包含 url 和 content 两个字段
- content 为该链接的描述/用途说明
- 只提取用户输入中明确出现的链接
"""


class ParsedUrlItem(BaseModel):
    url: str
    content: str


class ParsedUrlList(BaseModel):
    items: List[ParsedUrlItem]


class CamelScraperConfig(BaseModel):
    """爬取配置"""
    model: str = "deepseek"
    max_retries: int = 3
    max_workers: int = 3


class CamelScraperAgent:
    """CAMEL-AI 多 URL 爬取主调度器

    接收 msg 文本（含多个 URL 及描述），先用解析 Agent 提取 URL 列表，
    按顺序分发给 SubAgent 处理，最后用 MergeAgent 合并所有结果。

    Usage:
        tab = Chromium().new_tab()
        agent = CamelScraperAgent(tab)
        result = agent.run(
            msg="页面A：https://example.com/page1, 页面B：https://example.com/page2",
            field_descriptions={"field1": "描述1", "field2": "描述2"},
        )
    """

    def __init__(self, tab: MixTab, config: CamelScraperConfig = None):
        self.tab = tab
        self.config = config or CamelScraperConfig()

    def _parse_msg(self, msg: str, model_name: str) -> List[dict]:
        """使用 LLM 解析 msg 文本，提取 URL 和描述"""
        model = get_model(model_name)
        agent = ChatAgent(
            PARSE_MSG_PROMPT,
            model=model,
            output_language="en",
        )

        with enable_no_proxy_for_aliyun(NO_PROXY_TARGETS):
            response = agent.step(msg, response_format=ParsedUrlList)

        if response:
            if (
                hasattr(response, "msg")
                and response.msg
                and getattr(response.msg, "parsed", None)
            ):
                parsed = response.msg.parsed
                if isinstance(parsed, ParsedUrlList):
                    return [item.model_dump() for item in parsed.items]
                if isinstance(parsed, dict) and "items" in parsed:
                    return parsed["items"]
            elif hasattr(response, "msgs") and response.msgs:
                first_msg = response.msgs[0]
                parsed = getattr(first_msg, "parsed", None)
                if isinstance(parsed, ParsedUrlList):
                    return [item.model_dump() for item in parsed.items]
                if isinstance(parsed, dict) and "items" in parsed:
                    return parsed["items"]

        logger.error("Failed to parse msg: no structured content")
        return []

    def _merge_results(
        self,
        base_info: dict,
        parsed_urls: list,
        sub_agent_results: list,
        field_descriptions: dict,
        user_prompt: str,
        model_name: str,
    ) -> Optional[dict]:
        """使用 MergeAgent 合并所有结果"""
        model = get_model(model_name)
        agent = ChatAgent(
            MERGE_AGENT_SYSTEM_PROMPT,
            model=model,
            output_language="en",
        )

        prompt = build_merge_agent_prompt(
            base_info=base_info,
            parsed_urls=parsed_urls,
            sub_agent_results=sub_agent_results,
            field_descriptions=field_descriptions,
            user_prompt=user_prompt,
        )

        with enable_no_proxy_for_aliyun(NO_PROXY_TARGETS):
            response = agent.step(prompt)

        content = None
        if response:
            if hasattr(response, "msg") and response.msg:
                content = response.msg.content
            elif hasattr(response, "msgs") and response.msgs:
                content = response.msgs[0].content

        if content:
            try:
                return json.loads(content)
            except (json.JSONDecodeError, TypeError):
                pass

        logger.error("MergeAgent failed to produce valid result")
        return None

    def run(
        self,
        msg: str,
        base_info: Dict[str, str] = None,
        field_descriptions: Dict[str, str] = None,
        user_prompt: str = "",
        model: str = None,
    ) -> dict:
        """执行爬取任务

        Args:
            msg: 传给 LLM 的链接信息，如 "页面A：https://xxx, 页面B：https://yyy"
            base_info: 已知的基础信息
            field_descriptions: 需要提取的字段及描述，如 {"field_name": "字段说明"}
            user_prompt: 用户自定义的字段提取和合并逻辑
            model: 覆盖 config 中的模型设置

        Returns:
            dict - 合并后的最终结构化数据
        """
        if not msg:
            logger.warning("No msg provided")
            return {}

        base = dict(base_info or {})
        field_descs = field_descriptions or {}
        effective_model = model or self.config.model

        parsed_urls = self._parse_msg(msg, effective_model)
        if not parsed_urls:
            logger.warning("No URLs parsed from msg")
            return {}

        logger.info(f"Parsed {len(parsed_urls)} URLs: {parsed_urls}")

        sub_agent = SubAgent(
            self.tab,
            model_name=effective_model,
            max_retries=self.config.max_retries,
        )

        accumulated_info = dict(base)
        sub_agent_results: List[dict] = []

        for index, item in enumerate(parsed_urls):
            url = item["url"]
            content_desc = item.get("content", "")
            enhanced_prompt = user_prompt
            if content_desc:
                enhanced_prompt = (
                    f"当前链接用途：{content_desc}\n补充逻辑：\n{user_prompt}"
                    if user_prompt
                    else f"当前链接用途：{content_desc}"
                )

            sub_result = sub_agent.process(
                url=url,
                known_info=accumulated_info,
                field_descriptions=field_descs,
                user_prompt=enhanced_prompt,
            )

            if sub_result.success and sub_result.data is not None:
                extracted = sub_result.data
                accumulated_info = {**accumulated_info, **extracted}
                sub_agent_results.append({"url": url, "data": extracted})
                logger.info(
                    f"SubAgent {index + 1}/{len(parsed_urls)} success from {url}"
                )
            else:
                logger.error(
                    f"SubAgent {index + 1}/{len(parsed_urls)} failed from {url}: {sub_result.error}"
                )
                sub_agent_results.append(
                    {"url": url, "data": {}, "error": sub_result.error}
                )

        if not sub_agent_results:
            return {
                **base,
                "data_source_type": "camel_scraper",
                "data_source_model": effective_model,
            }

        merged = self._merge_results(
            base_info=base,
            parsed_urls=parsed_urls,
            sub_agent_results=sub_agent_results,
            field_descriptions=field_descs,
            user_prompt=user_prompt,
            model_name=effective_model,
        )

        if merged:
            result = {
                **merged,
                "data_source_type": "camel_scraper",
                "data_source_model": effective_model,
            }
            logger.info("MergeAgent completed successfully")
            return result

        logger.warning("Merge failed, returning accumulated info")
        return {
            **accumulated_info,
            "data_source_type": "camel_scraper",
            "data_source_model": effective_model,
        }
