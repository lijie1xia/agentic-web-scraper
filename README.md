# Scraper Framework

通用的 LLM Agent 网页结构化采集框架。基于 CAMEL-AI + DrissionPage/Playwright + crawl4ai，提供两种核心爬取模式和多种工具组件，可快速复用到任意网页采集项目。

## 核心特性

- **LLM Crawl 模式**: 用户提供 URL，LLM Agent 自动爬取页面并提取结构化数据
- **Agent Crawl 模式 (camel_scraper)**: 多 URL 分发 + 子 Agent 并行提取 + 合并 Agent 整合
- **LLM Mapper**: 批量字段映射，通过 LLM 从参考内容中匹配数据
- **PDF 视觉解析**: 使用视觉大模型从 PDF 图片中提取信息
- **BaseSpider 基类**: 浏览器管理、多线程爬取、重试、数据保存

## 安装

**不要直接 `pip install -r requirements.txt`。**  
新版 pip 的依赖解析器会因为 `camel-ai`（要求 `psutil<6`）和 `crawl4ai`（要求 `psutil>=6.1.1`）声明冲突而报 `ResolutionImpossible`。按下面步骤安装即可绕过。

### 1. 创建并激活虚拟环境

```bash
python -m venv .venv

# Windows PowerShell
.\.venv\Scripts\Activate.ps1

# macOS / Linux
# source .venv/bin/activate
```

### 2. 安装 Python 依赖（推荐方式）

```bash
python -m pip install -U pip

# 必须加 legacy-resolver：否则会因 camel-ai / crawl4ai 的 psutil 区间冲突直接失败
python -m pip install -r requirements.txt --use-deprecated=legacy-resolver
```

装完后强制钉到实测可用的组合（防止解析过程中被拉到 `mcp 2.x` 或 `psutil 7.x`）：

```bash
python -m pip install "mcp>=1.3.0,<2" "psutil>=6.1.1,<7"
```

冒烟检查：

```bash
python -c "from camel.agents import ChatAgent; from mcp.server import FastMCP; print('deps ok')"
```

### 为什么不能裸装？

| 包 | 约束 | 说明 |
|---|---|---|
| `mcp` | `>=1.3.0,<2` | **硬冲突**：`camel-ai` 仍 import `FastMCP`；装到 `mcp 2.x` 会直接 `ImportError` |
| `psutil` | `>=6.1.1,<7` | **软冲突**：`crawl4ai` 要 `>=6.1.1`，`camel-ai` 元数据写 `<6`；`6.1.x` 两边实测都能 import |
| `pydantic` | `<=2.12.0` | 与 `camel-ai` 声明范围对齐 |

`pip check` 仍可能提示：

```text
camel-ai ... requires psutil<6, ..., but you have psutil 6.1.x
```

可忽略。不要为了消警告去装 `psutil 5.x` 或 `7.x`。

### 3. 安装浏览器依赖

```bash
# Playwright（crawl4ai 会用到）
python -m playwright install chromium

# DrissionPage（首次会拉起 Chrome）
python -c "from DrissionPage import Chromium; Chromium()"
```

### 4. 配置环境变量

```bash
# Windows PowerShell
Copy-Item .env.demo .env

# macOS / Linux
# cp .env.demo .env
```

最少配置：

```env
DEEPSEEK_API_KEY=sk-xxx
CRAWL_MODEL=deepseek
```

### 5. 若已装坏，快速修复

```bash
# mcp 2.x 导致 FastMCP ImportError 时
python -m pip install "mcp>=1.3.0,<2"

# psutil 版本不对时
python -m pip install "psutil>=6.1.1,<7"
```

## 快速开始

### 1. LLM Crawl - 最简单的爬取方式

提供 URL，让 LLM 自动爬取并提取结构化数据:

```python
from DrissionPage import Chromium
from scraper_framework.agents.llm_agent import LLMAgentScraper

# 创建浏览器和 Tab
tab = Chromium().new_tab()

# 创建爬取器
scraper = LLMAgentScraper(tab, model="deepseek")

# 爬取 - 提供 URL 和要提取的字段
result = scraper.crawl(
    msg="产品页面：https://example.com/product/123",
    output_fields={
        "product_name": "产品名称",
        "price": "价格",
        "description": "产品描述",
    },
)

print(result)
# {"product_name": "...", "price": "...", "description": "..."}
```

### 2. LLM Crawl 便捷函数 - 自动合并数据

```python
from DrissionPage import Chromium
from scraper_framework.agents.llm_agent import llm_crawl

tab = Chromium().new_tab()

# 已有数据
existing_data = {"url": "https://example.com/page", "name": "已知名称"}

# LLM 爬取并合并（不覆盖已有非空值）
result = llm_crawl(
    tab=tab,
    msg="页面内容：https://example.com/page",
    existing_data=existing_data,
    output_fields={"name": "名称", "price": "价格", "category": "分类"},
    model="deepseek",
)

print(result)
# {"url": "...", "name": "已知名称", "price": "...", "category": "..."}
```

### 3. Agent Crawl - 多 URL 分发爬取

适用于需要从多个不同页面提取信息并合并的场景:

```python
from DrissionPage import Chromium
from scraper_framework.agents.camel_agent import CamelScraperAgent, CamelScraperConfig

tab = Chromium().new_tab()

config = CamelScraperConfig(model="deepseek", max_retries=3)
agent = CamelScraperAgent(tab, config)

result = agent.run(
    msg="""
    产品页面：https://example.com/product/123,
    价格页面：https://example.com/product/123/pricing,
    评价页面：https://example.com/product/123/reviews
    """,
    field_descriptions={
        "product_name": "产品名称",
        "price": "价格",
        "rating": "评分",
        "reviews": "用户评价摘要",
    },
    user_prompt="优先从产品页面提取基本信息，价格从价格页面提取",
)

print(result)
```

### 4. LLM Mapper - 批量字段映射

从参考内容中为批量数据匹配字段值:

```python
from scraper_framework.mapper import llm_mapper

# 待补充的数据
data = [
    {"id": "1", "product_name": "iPhone 15"},
    {"id": "2", "product_name": "Samsung Galaxy S24"},
]

# 参考内容 - 映射关系
reference = {
    "type": "mapping",
    "data": {
        "iPhone 15": {"price": "$799", "brand": "Apple"},
        "Samsung Galaxy S24": {"price": "$899", "brand": "Samsung"},
    }
}

result = llm_mapper(
    data=data,
    reference=reference,
    match_field="product_name",
    target_fields=["price", "brand"],
    id_field="id",
)

print(result)
# [
#   {"id": "1", "product_name": "iPhone 15", "price": "$799", "brand": "Apple"},
#   {"id": "2", "product_name": "Samsung Galaxy S24", "price": "$899", "brand": "Samsung"},
# ]
```

### 5. PDF 视觉解析

从 PDF 文件中提取结构化数据:

```python
from scraper_framework.scrapers import pdf_crawl

existing_data = {"url": "https://example.com/doc.pdf"}

result = pdf_crawl(
    pdf_urls=["https://example.com/doc.pdf"],
    existing_data=existing_data,
    pdf_crawl_field={
        "title": "文档标题",
        "summary": "文档摘要",
        "key_findings": "关键发现",
    },
    target_keywords=["summary", "conclusion"],  # 可选：筛选 PDF 页面
)

print(result)
```

### 6. 自定义爬虫 (继承 BaseSpider)

```python
from scraper_framework.spider import BaseSpider, ScrapeResult, MixTab
from scraper_framework.agents.llm_agent import llm_crawl

class MyProductSpider(BaseSpider):
    def get_list_urls(self, tab: MixTab):
        """获取产品列表页"""
        tab.get("https://example.com/products")
        items = tab.eles("css:.product-card")
        return [
            {"url": item.ele("css:a").attr("href"), "name": item.ele("css:.name").text}
            for item in items
        ]

    def scrape_detail_page(self, tab, item_info, user_prompt=None):
        """爬取产品详情页"""
        url = item_info["url"]

        # 方式1: 使用 LLM 爬取
        result = llm_crawl(
            tab=tab,
            msg=f"产品页面：{url}",
            existing_data=item_info,
            output_fields={
                "product_name": "产品名称",
                "price": "价格",
                "description": "产品描述",
                "specs": "规格参数",
            },
        )

        return ScrapeResult(data=result)

# 使用
spider = MyProductSpider(
    school_name="my_store",
    max_workers=5,
    output_dir="output",
)
spider.run()
```

## 项目结构

```
scraper_framework/
├── __init__.py              # 包入口
├── models.py                # 通用数据模型 (ScrapeResult, ErrorInfo, etc.)
├── logger.py                # 日志配置
├── mapper.py                # LLM 批量字段映射
├── tools/                   # 基础工具
│   ├── __init__.py
│   ├── model_factory.py     # LLM 模型工厂 (Qwen/OpenAI)
│   └── page_fetcher.py      # 页面抓取工具 (DrissionPage/Playwright + crawl4ai)
├── agents/                  # Agent 爬取模式
│   ├── __init__.py
│   ├── camel_agent/         # CAMEL-AI Agent (多URL分发+子Agent+合并)
│   │   ├── __init__.py
│   │   ├── master.py        # 主调度器
│   │   ├── sub_agent.py     # 子Agent (单URL爬取)
│   │   ├── prompts.py       # 提示词模板
│   │   └── tools.py         # 工具函数
│   └── llm_agent/           # 简单 LLM Agent (单次爬取)
│       ├── __init__.py
│       └── llm_scraper.py   # LLM 爬取核心
├── spider/                  # 爬虫基类
│   ├── __init__.py
│   └── base_spider.py       # BaseSpider (浏览器管理/多线程/重试/保存)
├── scrapers/                # 专项爬取器
│   ├── __init__.py
│   └── pdf_scraper.py       # PDF 视觉解析
└── prompts/                 # 提示词模板
    ├── __init__.py
    └── base.py              # 默认提示词
```

## 两种爬取模式对比

| 特性 | LLM Crawl | Agent Crawl (camel_scraper) |
|------|-----------|---------------------------|
| 入参 | URL 消息文本 | URL 消息文本 |
| 处理方式 | 单次 LLM 调用 | 解析→分发→提取→合并 |
| 并行能力 | 单次调用 | 子 Agent 顺序执行 |
| 适用场景 | 单页面提取 | 多页面信息整合 |
| 复杂度 | 低 | 高 |
| 依赖 | CAMEL-AI | CAMEL-AI |

## 模型配置

### DeepSeek

```python
from scraper_framework.tools import get_model

model = get_model("deepseek")  # 使用 DEEPSEEK_API_KEY
```

### 本地/自定义模型

```python
model = get_model("local_qwen")  # 使用 LOCAL_API_KEY, LOCAL_BASE_URL, LOCAL_MODEL
```

### 自定义 OpenAI 兼容

```python
model = get_model(
    "my-model",
    api_key="sk-xxx",
    base_url="http://localhost:8000/v1",
    model_type="gpt-4",
)
```

## 环境变量

| 变量名 | 说明 | 必需 |
|--------|------|------|
| `DEEPSEEK_API_KEY` | DeepSeek API Key | 使用 deepseek 时必需 |
| `LOCAL_API_KEY` | 本地模型 API Key | 使用 local_qwen 时必需 |
| `LOCAL_BASE_URL` | 本地模型 API 地址 | 使用 local_qwen 时必需 |
| `LOCAL_MODEL` | 本地模型名称 | 使用 local_qwen 时必需 |
| `CRAWL_MODEL` | 默认模型 (deepseek/local_qwen) | 否 |
| `VL_BASE_URL` | 视觉模型 API 地址 | PDF 解析时必需 |
| `VL_MODEL` | 视觉模型名称 | PDF 解析时必需 |
| `VL_API_KEY` | 视觉模型 API Key（可选，默认回退 DEEPSEEK_API_KEY） | 否 |

## License

MIT
