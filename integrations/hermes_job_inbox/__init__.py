"""微信私聊收件：只追加文本，不调用模型，不回复。

2026-10-26 核对 Hermes 微信适配器：入站只提取文本、图片、语音、文件、视频。
分享卡片和截图不会变成 JD 正文，因此这里只接收文本；其他类型交回 Hermes。
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

MAX_TEXT = 100000


def _kind(event):
    value = getattr(event, 'message_type', 'text')
    return str(getattr(value, 'value', value)).lower()


def capture(event, **kwargs):
    """白名单私聊文本写入收件箱并跳过模型。其余情况返回 None，由 Hermes 照常处理。"""
    try:
        path = os.environ.get('JOB_INBOX_PATH', '').strip()
        allowed = {item.strip() for item in os.environ.get('JOB_INBOX_USERS', '').split(',') if item.strip()}
        source = getattr(event, 'source', None)
        user_id = getattr(source, 'user_id', None)
        if (not path or not allowed or getattr(source, 'chat_type', '') != 'dm'
                or user_id not in allowed or _kind(event) != 'text'):
            return None
        text = getattr(event, 'text', None)
        message_id = getattr(event, 'message_id', None)
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT:
            return None
        if not isinstance(message_id, str) or not message_id.strip():
            return None
        received = getattr(event, 'timestamp', None)
        record = {
            'message_id': message_id,
            'received_at': received.isoformat() if isinstance(received, datetime) else datetime.now(timezone.utc).isoformat(),
            'text': text,
        }
        with open(path, 'a', encoding='utf-8') as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + '\n')
        return {'action': 'skip', 'reason': 'job-inbox'}
    except Exception:
        return None


def register(ctx):
    ctx.register_hook('pre_gateway_dispatch', capture)
