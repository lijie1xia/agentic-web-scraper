"""每日脚本只在摘要变化时输出，全部使用离线样本。"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DailyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.config = self.folder / 'sources.json'
        self.settings = {
            'database': str(self.folder / 'jobs.db'),
            'report': str(self.folder / 'report.txt'),
            'notice_state': str(self.folder / 'notice.txt'),
            'inputs': [str(ROOT / 'data/job_workflow_examples.json')],
            'boards': [],
            'allow_network': False,
        }

    def run_daily(self, output_failure=None):
        self.config.write_text(json.dumps(self.settings), encoding='utf-8')
        command = [sys.executable, '-S']
        if output_failure:
            # 在真实子进程中仅替换标准输出，岗位导入和状态读写仍走实际脚本。
            command.extend(['-c', '''
import runpy
import sys
from unittest.mock import patch

failure = sys.argv.pop(1)
sys.argv = sys.argv[1:]
sys.stderr.reconfigure(encoding='utf-8')

class FailingOutput:
    def write(self, text):
        if failure == 'write':
            raise BrokenPipeError('injected stdout write failure')
        return len(text)

    def flush(self):
        raise BrokenPipeError('injected stdout flush failure')

with patch('sys.stdout', FailingOutput()):
    runpy.run_path(sys.argv[0], run_name='__main__')
''', output_failure])
        command.extend([str(ROOT / 'scripts/run_job_daily.py'), '--config', str(self.config)])
        return subprocess.run(command, capture_output=True, text=True, encoding='utf-8', timeout=20)

    def test_output_failure_preserves_state_until_successful_retry(self):
        state = self.folder / 'notice.txt'
        previous = '此前已输出的摘要\n'.encode('utf-8')
        for failure in ('write', 'flush'):
            with self.subTest(failure=failure):
                state.write_bytes(previous)
                failed = self.run_daily(output_failure=failure)
                self.assertEqual(failed.returncode, 1, failed.stderr)
                self.assertIn(f'injected stdout {failure} failure', failed.stderr)
                self.assertEqual(state.read_bytes(), previous)
                self.assertTrue((self.folder / 'report.txt').exists())

                retry = self.run_daily()
                self.assertEqual(retry.returncode, 0, retry.stderr)
                self.assertIn('岗位总数: 3', retry.stdout)
                self.assertEqual(state.read_text(encoding='utf-8'), retry.stdout)
                saved = state.read_bytes()

                third = self.run_daily()
                self.assertEqual(third.returncode, 0, third.stderr)
                self.assertEqual(third.stdout, '')
                self.assertEqual(state.read_bytes(), saved)

    def test_unchanged_second_run_is_silent(self):
        first = self.run_daily()
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertIn('岗位总数: 3', first.stdout)
        self.assertTrue((self.folder / 'report.txt').exists())
        second = self.run_daily()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(second.stdout, '')

    def test_source_error_and_recovery_are_each_reported_once(self):
        self.assertEqual(self.run_daily().returncode, 0)
        self.settings['inputs'].append(str(self.folder / 'missing.json'))
        failed = self.run_daily()
        self.assertEqual(failed.returncode, 0, failed.stderr)
        self.assertIn('来源异常', failed.stdout)
        self.assertIn('missing.json', failed.stdout)
        self.assertEqual(self.run_daily().stdout, '')
        self.settings['inputs'].pop()
        recovered = self.run_daily()
        self.assertIn('岗位总数: 3', recovered.stdout)
        self.assertNotIn('来源异常', recovered.stdout)

    def test_campus_source_still_requires_network_opt_in(self):
        self.settings['inputs'] = []
        self.settings['campus'] = {'enabled': True, 'pages': 1, 'max_jobs': 4, 'known_urls': []}
        result = self.run_daily()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('来源异常', result.stdout)
        self.assertIn('联网', result.stdout)

    def test_no_sources_is_configuration_error(self):
        self.settings['inputs'] = []
        result = self.run_daily()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('来源', result.stderr)
        self.assertFalse((self.folder / 'notice.txt').exists())


if __name__ == '__main__':
    unittest.main()
