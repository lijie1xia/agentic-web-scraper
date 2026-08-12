"""模块2 decision 评分最小测试（纯 Python，不依赖 camel / 浏览器）"""

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper_framework.job_agent.decision import score, score_jobs
from scraper_framework.job_agent.skill_profile import DEFAULT_SKILL_PROFILE, load_skill_profile


def _base_job(**overrides):
    job = {
        "job_title": "后端开发实习生",
        "company": "Example",
        "location": "北京",
        "work_mode": "hybrid",
        "job_level": "unknown",
        "experience_years": "",
        "target_candidate": "2027届本科在读",
        "education": "本科",
        "salary_range": "",
        "responsibilities": ["写代码"],
        "required_skills": ["Python"],
        "preferred_skills": [],
        "tech_stack": ["Python", "Docker", "Git"],
        "jd_summary": "示例",
        "extraction_status": "ok",
        "source_url": "https://example.com/job/1",
    }
    job.update(overrides)
    return job


PROFILE = load_skill_profile()


def test_tech_full_match():
    job = _base_job(tech_stack=["Python", "Docker", "Git"])
    d = score(job, PROFILE)
    assert d["score"] is not None
    assert d["score"] >= 70  # 技术栈满分 70 + 其它加分
    assert any("完全匹配" in r for r in d["reasons"])
    assert d["recommend"] is True


def test_tech_partial_match():
    job = _base_job(tech_stack=["Python", "Java", "Kafka"])
    d = score(job, PROFILE)
    assert d["score"] is not None
    assert any("部分匹配" in r for r in d["reasons"])
    # 1/3 * 70 ≈ 23.3，低于完全匹配
    full = score(_base_job(tech_stack=["Python", "Docker", "Git"]), PROFILE)
    assert d["score"] < full["score"]


def test_education_ok():
    job = _base_job(education="本科")
    d = score(job, PROFILE)
    assert any("学历要求符合" in r for r in d["reasons"])
    assert d["recommend"] is True


def test_education_fail():
    job = _base_job(education="硕士")
    d = score(job, PROFILE)
    assert d["recommend"] is False
    assert any("学历明显不符合" in r for r in d["reasons"])


def test_experience_fresh_grad():
    job = _base_job(
        experience_years="应届生",
        target_candidate="2027届本科及以上学历在读",
    )
    d = score(job, PROFILE)
    assert any("经验要求符合" in r for r in d["reasons"])
    assert d["recommend"] is True

    # 届别不能被当成「2027 年经验」
    job2 = _base_job(experience_years="2027届", target_candidate="")
    d2 = score(job2, PROFILE)
    assert d2["recommend"] is True
    assert not any("经验要求过高" in r for r in d2["reasons"])


def test_experience_two_years_required():
    job = _base_job(experience_years="2年以上")
    d = score(job, PROFILE)
    assert d["recommend"] is False
    assert any("经验" in r for r in d["reasons"])


def test_work_mode_match():
    job = _base_job(work_mode="remote")
    d = score(job, PROFILE)
    assert any("工作方式匹配" in r for r in d["reasons"])


def test_work_mode_unknown():
    job = _base_job(work_mode="unknown")
    d = score(job, PROFILE)
    assert any("工作方式未知" in r for r in d["reasons"])
    # 未知不导致否决
    assert d["score"] is not None


def test_empty_fields_not_guessed():
    job = _base_job(
        education="",
        experience_years="",
        target_candidate="",
        work_mode="",
        tech_stack=[],
        required_skills=[],
    )
    d = score(job, PROFILE)
    assert d["score"] is not None
    assert any("学历要求未知" in r for r in d["reasons"])
    assert any("经验要求未知" in r for r in d["reasons"])
    assert any("工作方式未知" in r for r in d["reasons"])
    # 空字段不能直接判不符合学历
    assert not any("学历明显不符合" in r for r in d["reasons"])


def test_invalid_jd():
    job = _base_job(extraction_status="page_invalid")
    d = score(job, PROFILE)
    assert d["score"] is None
    assert d["recommend"] is False
    assert d["reasons"] == ["JD无效或提取失败"]

    job2 = _base_job(error="llm_extract_failed", extraction_status="ok")
    d2 = score(job2, PROFILE)
    assert d2["score"] is None
    assert d2["recommend"] is False


def test_score_does_not_mutate_job():
    job = _base_job()
    before = copy.deepcopy(job)
    score(job, PROFILE)
    assert job == before


def test_score_jobs_structure_and_sort():
    jobs = [
        _base_job(tech_stack=["Java"], source_url="a"),
        _base_job(tech_stack=["Python", "Docker", "Git", "Linux"], source_url="b"),
        _base_job(extraction_status="page_invalid", source_url="c"),
    ]
    original = copy.deepcopy(jobs)
    scored = score_jobs(jobs, PROFILE, sort_by_score=True)
    assert jobs == original  # 不修改原列表
    assert len(scored) == 3
    assert "job" in scored[0] and "decision" in scored[0]
    assert "score" in scored[0]["decision"]
    # 无效 JD 排在最后（score=None）
    assert scored[-1]["decision"]["score"] is None
    # 高分在前
    assert scored[0]["decision"]["score"] >= (scored[1]["decision"]["score"] or -1)


def test_default_profile_export():
    assert "tech_stack" in DEFAULT_SKILL_PROFILE
    assert DEFAULT_SKILL_PROFILE["experience_years"] == 0


if __name__ == "__main__":
    tests = [
        test_tech_full_match,
        test_tech_partial_match,
        test_education_ok,
        test_education_fail,
        test_experience_fresh_grad,
        test_experience_two_years_required,
        test_work_mode_match,
        test_work_mode_unknown,
        test_empty_fields_not_guessed,
        test_invalid_jd,
        test_score_does_not_mutate_job,
        test_score_jobs_structure_and_sort,
        test_default_profile_export,
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
