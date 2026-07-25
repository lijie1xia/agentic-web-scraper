"""通用数据模型"""

from typing import Any, Dict, List, Optional, TypedDict, NotRequired
from pydantic import BaseModel, Field


class ScrapeResult(BaseModel):
    """单个页面爬取结果"""
    data: Any = None
    err_info: Optional[Dict[str, Any]] = None


class ErrorInfo(TypedDict):
    url: str
    err_list: List[str]
    should_retry: NotRequired[bool]
    after_retry: NotRequired[bool]


class CrawlerProgress(BaseModel):
    """爬取进度"""
    total_count: int = 0
    data: List[Dict[str, Any]] = Field(default_factory=list)
    remark: str = ""
    err_list: List[ErrorInfo] = Field(default_factory=list)


class SpiderResponse(BaseModel):
    """爬虫响应"""
    data: List[Dict[str, Any]] = Field(default_factory=list)
    failed_data: List[Dict[str, Any]] = Field(default_factory=list)
    data_path: Optional[str] = Field(default=None)
    failed_data_path: Optional[str] = Field(default=None)
    statistics_data: Optional[Dict[str, Any]] = Field(default=None)


class FieldItem(BaseModel):
    """字段提取结果项"""
    field_name: str
    value: str
    source_url: str = ""
    _remark: str = ""
