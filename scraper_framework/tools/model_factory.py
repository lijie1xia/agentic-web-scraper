"""LLM 模型工厂 - 支持多种模型后端"""

import os
from contextlib import contextmanager
from typing import Optional

from camel.models import ModelFactory
from camel.types import ModelPlatformType
from dotenv import load_dotenv

load_dotenv()

NO_PROXY_TARGETS = [
    "dashscope.aliyuncs.com",
    "aliyuncs.com",
    ".aliyuncs.com",
    "aliyun.com",
    ".aliyun.com",
]


@contextmanager
def enable_no_proxy_for_aliyun(domains=None):
    """临时添加阿里云域名到 NO_PROXY，退出时自动恢复"""
    if domains is None:
        domains = NO_PROXY_TARGETS
    backup_NO_PROXY = os.environ.get("NO_PROXY")
    backup_no_proxy = os.environ.get("no_proxy")
    try:
        cur = backup_NO_PROXY or backup_no_proxy or ""
        items = [x.strip() for x in cur.split(",") if x.strip()]
        merged = ",".join(dict.fromkeys(items + domains))
        os.environ["NO_PROXY"] = merged
        os.environ["no_proxy"] = merged
        yield
    finally:
        if backup_NO_PROXY is not None:
            os.environ["NO_PROXY"] = backup_NO_PROXY
        else:
            os.environ.pop("NO_PROXY", None)
        if backup_no_proxy is not None:
            os.environ["no_proxy"] = backup_no_proxy
        else:
            os.environ.pop("no_proxy", None)


def get_model(model_name: str = "qwen", **kwargs):
    """根据模型名称获取 CAMEL 模型实例

    支持的模型名称:
        - "qwen": 阿里云 Qwen (需要 QWEN_API_KEY)
        - "local_qwen": 本地/自定义 OpenAI 兼容模型 (需要 LOCAL_API_KEY, LOCAL_BASE_URL, LOCAL_MODEL)
        - 任意 OpenAI 兼容模型: 通过 kwargs 传入 api_key, base_url, model_type

    Args:
        model_name: 模型名称
        **kwargs: 额外参数，可覆盖 api_key, base_url, model_type, timeout 等

    Returns:
        CAMEL 模型实例
    """
    timeout = kwargs.get("timeout", 300)

    if model_name == "qwen":
        api_key = kwargs.get("api_key") or os.getenv("QWEN_API_KEY")
        if not api_key:
            raise RuntimeError("QWEN_API_KEY environment variable is not set.")
        with enable_no_proxy_for_aliyun():
            return ModelFactory.create(
                model_platform=ModelPlatformType.QWEN,
                model_type=kwargs.get("model_type", "qwen3-max"),
                api_key=api_key,
                timeout=timeout,
            )

    if model_name == "local_qwen":
        api_key = kwargs.get("api_key") or os.getenv("LOCAL_API_KEY")
        base_url = kwargs.get("base_url") or os.getenv("LOCAL_BASE_URL")
        model_type = kwargs.get("model_type") or os.getenv("LOCAL_MODEL")
        with enable_no_proxy_for_aliyun():
            return ModelFactory.create(
                model_platform=ModelPlatformType.OPENAI,
                model_type=model_type,
                url=base_url,
                api_key=api_key,
                timeout=timeout,
            )

    api_key = kwargs.get("api_key") or os.getenv("OPENAI_API_KEY")
    base_url = kwargs.get("base_url") or os.getenv("OPENAI_BASE_URL")
    return ModelFactory.create(
        model_platform=ModelPlatformType.OPENAI,
        model_type=kwargs.get("model_type", model_name),
        url=base_url,
        api_key=api_key,
        timeout=timeout,
    )
