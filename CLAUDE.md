# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup

```bash
pip install -r requirements.txt
```

Copy `.env.demo` to `.env` and fill in API keys. Install Chrome driver if needed:

```bash
python -c "from DrissionPage import Chromium; Chromium()"
```

## Running Tests

```bash
# Run the test file directly (uses importlib to bypass camel-ai imports)
python tests/test_doc_agent.py
```

There is no test runner configured. Tests are plain Python scripts using `assert` statements. The test file uses a manual `importlib` workaround to isolate `doc_agent` from the rest of the package's import chain (which pulls in `camel-ai` and `DrissionPage`).

## Architecture

The framework provides three distinct scraping modes, all sharing the same model factory and page fetching utilities.

### Layers

**`tools/`** — Foundation layer
- `model_factory.py`: `get_model(name)` returns a CAMEL-AI model. Supports `"deepseek"` (DeepSeek official API via `DEEPSEEK_API_KEY`), `"local_qwen"` (any OpenAI-compatible endpoint), or raw kwargs. Also exposes `enable_no_proxy_for_aliyun()` context manager — wraps API calls that should bypass proxy (DeepSeek / Aliyun domains).
- `page_fetcher.py`: Page-to-Markdown conversion. Sync version uses DrissionPage (`fetch_page_as_markdown_sync`), async version uses Playwright (`fetch_page_as_markdown_async`). Both use crawl4ai internally for HTML→Markdown.

**`agents/`** — Three scraping modes

1. **`llm_agent/`** — Single-shot LLM scrape. `LLMAgentScraper.crawl()` fetches one page and extracts structured fields. `llm_crawl()` is a convenience wrapper that merges results into existing data without overwriting non-empty values.

2. **`agents/camel_agent/`** — Multi-URL orchestration. `CamelScraperAgent.run()` uses three sub-agents in sequence:
   - Parse agent: extracts URL list from free-text `msg`
   - `SubAgent`: processes each URL sequentially, accumulating results
   - Merge agent: consolidates all sub-results into a single dict
   Results always include `data_source_type: "camel_scraper"`.

3. **`agents/doc_agent/`** — Autonomous document exploration. `DocAgent.run()` gives the LLM a `fetch_document` tool and lets it self-navigate across pages. The tool layer handles URL dedup; the Python outer loop enforces `max_depth` and detects stalls (2 consecutive steps with no tool calls). Final output is detected by presence of `extracted_data` key in the Agent's JSON response.

**`spider/base_spider.py`** — `BaseSpider` abstract class for multi-threaded production crawls. Subclasses implement `get_list_urls(tab)` and `scrape_detail_page(tab, item_info)`. Manages a single shared Chromium browser instance with thread-safe recreation on crash. Saves results to JSON in `output_dir`.

**`mapper.py`** — `llm_mapper()`: batch field mapping via LLM. Matches items in a list against a reference dict by a key field, fills in target fields.

**`scrapers/pdf_scraper.py`** — `pdf_crawl()`: downloads PDFs, renders pages as images, uses a vision LLM (configured via `VL_BASE_URL`/`VL_MODEL`) to extract structured fields.

### Data flow

All agents return `ScrapeResult(data=dict, err_info=dict)`. `err_info` with `should_retry=True` triggers retry logic in `BaseSpider`. The `data_source_type` and `data_source_model` fields are always injected into final results.

### Environment variables

| Variable | Purpose |
|---|---|
| `DEEPSEEK_API_KEY` | DeepSeek API key |
| `LOCAL_API_KEY` / `LOCAL_BASE_URL` / `LOCAL_MODEL` | OpenAI-compatible endpoint |
| `CRAWL_MODEL` | Default model (`deepseek` or `local_qwen`) |
| `VL_BASE_URL` / `VL_MODEL` / `VL_API_KEY` | Vision model for PDF parsing |
