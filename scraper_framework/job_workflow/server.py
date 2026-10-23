"""Loopback-only review HTTP server with CSRF and DNS-rebinding protection."""
from __future__ import annotations

import hmac
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from .review_page import render_page

MAX_BODY = 1024 * 1024


def create_server(service_factory, *, host='127.0.0.1', port=8765):
    if host != '127.0.0.1':
        raise ValueError('审核台只允许绑定 127.0.0.1，不可公开暴露个人求职数据')

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            # Avoid JD, material, approval tokens and personal URLs in access logs.
            pass

        def _trusted_host(self):
            port = self.server.server_address[1]
            return self.headers.get('Host') in {f'127.0.0.1:{port}', f'localhost:{port}'}

        def _reply(self, code, text, *, content_type='text/html; charset=utf-8'):
            body = text.encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            # 保留同源表单的 Origin，避免 Chromium 发送 null；跨源仍不携带 Referer。
            self.send_header('Referrer-Policy', 'same-origin')
            self.send_header('X-Frame-Options', 'DENY')
            token = self.server.csrf_token
            self.send_header('Content-Security-Policy', f"default-src 'none'; style-src 'nonce-{token}'; script-src 'nonce-{token}'; connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def _page(self, service, notice=''):
            rows = service.rows()
            query = parse_qs(urlsplit(self.path).query)
            category = query.get('category', [''])[0]
            status = query.get('status', [''])[0]
            if category:
                rows = [r for r in rows if r.get('decision', {}).get('category') == category]
            if status:
                rows = [r for r in rows if r.get('status') == status]
            return render_page(rows, token=self.server.csrf_token, notice=notice, summary=service.summary())

        def do_GET(self):
            if not self._trusted_host():
                return self._reply(403, 'Host rejected', content_type='text/plain; charset=utf-8')
            path = urlsplit(self.path).path
            if path not in {'/', '/report', '/health'}:
                return self._reply(404, 'Not found')
            if path == '/health':
                return self._reply(200, 'ok', content_type='text/plain; charset=utf-8')
            service = self.server.service_factory()
            try:
                if path == '/report':
                    self._reply(200, service.report_text(), content_type='text/plain; charset=utf-8')
                else:
                    self._reply(200, self._page(service))
            except Exception:
                self._reply(500, '读取工作台失败；请检查数据库及配置。')
            finally:
                service.close()

        def do_POST(self):
            if not self._trusted_host():
                return self._reply(403, 'Host rejected')
            origin = self.headers.get('Origin')
            if origin is not None and origin != f"http://{self.headers.get('Host')}":
                return self._reply(403, 'Origin rejected')
            if self.headers.get('Sec-Fetch-Site') == 'cross-site':
                return self._reply(403, 'Cross-site request rejected')
            if self.headers.get_content_type() != 'application/x-www-form-urlencoded':
                return self._reply(415, 'Form encoding required')
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= MAX_BODY:
                    return self._reply(413, 'Request too large or empty')
                fields = parse_qs(self.rfile.read(length).decode('utf-8'), max_num_fields=10000, keep_blank_values=True)
            except (ValueError, UnicodeError):
                return self._reply(400, 'Invalid form')
            token = fields.get('csrf', [''])[0]
            if not hmac.compare_digest(token, self.server.csrf_token):
                return self._reply(403, 'CSRF rejected')
            value = lambda name: fields.get(name, [''])[0]
            service = self.server.service_factory()
            try:
                path = urlsplit(self.path).path
                if path == '/import':
                    row = service.import_text(value('text'), source_url=value('url'))
                    notice = f"已保存岗位 #{row['id']}；未调用模型，未发送。"
                elif path == '/approve':
                    selected = list(dict.fromkeys(fields.get('selected', [])))
                    selections = [{'job_id': int(i), 'expected_jd_hash': value(f'jd_{i}'), 'expected_material_hash': value(f'material_{i}'), 'expected_revision': int(value(f'revision_{i}'))} for i in selected]
                    result = service.approve_batch(selections, acknowledge_review=value('acknowledge_review') == 'yes')
                    notice = f"批准 {len(result['approved'])} 条，未批准 {len(result['errors'])} 条。没有发送任何申请。"
                    if result['errors']:
                        notice += '\n' + '\n'.join(result['errors'])
                elif path == '/edit':
                    service.edit_message(int(value('job_id')), value('message'), expected_material_hash=value('expected_material_hash'), expected_revision=int(value('expected_revision')))
                    notice = '材料已保存；如内容发生变化，旧审批已失效。请重新审核事实。'
                elif path == '/manual-submit':
                    service.manual_submission(int(value('job_id')), evidence=value('evidence'), expected_jd_hash=value('expected_jd_hash'), expected_material_hash=value('expected_material_hash'), expected_revision=int(value('expected_revision')), expected_approval_id=int(value('expected_approval_id')))
                    notice = '已登记你人工确认的发送结果；这不是系统自动投递回执。'
                elif path == '/followup':
                    service.followup(int(value('job_id')), status=value('status'), note=value('note'))
                    notice = '已保存人工跟进记录。'
                elif path == '/skip':
                    service.skip(int(value('job_id')))
                    notice = '已跳过岗位。'
                else:
                    return self._reply(404, 'Not found')
                self._reply(200, self._page(service, notice))
            except (ValueError, PermissionError, KeyError, RuntimeError) as exc:
                self._reply(400, self._page(service, f'操作未完成：{exc}'))
            except Exception:
                self._reply(500, '操作失败，未确认成功；请检查状态，不要盲目重复提交。')
            finally:
                service.close()

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    server.service_factory = service_factory
    server.csrf_token = secrets.token_urlsafe(32)
    return server
