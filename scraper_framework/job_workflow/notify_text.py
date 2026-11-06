"""把日报转成邮件友好的纯文本：去掉 markdown 记号，岗位之间空行分隔。"""
from __future__ import annotations

import re

_JOB_LINE = re.compile(r'^#(\d+)\s+(.+?)\s*\|\s*([^|]+?)\s*\|\s*(.+)$')
_MARKUP = re.compile(r'(\*\*|__|^#{1,6}\s+)')


def to_plain(text):
    """按段落拼装，岗位条目各占一段，避免一整片竖线分隔的密排文本。"""
    blocks, paragraph = [], []

    def flush():
        if paragraph:
            blocks.append('\n'.join(paragraph))
            paragraph.clear()

    for raw in text.replace('\r\n', '\n').split('\n'):
        line = _MARKUP.sub('', raw).rstrip()
        match = _JOB_LINE.match(line.strip())
        if match:
            flush()
            job_id, title, status, note = (part.strip() for part in match.groups())
            blocks.append(f'[{job_id}] {title}\n    状态：{status}\n    说明：{note}')
        elif line.strip():
            paragraph.append(line)
        else:
            flush()
    flush()
    return '\n\n'.join(blocks) + '\n' if blocks else ''
