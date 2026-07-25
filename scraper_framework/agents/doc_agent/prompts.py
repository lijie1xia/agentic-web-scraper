"""DocAgent 提示词模板 - Tool Calling 驱动"""

import json
from typing import Dict, List

from .models import ExplorationState


NAVIGATOR_SYSTEM_PROMPT = """你是一个智能网页探索 Agent。你的任务是根据用户给定的起始 URL 和任务目标，自主探索网站，找到包含目标信息的页面，并提取结构化数据。

## 你的能力

你可以调用 fetch_document 工具获取任意 URL 的页面内容。工具会返回该页面的 Markdown 正文和页面中的所有关联链接。

## 工作方式

1. 首先调用 fetch_document 获取起始 URL 的页面内容
2. 阅读返回的 Markdown 内容和链接列表
3. 根据任务目标，判断：
   - 当前页面是否包含目标信息 → 提取字段
   - 当前页面是否有相关链接值得继续探索 → 调用 fetch_document 获取新页面
   - 所有信息已收集完毕 → 输出最终结果
4. 重复以上过程，直到任务完成

## 重要规则

1. 你必须先调用 fetch_document 获取页面内容，不能凭空杜撰
2. 从返回的链接列表中，基于链接文本和当前页面语义选择最相关的链接
3. 不要重复访问已经出现在对话历史中的 URL
4. 如果当前页面已包含足够的目标信息，直接提取，不需要继续探索
5. 所有提取的值必须是字符串类型
6. 如果某个字段在当前页面找不到，不要编造内容
7. 每次调用 fetch_document 后，仔细阅读返回的内容再决定下一步

## 输出格式

当你认为任务已完成或无法继续时，输出以下 JSON 格式：

```json
{
    "extracted_data": {"字段名": "提取值", ...},
    "is_complete": true,
    "summary": "简要说明探索过程和结果"
}
```

- extracted_data: 所有已提取的字段（字符串值）
- is_complete: true 表示任务完成，false 表示无法继续但有部分结果
- summary: 探索过程简述
"""


def build_initial_prompt(
    task: str,
    start_url: str,
    output_fields: Dict[str, str],
    user_prompt: str = "",
) -> str:
    """构建初始用户消息

    Args:
        task: 用户任务描述
        start_url: 起始 URL
        output_fields: 需要提取的字段及说明
        user_prompt: 用户补充说明

    Returns:
        初始用户消息文本
    """
    fields_desc = []
    for name, desc in output_fields.items():
        fields_desc.append(f"  - {name}: {desc}")
    fields_text = "\n".join(fields_desc) if fields_desc else "  (由 Agent 根据任务自行判断)"

    prompt = f"""## 任务

{task}

## 起始 URL

{start_url}

## 需要提取的字段

{fields_text}

## 开始

请先调用 fetch_document 工具获取起始 URL 的页面内容，然后根据页面内容决定下一步操作。

工具调用示例：
- fetch_document(url="{start_url}")
"""

    if user_prompt:
        prompt += f"\n## 补充说明\n\n{user_prompt}\n"

    return prompt


def build_step_context(
    state: ExplorationState,
) -> str:
    """构建步骤间的上下文信息（注入到下一轮 prompt 中）

    Args:
        state: 当前探索状态

    Returns:
        上下文文本
    """
    visited_text = "\n".join(f"  - {url}" for url in state.visited_urls) if state.visited_urls else "  (无)"

    extracted_text = json.dumps(state.extracted_data, ensure_ascii=False, indent=2) if state.extracted_data else "  (暂无)"

    fields_desc = []
    for name, desc in state.output_fields.items():
        val = state.extracted_data.get(name, "")
        status = f"✓ 已提取: {val[:80]}" if val else "✗ 待提取"
        fields_desc.append(f"  - {name} ({desc}): {status}")
    fields_text = "\n".join(fields_desc)

    remaining = state.max_depth - len(state.visited_urls)

    context = f"""---

## 探索上下文（供参考，不需要你回复这部分）

### 已访问的 URL（请勿重复访问）
{visited_text}

### 已提取的字段
{fields_text}

### 当前已提取的数据
{extracted_text}

### 剩余探索步数
{remaining} 步

---
"""
    return context
