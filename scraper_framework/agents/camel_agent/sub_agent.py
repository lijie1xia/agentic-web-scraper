"""SubAgent - 使用 CAMEL-AI ChatAgent 自主调用工具爬取并提取数据"""

import json
import time
from typing import Any, Dict, Optional, Type, Union

from camel.agents import ChatAgent
from camel.toolkits import FunctionTool
from DrissionPage.items import MixTab
from pydantic import BaseModel

from .prompts import SUB_AGENT_SYSTEM_PROMPT, build_sub_agent_prompt
from .tools import fetch_page_as_markdown, get_model, enable_no_proxy_for_aliyun, NO_PROXY_TARGETS
from ...logger import get_spider_logger

logger = get_spider_logger(__name__)


def _extract_json(text: str) -> Optional[Any]:
    """从文本中提取 JSON 对象或数组"""
    if not isinstance(text, str):
        return None
    text = text.strip()
    if not text:
        return None

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

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


class SubAgentResult(BaseModel):
    """子 Agent 结果"""
    success: bool
    url: str
    data: Optional[dict] = None
    error: Optional[str] = None


class SubAgent:
    """子 Agent - 使用 CAMEL-AI ChatAgent 自主调用工具爬取并提取数据"""

    def __init__(
        self,
        tab: MixTab,
        model_name: str = "deepseek",
        max_retries: int = 3,
        response_model: Optional[Type[BaseModel]] = None,
    ):
        self.tab = tab
        self.model_name = model_name
        self.max_retries = max_retries
        self.response_model = response_model
        self.model = get_model(model_name)
        self._setup_agent()

    def _setup_agent(self):
        """初始化 ChatAgent 并注册工具"""

        def fetch_page_tool(url: str) -> str:
            """爬取指定URL页面，返回Markdown格式内容"""
            return fetch_page_as_markdown(self.tab, url)

        tool = FunctionTool(fetch_page_tool)
        self.agent = ChatAgent(
            SUB_AGENT_SYSTEM_PROMPT,
            model=self.model,
            output_language="en",
            tools=[tool],
        )

    def _parse_response(self, response: Any) -> Optional[dict]:
        """解析 LLM 响应，优先读取结构化输出，失败时回退到 JSON 文本解析"""
        parsed = None
        content = None

        if response:
            if hasattr(response, "msg") and response.msg:
                parsed = getattr(response.msg, "parsed", None)
                content = response.msg.content
            elif hasattr(response, "msgs") and response.msgs:
                first_msg = response.msgs[0]
                parsed = getattr(first_msg, "parsed", None)
                content = first_msg.content

        if self.response_model and isinstance(parsed, self.response_model):
            return parsed.model_dump()

        if isinstance(parsed, dict):
            if self.response_model:
                try:
                    return self.response_model.model_validate(parsed).model_dump()
                except Exception:
                    pass
            return parsed

        json_obj = _extract_json(content)
        if isinstance(json_obj, dict):
            if self.response_model:
                try:
                    return self.response_model.model_validate(json_obj).model_dump()
                except Exception:
                    pass
            return json_obj

        return None

    def process(
        self,
        url: str,
        known_info: dict,
        field_descriptions: Dict[str, str],
        user_prompt: str = "",
    ) -> SubAgentResult:
        """处理单个 URL 的数据提取

        Args:
            url: 要爬取的链接
            known_info: 已知信息
            field_descriptions: 需要提取的字段及描述
            user_prompt: 用户自定义提取逻辑

        Returns:
            SubAgentResult
        """
        prompt = build_sub_agent_prompt(url, known_info, field_descriptions, user_prompt)

        for attempt in range(1, self.max_retries + 1):
            try:
                with enable_no_proxy_for_aliyun(NO_PROXY_TARGETS):
                    response = self.agent.step(prompt)
                parsed_data = self._parse_response(response)
                if parsed_data is not None:
                    logger.info(f"SubAgent successfully extracted data from {url}")
                    return SubAgentResult(success=True, url=url, data=parsed_data)
                logger.warning(
                    f"SubAgent failed to parse structured data on attempt {attempt}: {url}"
                )
            except Exception as e:
                logger.error(
                    f"SubAgent error on attempt {attempt}: {url}: {e}"
                )

            if attempt < self.max_retries:
                time.sleep(2 ** attempt)

        return SubAgentResult(success=False, url=url, error="Max retries exceeded")
