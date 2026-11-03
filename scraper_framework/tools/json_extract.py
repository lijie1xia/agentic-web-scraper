"""从模型输出里抠 JSON ，无需浏览器或者 crawl4ai 依赖。"""

from typing import Any, Optional
import json


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
