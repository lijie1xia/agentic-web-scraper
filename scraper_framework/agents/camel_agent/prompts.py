"""CAMEL Agent 提示词模板"""

import json
from typing import Dict, List


SUB_AGENT_SYSTEM_PROMPT = """
角色：你是一个资深的网页数据爬虫专家

职责：根据已知的信息和提供的链接，使用爬虫工具获取页面内容，从中提取结构化的信息

处理流程：
1. 【必须】首先调用 fetch_page_as_markdown 工具爬取用户提供的链接，获取页面内容
2. 仔细阅读工具返回的内容，结合已知信息，提取所有相关字段
3. 提取过程中要严格保证所有的信息必须是从工具返回的内容中获取的，如果没有获取到则空着，杜绝自我杜撰
4. 如果某个字段在页面中找不到，返回空字符串 ""
5. 所有返回值必须是字符串类型

重要提醒：
- 必须先调用工具获取页面内容，不能凭空杜撰
- 工具调用后会返回页面内容，基于该内容提取字段

输出要求：
- 严格使用JSON格式输出，以 { 开头，以 } 结尾
- 不要输出数组，不要使用代码块，不要输出JSON以外的内容
"""


MERGE_AGENT_SYSTEM_PROMPT = """
角色：你是一个数据融合专家

职责：从多个子Agent的提取结果中，选择最合适的值合并成最终的完整信息

处理原则：
1. 优先选择更完整、更具体的信息
2. 对于同一字段，如果多个来源有冲突，选择最权威的来源
3. 如果某个字段所有来源都为空，返回空字符串
4. 所有返回值必须是字符串类型

重要：必须同时输出 llm_crawl_field 字段，记录每个URL提供了哪些有效字段。
格式：llm_crawl_field = [{"source_url": "url1", "field": ["field1", "field2"]}, ...]

输出要求：
- 严格按照指定的模型结构输出
- 只输出一个JSON对象，不要输出数组
- llm_crawl_field 字段必须包含，记录每个来源URL对应的字段列表
"""


def build_sub_agent_prompt(
    url: str,
    known_info: dict,
    field_descriptions: dict,
    user_prompt: str = "",
) -> str:
    """构建 SubAgent 的用户消息

    Args:
        url: 要爬取的链接
        known_info: 已知的信息
        field_descriptions: 字段名称及描述
        user_prompt: 用户自定义的提取逻辑提示词
    """
    known_parts = []
    for key, value in known_info.items():
        if value and isinstance(value, str) and value.strip():
            truncated = value[:200] if len(value) > 200 else value
            known_parts.append(f"  {key}: {truncated}")
    known_summary = "\n".join(known_parts) if known_parts else "No known info"

    fields_json = json.dumps(field_descriptions, ensure_ascii=False, indent=2)

    prompt = f"""请从以下链接中提取信息：

**目标链接：** {url}

**当前已知的信息：**
{known_summary}

**需要提取的字段及说明：**
{fields_json}

**操作步骤：**
1. 首先必须调用 fetch_page_as_markdown 工具，传入参数 url="{url}"
2. 等待工具返回页面内容
3. 基于工具返回的内容提取上述字段
4. 以JSON格式输出提取结果
"""

    if user_prompt:
        prompt += f"\n**补充提取逻辑：**\n{user_prompt}\n"

    return prompt


def build_merge_agent_prompt(
    base_info: dict,
    parsed_urls: list,
    sub_agent_results: list,
    field_descriptions: dict,
    user_prompt: str = "",
) -> str:
    """构建 MergeAgent 的用户消息

    Args:
        base_info: 初始已知信息
        parsed_urls: 解析出的URL列表
        sub_agent_results: 各子Agent的提取结果列表
        field_descriptions: 字段名称及描述
        user_prompt: 用户自定义的合并逻辑提示词
    """
    base_info_json = json.dumps(base_info or {}, ensure_ascii=False, indent=2)

    urls_desc = []
    for item in parsed_urls:
        url = item.get("url", "")
        content = item.get("content", "")
        urls_desc.append(f"  - {url}: {content}")
    urls_summary = "\n".join(urls_desc) if urls_desc else "None"

    results_summary = []
    for i, result in enumerate(sub_agent_results):
        url = result.get("url", "unknown")
        data = result.get("data", {})
        data_json = json.dumps(data, ensure_ascii=False, indent=2)
        results_summary.append(f"[Source {i+1}] {url}\n{data_json}")

    fields_json = json.dumps(field_descriptions, ensure_ascii=False, indent=2)

    prompt = f"""
请将以下信息合并成一个完整的数据：

**初始已知信息：**
{base_info_json}

**URL列表及用途：**
{urls_summary}

**各子Agent提取结果：**
{chr(10).join(results_summary) if results_summary else "None"}

**需要输出的字段及说明：**
{fields_json}

**特别注意：**
必须额外输出一个 llm_crawl_field 字段，记录每个URL提供了哪些有效的字段值。
格式示例：
llm_crawl_field = [
  {{"source_url": "https://xxx.com/page1", "field": ["field1", "field2"]}},
  {{"source_url": "https://xxx.com/page2", "field": ["field3"]}}
]
只记录最终采用且非空的字段，不记录空字符串字段。
"""

    if user_prompt:
        prompt += f"\n**补充合并逻辑：**\n{user_prompt}\n"

    prompt += "\n请根据以上信息，选择最合适的值合并成最终结果，并务必包含 llm_crawl_field 字段。"

    return prompt
