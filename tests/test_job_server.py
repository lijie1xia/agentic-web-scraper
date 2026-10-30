import http.client
import sys
import threading
import unittest
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class FakeService:
    calls = []
    def rows(self): return []
    def summary(self): return {'jobs': 0}
    def close(self): pass
    def report_text(self): return 'No external submissions.'
    def import_text(self, text, *, source_url=''):
        self.calls.append((text, source_url))
        return {'id': 1}

    def import_batch_text(self, text, *, source_url=''):
        row = self.import_text(text, source_url=source_url)
        return {'processed': [row['id']], 'errors': []}

    def approve_batch(self, selections, *, acknowledge_review):
        self.calls.append(('approve', selections, acknowledge_review))
        return {'approved': [1], 'errors': []}

    def edit_message(self, job_id, message, *, expected_material_hash, expected_revision):
        self.calls.append(('edit', job_id, message, expected_material_hash, expected_revision))

    def manual_submission(self, job_id, *, evidence, expected_jd_hash, expected_material_hash,
                          expected_revision, expected_approval_id):
        self.calls.append(('manual', job_id, evidence, expected_jd_hash, expected_material_hash,
                           expected_revision, expected_approval_id))


class ServerTests(unittest.TestCase):
    def setUp(self):
        from scraper_framework.job_workflow.server import create_server
        FakeService.calls = []
        self.server = create_server(FakeService, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    def request(self, method='GET', path='/', body=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        conn.request(method, path, body, headers or {})
        response = conn.getresponse()
        result = response.status, dict(response.getheaders()), response.read().decode('utf-8')
        conn.close()
        return result

    def test_local_page_has_csp_and_no_cache(self):
        status, headers, text = self.request()
        self.assertEqual(status, 200)
        self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
        self.assertIn('no-store', headers['Cache-Control'])
        self.assertEqual(headers['Referrer-Policy'], 'same-origin')
        self.assertIn('本地求职审核台', text)

    def test_rebinding_host_rejected(self):
        self.assertEqual(self.request(headers={'Host': 'attacker.test'})[0], 403)

    def test_mutation_needs_csrf_and_same_origin(self):
        fields = {'text': '岗位描述', 'csrf': self.server.csrf_token}
        self.assertEqual(self.request('POST','/import',urlencode({'text': 'bad'}),{'Content-Type':'application/x-www-form-urlencoded'})[0],403)
        self.assertEqual(self.request('POST','/import',urlencode(fields),{'Content-Type':'application/x-www-form-urlencoded','Origin':'https://evil.test'})[0],403)
        self.assertEqual(self.request('POST','/import',urlencode(fields),{'Content-Type':'application/x-www-form-urlencoded','Origin':'null'})[0],403)
        self.assertEqual(FakeService.calls, [])
        status, _, _ = self.request('POST','/import',urlencode(fields),{'Content-Type':'application/x-www-form-urlencoded','Origin':f'http://127.0.0.1:{self.port}'})
        self.assertEqual(status,200)
        self.assertEqual(len(FakeService.calls),1)

    def test_forms_forward_displayed_revision_and_approval_identity(self):
        cases = [
            ('/approve', {'selected': '1', 'jd_1': 'jd', 'material_1': 'mat',
                          'revision_1': '4', 'acknowledge_review': 'yes'},
             ('approve', [{'job_id': 1, 'expected_jd_hash': 'jd',
                           'expected_material_hash': 'mat', 'expected_revision': 4}], True)),
            ('/edit', {'job_id': '1', 'message': '正文', 'expected_material_hash': 'mat',
                       'expected_revision': '4'}, ('edit', 1, '正文', 'mat', 4)),
            ('/manual-submit', {'job_id': '1', 'evidence': '本地证据', 'expected_jd_hash': 'jd',
                                'expected_material_hash': 'mat', 'expected_revision': '4',
                                'expected_approval_id': '9'}, ('manual', 1, '本地证据', 'jd', 'mat', 4, 9))]
        headers = {'Content-Type': 'application/x-www-form-urlencoded',
                   'Origin': f'http://127.0.0.1:{self.port}'}
        for path, fields, expected in cases:
            with self.subTest(path=path):
                fields['csrf'] = self.server.csrf_token
                self.assertEqual(self.request('POST', path, urlencode(fields), headers)[0], 200)
                self.assertEqual(FakeService.calls[-1], expected)

    def test_missing_numeric_snapshots_are_rejected_before_service_mutation(self):
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        for path, fields in [('/approve', {'selected': '1'}), ('/edit', {'job_id': '1'}),
                             ('/manual-submit', {'job_id': '1', 'expected_revision': '1'})]:
            fields['csrf'] = self.server.csrf_token
            self.assertEqual(self.request('POST', path, urlencode(fields), headers)[0], 400)
        self.assertEqual(FakeService.calls, [])

    def test_public_bind_refused(self):
        from scraper_framework.job_workflow.server import create_server
        with self.assertRaises(ValueError):
            create_server(FakeService, host='0.0.0.0', port=0)


if __name__ == '__main__': unittest.main()
