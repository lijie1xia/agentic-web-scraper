"""邮件通知：MIME 构造、授权码读取和 SMTP 调用，全部离线。"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scraper_framework.job_workflow import mailer


def settings(folder, **overrides):
    auth = folder / 'smtp_auth.txt'
    auth.write_text('  abcd1234\n', encoding='utf-8')
    data = {'host': 'smtp.163.com', 'port': '465', 'sender': 'a@163.com',
            'recipients': ['a@163.com'], 'auth_file': str(auth), 'subject': '岗位日报'}
    data.update(overrides)
    return data


class MailTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def test_build_message_carries_headers_and_utf8_body(self):
        message = mailer.build('岗位日报', '岗位总数: 3', 'a@163.com', ['b@163.com'])
        self.assertEqual(message['Subject'], '岗位日报')
        self.assertEqual(message['From'], 'a@163.com')
        self.assertEqual(message['To'], 'b@163.com')
        self.assertIn('岗位总数: 3', message.get_content())
        self.assertEqual(message.get_content_charset(), 'utf-8')

    def test_send_reads_auth_code_and_logs_in_then_sends(self):
        client = MagicMock()
        client.__enter__.return_value = client
        factory = MagicMock(return_value=client)
        mailer.send(settings(self.folder), '报告正文', factory=factory)
        self.assertEqual(factory.call_args.args[:2], ('smtp.163.com', 465))
        client.login.assert_called_once_with('a@163.com', 'abcd1234')
        client.send_message.assert_called_once()

    def test_missing_or_empty_auth_file_is_reported_with_setup_hint(self):
        missing = settings(self.folder, auth_file=str(self.folder / 'nope.txt'))
        with self.assertRaises(ValueError) as ctx:
            mailer.send(missing, 'x', factory=MagicMock())
        self.assertIn('set_job_mail_auth', str(ctx.exception))
        (self.folder / 'empty.txt').write_text('   \n', encoding='utf-8')
        with self.assertRaises(ValueError):
            mailer.send(settings(self.folder, auth_file=str(self.folder / 'empty.txt')), 'x', factory=MagicMock())

    def test_invalid_settings_are_rejected_before_connecting(self):
        for bad in ({'host': ''}, {'sender': ''}, {'recipients': []}, {'port': 'smtp'}):
            with self.subTest(bad=bad):
                factory = MagicMock()
                with self.assertRaises(ValueError):
                    mailer.send(settings(self.folder, **bad), 'x', factory=factory)
                factory.assert_not_called()

    def test_default_subject_includes_date_when_not_configured(self):
        message = mailer.build(None, '正文', 'a@163.com', ['a@163.com'])
        self.assertRegex(message['Subject'], r'岗位日报 \d{4}-\d{2}-\d{2}')

    def test_send_failure_surfaces_as_runtime_error(self):
        client = MagicMock()
        client.__enter__.return_value = client
        client.login.side_effect = OSError('smtp unavailable')
        with self.assertRaises(RuntimeError):
            mailer.send(settings(self.folder), 'x', factory=MagicMock(return_value=client))


if __name__ == '__main__':
    unittest.main()
