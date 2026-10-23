"""Offline ingestion contract; direct loading avoids optional agent dependencies."""
import ast
import importlib.util
from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load_offline():
    path = ROOT / "scraper_framework/job_workflow/offline.py"
    assert path.exists(), "offline ingestion module has not been implemented"
    spec = importlib.util.spec_from_file_location("offline_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OfflineTests(unittest.TestCase):
    def test_labeled_metadata_raw_evidence_and_missing_values(self):
        text = "岗位名称：Python实习生\n公司：示例公司\n工作地点：广州\n线上面试"
        result = load_offline().extract_text(text, source_url="https://example.invalid/jd")
        self.assertEqual(result["job_title"], "Python实习生")
        self.assertEqual(result["company"], "示例公司")
        self.assertEqual(result["location"], "广州")
        self.assertEqual(result["work_mode"], "unknown")
        self.assertEqual(result["experience_years"], "")
        self.assertEqual(result["job_level"], "unknown")
        self.assertEqual(result["raw_text"], text)
        self.assertEqual(result["source_url"], "https://example.invalid/jd")
        self.assertEqual(result["extraction_method"], "rules")
        self.assertTrue(result["warnings"])
        self.assertTrue(any(e["quote"] == "公司：示例公司" for e in result["evidence"]))


    def test_sections_keep_optional_skills_separate_and_stop_at_benefits(self):
        result = load_offline().extract_text(
            "职位：后端实习生\n任职要求：\n- 熟悉 Python、SQL\n"
            "- Docker 优先\n加分项：\n- LangChain\n岗位职责：\n"
            "- 使用 Flask 开发服务\n福利待遇：\nJava 培训\n"
        )
        self.assertEqual(result["required_skills"], ["Python", "SQL"])
        self.assertEqual(result["preferred_skills"], ["Docker", "LangChain"])
        self.assertEqual(result["responsibilities"], ["使用 Flask 开发服务"])
        self.assertIn("Flask", result["tech_stack"])
        self.assertNotIn("Java", result["required_skills"])


    def test_eligibility_is_literal_and_optional_conditions_do_not_become_required(self):
        result = load_offline().extract_text(
            "任职要求\n2027届在读学生\n本科及以上学历\n3年以上工作经验\n"
            "每周至少到岗4天，连续实习6个月\n加分项\n硕士优先\n"
            "工作方式：远程办公\n"
        )
        self.assertEqual(result["target_candidate"], "2027届在读学生")
        self.assertEqual(result["education"], "本科及以上学历")
        self.assertEqual(result["experience_years"], "3年以上工作经验")
        self.assertEqual(result["job_level"], "unknown")
        self.assertEqual(result["work_mode"], "remote")
        self.assertIn("每周至少到岗4天，连续实习6个月", result["required_conditions"])
        self.assertIn("硕士优先", result["preferred_conditions"])


    def test_ambiguous_labels_and_interview_location_are_not_asserted(self):
        result = load_offline().extract_text(
            "职位：开发\n职位：测试\n工作地点：线上面试\n工作经验：2027届\n"
        )
        self.assertEqual(result["job_title"], "")
        self.assertEqual(result["location"], "")
        self.assertEqual(result["experience_years"], "")
        self.assertTrue(any("job_title" in w for w in result["warnings"]))
        self.assertEqual(len([e for e in result["evidence"] if e["field"] == "job_title"]), 2)

    def test_optional_clauses_negations_and_alternatives_do_not_become_hard_skills(self):
        result = load_offline().extract_text(
            "任职要求\n熟悉 Python，Docker 优先\n无需 Java 经验\n"
            "Go 或 Rust 均可\n福利待遇\nSQL 培训\n"
        )
        self.assertEqual(result["required_skills"], ["Python"])
        self.assertEqual(result["preferred_skills"], ["Docker"])
        self.assertTrue(any("歧义" in w for w in result["warnings"]))


    def test_schema_parity_empty_and_unclassified_text_without_api_calls(self):
        before = set(sys.modules)
        schema = ast.parse((ROOT / "scraper_framework/job_agent/schema.py").read_text(encoding="utf-8"))
        fields = next(ast.literal_eval(node.value) for node in schema.body
                      if isinstance(node, ast.AnnAssign) and node.target.id == "JD_OUTPUT_FIELDS")
        with patch.object(socket, "socket", side_effect=AssertionError("network forbidden")) as network:
            module = load_offline()
            empty = module.extract_text(" \n")
            raw = module.extract_text("Some unlabeled title\nPython MySQL JavaScript")
        self.assertEqual(network.call_count, 0)
        self.assertTrue(set(fields).issubset(empty))
        self.assertEqual(empty["extraction_status"], "empty")
        self.assertEqual(raw["job_title"], "")
        self.assertEqual(raw["required_skills"], [])
        self.assertEqual(raw["tech_stack"], ["Python", "MySQL", "JavaScript"])
        self.assertFalse(any(name.startswith(("camel", "openai", "scraper_framework.job_agent")) for name in set(sys.modules) - before))
        self.assertEqual(raw, module.extract_text(raw["raw_text"]))
        with self.assertRaises(TypeError):
            module.extract_text(None)

    def test_optional_labeled_education_and_negated_remote_are_not_hard_facts(self):
        result = load_offline().extract_text("加分项：\n学历：硕士优先\n工作方式：不支持远程办公\n")
        self.assertEqual(result["education"], "")
        self.assertEqual(result["work_mode"], "unknown")

    def test_ambiguous_education_extraction_does_not_reject_bachelor(self):
        """标签与普通条款的否定、替代关系均保留证据，不制造学历门槛。"""
        from scraper_framework.job_agent.decision import score

        profile = {"education": "本科", "tech_stack": ["Python"], "experience_years": 0}
        for value in ("不要求硕士学历", "无需硕士学历", "硕士或同等工作经验",
                      "本科或硕士", "master not required", "master or equivalent experience"):
            for prefix in ("学历：", "任职要求\n学历：", "任职要求\n"):
                with self.subTest(value=value, prefix=prefix):
                    text = prefix + value + "\n任职要求\nPython\n工作经验：无需工作经验"
                    extracted = load_offline().extract_text(text)
                    decision = score(extracted, profile)
                    self.assertNotEqual(decision["category"], "reject", decision["reasons"])
                    self.assertEqual(extracted["education"], "")
                    self.assertIn("job.education", decision["missing_data"])
                    self.assertFalse(any("学历要求符合" in reason for reason in decision["reasons"]))
                    self.assertEqual(extracted["required_skills"], ["Python"])
                    self.assertEqual(extracted["raw_text"], text)
                    quote = ("学历：" if prefix.endswith("学历：") else "") + value
                    self.assertTrue(any(e["quote"] == quote for e in extracted["evidence"]))
                    self.assertTrue(any("歧义" in warning for warning in extracted["warnings"]))
                    if prefix.endswith("学历："):
                        self.assertTrue(any(e["field"] == "education" and e["status"] == "unresolved"
                                            for e in extracted["evidence"] if e.get("status")))


    def test_conflicting_qualifications_and_work_modes_are_left_unresolved(self):
        result = load_offline().extract_text(
            "任职要求\n本科及以上\n硕士及以上\n"
            "工作方式：remote\n工作方式：onsite\n"
        )
        self.assertEqual(result["education"], "")
        self.assertEqual(result["work_mode"], "unknown")
        self.assertTrue(any("education" in w for w in result["warnings"]))
        self.assertTrue(any("work_mode" in w for w in result["warnings"]))


if __name__ == "__main__":
    unittest.main()
