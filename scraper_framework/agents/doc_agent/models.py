"""Document Navigation 数据模型"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class Link(BaseModel):
    """页面中的关联链接"""
    text: str = Field(description="链接显示文本")
    url: str = Field(description="链接 URL (绝对路径)")


class Document(BaseModel):
    """抓取后的页面文档"""
    url: str = Field(description="页面 URL")
    title: str = Field(default="", description="页面标题")
    content: str = Field(description="页面 Markdown 正文内容")
    links: List[Link] = Field(default_factory=list, description="页面中的关联链接列表")


class ExplorationState(BaseModel):
    """探索状态 - 贯穿整个探索过程"""
    task: str = Field(description="用户任务描述")
    start_url: str = Field(description="起始 URL")
    output_fields: Dict[str, str] = Field(default_factory=dict, description="需要提取的字段及说明")
    max_depth: int = Field(default=10, description="最大探索步数")
    visited_urls: List[str] = Field(default_factory=list, description="已访问的 URL 列表")
    extracted_data: Dict[str, Any] = Field(default_factory=dict, description="已提取的结构化数据")
    history_log: List[str] = Field(default_factory=list, description="探索历史日志")
