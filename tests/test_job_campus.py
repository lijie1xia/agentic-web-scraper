"""港中大公开页面的离线结构测试；夹具按实读 HTML 精简，不含联系方式。"""
import sys
import io
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
BASE = 'https://career.cuhk.edu.cn'
URL = BASE + '/en/job/view/id/468767'
LIST = '''<div class="sousuo_list"><ul><li>
<div class="sousuo_list_name"><a href="javascript:;">公司</a></div>
<div class="sousuo_list_xx"><div class="col-sm-9">
<a target="_blank" href="/en/job/view/id/468767" class="f18">AI工作流实习生（Codex等）</a>
</div></div></li></ul></div>'''

JOB = '''<div class="col-md-9"><div class="titles c_zise">
AI工作流实习生（Codex等）<a href="javascript:getCollect(468767)"></a></div>
<div class="row mb20"><div class="col-xs-12 col-sm-9 mt10 mb15">
<span class="mr20">Post Time：2026-07-10</span><span>Deadline：2026-12-31</span>
</div><div style="display:none"><a href="javascript:getApply(468767)">Apply</a></div></div>
<div class="article"><div class="mb20">
<p>Company name：<a href="javascript:;">深圳锐圳科技有限公司</a></p>
<p>Countries &amp; Regions：Guangdong - Shenzhen</p><p>Work Type：Internship</p>
<p>Salary Range：3000-4499</p></div><div class="mb20">
<h3 class="subart_h3">Job Description</h3><div><p>在校生 / 应届生均可。</p>
<p>会写代码（Python/Shell/）；实习至少3个月、每周≥4天。</p>
<script>hidden_code()</script></div></div>
<div class="mb20"><h3 class="subart_h3">Other information</h3><p>非岗位内容</p></div>
</div></div>'''


class Reply(io.BytesIO):
    def __init__(self, body, url, status=200):
        super().__init__(body.encode('utf-8') if isinstance(body, str) else body)
        self.url, self.status = url, status

    def geturl(self):
        return self.url


class CampusTests(unittest.TestCase):
    def test_invalid_options_never_open_network(self):
        from scraper_framework.job_workflow.campus import fetch_campus
        invalid = [{'pages': 3}, {'pages': 0}, {'pages': True}, {'max_jobs': 9},
                   {'max_jobs': 0}, {'max_jobs': 1.5}, {'keywords': 'AI'},
                   {'keywords': ['']}, {'keywords': ['AI'] * 21},
                   {'known_urls': [URL] * 9}, {'known_urls': URL}]
        for suffix in ['/job/operate', '/en/job/view/id/468767?apply=1',
                       '/en/job/view/id/468767#anchor', '/en/job/view/id/../468767']:
            invalid.append({'known_urls': [BASE + suffix]})
        for url in ['http://career.cuhk.edu.cn/en/job/view/id/1',
                    'https://career.cuhk.edu.cn.evil.test/en/job/view/id/1',
                    'https://user@career.cuhk.edu.cn/en/job/view/id/1',
                    'https://career.cuhk.edu.cn:443/en/job/view/id/1', URL + '\n']:
            invalid.append({'known_urls': [url]})
        with patch('urllib.request.OpenerDirector.open') as opened:
            for options in invalid:
                with self.subTest(options=options), self.assertRaises(ValueError):
                    fetch_campus(allow_network=True, **options)
            opened.assert_not_called()

    def test_title_filter_empty_results_and_known_bypass(self):
        from scraper_framework.job_workflow.campus import fetch_campus
        unrelated = LIST.replace('AI工作流实习生（Codex等）', '财务实习生')
        def opened(request, timeout):
            return Reply(unrelated if '/search' in request.full_url else JOB, request.full_url)
        with patch('urllib.request.OpenerDirector.open', side_effect=opened) as mocked:
            self.assertEqual(fetch_campus(allow_network=True), [])
            self.assertEqual(mocked.call_count, 1)
            self.assertEqual(len(fetch_campus(allow_network=True, keywords=['财务'])), 1)
            self.assertEqual(fetch_campus(allow_network=True, keywords=[]), [])
            self.assertEqual(len(fetch_campus(allow_network=True, keywords=[], known_urls=[URL])), 1)
        with patch('urllib.request.OpenerDirector.open', side_effect=lambda request, timeout:
                   Reply(LIST.replace('AI工作流实习生（Codex等）', 'python 开发'), request.full_url)
                   if '/search' in request.full_url else Reply(JOB, request.full_url)):
            self.assertEqual(len(fetch_campus(allow_network=True)), 1)

    def test_new_and_known_share_eight_detail_budget(self):
        from scraper_framework.job_workflow.campus import fetch_campus
        many = '<div class="sousuo_list"><ul>' + ''.join(
            f'<li><a href="/en/job/view/id/{number}">AI实习</a></li>'
            for number in range(100, 120)) + '</ul></div>'
        calls = []
        def opened(request, timeout):
            calls.append(request.full_url)
            return Reply(many if '/search' in request.full_url else JOB, request.full_url)
        with patch('urllib.request.OpenerDirector.open', side_effect=opened):
            rows = fetch_campus(allow_network=True, pages=2,
                                known_urls=[URL, URL.replace('/en/', '/')])
        self.assertEqual(len(calls), 10)
        self.assertEqual(len(rows), 8)
        self.assertEqual(calls[2], URL)
        self.assertEqual(len({row['job']['external_id'] for row in rows}), 8)

    def test_bad_response_and_network_failure_raise_without_retry(self):
        from scraper_framework.job_workflow import campus
        cases = [(Reply('error', campus.LIST_URL, 503), ValueError),
                 (Reply('moved', campus.LIST_URL, 302), ValueError),
                 (Reply(LIST, BASE + '/login'), ValueError),
                 (Reply('<html>登录</html>', campus.LIST_URL), ValueError),
                 (Reply(b'\xff', campus.LIST_URL), UnicodeDecodeError)]
        for response, error in cases:
            with self.subTest(error=error), patch('urllib.request.OpenerDirector.open', return_value=response) as opened:
                with self.assertRaises(error):
                    campus.fetch_campus(allow_network=True)
                self.assertEqual(opened.call_count, 1)
        with patch('urllib.request.OpenerDirector.open', side_effect=TimeoutError) as opened:
            with self.assertRaises(TimeoutError):
                campus.fetch_campus(allow_network=True)
            self.assertEqual(opened.call_count, 1)
        with patch.object(campus, 'MAX_BYTES', 16), patch('urllib.request.OpenerDirector.open',
                return_value=Reply('x' * 17, campus.LIST_URL)):
            with self.assertRaises(ValueError):
                campus.fetch_campus(allow_network=True)

    def test_opener_installs_fail_closed_redirect_handler(self):
        import urllib.request
        from scraper_framework.job_workflow import campus
        real_builder = urllib.request.build_opener
        def builder(*handlers):
            self.assertTrue(any(isinstance(handler, campus._NoRedirect) for handler in handlers))
            with self.assertRaises(ValueError):
                handlers[0].redirect_request(None, None, 302, '', {}, BASE + '/login')
            return real_builder(*handlers)
        with patch('urllib.request.build_opener', side_effect=builder), patch(
                'urllib.request.OpenerDirector.open', return_value=Reply(
                    '<div class="sousuo_list"><ul></ul></div>', campus.LIST_URL)):
            self.assertEqual(campus.fetch_campus(allow_network=True), [])
        self.assertFalse(campus.COMPLETE_SNAPSHOT)

    def test_fetch_is_opt_in_bounded_sequential_and_refreshes_known_first(self):
        from scraper_framework.job_workflow.campus import fetch_campus
        calls = []
        class Response(io.BytesIO):
            status = 200
            def geturl(self):
                return calls[-1]
        def opened(request, timeout):
            calls.append(request.full_url)
            self.assertEqual(timeout, 20)
            self.assertEqual(request.get_method(), 'GET')
            self.assertEqual(request.get_header('User-agent'), 'JobReviewLocal/1.0')
            self.assertIsNone(request.data)
            value = LIST if '/search' in request.full_url else JOB
            return Response(value.encode('utf-8'))
        with patch('urllib.request.OpenerDirector.open', side_effect=opened):
            with self.assertRaises(PermissionError):
                fetch_campus()
            self.assertEqual(calls, [])
            rows = fetch_campus(allow_network=True, pages=2, max_jobs=2,
                                known_urls=[BASE + '/job/view/id/469375'])
        self.assertEqual(calls, [BASE + '/en/job/search',
                                BASE + '/en/job/search?domain=careercuhk&page=2',
                                BASE + '/job/view/id/469375', URL])
        self.assertEqual([row['job']['external_id'] for row in rows], ['469375', '468767'])

    def test_job_preserves_explicit_fields_and_only_description(self):
        from scraper_framework.job_workflow.campus import parse_job
        row = parse_job(JOB, URL)
        self.assertEqual(row['source'], 'cuhk')
        self.assertEqual(row['job'], {
            'external_id': '468767', 'source_url': URL,
            'job_title': 'AI工作流实习生（Codex等）', 'company': '深圳锐圳科技有限公司',
            'location': 'Guangdong - Shenzhen', 'employment_type': 'Internship',
            'salary_range': '3000-4499', 'deadline': '2026-12-31',
            'published_at': '2026-07-10',
        })
        self.assertIn('在校生 / 应届生均可', row['raw_jd'])
        self.assertNotIn('hidden_code', row['raw_jd'])
        self.assertNotIn('非岗位内容', row['raw_jd'])
        cn = JOB.replace('Company name', '公司名称').replace('Countries &amp; Regions', '工作地点')
        cn = cn.replace('Work Type', '工作性质').replace('Salary Range', '薪资待遇')
        cn = cn.replace('Job Description', '工作内容描述').replace('Deadline', '结束时间')
        cn = cn.replace('Post Time', '发布时间')
        self.assertEqual(parse_job(cn, URL), row)
        missing = JOB.replace('<span>Deadline：2026-12-31</span>', '')
        self.assertNotIn('deadline', parse_job(missing, URL)['job'])
        for bad in ['<html>请登录</html>', JOB.replace('Job Description', 'Other'),
                    JOB.replace('2026-12-31', '2026-02-30')]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse_job(bad, URL)
        with self.assertRaises(ValueError):
            parse_job(JOB, BASE + '/job/operate')

    def test_detail_body_cannot_override_header_deadline(self):
        from scraper_framework.job_workflow.campus import parse_job
        poisoned = JOB.replace('在校生 / 应届生均可。',
                               '<span>Deadline：2099-01-01</span>在校生 / 应届生均可。')
        self.assertEqual(parse_job(poisoned, URL)['job']['deadline'], '2026-12-31')

    def test_changed_list_shape_is_not_a_fake_empty_snapshot(self):
        from scraper_framework.job_workflow.campus import parse_list
        for bad in [LIST.replace('/en/job/view/id/468767', '/new-job/468767'),
                    '<div class="sousuo_list"><ul><li>请登录查看</li></ul></div>']:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse_list(bad)

    def test_list_reads_real_structure_and_deduplicates_official_ids(self):
        from scraper_framework.job_workflow.campus import parse_list
        extra = '''<a href="/job/view/id/468767">重复中文路径</a>
        <a href="https://evil.test/en/job/view/id/12">外站</a>
        <a href="/job/operate">申请</a><a href="/en/job/view/id/13?x=1">参数</a>
        <a href="/job/view/id/469375"><span>AI Agent</span> 研发工程师</a>'''
        rows = parse_list(LIST.replace('</ul>', extra + '</ul>'))
        self.assertEqual(rows, [
            {'url': URL, 'title': 'AI工作流实习生（Codex等）'},
            {'url': BASE + '/job/view/id/469375', 'title': 'AI Agent 研发工程师'},
        ])
        self.assertEqual(parse_list('<div class="sousuo_list"><ul></ul></div>'), [])
        for bad in ['<html>请登录</html>', LIST.replace('</div>', '')]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse_list(bad)


if __name__ == '__main__':
    unittest.main()
