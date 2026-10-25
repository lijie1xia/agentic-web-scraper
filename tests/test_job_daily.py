"""每日脚本只在摘要变化时输出，全部使用离线样本。"""
import io
import json
import runpy
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

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

    def configure_notification(self, response='{"success": true}', returncode=0, enabled=True):
        # 本机替身只记录参数和标准输入，绝不调用 Hermes 或网络。
        helper = self.folder / 'fake_hermes.py'
        helper.write_text('''
import json
import sys
from pathlib import Path

folder = Path(sys.argv[1])
state = folder / 'notice.txt'
sys.stdin.reconfigure(encoding='utf-8')
record = {
    'args': sys.argv[4:],
    'notice': sys.stdin.read(),
    'previous': state.read_text(encoding='utf-8') if state.exists() else None,
}
with (folder / 'sent.jsonl').open('a', encoding='utf-8') as stream:
    stream.write(json.dumps(record, ensure_ascii=False) + '\\n')
sys.stdout.reconfigure(encoding='utf-8')
print(json.loads(sys.argv[2])['response'])
raise SystemExit(int(sys.argv[3]))
''', encoding='utf-8')
        self.settings['notification'] = {
            'enabled': enabled,
            'target': 'weixin',
            'command': [sys.executable, '-S', str(helper), str(self.folder),
                        json.dumps({'response': response}), str(returncode)],
        }

    def sent_notices(self):
        log = self.folder / 'sent.jsonl'
        return [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()] if log.exists() else []

    def test_notification_success_advances_state_after_cli_acceptance(self):
        self.configure_notification()
        state = self.folder / 'notice.txt'
        state.write_text('旧摘要\n', encoding='utf-8')
        result = self.run_daily()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('岗位总数: 3', result.stdout)
        self.assertEqual(self.sent_notices(), [{
            'args': ['send', '--to', 'weixin', '--json'],
            'notice': result.stdout,
            'previous': '旧摘要\n',
        }])
        self.assertEqual(state.read_text(encoding='utf-8'), result.stdout)

    def test_notification_command_failure_preserves_state_without_retry(self):
        self.configure_notification(returncode=7)
        state = self.folder / 'notice.txt'
        previous = '旧摘要\n'.encode('utf-8')
        state.write_bytes(previous)
        result = self.run_daily()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('岗位总数: 3', result.stdout)
        self.assertIn('通知', result.stderr)
        self.assertEqual(state.read_bytes(), previous)
        self.assertEqual(len(self.sent_notices()), 1)

    def test_notification_requires_json_object_with_literal_success_true(self):
        state = self.folder / 'notice.txt'
        previous = '旧摘要\n'.encode('utf-8')
        for response in ('{"success": false}', '{"success": 1}', '{"success": "true"}',
                         '{}', '[]', 'null', 'true', 'not json', ''):
            with self.subTest(response=response):
                self.configure_notification(response=response)
                state.write_bytes(previous)
                before = len(self.sent_notices())
                result = self.run_daily()
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn('岗位总数: 3', result.stdout)
                self.assertEqual(state.read_bytes(), previous)
                self.assertEqual(len(self.sent_notices()), before + 1)

    def test_invalid_notification_config_fails_without_sending(self):
        self.configure_notification()
        valid = self.settings['notification'].copy()
        invalid = [None, [], {}, {**valid, 'enabled': 'true'}, {**valid, 'enabled': 1},
                   {**valid, 'enabled': None}, {**valid, 'target': 'telegram'},
                   {**valid, 'command': []}, {**valid, 'command': 'hermes'},
                   {**valid, 'command': ['']}, {**valid, 'command': [None]},
                   {key: value for key, value in valid.items() if key != 'command'}]
        state = self.folder / 'notice.txt'
        previous = '旧摘要\n'.encode('utf-8')
        for notification in invalid:
            with self.subTest(notification=notification):
                self.settings['notification'] = notification
                state.write_bytes(previous)
                result = self.run_daily()
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn('通知配置', result.stderr)
                self.assertNotIn('Traceback', result.stderr)
                self.assertEqual(self.sent_notices(), [])
                self.assertEqual(state.read_bytes(), previous)

    def test_notification_timeout_preserves_state_without_retry(self):
        self.configure_notification()
        self.config.write_text(json.dumps(self.settings), encoding='utf-8')
        state = self.folder / 'notice.txt'
        previous = '旧摘要\n'.encode('utf-8')
        state.write_bytes(previous)
        main = runpy.run_path(str(ROOT / 'scripts/run_job_daily.py'))['main']
        real_run = subprocess.run
        attempts = []

        def timeout_send(command, **kwargs):
            if '--to' in command:
                attempts.append((command, kwargs))
                raise subprocess.TimeoutExpired(command, kwargs['timeout'])
            return real_run(command, **kwargs)

        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr), patch('subprocess.run', side_effect=timeout_send):
            result = main(['--config', str(self.config)])
        self.assertEqual(result, 1)
        self.assertIn('岗位总数: 3', stdout.getvalue())
        self.assertIn('timed out', stderr.getvalue())
        self.assertEqual(state.read_bytes(), previous)
        self.assertEqual(len(attempts), 1)
        command, kwargs = attempts[0]
        self.assertEqual(command, self.settings['notification']['command'] + ['send', '--to', 'weixin', '--json'])
        self.assertEqual(kwargs['input'], stdout.getvalue())
        self.assertEqual(kwargs['encoding'], 'utf-8')
        self.assertEqual(kwargs['timeout'], 30)
        self.assertIs(kwargs['shell'], False)
        self.assertIs(kwargs['capture_output'], True)
        self.assertIs(kwargs['text'], True)

    def test_unchanged_notification_is_silent_without_send(self):
        self.configure_notification()
        first = self.run_daily()
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(len(self.sent_notices()), 1)
        state = self.folder / 'notice.txt'
        saved = state.read_bytes()
        second = self.run_daily()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(second.stdout, '')
        self.assertEqual(len(self.sent_notices()), 1)
        self.assertEqual(state.read_bytes(), saved)

    def test_disabled_or_absent_notification_only_updates_stdout_state(self):
        for present in (False, True):
            with self.subTest(present=present):
                self.configure_notification(enabled=False)
                if not present:
                    self.settings.pop('notification')
                state = self.folder / 'notice.txt'
                state.write_text('旧摘要\n', encoding='utf-8')
                result = self.run_daily()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('岗位总数: 3', result.stdout)
                self.assertEqual(self.sent_notices(), [])
                self.assertEqual(state.read_text(encoding='utf-8'), result.stdout)

    def test_stdout_failure_prevents_notification(self):
        self.configure_notification()
        state = self.folder / 'notice.txt'
        previous = '旧摘要\n'.encode('utf-8')
        for failure in ('write', 'flush'):
            with self.subTest(failure=failure):
                state.write_bytes(previous)
                result = self.run_daily(output_failure=failure)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn(f'injected stdout {failure} failure', result.stderr)
                self.assertEqual(state.read_bytes(), previous)
                self.assertEqual(self.sent_notices(), [])

    def test_missing_notification_executable_preserves_state(self):
        self.configure_notification()
        self.settings['notification']['command'] = [str(self.folder / 'missing-hermes.exe')]
        result = self.run_daily()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('岗位总数: 3', result.stdout)
        self.assertFalse((self.folder / 'notice.txt').exists())
        self.assertEqual(self.sent_notices(), [])

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

    def test_committed_default_config_keeps_network_and_notifications_disabled(self):
        settings = json.loads((ROOT / 'config/job_sources.json').read_text(encoding='utf-8'))
        self.assertIs(settings['allow_network'], False)
        self.assertEqual(settings.get('notification'), {
            'enabled': False, 'target': 'weixin', 'command': ['hermes'],
        })

    def test_no_sources_is_configuration_error(self):
        self.settings['inputs'] = []
        result = self.run_daily()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('来源', result.stderr)
        self.assertFalse((self.folder / 'notice.txt').exists())


if __name__ == '__main__':
    unittest.main()
