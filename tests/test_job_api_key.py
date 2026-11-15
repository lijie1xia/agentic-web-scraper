"""访客自带 API Key 的透传：不读写环境变量，不发起真实请求。"""
import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CAMEL_READY = importlib.util.find_spec("camel") is not None


@unittest.skipUnless(CAMEL_READY, "需要 camel 才能构造 ChatAgent 调用路径")
class ApiKeyPassthroughTests(unittest.TestCase):
    def test_greeting_uses_explicit_key_without_touching_env(self):
        from scraper_framework.job_agent import generate
        decision = {'recommend': True, 'category': 'priority', 'score': 90,
                    'reasons': ['技术栈重合'], 'skill_evidence': []}
        job = {'job_title': 'AI应用开发实习生', 'tech_stack': ['Python'], 'required_skills': ['Python']}
        resume = {'projects': [{'name': '项目', 'tags': ['Python'], 'one_liner': '开发 Python 服务。'}]}
        with mock.patch.dict('os.environ', {}, clear=False) as env:
            env.pop('DEEPSEEK_API_KEY', None)
            with mock.patch('scraper_framework.tools.model_factory.get_model') as get_model, \
                    mock.patch('camel.agents.ChatAgent'):
                get_model.return_value = object()
                generate.generate_greeting(job, decision, resume, api_key='visitor-key')
        self.assertEqual(get_model.call_args.kwargs.get('api_key'), 'visitor-key')

    def test_text_extraction_uses_explicit_key(self):
        from scraper_framework.job_agent import extract
        with mock.patch.object(extract, 'get_model') as get_model, \
                mock.patch.object(extract, 'ChatAgent'):
            get_model.return_value = object()
            extract.extract_jd_from_text('职位：后端开发实习生\n任职要求：Python', max_retries=1, api_key='visitor-key')
        self.assertEqual(get_model.call_args.kwargs.get('api_key'), 'visitor-key')


if __name__ == '__main__':
    unittest.main()
