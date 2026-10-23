"""Offline conservative eligibility regression tests (stdlib unittest)."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scraper_framework.job_agent.decision import score, score_jobs
from scraper_framework.job_agent.skill_profile import load_skill_profile


def job(**overrides):
    result = {
        "job_title": "后端开发实习生",
        "education": "本科",
        "experience_years": "应届生",
        "target_candidate": "2027届本科在读",
        "tech_stack": ["Python"],
        "required_skills": ["Python"],
        "preferred_skills": [],
        "work_mode": "hybrid",
        "extraction_status": "ok",
    }
    result.update(overrides)
    return result


class EligibilityTests(unittest.TestCase):
    def setUp(self):
        self.profile = load_skill_profile()

    def test_missing_technical_evidence_requires_review(self):
        decision = score(job(tech_stack=[], required_skills=[]), self.profile)
        self.assertFalse(decision["recommend"])
        self.assertEqual(decision.get("category"), "review")
        self.assertIn("job.technical_skills", decision["missing_data"])
        self.assertTrue(decision["warnings"])
        self.assertLessEqual(decision["score"], 30)


    def test_explicit_graduation_cohorts_are_eligibility_constraints(self):
        for fields in (
            {"target_candidate": "仅限2026届毕业生"},
            {"target_candidate": "", "experience_years": "2026届"},
            {"target_candidate": "", "graduate_year": 2026},
            {"target_candidate": "", "raw_jd": "任职要求：仅限2026届毕业生。"},
        ):
            with self.subTest(fields=fields):
                decision = score(job(**fields), self.profile)
                self.assertFalse(decision["recommend"])
                self.assertEqual(decision.get("category"), "reject")
                self.assertTrue(any("届别" in r for r in decision["reasons"]))

        for text in ("2026/2027届毕业生", "2026至2028届", "2027届本科在读"):
            with self.subTest(text=text):
                self.assertTrue(score(job(target_candidate=text), self.profile)["recommend"])

        # Dates unrelated to eligibility and preferred cohorts are not hard gates.
        for fields in (
            {"target_candidate": "应届", "raw_jd": "公司创立于2026年。"},
            {"target_candidate": "2026届优先"},
        ):
            self.assertNotEqual(score(job(**fields), self.profile)["category"], "reject")


    def test_cohort_modality_is_local_to_its_clause(self):
        for text, category in (
            ("仅限2026届毕业生，熟悉Python优先。", "reject"),
            ("招聘后端开发，团队已有2026届毕业生。", "priority"),
        ):
            with self.subTest(text=text):
                decision = score(job(target_candidate="", raw_jd=text), self.profile)
                self.assertEqual(decision["category"], category)
                if category == "reject":
                    evidence = decision["graduation_evidence"][0]
                    self.assertFalse(evidence["optional"])
                    self.assertEqual(evidence["text"], "仅限2026届毕业生")
                else:
                    self.assertEqual(decision["graduation_evidence"], [])

    def test_negated_cohort_is_not_a_positive_requirement(self):
        for field in ("target_candidate", "raw_jd"):
            with self.subTest(field=field):
                decision = score(job(**{field: "不招收2026届毕业生"}), self.profile)
                self.assertEqual(decision["category"], "review")
                self.assertFalse(decision["recommend"])
                self.assertTrue(decision["warnings"])
                self.assertFalse(any("届别不符合" in reason for reason in decision["reasons"]))

    def test_cohort_with_experience_alternative_requires_review(self):
        profile = dict(self.profile, graduate_year=2027, experience_years=3)
        for fields in (
            {"target_candidate": "2026届应届生或有工作经验者"},
            {"experience_years": "2026届应届生或有工作经验者"},
            {"raw_jd": "招聘2026届应届生或有工作经验者"},
        ):
            with self.subTest(fields=fields):
                decision = score(job(**fields), profile)
                self.assertEqual(decision["category"], "review")
                self.assertTrue(decision["warnings"])
                self.assertFalse(any("届别不符合" in reason for reason in decision["reasons"]))

    def test_required_skills_outweigh_optional_skills_with_evidence(self):
        mandatory = score(job(required_skills=["Python"], preferred_skills=["Rust"],
                              tech_stack=["Python", "Rust"]), self.profile)
        optional = score(job(required_skills=["Rust"], preferred_skills=["Python"],
                             tech_stack=["Python", "Rust"]), self.profile)
        self.assertGreater(mandatory["score"], optional["score"])
        self.assertTrue(mandatory["recommend"])
        self.assertFalse(optional["recommend"])
        self.assertEqual(optional["category"], "review")
        self.assertEqual(optional["missing_skills"]["required"], ["Rust"])
        self.assertEqual(mandatory["missing_skills"]["preferred"], ["Rust"])
        self.assertIn({"field": "required_skills", "skill": "Rust", "matched": False},
                      optional["skill_evidence"])

        # tech_stack is a summary, never permission to ignore hard requirements.
        hidden_gap = score(job(required_skills=["Rust"], tech_stack=["Python"]), self.profile)
        self.assertFalse(hidden_gap["recommend"])

        duplicated = score(job(tech_stack=["Python", "py", "Python"],
                               required_skills=["Python", "py"]), self.profile)
        self.assertEqual(duplicated["score"], score(job(), self.profile)["score"])
        self.assertEqual(duplicated["missing_skills"]["required"], [])

    def test_skill_substrings_are_not_evidence(self):
        profile = dict(self.profile, tech_stack=["Django", "JavaScript"])
        decision = score(job(tech_stack=["Go", "Java"], required_skills=["Go", "Java"]), profile)
        self.assertFalse(decision["recommend"])
        self.assertEqual(decision.get("missing_skills", {}).get("required"), ["Go", "Java"])


    def test_ambiguous_experience_is_review_not_rejection(self):
        for text in ("1年以内", "up to 2 years", "1-3年优先", "2027",
                     "熟悉Python3", "应届生或2年以上经验", "3个月实习", "经验丰富", "3-1年"):
            with self.subTest(text=text):
                decision = score(job(experience_years=text), self.profile)
                self.assertEqual(decision["category"], "review")
                self.assertFalse(decision["recommend"])
                self.assertTrue(decision["warnings"])

        for text in ("2年以上", "1-3 years", "at least 2 years", "2+ years", 2):
            with self.subTest(text=text):
                self.assertEqual(score(job(experience_years=text), self.profile)["category"], "reject")

    def test_missing_candidate_experience_is_not_assumed_zero(self):
        for value in (None, "unknown", -1, float("nan")):
            decision = score(job(experience_years="2年"), dict(self.profile, experience_years=value))
            self.assertEqual(decision["category"], "review")
            self.assertIn("profile.experience_years", decision["missing_data"])
            self.assertTrue(decision["warnings"])


    def test_optional_target_roles_rank_ai_apps_then_backend(self):
        jobs = [job(job_title="前端开发实习生"), job(job_title="后端开发实习生"),
                job(job_title="AI应用开发实习生")]
        profile = dict(self.profile, target_roles=["ai_application", "backend"])
        ranked = score_jobs(jobs, profile)
        self.assertEqual([r["job"]["job_title"] for r in ranked],
                         ["AI应用开发实习生", "后端开发实习生", "前端开发实习生"])
        self.assertEqual([r["decision"].get("role_priority") for r in ranked], [0, 1, None])
        self.assertEqual(ranked[-1]["decision"]["category"], "review")
        self.assertFalse(ranked[-1]["decision"]["recommend"])
        self.assertTrue(score(jobs[0], self.profile)["recommend"])
        explicit = dict(profile, deal_breakers={"target_roles_only": True})
        self.assertEqual(score(jobs[0], explicit)["category"], "reject")
        aliases = dict(self.profile, target_roles=["AI应用", "后端"])
        self.assertEqual(score(jobs[2], aliases)["role_priority"], 0)


    def test_compound_title_matches_each_explicit_role_family(self):
        for roles in (["backend"], ["ai_application"], ["backend", "ai_application"]):
            with self.subTest(roles=roles):
                profile = dict(self.profile, target_roles=roles,
                               deal_breakers={"target_roles_only": True})
                decision = score(job(job_title="AI应用后端开发工程师"), profile)
                self.assertEqual(decision["category"], "priority")
                self.assertEqual(decision["role_priority"], 0)

    def test_all_decisions_have_metadata_and_invalid_batch_items_stay_invalid(self):
        invalid_jobs = [None, "not a job", job(extraction_status="page_invalid"), job(error="failed")]
        decisions = [score(value, self.profile) for value in invalid_jobs]
        decisions += [item["decision"] for item in score_jobs(invalid_jobs, self.profile)]
        for decision in decisions:
            self.assertEqual(decision.get("category"), "reject")
            self.assertIsNone(decision["score"])
            self.assertFalse(decision["recommend"])
            for field in ("warnings", "missing_data", "skill_evidence", "graduation_evidence"):
                self.assertIsInstance(decision[field], list)
            self.assertEqual(set(decision["missing_skills"]), {"required", "preferred", "unspecified"})

    def test_missing_data_is_explicit_without_inventing_jd_evidence(self):
        candidate = {"tech_stack": [], "experience_years": 0}
        empty = score({}, candidate)
        self.assertEqual(empty["category"], "review")
        self.assertEqual(empty["score"], 0)
        self.assertTrue({"job.technical_skills", "job.education", "job.experience_years",
                         "job.work_mode", "profile.tech_stack", "profile.education"}
                        .issubset(set(empty["missing_data"])))
        self.assertEqual(empty["skill_evidence"], [])
        self.assertEqual(empty["graduation_evidence"], [])
        decision = score(job(), candidate)
        self.assertIn("profile.graduate_year", decision["missing_data"])
        self.assertTrue(all(e["field"] not in {"raw_jd", "raw_text", "jd_text"}
                            for e in decision["graduation_evidence"]))
        original = job(raw_jd="要求：2027届毕业生。", tech_stack=["Python", "py"])
        before, profile_before = copy.deepcopy(original), copy.deepcopy(self.profile)
        score_jobs([original], self.profile, sort_by_score=False)
        self.assertEqual(original, before)
        self.assertEqual(self.profile, profile_before)


    def test_raw_cohort_evidence_does_not_turn_company_dates_into_eligibility(self):
        decision = score(job(target_candidate="", raw_jd="公司成立于2027年，要求2026届毕业生。"), self.profile)
        self.assertEqual(decision["category"], "reject")
        self.assertEqual(decision["graduation_evidence"][0]["years"], [2026])
        self.assertNotEqual(score(job(target_candidate="", raw_jd="团队里有很多2026届毕业生。"),
                                  self.profile)["category"], "reject")
        self.assertEqual(score(job(target_candidate="2026年毕业"), self.profile)["category"], "reject")


    def test_unparseable_graduation_year_requires_review(self):
        for target in ("", "2027届本科在读"):
            with self.subTest(target=target):
                decision = score(job(graduate_year="待确认", target_candidate=target), self.profile)
                self.assertEqual(decision["category"], "review")
                self.assertFalse(decision["recommend"])
                self.assertTrue(decision["warnings"])
                self.assertIn({"field": "graduate_year", "text": "待确认", "years": [],
                               "optional": False, "ambiguous": True}, decision["graduation_evidence"])
        decision = score(job(target_candidate="仅限2026届毕业生"),
                         dict(self.profile, graduate_year="待确认"))
        self.assertEqual(decision["category"], "review")
        self.assertIn("profile.graduate_year", decision["missing_data"])
        self.assertTrue(decision["warnings"])

    def test_preferences_are_not_candidate_credentials(self):
        profile = dict(self.profile)
        del profile["education"]
        decision = score(job(), profile)
        self.assertEqual(decision["category"], "review")
        self.assertIn("profile.education", decision["missing_data"])

    def test_ambiguous_target_candidate_does_not_prove_zero_experience(self):
        decision = score(job(experience_years="", target_candidate="应届生或3年以上经验"), self.profile)
        self.assertEqual(decision["category"], "review")
        self.assertIn("job.experience_years", decision["missing_data"])


    def test_open_ended_or_negated_cohort_text_requires_review(self):
        for text in ("2026届及以后", "2028届及以前", "不限届别，2026届也可", "非2027届",
                     "class of 2026 or later", "2028-2026届"):
            with self.subTest(text=text):
                decision = score(job(target_candidate=text), self.profile)
                self.assertEqual(decision["category"], "review")
                self.assertFalse(decision["recommend"])
                self.assertTrue(decision["warnings"])


if __name__ == "__main__":
    unittest.main()
