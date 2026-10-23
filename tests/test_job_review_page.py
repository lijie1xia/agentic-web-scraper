import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class ReviewPageTests(unittest.TestCase):
    def test_preview_escapes_untrusted_job_and_material(self):
        from scraper_framework.job_workflow.review_page import render_page
        row = {'id': 1, 'job': {'job_title': '<script>alert(1)</script>', 'company': 'A', 'source_url': 'javascript:alert(1)'}, 'decision': {'score': 70, 'category': 'review', 'reasons': ['<b>reason</b>']}, 'status': 'READY_FOR_REVIEW', 'jd_hash': 'jd1', 'raw_jd': '<img src=x onerror=alert(1)>', 'material': {'content_hash': 'mat1', 'content': {'message': '</textarea><script>evil()</script>', 'warnings': [], 'evidence': []}}}
        page = render_page([row], token='safe-token')
        self.assertNotIn('<script>alert(1)', page)
        self.assertNotIn('href="javascript:', page)
        self.assertNotIn('</textarea><script>evil()', page)
        self.assertIn('&lt;script&gt;alert(1)', page)

    def test_approval_posts_material_and_job_snapshots_with_csrf(self):
        from scraper_framework.job_workflow.review_page import render_page
        row = {'id': 12, 'job': {'job_title': 'Python intern'}, 'decision': {'category': 'priority'}, 'status': 'READY_FOR_REVIEW', 'jd_hash': 'jdhash', 'material': {'content_hash': 'mathash', 'content': {'message': 'Hello'}}}
        row['revision'] = row['material']['revision'] = 7
        page = render_page([row], token='nonce')
        self.assertIn('name="csrf" value="nonce"', page)
        self.assertIn('name="jd_12" value="jdhash"', page)
        self.assertIn('name="material_12" value="mathash"', page)
        self.assertIn('form="batch" type="hidden" name="revision_12" value="7"', page)
        self.assertIn('name="expected_revision" value="7"', page)
        self.assertIn('value="12"', page)
        self.assertIn('人工发送', page)
        self.assertNotIn('默认已投递', page)

    def test_manual_form_binds_approval_identity_and_revision(self):
        from scraper_framework.job_workflow.review_page import render_page
        row = {'id': 1, 'revision': 3, 'approval_id': 8, 'status': 'APPROVED',
               'jd_hash': 'jd', 'material': {'revision': 3, 'content_hash': 'mat',
                                            'content': {'message': '正文'}}}
        page = render_page([row], token='nonce')
        self.assertIn('action="/manual-submit"', page)
        self.assertIn('name="expected_approval_id" value="8"', page)
        self.assertIn('name="expected_revision" value="3"', page)
        row.pop('approval_id')
        self.assertNotIn('action="/manual-submit"', render_page([row], token='nonce'))

    def test_missing_or_historical_snapshots_do_not_render_mutation_forms(self):
        from scraper_framework.job_workflow.review_page import render_page
        for revision in (None, 2):
            row = {'id': 1, 'revision': revision, 'approval_id': 8, 'status': 'APPROVED',
                   'jd_hash': 'jd', 'material': {'revision': 1, 'content_hash': 'mat',
                                                'content': {'message': '旧正文'}}}
            page = render_page([row], token='nonce')
            self.assertNotIn('name="selected"', page)
            self.assertNotIn('action="/edit"', page)
            self.assertNotIn('action="/manual-submit"', page)

    def test_rejected_and_submitted_cards_are_not_batch_approvable(self):
        from scraper_framework.job_workflow.review_page import render_page
        rows = [{'id': i, 'job': {}, 'decision': {'category': cat}, 'status': status, 'jd_hash': 'x', 'material': {'content_hash': 'y', 'content': {'message': 'Hi'}}} for i,cat,status in [(1,'reject','READY_FOR_REVIEW'),(2,'priority','SUBMITTED')]]
        page = render_page(rows, token='nonce')
        self.assertNotIn('name="selected"', page)


if __name__ == '__main__':
    unittest.main()
