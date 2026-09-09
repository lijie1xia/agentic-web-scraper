"""模块3 greeting 生成最小测试（纯 Python，不依赖 camel / 浏览器）"""

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper_framework.job_agent.generate import (
    generate_greeting,
    generate_greetings,
    select_relevant_highlights,
)
from scraper_framework.job_agent.resume_highlights import (
    DEFAULT_RESUME_HIGHLIGHTS,
    load_resume_highlights,
)


def _job(**overrides):
    job = {
        "job_title": "AI Agent 开发实习生",
        "company": "Example",
        "tech_stack": ["Python", "Agent", "LangGraph"],
        "required_skills": ["Python", "Agent"],
        "extraction_status": "ok",
    }
    job.update(overrides)
    return job


def _decision(recommend=True, **overrides):
    d = {
        "score": 72.0,
        "recommend": recommend,
        "reasons": ["技术栈部分匹配 2/3（Python、Agent）"],
    }
    d.update(overrides)
    return d


RESUME = load_resume_highlights()


def test_select_picks_highest_overlap():
    job = _job(tech_stack=["Agent", "MCP"])
    picked = select_relevant_highlights(job, RESUME, top_k=2)
    assert len(picked) == 2
    names = [p["name"] for p in picked]
    # Agent+MCP 双命中启德迁移项目；次选为其它 Agent 项目
    assert "启德教育-海外院校数据采集迁移" in names
    assert names[0] == "启德教育-海外院校数据采集迁移"


def test_select_fallback_required_skills():
    job = _job(tech_stack=[], required_skills=["Agent"])
    picked = select_relevant_highlights(job, RESUME, top_k=1)
    assert picked
    assert picked[0]["name"] == "启德教育-海外院校数据采集迁移"


def test_select_skips_empty_one_liner():
    resume = {
        "projects": [
            {"name": "empty", "one_liner": "", "tags": ["Agent"]},
            {
                "name": "ok",
                "one_liner": "有一句话",
                "tags": ["Python"],
            },
        ]
    }
    picked = select_relevant_highlights(_job(tech_stack=["Python"]), resume, top_k=2)
    assert [p["name"] for p in picked] == ["ok"]


def test_generate_greeting_skips_not_recommend():
    greetings = generate_greeting(
        _job(),
        _decision(recommend=False),
        RESUME,
    )
    assert greetings == []


def test_generate_greeting_uses_llm_once():
    import scraper_framework.job_agent.generate as g

    calls = []

    def fake_llm(prompt, model):
        calls.append((prompt, model))
        return [
            {"style": "简洁直接版", "text": "a" * 140},
            {"style": "突出项目匹配版", "text": "b" * 140},
            {"style": "突出学习意愿版", "text": "c" * 140},
        ]

    old = g._call_llm
    g._call_llm = fake_llm
    try:
        greetings = generate_greeting(_job(), _decision(recommend=True), RESUME)
        assert len(greetings) == 3
        assert greetings[0]["style"] == "简洁直接版"
        assert len(calls) == 1  # 一次产出 3 版，不循环打磨
        assert "再来一版" not in calls[0][0]
        assert "重新生成" not in calls[0][0]
    finally:
        g._call_llm = old


def test_generate_greetings_structure_and_no_mutate():
    import scraper_framework.job_agent.generate as g

    ranked = [
        {"job": _job(company="A"), "decision": _decision(recommend=True)},
        {"job": _job(company="B"), "decision": _decision(recommend=False)},
    ]
    original = copy.deepcopy(ranked)

    def fake_llm(prompt, model):
        return [{"style": "简洁直接版", "text": "hello" * 30}]

    old = g._call_llm
    g._call_llm = fake_llm
    try:
        out = generate_greetings(ranked, RESUME, model="deepseek")
    finally:
        g._call_llm = old

    assert ranked == original
    assert len(out) == 2
    assert "greetings" in out[0] and "job" in out[0] and "decision" in out[0]
    assert out[0]["greetings"]
    assert out[1]["greetings"] == []


def test_default_resume_export():
    assert "projects" in DEFAULT_RESUME_HIGHLIGHTS
    assert "skills" in DEFAULT_RESUME_HIGHLIGHTS
    assert DEFAULT_RESUME_HIGHLIGHTS["background"]
    names = [p["name"] for p in DEFAULT_RESUME_HIGHLIGHTS["projects"]]
    assert "启德教育-海外院校数据采集迁移" in names
    assert "RAG垂直领域问答后端" in names


if __name__ == "__main__":
    tests = [
        test_select_picks_highest_overlap,
        test_select_fallback_required_skills,
        test_select_skips_empty_one_liner,
        test_generate_greeting_skips_not_recommend,
        test_generate_greeting_uses_llm_once,
        test_generate_greetings_structure_and_no_mutate,
        test_default_resume_export,
    ]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"  OK {fn.__name__}")
        except Exception as e:
            failed += 1
            print(f"  FAIL {fn.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
