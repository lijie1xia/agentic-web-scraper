"""用真实招聘 App 复制格式（已脱敏精简）校准筛选规则（离线 unittest）。"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scraper_framework.job_agent.evaluation import role_matches
from scraper_framework.job_workflow.offline import extract_text
from scraper_framework.job_workflow.service import Workflow

ROOT = Path(__file__).resolve().parents[1]
RESUME = {'projects': [{'name': '项目', 'tags': ['Python'], 'one_liner': '开发 Python 服务。'}]}

AGENT_INTERN = """Agent实习
 300-500元/天
深圳 5天/周 6个月 本科
公司基本信息
职位描述
- Golang
- Python
【岗位职责】
1、负责 AI Agent 执行引擎的核心开发，设计任务拆解、工具调用、上下文管理等。
职位要求
1、本科及以上学历在读，计算机、软件工程等相关专业优先；
2、了解LLM原理，需要有使用LLM进行项目开发和效果调优的经验；
3、了解AI Agent技术栈（如 ToolUse、Skills、ReAct、Multi-Agent），具备扎实的代码能力；
"""

INLINE_SALARY = """Java开发工程师（长期实习）提供转正200-300元/天
广州-天河区  实习  4天/周  3个月  本科  学生可投  招2人
职位要求:
1、熟练掌握Java编程语言，熟悉Spring框架相关技术
"""

FULL_TIME = """Agent开发工程师（应届生）
 11-20K
深圳 经验不限 本科
岗位职责
参与RAG知识库、智能工具调用、对话智能体等模块的开发与调试。
任职要求
1、掌握Python基础，了解大模型应用、RAG、Agent框架基础原理即可。
"""

GENERIC_AI = """AI实习生
 150-180元/天
广州 4天/周 3个月 本科
岗位职责:
1.Agent 应用开发：参与基于大模型的 Agent 应用的编码实现。
岗位要求：
1.熟悉springboot，会使用TypeScript、 Python更好。
"""

CLOSED = """AI 创新专项实习生（Agent 开发方向）
 200-300元/天
深圳 3天/周 2个月 学历不限
职位已关闭
职位描述
搭 Agent 工作流：基于产品需求的场景下，搭建可以自动运转的 agent pipeline
"""

LABELING = """数据标记/采集实习生（27届）
 160-170元/天
深圳 5天/周 3个月 本科
岗位职责：
1. 协助完成数据的标记与采集工作；
任职要求：
1. 2027届毕业生，本科及以上学历在读；
"""

AIGC_VIDEO = """AIGC实习生（Ai视频、Ai漫剧方向）4-5k
广州  经验不限  学历不限  招20人
工作内容
1、基于公司不同AIGC场景与需求，进行AI视频制作、视频剪辑等。
"""

ELITE_SCHOOL = """科研助手（RA）Agent方向
 300-350元/天
深圳 5天/周 12个月 本科
任职要求
- 211院校本科以上学历，具有计算机或其他相关理工科背景；
- 熟练使用 Linux、Git 等基本开发环境；
"""

EXPERIENCE_WITH_FRESH = """Java开发工程师（Agent应用）
 6-10K
广州 1-3年 大专
任职要求：
1. 1-3年相关开发经验，优秀应届生或有实际 AI 应用、智能体搭建者也可考虑。
2. 熟悉 Java EE技术体系，熟悉Spring Boot等主流框架
"""


def profile():
    return json.loads((ROOT / 'data/skill_profile.json').read_text(encoding='utf-8'))


class HeaderExtractionTests(unittest.TestCase):
    def test_reads_unlabeled_app_header(self):
        job = extract_text(AGENT_INTERN)
        self.assertEqual((job['job_title'], job['salary_range'], job['location']),
                         ('Agent实习', '300-500元/天', '深圳'))
        self.assertEqual((job['days_per_week'], job['internship_months']), (5, 6))
        # 正文条款比头部摘要更具体，头部只补空字段。
        self.assertTrue(job['education'].startswith('本科及以上学历在读'))
        self.assertEqual(extract_text(INLINE_SALARY)['education'], '本科')
        self.assertEqual(job['employment_type'], 'internship')
        self.assertTrue(any(item.get('status') == 'header' for item in job['evidence']))

    def test_salary_on_title_line_and_district_location(self):
        job = extract_text(INLINE_SALARY)
        self.assertEqual(job['job_title'], 'Java开发工程师（长期实习）提供转正')
        self.assertEqual(job['salary_range'], '200-300元/天')
        self.assertEqual(job['location'], '广州-天河区')
        self.assertEqual(job['employment_type'], 'internship')

    def test_monthly_salary_is_full_time(self):
        job = extract_text(FULL_TIME)
        self.assertEqual(job['salary_range'], '11-20K')
        self.assertEqual(job['experience_years'], '经验不限')
        self.assertEqual(job['employment_type'], 'full_time')

    def test_labels_take_precedence_and_plain_first_line_is_not_title(self):
        labeled = extract_text('职位：Python后端实习生\n 200元/天\n深圳 5天/周 6个月 本科')
        self.assertEqual(labeled['job_title'], 'Python后端实习生')
        self.assertEqual(extract_text('Some unlabeled title\nPython')['job_title'], '')

    def test_react_paradigm_is_not_react_framework(self):
        job = extract_text(AGENT_INTERN)
        self.assertNotIn('React', job['required_skills'] + job['tech_stack'])
        self.assertIn('React', extract_text('任职要求\n熟悉 React 和 Python')['required_skills'])

    def test_closed_posting_is_recorded(self):
        self.assertTrue(extract_text(CLOSED).get('posting_closed'))
        self.assertNotIn('posting_closed', extract_text(AGENT_INTERN))

    def test_header_experience_conflicting_with_fresh_grad_text_is_not_recorded(self):
        job = extract_text(EXPERIENCE_WITH_FRESH)
        self.assertEqual(job['experience_years'], '')
        self.assertTrue(any('正文接受应届' in text for text in job['warnings']))


class RoleTests(unittest.TestCase):
    def test_sample_titles_map_to_role_families(self):
        for title in ('Agent实习', 'RAG研发工程师', 'AI技术开发管培生', '科研助手（RA）Agent方向',
                      'AI Agent 开发实习生', 'AI agent开发工程师', '大模型应用开发实习生'):
            with self.subTest(title=title):
                self.assertTrue(role_matches(title, 'ai_application'))
        for title in ('Java开发工程师（长期实习）', 'Python开发实习生', 'Golang后端实习生'):
            with self.subTest(title=title):
                self.assertTrue(role_matches(title, 'backend'))
        for title in ('前端开发实习生', 'Storage Engineer', 'MongoDB 运维', 'AIGC实习生', 'Agency Sales'):
            with self.subTest(title=title):
                self.assertFalse(role_matches(title, 'ai_application') or role_matches(title, 'backend'))


class SampleDecisionTests(unittest.TestCase):
    def setUp(self):
        self.flow = Workflow(':memory:', profile=profile(), resume=RESUME)
        self.addCleanup(self.flow.close)

    def test_wanted_internships_reach_priority(self):
        for text in (AGENT_INTERN, GENERIC_AI):
            with self.subTest(title=text.splitlines()[0]):
                row = self.flow.import_text(text)
                self.assertEqual(row['decision']['category'], 'priority')
                self.assertEqual(row['decision']['role_priority'], 0)
        generic = self.flow.rows()[-1]['decision']
        self.assertTrue(any('按职责原文判断方向' in text for text in generic['reasons']))

    def test_generic_ai_title_without_development_duties_is_not_inferred(self):
        row = self.flow.import_text('AI实习生\n 150元/天\n广州 5天/周 3个月 本科\n岗位职责：\n整理大模型资讯\n')
        self.assertIsNone(row['decision']['role_priority'])

    def test_unwanted_roles_and_closed_postings_are_rejected(self):
        for text, reason in ((LABELING, '数据标注/采集'), (AIGC_VIDEO, 'AIGC 内容制作'), (CLOSED, '已关闭')):
            with self.subTest(reason=reason):
                row = self.flow.import_text(text)
                self.assertEqual(row['decision']['category'], 'reject')
                self.assertTrue(any(reason in text for text in row['decision']['reasons']))
        crawler = self.flow.import_text('数据采集开发实习生\n 200元/天\n深圳 5天/周 6个月 本科\n任职要求\nPython\n')
        self.assertNotEqual(crawler['decision']['category'], 'reject')

    def test_elite_school_requirement_needs_review(self):
        row = self.flow.import_text(ELITE_SCHOOL)
        self.assertEqual(row['decision']['category'], 'review')
        self.assertTrue(any('211' in text for text in row['decision']['warnings']))

    def test_full_time_new_grad_is_review_and_after_internships(self):
        full = self.flow.import_text(FULL_TIME)
        intern = self.flow.import_text(INLINE_SALARY)
        self.assertEqual(full['decision']['category'], 'review')
        ordered = [row['id'] for row in self.flow.rows()]
        self.assertLess(ordered.index(intern['id']), ordered.index(full['id']))

    def test_zhejiang_city_counts_as_province_tier(self):
        row = self.flow.import_text(AGENT_INTERN.replace('深圳 5天', '杭州 5天'))
        self.assertEqual(row['decision']['location_priority'], 1)


if __name__ == '__main__':
    unittest.main()
