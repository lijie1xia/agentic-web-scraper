"""港中大（深圳）公开招聘的有界、部分发现；绝非全站快照。

仅供个人低频读取；公开展示不代表校外申请资格或转载授权。
不登录、不申请、不跟随重定向，不调用业务 LLM。
"""
from __future__ import annotations

import html as html_module
import re
import urllib.request
from itertools import islice
from datetime import date
from html.parser import HTMLParser

from .sources import MAX_BYTES, _NoRedirect, html_to_text

DEFAULT_KEYWORDS = ('AI', 'Agent', '大模型', 'Python', 'Java', '后端', '开发实习')

SOURCE = 'cuhk'
COMPLETE_SNAPSHOT = False
BASE_URL = 'https://career.cuhk.edu.cn'
LIST_URL = BASE_URL + '/en/job/search'
_DETAIL = re.compile(r'https://career\.cuhk\.edu\.cn/(?:en/)?job/view/id/([1-9][0-9]{0,11})')
_VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}


def _detail_url(value):
    if not isinstance(value, str) or not _DETAIL.fullmatch(value):
        raise ValueError('只允许固定官网的无参数岗位详情 URL')
    return value


class _Node:
    def __init__(self, tag='', attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []
        self.closed = tag in _VOID

    def nodes(self):
        yield self
        for child in self.children:
            if isinstance(child, _Node):
                yield from child.nodes()

    def markup(self):
        content = ''.join(child.markup() if isinstance(child, _Node) else html_module.escape(child)
                          for child in self.children)
        return f'<{self.tag}>{content}</{self.tag}>' if self.tag else content

    def text(self):
        return html_to_text(self.markup())

    def has_class(self, name):
        return name in self.attrs.get('class', '').split()


class _Page(HTMLParser):
    def __init__(self, value):
        super().__init__(convert_charrefs=True)
        if not isinstance(value, str) or len(value.encode('utf-8')) > MAX_BYTES:
            raise ValueError('公开页面格式或大小异常')
        self.root = _Node()
        self.stack = [self.root]
        self.feed(value)
        self.close()

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in _VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                self.stack[index].closed = True
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)

    def section(self, name):
        nodes = [node for node in self.root.nodes() if node.has_class(name)]
        if len(nodes) != 1 or not nodes[0].closed:
            raise ValueError(f'公开页面缺少完整的 {name} 结构')
        return nodes[0]


def parse_list(html: str) -> list[dict]:
    """仅返回列表区域内的官网详情，按官方 ID 去重，不跟随其他链接。"""
    section = _Page(html).section('sousuo_list')
    if not any(node.tag == 'ul' and node.closed for node in section.nodes()):
        raise ValueError('公开列表缺少完整的 ul 结构')
    rows, seen = [], set()
    for node in section.nodes():
        if node.tag != 'a':
            continue
        href = node.attrs.get('href') or ''
        url = BASE_URL + href if href.startswith('/') else href
        match = _DETAIL.fullmatch(url)
        if not match or match[1] in seen:
            continue
        title = ' '.join(node.text().split())
        if not title or not node.closed:
            raise ValueError('公开列表岗位标题缺失')
        seen.add(match[1])
        rows.append({'url': url, 'title': title})
    if not rows and any(node.tag == 'li' for node in section.nodes()):
        raise ValueError('公开列表非空但无法识别岗位链接，需人工核验')
    return rows


def parse_job(html: str, url: str) -> dict:
    """只映射明示字段，保留明确截止日期；绝不推断毕业届次或申请资格。"""
    _detail_url(url)
    page = _Page(html)
    title = ' '.join(page.section('titles').text().split())
    article = page.section('article')
    blocks = [child for child in article.children if isinstance(child, _Node)]
    descriptions = [block for block in blocks if any(
        node.tag == 'h3' and node.text() in {'Job Description', '工作内容描述'}
        for node in block.nodes())]
    if not title or len(descriptions) != 1 or not descriptions[0].closed:
        raise ValueError('公开详情标题或职位描述结构异常')
    body = [child for child in descriptions[0].children if isinstance(child, _Node) and child.tag == 'div']
    if len(body) != 1 or not body[0].closed or not body[0].text():
        raise ValueError('公开详情缺少完整职位正文')
    raw = body[0].text()
    if len(raw) > 100000:
        raise ValueError('JD 原文超过本地导入上限')
    job = {'external_id': _DETAIL.fullmatch(url)[1], 'source_url': url, 'job_title': title}
    labels = {'Company name': 'company', '公司名称': 'company',
              'Countries & Regions': 'location', '工作地点': 'location',
              'Work Type': 'employment_type', '工作性质': 'employment_type',
              'Salary Range': 'salary_range', '薪资待遇': 'salary_range'}
    # 只读取首个结构化信息块，不把任职描述中的同名词当作元数据。
    for node in blocks[0].nodes():
        if node.tag == 'p':
            parts = re.split(r'[:：]', node.text(), maxsplit=1)
            if len(parts) == 2 and parts[0].strip() in labels and parts[1].strip():
                job[labels[parts[0].strip()]] = parts[1].strip()
    headers = [child for child in page.section('col-md-9').children
               if isinstance(child, _Node) and child.has_class('row') and child.has_class('mb20')]
    for node in (node for header in headers for node in header.nodes()):
        if node.tag != 'span':
            continue
        match = re.fullmatch(r'(Deadline|结束时间|Post Time|发布时间)\s*[:：]\s*(.*)', node.text())
        if match:
            field = 'deadline' if match[1] in {'Deadline', '结束时间'} else 'published_at'
            value = match[2].strip()
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
                raise ValueError('公开详情日期格式异常，需人工核验')
            job[field] = date.fromisoformat(value).isoformat()
    return {'source': SOURCE, 'raw_jd': raw, 'job': job}


def _read_html(opener, url):
    """与 sources 使用相同 UA、20 秒超时和响应上限；只做一次 GET。"""
    request = urllib.request.Request(url, headers={
        'Accept': 'text/html', 'User-Agent': 'JobReviewLocal/1.0'}, method='GET')
    with opener.open(request, timeout=20) as response:
        if response.status != 200 or response.geturl() != url:
            raise ValueError('公开来源 HTTP 状态或最终 URL 异常')
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('公开来源响应过大')
    return raw.decode('utf-8-sig')


def fetch_campus(*, allow_network=False, pages=1, max_jobs=8, keywords=None, known_urls=()) -> list[dict]:
    """最多两页列表和八个详情（已知与新增共享预算），只返回部分发现。

    已知详情优先复查且不受标题关键词过滤；不会据此判定未出现的岗位下架。
    keywords=None 使用默认词，空序列不发现新岗位。错误直接上抛，不伪装空列表。
    """
    if not allow_network:
        raise PermissionError('公开来源读取默认关闭；必须显式允许联网')
    if type(pages) is not int or not 1 <= pages <= 2:
        raise ValueError('pages 必须为 1 或 2')
    if type(max_jobs) is not int or not 1 <= max_jobs <= 8:
        raise ValueError('max_jobs 必须为 1 到 8')
    terms = DEFAULT_KEYWORDS if keywords is None else tuple(islice(keywords, 21))
    if isinstance(keywords, str) or len(terms) > 20 or any(
            not isinstance(term, str) or not term.strip() or len(term) > 80 for term in terms):
        raise ValueError('keywords 必须是最多 20 个非空短关键词')
    known = tuple(islice(known_urls, 9))
    if isinstance(known_urls, str) or len(known) > 8:
        raise ValueError('known_urls 必须是最多 8 个官网详情 URL')
    urls, seen = [], set()
    for url in known:
        identity = _DETAIL.fullmatch(_detail_url(url))[1]
        if identity not in seen:
            urls.append(url)
            seen.add(identity)
    opener = urllib.request.build_opener(_NoRedirect())
    for number in range(1, pages + 1):
        list_url = LIST_URL if number == 1 else LIST_URL + '?domain=careercuhk&page=2'
        for item in parse_list(_read_html(opener, list_url)):
            identity = _DETAIL.fullmatch(item['url'])[1]
            if identity not in seen and any(term.casefold() in item['title'].casefold() for term in terms):
                urls.append(item['url'])
                seen.add(identity)
    return [parse_job(_read_html(opener, url), url) for url in urls[:max_jobs]]
