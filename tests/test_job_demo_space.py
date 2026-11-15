"""公开 Demo 的免费路径与访客 Key 透传；不联网、不调用模型。"""
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

JD = '职位：AI应用开发实习生\n公司：某智能科技\n任职要求：\n- 本科在读\n- 熟悉 Python、LangChain\n'


def _load_app():
    spec = importlib.util.spec_from_file_location('job_demo_app', ROOT / 'spaces/job_demo/app.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DemoSpaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _load_app()

    def test_free_path_uses_rules_and_never_asks_for_a_key(self):
        extract, score, greeting = self.app.run_pipeline(JD, '')
        self.assertIn('规则抽取，未调用模型', extract)
        self.assertIn('AI应用开发实习生', extract)
        self.assertIn('推荐', score)
        self.assertIn('预置示例文案', greeting)
        self.assertIn('高级选项', greeting)

    def test_empty_text_returns_prompt_without_outputs(self):
        extract, score, greeting = self.app.run_pipeline('   ', '')
        self.assertIn('请先粘贴', extract)
        self.assertEqual((score, greeting), ('', ''))

    def test_visitor_key_is_forwarded_to_both_calls(self):
        seen = {}
        fake_extract = types.ModuleType('scraper_framework.job_agent.extract')
        fake_generate = types.ModuleType('scraper_framework.job_agent.generate')

        def extract(text, **kwargs):
            seen['extract'] = kwargs.get('api_key')
            return {'job_title': 'AI应用开发实习生', 'company': '某公司', 'required_skills': ['Python'],
                    'tech_stack': ['Python'], 'preferred_skills': []}

        def greeting(job, decision, resume, **kwargs):
            seen['greeting'] = kwargs.get('api_key')
            return [{'style': '简洁直接版', 'text': '您好，这是一段由访客 Key 生成的示例文案。'}]

        fake_extract.extract_jd_from_text = extract
        fake_generate.generate_greeting = greeting
        with mock.patch.dict(sys.modules, {
            'scraper_framework.job_agent.extract': fake_extract,
            'scraper_framework.job_agent.generate': fake_generate,
        }):
            extract_md, score_md, greetings = self.app.run_pipeline(JD, 'sk-visitor')
        self.assertEqual(seen, {'extract': 'sk-visitor', 'greeting': 'sk-visitor'})
        self.assertIn('模型抽取（你的 Key）', extract_md)
        self.assertIn('简洁直接版', greetings)

    def test_auth_error_is_reported_without_leaking_the_key(self):
        fake_extract = types.ModuleType('scraper_framework.job_agent.extract')

        def boom(*args, **kwargs):
            raise RuntimeError('401 Unauthorized: invalid api key')

        fake_extract.extract_jd_from_text = boom
        with mock.patch.dict(sys.modules, {'scraper_framework.job_agent.extract': fake_extract}):
            extract_md, _, _ = self.app.run_pipeline(JD, 'sk-secret-value')
        self.assertIn('Key 无效或余额不足', extract_md)
        self.assertNotIn('sk-secret-value', extract_md)


if __name__ == '__main__':
    unittest.main()
