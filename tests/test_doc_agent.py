"""DocAgent 测试 - Tool Calling 模式"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

# 直接用 importlib 导入子模块，避免触发 agents/__init__.py 的 camel_agent 导入链
import importlib
import importlib.util

def _import_module(dotted_name: str, file_path: str):
    """绕过包 __init__.py 直接导入模块"""
    spec = importlib.util.spec_from_file_location(dotted_name, file_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[dotted_name] = mod
    spec.loader.exec_module(mod)
    return mod

_base = Path(__file__).parent.parent / "scraper_framework"

_models = _import_module(
    "scraper_framework.agents.doc_agent.models",
    str(_base / "agents" / "doc_agent" / "models.py"),
)
Document = _models.Document
Link = _models.Link
ExplorationState = _models.ExplorationState

_prompts = _import_module(
    "scraper_framework.agents.doc_agent.prompts",
    str(_base / "agents" / "doc_agent" / "prompts.py"),
)
build_initial_prompt = _prompts.build_initial_prompt
build_step_context = _prompts.build_step_context

_page_source = _import_module(
    "scraper_framework.agents.doc_agent.page_source",
    str(_base / "agents" / "doc_agent" / "page_source.py"),
)

_fetcher = _import_module(
    "scraper_framework.agents.doc_agent.document_fetcher",
    str(_base / "agents" / "doc_agent" / "document_fetcher.py"),
)
DocumentFetcher = _fetcher.DocumentFetcher

try:
    _agent_mod = _import_module(
        "scraper_framework.agents.doc_agent.agent",
        str(_base / "agents" / "doc_agent" / "agent.py"),
    )
    DocAgent = _agent_mod.DocAgent
    HAS_CAMEL = True
except Exception:
    HAS_CAMEL = False


# ============================================================
# 数据模型
# ============================================================

def test_document_model():
    doc = Document(
        url="https://example.com/programs",
        title="Programs",
        content="# Programs\n\n- [MSc CS](/cs)",
        links=[Link(text="MSc CS", url="https://example.com/cs")],
    )
    assert doc.url == "https://example.com/programs"
    assert len(doc.links) == 1
    print("PASS: test_document_model")


def test_exploration_state_model():
    state = ExplorationState(
        task="test task", start_url="https://example.com",
        output_fields={"name": "名称"}, max_depth=10,
    )
    assert state.max_depth == 10
    assert len(state.visited_urls) == 0
    print("PASS: test_exploration_state_model")


# ============================================================
# DocumentFetcher
# ============================================================

def test_document_fetcher_with_mock_tab():
    mock_tab = MagicMock()
    mock_tab.ele.return_value.html = "<html><body></body></html>"
    mock_tab.eles.return_value = []
    mock_tab.ele.return_value.text = ""
    fetcher = DocumentFetcher(tab=mock_tab)
    with patch("scraper_framework.agents.doc_agent.page_source.html_to_markdown") as m:
        m.return_value = "# Test"
        doc = fetcher.fetch("https://example.com")
    assert doc.content == "# Test"
    print("PASS: test_document_fetcher_with_mock_tab")


def test_document_fetcher_requires_tab_or_source():
    try:
        DocumentFetcher()
        assert False
    except ValueError:
        pass
    print("PASS: test_document_fetcher_requires_tab_or_source")


# ============================================================
# 提示词
# ============================================================

def test_build_initial_prompt():
    p = build_initial_prompt("find CS programs", "https://example.com", {"name": "名称"})
    assert "find CS programs" in p
    assert "https://example.com" in p
    assert "fetch_document" in p
    print("PASS: test_build_initial_prompt")


def test_build_step_context():
    state = ExplorationState(
        task="test", start_url="https://example.com",
        output_fields={"name": "名称"},
        visited_urls=["https://example.com", "https://example.com/cs"],
        extracted_data={"name": "MSc CS"},
    )
    ctx = build_step_context(state)
    assert "https://example.com/cs" in ctx
    assert "MSc CS" in ctx
    assert "✓ 已提取" in ctx
    print("PASS: test_build_step_context")


# ============================================================
# Agent 核心逻辑
# ============================================================

def test_is_final_output():
    if not HAS_CAMEL:
        print("SKIP: test_is_final_output (camel-ai not installed)")
        return
    agent = _mock_agent()
    assert agent._is_final_output('{"extracted_data": {"name": "x"}}') is True
    assert agent._is_final_output('[{"extracted_data": {"name": "x"}}]') is True
    assert agent._is_final_output('{"action": "explore"}') is False
    assert agent._is_final_output('') is False
    assert agent._is_final_output(None) is False
    print("PASS: test_is_final_output")


def test_parse_final_output():
    if not HAS_CAMEL:
        print("SKIP: test_parse_final_output (camel-ai not installed)")
        return
    agent = _mock_agent()
    r = agent._parse_final_output('{"extracted_data": {"name": "MSc CS"}}')
    assert r["name"] == "MSc CS"
    r = agent._parse_final_output('[{"extracted_data": {"name": "x"}}]')
    assert r["name"] == "x"
    r = agent._parse_final_output('{"action": "explore"}')
    assert r == {}
    print("PASS: test_parse_final_output")


def test_build_tools_visited_dedup():
    """测试工具层已访问 URL 去重"""
    if not HAS_CAMEL:
        print("SKIP: test_build_tools_visited_dedup (camel-ai not installed)")
        return
    agent = _mock_agent()
    tools, visited = agent._build_tools()
    fetch_fn = tools[0].func

    # 第一次访问
    with patch.object(agent.fetcher, "fetch") as m:
        m.return_value = Document(url="https://a.com", content="page1", links=[])
        r1 = json.loads(fetch_fn("https://a.com"))
    assert r1["content"] == "page1"
    assert "https://a.com" in visited

    # 第二次访问同一 URL，应返回 already_visited 提示
    r2 = json.loads(fetch_fn("https://a.com"))
    assert "Already visited" in r2["content"]
    assert r2.get("already_visited") is True
    print("PASS: test_build_tools_visited_dedup")


def test_extract_tool_calls():
    if not HAS_CAMEL:
        print("SKIP: test_extract_tool_calls (camel-ai not installed)")
        return
    agent = _mock_agent()
    resp = MagicMock()
    tc1 = MagicMock()
    tc1.name = "fetch_document"
    tc1.args = {"url": "https://a.com"}
    tc2 = MagicMock()
    tc2.name = "other_tool"
    tc2.args = {}
    resp.tool_calls = [tc1, tc2]
    calls = agent._extract_tool_calls(resp)
    assert len(calls) == 1
    assert calls[0]["url"] == "https://a.com"
    print("PASS: test_extract_tool_calls")


def test_extract_agent_text():
    if not HAS_CAMEL:
        print("SKIP: test_extract_agent_text (camel-ai not installed)")
        return
    agent = _mock_agent()
    resp = MagicMock()
    resp.msg.content = "hello"
    assert agent._extract_agent_text(resp) == "hello"
    resp2 = MagicMock()
    resp2.msg = None
    resp2.msgs = [MagicMock(content="from msgs")]
    assert agent._extract_agent_text(resp2) == "from msgs"
    print("PASS: test_extract_agent_text")


def _mock_agent():
    return DocAgent(tab=MagicMock(), model="deepseek")


# ============================================================
# 运行
# ============================================================

if __name__ == "__main__":
    tests = [
        test_document_model,
        test_exploration_state_model,
        test_document_fetcher_with_mock_tab,
        test_document_fetcher_requires_tab_or_source,
        test_build_initial_prompt,
        test_build_step_context,
        test_is_final_output,
        test_parse_final_output,
        test_build_tools_visited_dedup,
        test_extract_tool_calls,
        test_extract_agent_text,
    ]
    passed = failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"FAIL: {t.__name__}: {e}")
            failed += 1
    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
    print("ALL TESTS PASSED")
