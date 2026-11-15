"""部署脚本的代理开关：默认直连，只在显式配置时临时生效。"""
import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _load_deploy():
    spec = importlib.util.spec_from_file_location('job_demo_deploy', ROOT / 'spaces/job_demo/deploy.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DeployProxyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.deploy = _load_deploy()

    def test_without_proxy_environment_is_untouched(self):
        with mock.patch.dict(os.environ, {'HTTPS_PROXY': 'http://keep:1'}, clear=False):
            with self.deploy.proxy_environment(None):
                self.assertEqual(os.environ['HTTPS_PROXY'], 'http://keep:1')
            self.assertEqual(os.environ['HTTPS_PROXY'], 'http://keep:1')

    def test_proxy_is_applied_only_inside_the_block_and_restored(self):
        with mock.patch.dict(os.environ, {'HTTPS_PROXY': 'http://old:1'}, clear=False):
            with self.deploy.proxy_environment('http://127.0.0.1:7890'):
                for key in self.deploy.PROXY_ENV_KEYS:
                    self.assertEqual(os.environ[key], 'http://127.0.0.1:7890')
            self.assertEqual(os.environ['HTTPS_PROXY'], 'http://old:1')
            self.assertNotIn('HTTP_PROXY', os.environ)

    def test_proxy_defaults_to_environment_switch_not_hardcoded(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch.object(sys, 'argv', ['deploy.py']), \
                mock.patch.object(self.deploy, 'upload_hf') as upload:
            self.deploy.main()
        self.assertIsNone(upload.call_args.kwargs['proxy'])

        with mock.patch.dict(os.environ, {'HF_PROXY': 'http://10.0.0.2:8080'}, clear=True), \
                mock.patch.object(sys, 'argv', ['deploy.py']), \
                mock.patch.object(self.deploy, 'upload_hf') as upload:
            self.deploy.main()
        self.assertEqual(upload.call_args.kwargs['proxy'], 'http://10.0.0.2:8080')

    def test_explicit_flag_wins_over_environment(self):
        with mock.patch.dict(os.environ, {'HF_PROXY': 'http://env:1'}, clear=True), \
                mock.patch.object(sys, 'argv', ['deploy.py', '--proxy', 'http://flag:2']), \
                mock.patch.object(self.deploy, 'upload_hf') as upload:
            self.deploy.main()
        self.assertEqual(upload.call_args.kwargs['proxy'], 'http://flag:2')


if __name__ == '__main__':
    unittest.main()
