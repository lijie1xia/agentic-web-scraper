"""个人偏好只补充保守判断，不替代岗位证据（离线 unittest）。"""
import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scraper_framework.job_agent.decision import score
from scraper_framework.job_agent.skill_profile import load_skill_profile
from scraper_framework.job_workflow.service import Workflow

ROOT = Path(__file__).resolve().parents[1]
RESUME = {'projects': [{'name': '项目', 'tags': ['Python'], 'one_liner': '开发 Python 服务。'}]}


def profile():
    return json.loads((ROOT / 'data/skill_profile.demo.json').read_text(encoding='utf-8'))


def job(**changes):
    value = {'job_title': 'Python后端开发实习生', 'education': '本科',
             'experience_years': '应届', 'required_skills': ['Python'],
             'work_mode': 'onsite', 'salary_range': '180元/天'}
    value.update(changes)
    return value


class PreferenceTests(unittest.TestCase):
    def test_profile_records_confirmation_without_replacing_credentials(self):
        saved = profile()
        original = load_skill_profile()
        for field in ('deal_breakers', 'education', 'graduate_year',
                      'experience_years', 'preferred_work_mode'):
            self.assertEqual(saved[field], original[field])
        # 示例画像只在内置画像上追加公开技能，不含个人薪资和城市。
        self.assertEqual(saved['tech_stack'], original['tech_stack'] + ['LLM', 'SQL', 'Go'])
        prefs = saved.get('personal_preferences', {})
        self.assertEqual(prefs.get('location'), {
            'unrestricted': True, 'remote_allowed': True, 'overseas_allowed': True,
            'preferred_tiers': [['成都', '重庆'], ['武汉', '南京', '西安']],
            'province_preferences': []})
        self.assertEqual(saved.get('target_roles'), ['ai_application', 'backend'])
        self.assertEqual(prefs['backend_languages'], ['Java', 'Python'])
        self.assertEqual(prefs['fallback_roles'], ['testing', 'data_engineering'])
        self.assertEqual(prefs['fallback_policy'], 'only_if_no_suitable_main_roles')
        self.assertEqual(prefs['school_tier'], '本科')
        self.assertEqual(prefs['company'], {'unrestricted': True, 'job_fit_first': True})
        self.assertEqual(prefs['salary'], {'currency': 'CNY', 'period': 'day',
                                         'target': 200, 'minimum': 100})
        self.assertEqual(prefs['availability'], {
            'confirmed_on': '2026-01-01', 'notice_weeks': [1, 2],
            'days_per_week': 4, 'full_time': True, 'duration_months': 3,
            'date_policy': 'reconfirm_before_promising_start_date'})

    def test_workflow_rejects_explicit_daily_cny_entirely_below_floor(self):
        flow = Workflow(':memory:', profile=profile(), resume=RESUME)
        self.addCleanup(flow.close)
        for salary in ('99元/天', '50-99元/天', '99.99元/日', 'CNY 50–99/day',
                       '日薪99元', '每天99元', '人民币99元/天', '50元-99元/天'):
            with self.subTest(salary=salary):
                row = flow._ingest({'job': job(salary_range=salary)})
                self.assertEqual(row['decision']['category'], 'reject')
                self.assertFalse(row['decision']['recommend'])
                self.assertIsNone(flow.repo.latest_material(row['id']))
                self.assertIn('100', ' '.join(row['decision']['reasons']))

    def test_uncertain_pay_and_ranges_crossing_floor_require_review(self):
        from scraper_framework.job_workflow.preferences import calibrate
        candidate = profile()
        for salary in ('50-100元/天', '50-200元/天', '', None, '面议',
                       '3000元/月', '12000 CNY/month', '200/day', '200',
                       '$200/day', '200 USD/day', '200港元/天', '200日元/天',
                       '¥200/day', '100元/天起', '200元/天（含补贴）',
                       '200-100元/天', '100元/天或3000元/月', '100 200元/天', '1 00元/天'):
            with self.subTest(salary=salary):
                item = job(salary_range=salary)
                base = score(item, candidate)
                self.assertEqual(base['category'], 'priority')
                actual = calibrate(item, candidate, base)
                self.assertEqual(actual['category'], 'review')
                self.assertFalse(actual['recommend'])
                self.assertTrue(any('薪资' in warning for warning in actual['warnings']))
                self.assertEqual(actual['score'], base['score'])
                self.assertEqual(actual['skill_evidence'], base['skill_evidence'])

    def test_floor_and_target_are_distinct_and_never_upgrade_base_decision(self):
        from scraper_framework.job_workflow.preferences import calibrate
        candidate = profile()
        for salary, target_met in (('100元/天', False), ('199.99元/天', False),
                                   ('200元/天', True), ('100-200元/天', False),
                                   ('200-220元/天', True), ('RMB 200/day', True),
                                   ('200 CNY per day', True)):
            for changes, category in (({}, 'priority'), ({'required_skills': ['Rust']}, 'review'),
                                      ({'education': '博士'}, 'reject')):
                with self.subTest(salary=salary, category=category):
                    item = job(salary_range=salary, **changes)
                    base = score(item, candidate)
                    actual = calibrate(item, candidate, base)
                    self.assertEqual(actual['category'], category)
                    self.assertEqual(actual['recommend'], base['recommend'])
                    self.assertEqual(actual.get('salary_check', {}).get('target_guaranteed'), target_met)
                    self.assertEqual(actual['score'], base['score'])
                    self.assertEqual(actual['missing_skills'], base['missing_skills'])
                    self.assertEqual(actual['skill_evidence'], base['skill_evidence'])

    def test_calibration_does_not_mutate_inputs_or_share_nested_evidence(self):
        from scraper_framework.job_workflow.preferences import calibrate
        candidate = profile()
        for salary in ('99元/天', '80-200元/天', None, '200元/天'):
            item = job(salary_range=salary, education='博士')
            base = score(item, candidate)
            before = copy.deepcopy((item, candidate, base))
            actual = calibrate(item, candidate, base)
            self.assertEqual(actual['category'], 'reject')
            self.assertEqual((item, candidate, base), before)
            actual['skill_evidence'][0]['matched'] = 'changed'
            actual['warnings'].append('changed')
            self.assertEqual((item, candidate, base), before)

    def test_adjacent_roles_are_fallback_only_not_ineligible(self):
        from scraper_framework.job_workflow.preferences import calibrate
        candidate = profile()
        for title in ('测试开发实习生', '软件测试实习生', 'QA Engineer Intern',
                      'Software Testing Intern', '数据工程实习生', '数据开发实习生',
                      'Data Engineering Intern', 'Data Engineer Intern'):
            with self.subTest(title=title):
                item = job(job_title=title)
                base = score(item, candidate)
                actual = calibrate(item, candidate, base)
                self.assertIs(actual.get('fallback_only'), True)
                self.assertEqual(actual['category'], base['category'])
                self.assertNotEqual(actual['category'], 'reject')
                self.assertEqual(actual['score'], base['score'])
                self.assertEqual(actual['skill_evidence'], base['skill_evidence'])
                self.assertTrue(any('没有合适主方向' in text for text in actual['warnings']))
        for title in ('AI应用后端开发实习生', 'Java后端实习生', 'Python后端实习生',
                      '前端实习生', '数据分析实习生', 'Contest Engineer'):
            item = job(job_title=title)
            actual = calibrate(item, candidate, score(item, candidate))
            self.assertIs(actual.get('fallback_only'), False)
        # 后备岗位自身存在学历冲突时，仍保留真实硬性拒绝。
        item = job(job_title='测试开发实习生', education='博士')
        self.assertEqual(calibrate(item, candidate, score(item, candidate))['category'], 'reject')

    def test_compound_fallback_roles_require_review_even_with_main_keywords(self):
        from scraper_framework.job_workflow.preferences import calibrate
        candidate = profile()
        flow = Workflow(':memory:', profile=candidate, resume=RESUME)
        self.addCleanup(flow.close)
        titles = ('后端测试开发实习生', 'AI应用测试实习生', 'Backend QA Intern',
                  'AI Application Test Engineer Intern', '后端数据工程实习生',
                  'AI应用数据开发实习生', 'Backend Data Engineer Intern',
                  'AI Application Data Engineering Intern')
        fallback_rows = [flow._ingest({'job': job(job_title=title)}) for title in titles]
        main_rows = [flow._ingest({'job': job(job_title=title, preferred_skills=['Rust'])})
                     for title in ('AI应用后端开发实习生', 'Java后端实习生',
                                   'AI Application Backend Intern')]
        for title, row in zip(titles, fallback_rows):
            with self.subTest(title=title):
                base = score(row['job'], candidate)
                self.assertEqual(base['category'], 'priority')
                self.assertEqual(row['decision']['category'], 'review')
                self.assertIs(row['decision']['fallback_only'], True)
                self.assertFalse(row['decision']['recommend'])
                self.assertTrue(any('没有合适主方向' in warning
                                    for warning in row['decision']['warnings']))
                # 后备约束不重写技术证据、真实拒绝或薪资判断。
                for changes, category in (({}, 'review'),
                                          ({'required_skills': ['Rust']}, 'review'),
                                          ({'education': '博士'}, 'reject'),
                                          ({'salary_range': '99元/天'}, 'reject'),
                                          ({'salary_range': '80-120元/天'}, 'review')):
                    item = job(job_title=title, **changes)
                    original = score(item, candidate)
                    before = copy.deepcopy((item, candidate, original))
                    actual = calibrate(item, candidate, original)
                    self.assertEqual(actual['category'], category)
                    self.assertFalse(actual['recommend'])
                    self.assertTrue(actual['fallback_only'])
                    for field in ('score', 'skill_evidence', 'missing_skills',
                                  'graduation_evidence', 'missing_data', 'role_priority'):
                        self.assertEqual(actual[field], original[field])
                    for reason in original['reasons']:
                        self.assertIn(reason, actual['reasons'])
                    for warning in original['warnings']:
                        self.assertIn(warning, actual['warnings'])
                    salary_control = calibrate(job(**changes), candidate, original)
                    self.assertEqual(actual['salary_check'], salary_control['salary_check'])
                    self.assertEqual((item, candidate, original), before)
        for row in main_rows:
            self.assertEqual(row['decision']['category'], 'priority')
            self.assertTrue(row['decision']['recommend'])
            self.assertFalse(row['decision']['fallback_only'])
            self.assertLess(row['decision']['score'], fallback_rows[0]['decision']['score'])
        ordered = [row['id'] for row in flow.rows()]
        self.assertEqual(set(ordered[:len(main_rows)]), {row['id'] for row in main_rows})
        self.assertEqual(set(ordered[len(main_rows):]), {row['id'] for row in fallback_rows})

    def test_workflow_places_main_before_fallback_within_category(self):
        flow = Workflow(':memory:', profile=profile(), resume=RESUME)
        self.addCleanup(flow.close)
        items = [job(job_title='测试开发实习生'),
                 job(job_title='Python后端实习生', preferred_skills=['Rust']),
                 job(job_title='AI应用开发实习生', required_skills=['Rust']),
                 job(job_title='AI应用开发实习生', education='博士')]
        rows = [flow._ingest({'job': item}) for item in items]
        self.assertEqual([row['id'] for row in flow.rows()],
                         [rows[i]['id'] for i in (1, 2, 0, 3)])
        for row, item in zip(rows, items):
            base = score(item, flow.profile)
            self.assertEqual(row['decision']['category'], base['category'])
            self.assertEqual(row['decision']['score'], base['score'])
            self.assertEqual(row['decision']['skill_evidence'], base['skill_evidence'])
        # 没有主方向时，后备岗位仍展示且可人工审核，不伪造推荐。
        fallback = Workflow(':memory:', profile=profile(), resume=RESUME)
        self.addCleanup(fallback.close)
        fallback._ingest({'job': items[0]})
        only = fallback.rows()[0]
        self.assertEqual(only['decision']['category'], 'review')
        self.assertTrue(only['decision']['fallback_only'])
        self.assertIsNotNone(only['material'])

    def test_soft_locations_only_break_ties_and_never_exclude_overseas(self):
        flow = Workflow(':memory:', profile=profile(), resume=RESUME)
        self.addCleanup(flow.close)
        locations = ['海外/Remote', '西安', '南京', '武汉', '重庆', '成都', '']
        rows = [flow._ingest({'job': job(location=place)}) for place in locations]
        self.assertEqual([row['id'] for row in flow.rows()],
                         [rows[i]['id'] for i in (4, 5, 1, 2, 3, 0, 6)])
        self.assertEqual([row['decision']['category'] for row in rows], ['priority'] * len(rows))
        self.assertEqual({row['decision']['score'] for row in rows}, {100})
        self.assertEqual(rows[2]['job']['location'], '南京')
        lower_match = flow._ingest({'job': job(location='成都', preferred_skills=['Rust'])})
        self.assertEqual(flow.rows()[-1]['id'], lower_match['id'])

    def test_import_text_surfaces_salary_review_in_material_without_promises(self):
        flow = Workflow(':memory:', profile=profile(), resume=RESUME)
        self.addCleanup(flow.close)
        text = ('职位：AI应用开发实习生\n学历：本科\n招聘对象：2027届在读\n'
                '工作方式：坐班\n任职要求：Python\n薪资：80-120元/天\n'
                '到岗要求：必须明天到岗，每周6天，连续12个月')
        row = flow.import_text(text)
        self.assertEqual(row['decision']['category'], 'review')
        self.assertEqual(row['decision']['salary_check']['text'], '80-120元/天')
        material = flow.rows()[0]['material']['content']
        self.assertTrue(any('薪资范围跨越' in text for text in material['warnings']))
        self.assertTrue(any('到岗时间' in text for text in material['warnings']))
        for phrase in ('1周', '2周', '4天', '3个月', '三个月', '到岗', '2026-01-01'):
            self.assertNotIn(phrase, material['message'])
        self.assertFalse(any('到岗' in reason or '实习时长符合' in reason
                             for reason in row['decision']['reasons']))
        self.assertEqual(flow.profile['personal_preferences']['availability'],
                         profile()['personal_preferences']['availability'])

    def test_ai_role_ranks_before_backend_within_category(self):
        flow = Workflow(':memory:', profile=profile(), resume=RESUME)
        self.addCleanup(flow.close)
        backend = flow._ingest({'job': job(location='海外')})
        ai_lower = flow._ingest({'job': job(job_title='AI应用开发实习生', location='成都',
                                           preferred_skills=['Rust'])})
        ai_equal = flow._ingest({'job': job(job_title='AI应用开发实习生', location='海外')})
        self.assertLess(ai_lower['decision']['score'], backend['decision']['score'])
        self.assertEqual([row['id'] for row in flow.rows()],
                         [ai_equal['id'], ai_lower['id'], backend['id']])

    def test_full_time_ranks_after_internship_within_category(self):
        flow = Workflow(':memory:', profile=profile(), resume=RESUME)
        self.addCleanup(flow.close)
        full_time = flow._ingest({'job': job(job_title='AI应用开发工程师', salary_range='11-20K',
                                             employment_type='full_time')})
        intern = flow._ingest({'job': job(job_title='Java后端实习生', salary_range='',
                                          employment_type='internship')})
        self.assertEqual({full_time['decision']['category'], intern['decision']['category']}, {'review'})
        self.assertEqual([row['id'] for row in flow.rows()], [intern['id'], full_time['id']])
        self.assertTrue(any('应届全职岗' in text for text in full_time['decision']['warnings']))

    def test_profiles_without_personal_preferences_keep_existing_behavior(self):
        from scraper_framework.job_workflow.preferences import calibrate
        candidate = load_skill_profile()
        for item in (job(salary_range='100元/天'), job(salary_range=''),
                     job(job_title='测试开发实习生')):
            base = score(item, candidate)
            self.assertEqual(calibrate(item, candidate, base), base)


if __name__ == '__main__':
    unittest.main()
