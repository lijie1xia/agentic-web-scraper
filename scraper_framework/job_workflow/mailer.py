"""邮件通知：只从本机文件读取授权码，不写日志、不进仓库。"""
from __future__ import annotations

import smtplib
import ssl
from datetime import date
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path


def _auth_code(path):
    file = Path(path)
    if not file.is_file():
        raise ValueError(f'缺少邮箱授权码文件：{file}；先运行 scripts/set_job_mail_auth.py 写入')
    code = file.read_text(encoding='utf-8-sig').strip()
    if not code:
        raise ValueError('邮箱授权码文件为空，重新运行 scripts/set_job_mail_auth.py')
    return code


def build(subject, text, sender, recipients):
    """构造纯文本邮件，主题缺省时带上当天日期。"""
    message = EmailMessage()
    message['Subject'] = subject or f'岗位日报 {date.today().isoformat()}'
    message['From'] = sender
    message['To'] = ', '.join(recipients)
    message['Date'] = formatdate(localtime=True)
    message['Message-ID'] = make_msgid()
    message.set_content(text, subtype='plain', charset='utf-8')
    return message


def send(settings, text, *, factory=smtplib.SMTP_SSL, context=None):
    """按配置发信；失败统一转成 RuntimeError，由调用方决定是否推进状态。"""
    host = str(settings.get('host') or '').strip()
    sender = str(settings.get('sender') or '').strip()
    recipients = [str(item).strip() for item in settings.get('recipients') or [] if str(item).strip()]
    try:
        port = int(settings.get('port') or 465)
    except (TypeError, ValueError):
        raise ValueError('邮箱端口必须是数字') from None
    if not host or not sender or not recipients:
        raise ValueError('邮箱通知需要 host、sender 和至少一个 recipients')
    message = build(settings.get('subject'), text, sender, recipients)
    code = _auth_code(settings.get('auth_file') or '')
    try:
        with factory(host, port, context=context or ssl.create_default_context(), timeout=30) as client:
            client.login(sender, code)
            client.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise RuntimeError(f'邮件发送失败：{exc}') from None
    return {'sent': len(recipients)}
