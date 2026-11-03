"""默认求职者技能画像（模块2）。

可直接 import DEFAULT_SKILL_PROFILE，或用 load_skill_profile() 从 JSON 覆盖。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Union

DEFAULT_SKILL_PROFILE: Dict[str, Any] = {
    "tech_stack": [
        "Python",
        "Java",
        "Spring Boot",
        "Flask",
        "Docker",
        "Nginx",
        "Git",
        "Linux",
        "MySQL",
        "Redis",
        "LangChain",
        "RAG",
        "Agent",
        "AI Agent",
        "MCP",
        "Prompt Engineering",
        "Function Calling",
        "DrissionPage",
        "XPath",
        "pdfplumber",
        "RESTful API",
        "RxJava",
        "SSE",
        "Hugging Face",
        "向量检索",
    ],
    "education": "本科在读",
    "graduate_year": 2027,
    "experience_years": 0,
    "preferred_work_mode": [
        "remote",
        "hybrid",
        "onsite",
    ],
    "deal_breakers": {
        "min_education": "本科",
        "max_experience_required": 1,
    },
}


def default_skill_profile_path() -> Path:
    """个人画像优先。未放置 data/skill_profile.json 时使用可提交的示例画像。"""
    data_dir = Path(__file__).resolve().parents[2] / "data"
    personal = data_dir / "skill_profile.json"
    if personal.is_file():
        return personal
    return data_dir / "skill_profile.demo.json"


def load_skill_profile(path: Union[str, Path, None] = None) -> Dict[str, Any]:
    """加载 skill profile。

    path 为 None 时返回 DEFAULT_SKILL_PROFILE 的浅拷贝（嵌套 list/dict 另拷）。
    path 指向 JSON 时以其内容为准（需为对象）。
    """
    if path is None:
        return json.loads(json.dumps(DEFAULT_SKILL_PROFILE))

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"skill_profile JSON 必须是对象: {path}")
    return data


__all__ = [
    "DEFAULT_SKILL_PROFILE",
    "default_skill_profile_path",
    "load_skill_profile",
]
