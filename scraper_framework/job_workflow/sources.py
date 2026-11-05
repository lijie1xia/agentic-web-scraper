"""Bounded, read-only discovery. No credentials or application POST endpoint.

Greenhouse documents its unauthenticated published-job GET API at
https://developers.greenhouse.io/job-board.html . Network access is opt-in.
"""
from __future__ import annotations

import html
import json
import re
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

MAX_BYTES = 16 * 1024 * 1024
MAX_JOBS = 10000
LEVER_HOST = 'jobs.lever.co'
# Lever 一次性返回整个看板，但没有总数可核对，因此不据此判定岗位下架。
LEVER_COMPLETE_SNAPSHOT = False


class _TextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style'}:
            self.hidden += 1
        elif tag in {'p', 'br', 'li', 'div', 'h1', 'h2', 'h3'} and not self.hidden:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in {'script', 'style'} and self.hidden:
            self.hidden -= 1
        elif tag in {'p', 'li', 'div', 'h1', 'h2', 'h3'} and not self.hidden:
            self.parts.append('\n')

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def html_to_text(value: str) -> str:
    parser = _TextParser()
    parser.feed(html.unescape(value))
    return '\n'.join(line.strip() for line in ''.join(parser.parts).splitlines() if line.strip())


def _validate_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {'https', 'http'} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('岗位链接必须是无凭据的 HTTP(S) URL')
    return value


def load_export(path: str | Path) -> list[dict]:
    """Read old extract/scored/greeted JSON; always re-evaluate imported jobs."""
    path = Path(path)
    if path.stat().st_size > MAX_BYTES:
        raise ValueError('导入文件超过大小限制')
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(data, list) or len(data) > MAX_JOBS:
        raise ValueError('导入必须是有界的岗位 JSON 数组')
    rows = []
    for item in data:
        if not isinstance(item, dict):
            raise ValueError('每条岗位必须是 JSON 对象')
        job = item.get('job', item)
        if not isinstance(job, dict) or not any(job.get(key) for key in ('job_title', 'source_url', 'raw_jd')):
            raise ValueError('岗位缺少名称、来源链接或原文')
        job = dict(job)
        if job.get('source_url') and not str(job['source_url']).startswith('paste://'):
            _validate_url(str(job['source_url']))
        raw = item.get('raw_jd') or job.get('raw_jd') or ''
        if not isinstance(raw, str):
            raise ValueError('raw_jd 必须是文本')
        rows.append({'job': job, 'source': 'manual', 'raw_jd': raw})
    return rows


def greenhouse_url(board_token: str) -> str:
    if not isinstance(board_token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', board_token):
        raise ValueError('board_token 只允许字母、数字、下划线和短横线')
    return f'https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true'


def parse_greenhouse(payload: dict, board_token: str) -> list[dict]:
    greenhouse_url(board_token)
    if not isinstance(payload, dict) or not isinstance(payload.get('jobs'), list):
        raise ValueError('Greenhouse 返回格式异常')
    posts = payload['jobs']
    if len(posts) > MAX_JOBS:
        raise ValueError('岗位数量超过本地处理上限')
    meta = payload.get('meta')
    if meta is not None and not isinstance(meta, dict):
        raise ValueError('Greenhouse meta 必须是对象或空值')
    total = (meta or {}).get('total')
    if total is not None and (not isinstance(total, int) or total != len(posts)):
        raise ValueError('岗位快照不完整：总数与返回条数不符，不可据此判定岗位下架')
    result = []
    ids = set()
    for post in posts:
        if not isinstance(post, dict) or not post.get('id') or not post.get('title'):
            raise ValueError('岗位缺少官方 ID 或标题')
        external_id = str(post['id'])
        if external_id in ids:
            raise ValueError('官方快照包含重复岗位 ID')
        ids.add(external_id)
        url = _validate_url(str(post.get('absolute_url') or ''))
        content = post.get('content') or ''
        if not isinstance(content, str):
            raise ValueError('岗位正文格式错误')
        raw = html_to_text(content)
        location = post.get('location')
        if location is not None and not isinstance(location, dict):
            raise ValueError('Greenhouse location 必须是对象或空值')
        result.append({
            'source': f'greenhouse:{board_token}',
            'raw_jd': raw,
            'job': {
                'external_id': external_id, 'source_url': url,
                'job_title': str(post['title']),
                'company': str(post.get('company_name') or ''),
                'location': str((location or {}).get('name') or ''),
                'source_updated_at': str(post.get('updated_at') or ''),
            },
        })
    return result


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('来源发生重定向，需人工核验，未继续请求')


def lever_url(site: str) -> str:
    """Lever 公开看板 JSON 接口；只允许简单的 site token。"""
    if not isinstance(site, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', site):
        raise ValueError('Lever site 只允许字母、数字、下划线和短横线')
    return f'https://api.lever.co/v0/postings/{site}?mode=json'


def _lever_time(value) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return ''
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()


def parse_lever(payload, site: str) -> list[dict]:
    """把 Lever 看板 JSON 转成岗位行；字段缺失或域名不符直接报错。"""
    lever_url(site)
    if not isinstance(payload, list):
        raise ValueError('Lever 返回格式异常')
    if len(payload) > MAX_JOBS:
        raise ValueError('岗位数量超过本地处理上限')
    result, ids = [], set()
    for post in payload:
        if not isinstance(post, dict) or not post.get('id') or not post.get('text'):
            raise ValueError('岗位缺少官方 ID 或标题')
        external_id = str(post['id'])
        if external_id in ids:
            raise ValueError('官方快照包含重复岗位 ID')
        ids.add(external_id)
        url = _validate_url(str(post.get('hostedUrl') or ''))
        if urlsplit(url).scheme != 'https' or urlsplit(url).hostname != LEVER_HOST:
            raise ValueError('岗位链接不是 Lever 官方域名')
        categories = post.get('categories')
        if categories is not None and not isinstance(categories, dict):
            raise ValueError('Lever categories 必须是对象或空值')
        categories = categories or {}
        plain = post.get('descriptionPlain')
        raw = plain if isinstance(plain, str) and plain.strip() else html_to_text(str(post.get('description') or ''))
        result.append({
            'source': f'lever:{site}',
            'raw_jd': raw,
            'job': {
                'external_id': external_id,
                'source_url': url,
                'job_title': str(post['text']),
                'company': '',
                'location': str(categories.get('location') or ''),
                'employment_type': str(categories.get('commitment') or ''),
                'source_updated_at': _lever_time(post.get('createdAt')),
            },
        })
    return result


def fetch_lever(site: str, *, allow_network: bool = False, timeout: float = 20) -> list[dict]:
    """单次 GET、无重试、固定官方域名、无凭据与重定向。"""
    url = lever_url(site)
    if not allow_network:
        raise PermissionError('公开来源读取默认关闭；必须显式允许联网')
    if not 0 < timeout <= 60:
        raise ValueError('timeout 必须在 0 到 60 秒之间')
    request = urllib.request.Request(url, headers={'Accept': 'application/json', 'User-Agent': 'JobReviewLocal/1.0'}, method='GET')
    opener = urllib.request.build_opener(_NoRedirect())
    with opener.open(request, timeout=timeout) as response:
        if response.status != 200:
            raise ValueError(f'公开来源 HTTP 状态异常：{response.status}')
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('公开来源响应过大')
    return parse_lever(json.loads(raw.decode('utf-8')), site)


def fetch_greenhouse(board_token: str, *, allow_network: bool = False, timeout: float = 20) -> list[dict]:
    """Single GET, no retry, fixed official host, no cookies/auth or redirects."""
    url = greenhouse_url(board_token)
    if not allow_network:
        raise PermissionError('公开来源读取默认关闭；必须显式允许联网')
    if not 0 < timeout <= 60:
        raise ValueError('timeout 必须在 0 到 60 秒之间')
    request = urllib.request.Request(url, headers={'Accept': 'application/json', 'User-Agent': 'JobReviewLocal/1.0'}, method='GET')
    opener = urllib.request.build_opener(_NoRedirect())
    with opener.open(request, timeout=timeout) as response:
        if response.status != 200:
            raise ValueError(f'公开来源 HTTP 状态异常：{response.status}')
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('公开来源响应过大')
    return parse_greenhouse(json.loads(raw.decode('utf-8')), board_token)
