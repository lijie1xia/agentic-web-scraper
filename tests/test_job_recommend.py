"""每日推荐：硬门槛过滤与去重，不改变原有决策类别。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def row(job_id, *, title='AI应用开发实习生', company='某公司', location='深圳',
        score=90, category='priority', salary=(180, 180), missing=None, preferred=None,
        status='READY_FOR_REVIEW', fallback=False, availability=''):
    # 与 score() 一致：missing_skills 始终是三个列表，不能写成单个列表。
    decision = {'category': category, 'score': score, 'recommend': category == 'priority',
                'reasons': ['技术栈重合'],
                'missing_skills': {'required': list(missing or []),
                                   'preferred': list(preferred or []),
                                   'unspecified': []},
                'fallback_only': fallback, 'salary_check': None}
    if salary is not None:
        low, high = salary
        decision['salary_check'] = {'daily_cny_range': [low, high], 'minimum': 150,
                                    'target': 180, 'target_guaranteed': low >= 180}
    else:
        # 薪资未知时偏好校准仍会给出 salary_check，只是没有明确日薪区间。
        decision['salary_check'] = {'daily_cny_range': None, 'minimum': 150, 'target': 180,
                                    'target_guaranteed': None}
    return {'id': job_id, 'status': status, 'revision': 1, 'availability_warning': availability,
            'job': {'job_title': title, 'company': company, 'location': location,
                    'salary_range': '' if salary is None else f'{salary[0]}-{salary[1]}元/天'},
            'decision': decision}


class RecommendTests(unittest.TestCase):
    def test_excludes_rejected_terminal_and_missing_skill_rows(self):
        from scraper_framework.job_workflow.recommend import select_daily
        rows = [row(1, category='reject'), row(2, status='SUBMITTED'),
                row(3, missing=['Rust']), row(4, availability='已过截止日期 2026-01-01'),
                row(5)]
        picked = select_daily(rows)
        self.assertEqual([item['row']['id'] for item in picked], [5])

    def test_excludes_unknown_salary_but_keeps_explicit_offer(self):
        from scraper_framework.job_workflow.recommend import select_daily
        picked = select_daily([row(1, salary=None), row(2, salary=(150, 180))])
        self.assertEqual([item['row']['id'] for item in picked], [2])

    def test_fallback_only_appears_when_no_main_candidate(self):
        from scraper_framework.job_workflow.recommend import select_daily
        mixed = [row(1, title='测试开发实习生', fallback=True), row(2)]
        self.assertEqual([item['row']['id'] for item in select_daily(mixed)], [2])
        only = [row(3, title='测试开发实习生', fallback=True)]
        self.assertEqual([item['row']['id'] for item in select_daily(only)], [3])

    def test_orders_by_score_then_role_then_city_and_respects_limit(self):
        from scraper_framework.job_workflow.recommend import select_daily
        rows = [row(1, score=70, location='北京', company='甲'),
                row(2, score=95, location='上海', company='乙'),
                row(3, score=95, location='广州', company='丙'),
                row(4, score=80, location='广州', company='丁')]
        for item in rows:
            item['decision']['location_priority'] = {'广州': 0, '上海': 1, '北京': 2}.get(
                item['job']['location'], 9)
        picked = select_daily(rows, limit=3)
        self.assertEqual([item['row']['id'] for item in picked], [3, 2, 4])

    def test_dedupes_same_company_but_not_unknown_companies(self):
        from scraper_framework.job_workflow.recommend import select_daily
        rows = [row(1, company='甲公司', score=99), row(2, company='甲公司', score=90),
                row(3, company='', score=88), row(4, company='', score=87)]
        picked = select_daily(rows, limit=4)
        self.assertEqual([item['row']['id'] for item in picked], [1, 3, 4])

    def test_reasons_are_short_and_evidence_based(self):
        from scraper_framework.job_workflow.recommend import select_daily
        picked = select_daily([row(1, score=92, location='广州')])
        reasons = picked[0]['reasons']
        self.assertTrue(any('92' in text for text in reasons))
        self.assertTrue(any('广州' in text for text in reasons))
        self.assertLessEqual(len(reasons), 3)

    def test_preferred_gap_stays_while_required_gap_is_blocked(self):
        from scraper_framework.job_workflow.recommend import select_daily
        rows = [row(1, preferred=['Rust']), row(2, missing=['Go'])]
        self.assertEqual([item['row']['id'] for item in select_daily(rows)], [1])

    def test_pipeline_recommends_scored_priority_job(self):
        """从抽取、评分到推荐使用真实决策，空的技能分组不能挡掉优先岗位。"""
        import tempfile
        from scraper_framework.job_workflow.service import Workflow
        profile = {'tech_stack': ['Python', 'RAG'], 'education': '本科', 'graduate_year': 2027,
                   'experience_years': 0, 'preferred_work_mode': ['onsite']}
        resume = {'projects': [{'name': '项目', 'tags': ['Python'], 'one_liner': '开发 Python 服务。'}]}
        ready = ('职位：AI应用开发实习生\n公司：演示公司\n地点：广州\n学历：本科\n'
                 '招聘对象：2027届在读\n工作方式：坐班\n任职要求：Python、RAG\n加分项：Rust\n薪资：180元/天')
        gap = ('职位：后端开发实习生\n公司：另一公司\n地点：深圳\n学历：本科\n'
               '招聘对象：2027届在读\n工作方式：坐班\n任职要求：Python、Rust\n薪资：180元/天')
        with tempfile.TemporaryDirectory() as tmp:
            flow = Workflow(Path(tmp) / 'jobs.db', profile=profile, resume=resume)
            try:
                flow.import_text(ready)
                flow.import_text(gap)
                text = flow.report_text()
            finally:
                flow.close()
        window = text.split('今日推荐', 1)[1].split('优先考虑', 1)[0]
        self.assertIn('AI应用开发实习生', window)
        self.assertNotIn('后端开发实习生', window)
        self.assertNotIn('缺必需技能', window)

    def test_report_section_lists_recommendations_and_counts(self):
        import tempfile
        from scraper_framework.job_workflow.service import Workflow
        PROFILE = {'tech_stack': ['Python', 'RAG'], 'education': '本科', 'graduate_year': 2027,
                   'experience_years': 0, 'preferred_work_mode': ['onsite']}
        RESUME = {'projects': [{'name': '项目', 'tags': ['Python'], 'one_liner': '开发 Python 服务。'}]}
        JD = '职位：AI应用开发实习生\n公司：演示公司\n学历：本科\n招聘对象：2027届在读\n工作方式：坐班\n任职要求：Python、RAG\n薪资：180元/天'
        with tempfile.TemporaryDirectory() as tmp:
            flow = Workflow(Path(tmp) / 'jobs.db', profile=PROFILE, resume=RESUME)
            try:
                flow.import_text(JD)
                text = flow.report_text()
            finally:
                flow.close()
        self.assertIn('今日推荐', text)
        self.assertIn('AI应用开发实习生', text)


    def test_exclusion_summary_explains_empty_recommendation(self):
        from scraper_framework.job_workflow.recommend import exclusion_summary
        rows = [row(1, category='reject'), row(2, missing=['Rust']), row(3, salary=None)]
        self.assertEqual(exclusion_summary(rows), {'明确不符合': 1, '缺必需技能': 1, '薪资未明确': 1})


if __name__ == '__main__':
    unittest.main()
