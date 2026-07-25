"""DocAgent - 文档驱动的 Agent 自主网页探索 (Tool Calling 模式)

核心流程:
    用户任务 + 起始 URL
    → Agent 调用 fetch_document(url) 获取页面
    → Agent 阅读返回的 Markdown + 链接列表
    → Agent 自主决定: 继续调用 fetch_document / 输出提取结果
    → 循环直到 Agent 输出最终结果或达到最大步数

职责分层:
    Agent (step 内部): 选择下一个 URL、判断何时停止、提取字段
    系统 (Python 外层): 最大 step 次数、循环检测、已访问 URL 去重
    工具 (fetch_document): 已访问 URL 检查（返回提示而非重新抓取）

与现有 SubAgent / LLMAgentScraper 的架构一致性:
    - 均使用 CAMEL-AI ChatAgent + FunctionTool
    - Agent 在 step() 内部自主调用工具（一次 step 可包含多次工具调用）
    - Python 外层只做状态管理和安全边界控制
"""

import json
import time
from typing import Any, Callable, Dict, List, Optional, Set

from camel.agents import ChatAgent
from camel.toolkits import FunctionTool
from DrissionPage.items import MixTab

from .models import Document, ExplorationState, Link
from .document_fetcher import DocumentFetcher
from .page_source import PageSource
from .prompts import NAVIGATOR_SYSTEM_PROMPT, build_initial_prompt, build_step_context
from ...tools.model_factory import get_model, enable_no_proxy_for_aliyun, NO_PROXY_TARGETS
from ...agents.llm_agent.llm_scraper import extract_json
from ...models import ScrapeResult
from ...logger import get_spider_logger

logger = get_spider_logger(__name__)


class DocAgent:
    """文档驱动的 Agent 自主网页探索 (Tool Calling 模式)

    Agent 拥有 fetch_document 工具，自主决定调用时机和目标 URL。
    一次 step() 内 Agent 可连续调用多次 fetch_document。

    职责分层:
        Agent (step 内部): 选择 URL、判断停止、提取字段
        系统 (Python 外层): max_depth 限制、循环检测
        工具 (fetch_document): 已访问 URL 去重

    Usage:
        tab = Chromium().new_tab()
        agent = DocAgent(tab)
        result = agent.run(
            start_url="https://example.com",
            task="找到所有 Data Science 相关硕士项目，提取申请要求",
            output_fields={
                "program_name": "项目名称",
                "entry_requirements": "申请要求",
            },
        )
    """

    def __init__(
        self,
        tab: MixTab = None,
        page_source: Optional[PageSource] = None,
        model: str = "qwen",
        max_depth: int = 10,
        max_retries: int = 3,
    ):
        """初始化 DocAgent

        Args:
            tab: DrissionPage 的 MixTab 实例 (page_source 为 None 时使用)
            page_source: 自定义 PageSource 实现 (可选，优先于 tab)
            model: LLM 模型名称
            max_depth: 最大 step() 调用次数（每次 step 内 Agent 可多次调用工具）
            max_retries: 每步最大重试次数
        """
        self.model_name = model
        self.max_depth = max_depth
        self.max_retries = max_retries
        self.model = get_model(model)

        if page_source is not None:
            self.fetcher = DocumentFetcher(page_source=page_source)
        elif tab is not None:
            self.fetcher = DocumentFetcher(tab=tab)
        else:
            raise ValueError("Either tab or page_source must be provided")

    def _build_tools(self) -> list:
        """构建 CAMEL-AI FunctionTool 列表

        fetch_document 工具内部维护已访问 URL 集合，
        已访问过的 URL 返回提示信息而非重新抓取（工具层去重）。
        """

        visited_urls: Set[str] = set()

        def fetch_document(url: str) -> str:
            """获取指定 URL 的页面文档，返回 Markdown 正文和关联链接。

            当你想了解某个页面的内容时，调用此工具。
            工具会返回页面的 Markdown 文本和页面中发现的所有链接，
            你可以基于返回内容决定下一步操作。

            如果该 URL 已经被访问过，工具会返回提示信息，不会重复抓取。（260726:其实应该是访问过的存入缓存吧）

            Args:
                url: 要获取的页面 URL

            Returns:
                JSON 字符串，包含:
                - url: 页面 URL
                - title: 页面标题
                - content: Markdown 正文内容
                - links: 关联链接列表 [{"text": "链接文本", "url": "绝对URL"}, ...]
            """
            # 已访问 URL 去重（工具层负责）
            if url in visited_urls:
                return json.dumps({
                    "url": url,
                    "title": "",
                    "content": f"[Already visited] This URL has been visited before. Please choose a different link from the links you've seen.",
                    "links": [],
                    "already_visited": True,
                })

            visited_urls.add(url)

            try:
                doc = self.fetcher.fetch(url)
                return json.dumps(
                    {
                        "url": doc.url,
                        "title": doc.title,
                        "content": doc.content,
                        "links": [{"text": link.text, "url": link.url} for link in doc.links],
                    },
                    ensure_ascii=False,
                )
            except Exception as e:
                logger.error(f"fetch_document failed for {url}: {e}")
                return json.dumps({"error": str(e), "url": url, "content": "", "links": []})

        tool = FunctionTool(fetch_document)
        return [tool], visited_urls

    def _is_final_output(self, text: str) -> bool:
        """判断 Agent 输出是否为最终结果（包含 extracted_data 的 JSON）"""
        if not text:
            return False
        json_obj = extract_json(text)
        if isinstance(json_obj, dict) and "extracted_data" in json_obj:
            return True
        return False

    def _parse_final_output(self, text: str) -> Dict[str, Any]:
        """解析 Agent 的最终输出"""
        json_obj = extract_json(text)
        if isinstance(json_obj, list) and len(json_obj) > 0:
            json_obj = json_obj[0]
        if isinstance(json_obj, dict):
            return json_obj.get("extracted_data", {})
        return {}

    def _extract_tool_calls(self, response) -> List[Dict[str, str]]:
        """从 response 中提取工具调用记录"""
        calls = []
        if not (hasattr(response, "tool_calls") and response.tool_calls):
            return calls
        for tc in response.tool_calls:
            if isinstance(tc, dict):
                name = tc.get("name", "")
                args = tc.get("args", {})
            else:
                name = getattr(tc, "name", "")
                args = getattr(tc, "args", {})
            if name == "fetch_document":
                url = args.get("url", "") if isinstance(args, dict) else ""
                calls.append({"tool": name, "url": url})
        return calls

    def _extract_agent_text(self, response) -> str:
        """从 response 中提取 Agent 文本输出"""
        if hasattr(response, "msg") and response.msg:
            return response.msg.content or ""
        if hasattr(response, "msgs") and response.msgs:
            return response.msgs[0].content or ""
        return ""

    def run(
        self,
        start_url: str,
        task: str,
        output_fields: Dict[str, str] = None,
        user_prompt: str = "",
        on_step: Optional[Callable[[ExplorationState, int], None]] = None,
    ) -> ScrapeResult:
        """执行文档驱动的探索任务

        职责分层:
            Agent (step 内部): 自主调用 fetch_document，选择 URL，判断停止
            系统 (本方法): max_depth 限制、循环检测、状态注入

        一次 step() 内 Agent 可连续调用多次 fetch_document。
        如果某步 Agent 没有调用任何工具，说明它已无法继续，终止循环。

        Args:
            start_url: 起始 URL
            task: 任务描述
            output_fields: 需要提取的字段及说明
            user_prompt: 用户补充说明
            on_step: 每步回调

        Returns:
            ScrapeResult
        """
        output_fields = output_fields or {}

        state = ExplorationState(
            task=task,
            start_url=start_url,
            output_fields=output_fields,
            max_depth=self.max_depth,
        )

        logger.info(
            f"DocAgent: start, url={start_url}, task={task[:80]}, "
            f"max_depth={self.max_depth}, model={self.model_name}"
        )

        tools, visited_urls = self._build_tools()
        agent = ChatAgent(
            NAVIGATOR_SYSTEM_PROMPT,
            model=self.model,
            output_language="en",
            tools=tools,
            step_timeout=60 * 5,
        )

        current_prompt = build_initial_prompt(task, start_url, output_fields, user_prompt)
        final_data = {}
        consecutive_no_tool_calls = 0

        for step in range(1, self.max_depth + 1):
            logger.info(f"DocAgent: step {step}/{self.max_depth}")

            response = None
            for attempt in range(1, self.max_retries + 1):
                try:
                    with enable_no_proxy_for_aliyun(NO_PROXY_TARGETS):
                        response = agent.step(current_prompt)
                    break
                except Exception as e:
                    logger.error(f"DocAgent: step failed (attempt {attempt}): {e}")
                    if attempt < self.max_retries:
                        time.sleep(2 ** attempt)

            if response is None:
                state.history_log.append(f"Step {step}: LLM step failed")
                logger.error("DocAgent: LLM step failed")
                break

            agent_text = self._extract_agent_text(response)
            tool_calls = self._extract_tool_calls(response)

            # 记录本轮工具调用
            new_urls_this_step = []
            for tc in tool_calls:
                url = tc["url"]
                if url and url not in state.visited_urls:
                    state.visited_urls.append(url)
                    new_urls_this_step.append(url)
                    state.history_log.append(f"Step {step}: fetch_document({url})")

            logger.info(
                f"DocAgent: step {step}, tool_calls={len(tool_calls)}, "
                f"new_urls={len(new_urls_this_step)}, response_len={len(agent_text)}"
            )

            # 循环检测: 如果 Agent 没有调用任何工具，说明它已无法继续
            if not tool_calls:
                consecutive_no_tool_calls += 1
                if consecutive_no_tool_calls >= 2:
                    state.history_log.append(f"Step {step}: No tool calls for 2 consecutive steps, stopping")
                    logger.warning("DocAgent: no tool calls for 2 consecutive steps")
                    break
            else:
                consecutive_no_tool_calls = 0

            # 判断 Agent 是否输出了最终结果
            if self._is_final_output(agent_text):
                extracted = self._parse_final_output(agent_text)
                final_data.update(extracted)
                state.history_log.append(f"Step {step}: Final output produced")
                logger.info(f"DocAgent: final output at step {step}")
                break

            # 注入上下文，继续下一轮
            context = build_step_context(state)
            current_prompt = context + "\n\n请继续探索，或在信息充足时输出最终结果。"

            if on_step:
                on_step(state, step)

        # 兜底: 从最后一轮响应中尝试提取
        if not final_data and agent_text:
            extracted = self._parse_final_output(agent_text)
            if extracted:
                final_data.update(extracted)

        final_data["data_source_type"] = "doc_agent"
        final_data["data_source_model"] = self.model_name
        final_data["exploration_log"] = state.history_log
        final_data["visited_urls"] = state.visited_urls

        logger.info(
            f"DocAgent: done, visited={len(state.visited_urls)}, "
            f"fields={list(final_data.keys())}"
        )

        return ScrapeResult(data=final_data)
