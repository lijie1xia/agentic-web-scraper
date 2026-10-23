"""Grounded, data-only application material contract (no service dependencies)."""
import copy
import importlib.util
from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load_materials():
    path = ROOT / "scraper_framework/job_workflow/materials.py"
    assert path.exists(), "offline materials module has not been implemented"
    spec = importlib.util.spec_from_file_location("materials_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MaterialTests(unittest.TestCase):
    def test_real_score_categories_drive_material_warnings_and_rejection(self):
        """真实评分结果进入材料层时，不把优先岗位误报为待复核。"""
        from scraper_framework.job_agent.decision import score

        module = load_materials()
        profile = {"education": "本科", "tech_stack": ["Python"], "experience_years": 0}
        resume = {"projects": [{"one_liner": "参与 Python 后端开发", "tags": ["Python"]}]}
        for expected, overrides in (("priority", {}),
                                    ("review", {"required_skills": ["Rust"]}),
                                    ("reject", {"education": "博士"})):
            with self.subTest(category=expected):
                job = {"job_title": "后端开发", "required_skills": ["Python"],
                       "education": "本科", "experience_years": "0年", "work_mode": "onsite"}
                job.update(overrides)
                decision = score(job, profile)
                self.assertEqual(decision["category"], expected)
                if expected == "reject":
                    with self.assertRaisesRegex(ValueError, "reject"):
                        module.build_material(job, decision, resume)
                    continue
                material = module.build_material(job, decision, resume, resume_version="backend-v1")
                self.assertEqual(material["decision_category"], expected)
                self.assertEqual(any(w.startswith("review：") for w in material["warnings"]),
                                 expected == "review")
                self.assertTrue(set(decision["warnings"]).issubset(material["warnings"]))
                self.assertTrue(any("须人工核对" in w for w in material["warnings"]))
                self.assertFalse(any(w.startswith("ERROR:") for w in module.validate_material(material)))

    def test_legacy_apply_is_compatible_but_unknown_categories_require_review(self):
        """保留旧调用方的 apply，未知分类仍须复核且不授予发送权限。"""
        module = load_materials()
        for category in ("apply", "unrecognized", None):
            with self.subTest(category=category):
                material = module.build_material({}, {"category": category}, {})
                self.assertEqual(material["decision_category"], category)
                self.assertEqual(any(w.startswith("review：") for w in material["warnings"]),
                                 category != "apply")

    def test_chat_uses_one_relevant_project_verbatim_without_changing_resume(self):
        resume = {"projects": [
            {"name": "unrelated", "one_liner": "做过财务报表", "tags": ["Excel"]},
            {"name": "backend", "one_liner": "参与 Python 后端开发", "tags": ["Python"], "outcome": "优化过服务"},
        ]}
        before = copy.deepcopy(resume)
        result = load_materials().build_material(
            {"job_title": "后端实习生", "required_skills": ["Python"]},
            {"category": "apply"}, resume,
        )
        self.assertEqual(result["channel"], "chat")
        self.assertEqual(result["resume_version"], "not_selected")
        self.assertEqual(result["generation_method"], "template")
        self.assertIn("参与 Python 后端开发", result["message"])
        self.assertNotIn("财务报表", result["message"])
        self.assertNotIn("符合", result["message"])
        self.assertNotIn("\n", result["message"])
        self.assertLess(len(result["message"]), 180)
        self.assertEqual(resume, before)
        self.assertTrue(any(e["quote"] == "参与 Python 后端开发" for e in result["evidence"]))
        self.assertTrue(result["warnings"])


    def test_email_is_separate_opener_and_review_is_warned(self):
        module = load_materials()
        args = ({"job_title": "开发实习生", "tech_stack": ["Python"]},
                {"category": "review", "warnings": ["到岗时间未知"]},
                {"projects": [{"one_liner": "参与 Python 开发", "tags": ["Python"]}]})
        chat = module.build_material(*args)
        email = module.build_material(*args, channel="email", resume_version="backend-v1")
        self.assertNotEqual(email["message"], chat["message"])
        self.assertIn("招聘团队", email["message"])
        self.assertIn("\n", email["message"])
        self.assertEqual(email["resume_version"], "backend-v1")
        self.assertIn("到岗时间未知", email["warnings"])
        self.assertTrue(any("review" in w for w in email["warnings"]))
        self.assertNotIn("附件", email["message"])

    def test_reject_has_no_sendable_material_and_invalid_channels_error(self):
        module = load_materials()
        with self.assertRaisesRegex(ValueError, "reject"):
            module.build_material({}, {"category": "reject"}, {})
        with self.assertRaisesRegex(ValueError, "channel"):
            module.build_material({}, {"category": "review"}, {}, channel="sms")


    def test_missing_or_irrelevant_projects_never_fall_back_to_resume_facts(self):
        module = load_materials()
        for resume in ({}, {"projects": None}, {"projects": [
            {"one_liner": "有 Java 经验", "tags": ["Java"]},
            {"one_liner": "", "tags": ["Python"]},
        ]}):
            with self.subTest(resume=resume):
                result = module.build_material({"tech_stack": ["Python"]}, {}, resume)
                self.assertNotIn("Java", result["message"])
                self.assertNotIn("Python", result["message"])
                self.assertEqual(result["evidence"], [])
                self.assertTrue(any("相关项目" in w for w in result["warnings"]))
                self.assertTrue(any("岗位名称" in w for w in result["warnings"]))
                self.assertTrue(any("简历版本" in w for w in result["warnings"]))

    def test_exact_tag_match_does_not_match_java_to_javascript(self):
        result = load_materials().build_material(
            {"tech_stack": ["JavaScript"]}, {"category": "apply"},
            {"projects": [{"one_liner": "Java 后端开发", "tags": ["Java"]}]},
        )
        self.assertNotIn("Java 后端", result["message"])


    def test_validate_material_reports_edits_and_malformed_drafts_without_mutation(self):
        module = load_materials()
        self.assertTrue(callable(getattr(module, "validate_material", None)), "editable material validator is missing")
        draft = module.build_material({"job_title": "开发"}, {"category": "review"}, {})
        original = copy.deepcopy(draft)
        self.assertIsInstance(module.validate_material(draft), list)
        self.assertEqual(draft, original)
        draft["message"] += "我有10年经验，完全符合要求，保证下周到岗。"
        self.assertTrue(any("编辑" in w for w in module.validate_material(draft)))
        draft["message"] = " "
        self.assertTrue(any(w.startswith("ERROR:") for w in module.validate_material(draft)))
        self.assertTrue(any(w.startswith("ERROR:") for w in module.validate_material({"message": 1, "channel": "sms"})))
        self.assertTrue(any(w.startswith("ERROR:") for w in module.validate_material(None)))


    def test_plain_text_deterministic_material_without_network_or_model_imports(self):
        before = set(sys.modules)
        with patch.object(socket, "socket", side_effect=AssertionError("network forbidden")) as network:
            module = load_materials()
            args = ({"job_title": "<开发&实习>", "tech_stack": ["python"]},
                    {"category": "apply"},
                    {"projects": [{"one_liner": "使用 <Python> 开发", "tags": ["Python"]}]})
            result = module.build_material(*args)
            self.assertEqual(result, module.build_material(*args))
        self.assertEqual(network.call_count, 0)
        self.assertIn("<开发&实习>", result["message"])
        self.assertIn("使用 <Python> 开发", result["message"])
        self.assertFalse(any(name.startswith(("camel", "openai", "scraper_framework.job_agent")) for name in set(sys.modules) - before))

    def test_chat_omits_oversized_facts_instead_of_rewriting_or_truncating(self):
        resume = {"projects": [{"one_liner": "完整项目事实" * 80, "tags": ["Python"]}]}
        result = load_materials().build_material({"tech_stack": ["Python"]}, {"category": "apply"}, resume)
        self.assertLessEqual(len(result["message"]), 200)
        self.assertNotIn("完整项目事实", result["message"])
        self.assertTrue(any("过长" in w for w in result["warnings"]))


    def test_unusable_title_is_not_copied_into_a_chat_and_source_warnings_survive(self):
        module = load_materials()
        draft = module.build_material({"job_title": "标题\n" * 100, "warnings": ["地点无法确认"]},
                                      {"category": "review"}, {})
        self.assertNotIn("\n", draft["message"])
        self.assertLessEqual(len(draft["message"]), 200)
        self.assertIn("地点无法确认", draft["warnings"])

    def test_validation_rejects_malformed_evidence_entries(self):
        module = load_materials()
        draft = module.build_material({}, {"category": "apply"}, {})
        draft["evidence"] = ["unsupported assertion"]
        self.assertTrue(any(w.startswith("ERROR:") and "evidence" in w for w in module.validate_material(draft)))


if __name__ == "__main__":
    unittest.main()
