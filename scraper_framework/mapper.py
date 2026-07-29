"""LLM Mapper - 批量数据字段映射工具

通过 LLM 在参考内容中为每条数据查找对应的字段值，支持并发处理。
"""

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Union

from camel.agents import ChatAgent

from .tools.model_factory import get_model, enable_no_proxy_for_aliyun, NO_PROXY_TARGETS
from .agents.llm_agent.llm_scraper import extract_json
from .logger import get_spider_logger

logger = get_spider_logger(__name__)


def _build_prompt(
    batch: List[Dict],
    content: str,
    match_field: List[str],
    target_fields: List[str],
    id_field: str,
    instructions: str,
) -> str:
    """构造 Mapper Prompt"""
    fields_str = ", ".join(target_fields)

    return f"""
        你是智能映射助手。从参考内容中为每条数据查找对应值。

        # 数据（需要补充）
        {json.dumps(batch, ensure_ascii=False, indent=2)}

        # 参考内容
        {content}

        # 任务
        - 根据 "{' + '.join(match_field)}" 组合匹配
        - 提取字段：{fields_str}
        - 允许模糊匹配（忽略大小写、修饰词、缩写等）

        {f'# 额外说明: {instructions}' if instructions else ''}

        # 输出JSON数组（必须包含{id_field}和所有目标字段）
        [
        {{"{id_field}": "...", {", ".join([f'"{f}": "..."' for f in target_fields])}}}
        ]

        规则：
        1. 输出{len(batch)}条，顺序一致
        2. 找不到填""
        3. 数据只从参考内容中提取
        4. 必须包含 {id_field} 字段和所有目标字段 {fields_str}
        """


def _call_llm(prompt: str, model_name: str = "deepseek", retry: int = 3) -> List[Dict]:
    """调用 LLM"""
    for attempt in range(retry):
        try:
            model = get_model(model_name)
            agent = ChatAgent(prompt, model=model, output_language="en", tools=[])
            response = agent.step("请提取数据")
            result = extract_json(response.msg.content)

            if result and isinstance(result, list):
                return result

            logger.warning(f"Attempt {attempt + 1}/{retry}: parse failed")
        except Exception as e:
            logger.error(f"Attempt {attempt + 1}/{retry}: {e}")
            if attempt < retry - 1:
                time.sleep(2 ** attempt)
    return []


def llm_mapper(
    data: List[Dict],
    reference: Dict[str, Any],
    match_field: Union[str, List[str]],
    target_fields: Union[str, List[str]],
    additional_rules: str = "",
    id_field: str = "url",
    model: str = "deepseek",
    batch_size: int = 4,
    max_workers: int = 5,
    enable_async: bool = True,
) -> List[Dict]:
    """LLM 字段映射工具

    根据参考内容，通过 LLM 为每条数据查找对应的字段值。

    Args:
        data: 原始数据列表
        reference: 参考内容，格式:
            {"type": "mapping", "data": {key: value, ...}}
            {"type": "array", "data": [{...}, ...]}
            {"type": "html", "content": "<html>...</html>"}
            {"type": "text", "content": "plain text..."}
        match_field: 匹配字段名（单个或列表）
        target_fields: 要提取的目标字段（单个或列表）
        additional_rules: 额外的匹配规则说明
        id_field: 唯一标识字段名
        model: LLM 模型名称
        batch_size: 每批处理的数据量
        max_workers: 最发数
        enable_async: 是否启用并发

    Returns:
        补充后的数据列表

    Usage:
        result = llm_mapper(
            data=[{"url": "https://...", "name": "Product A"}],
            reference={"type": "mapping", "data": {"Product A": {"price": "$10"}}},
            match_field="name",
            target_fields=["price"],
            id_field="url",
        )
    """
    if isinstance(target_fields, str):
        target_fields = [target_fields]
    if isinstance(match_field, str):
        match_field = [match_field]

    if not data:
        logger.warning("No data to process")
        return data

    logger.info(
        f"Processing {len(data)} items, match: {match_field}, extract: {target_fields}"
    )

    slim_list = [
        {id_field: d.get(id_field, ""), **{f: d.get(f, "") for f in match_field}}
        for d in data
    ]

    if reference.get("type") == "mapping":
        content = json.dumps(reference.get("data", {}), ensure_ascii=False, indent=2)
    elif reference.get("type") == "array":
        content = json.dumps(reference.get("data", []), ensure_ascii=False, indent=2)
    elif reference.get("type") == "html":
        import asyncio
        from .tools.page_fetcher import html_to_markdown
        content = asyncio.run(html_to_markdown(reference.get("content", "")))
    else:
        content = reference.get("content", "")

    batches = [slim_list[i : i + batch_size] for i in range(0, len(slim_list), batch_size)]
    logger.info(f"Batches: {len(batches)}, batch_size: {batch_size}")

    all_results = []

    def process_batch(batch):
        prompt = _build_prompt(batch, content, match_field, target_fields, id_field, additional_rules)
        return _call_llm(prompt, model)

    if enable_async and len(batches) > 1:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(process_batch, b): i for i, b in enumerate(batches)}
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    result = future.result(timeout=60)
                    all_results.extend(result)
                    logger.info(f"Batch {idx + 1}/{len(batches)} done")
                except Exception as e:
                    logger.error(f"Batch {idx + 1} failed: {e}")
    else:
        for i, batch in enumerate(batches):
            result = process_batch(batch)
            all_results.extend(result)
            logger.info(f"Batch {i + 1}/{len(batches)} done")

    result_map = {r.get(id_field, ""): r for r in all_results if id_field in r}

    for item in data:
        key = item.get(id_field, "")
        crawled_fields = item.get("llm_crawl_field", [])

        if key in result_map:
            for field in target_fields:
                val = result_map[key].get(field, "")
                item[field] = val
                if val and field not in crawled_fields:
                    crawled_fields.append(field)

        item["llm_crawl_field"] = crawled_fields

    success = {f: sum(1 for d in data if d.get(f)) for f in target_fields}
    for field, count in success.items():
        pct = count / len(data) * 100 if data else 0
        logger.info(f"{field}: {count}/{len(data)} ({pct:.1f}%)")

    return data
