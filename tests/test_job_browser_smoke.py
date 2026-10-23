"""用真实 Chromium 验证临时本地数据库流程，不访问外部页面或账号。"""
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class BrowserSmoke(unittest.TestCase):
    def test_review_edit_reapprove_manual_record_and_followup(self):
        from playwright.sync_api import sync_playwright
        from scraper_framework.job_workflow.service import Workflow
        from scraper_framework.job_workflow.server import create_server
        profile = {'tech_stack':['Python','RAG'],'education':'本科','graduate_year':2027,'experience_years':0,'preferred_work_mode':['onsite']}
        resume = {'projects':[{'name':'demo','tags':['Python','RAG'],'one_liner':'搭建过Python RAG后端服务。'}]}
        jd = '职位：AI应用开发实习生\n公司：本地测试公司\n学历：本科\n招聘对象：2027届本科在读\n工作方式：坐班\n任职要求：Python、RAG'
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp)/'jobs.db'
            factory = lambda: Workflow(db,profile=profile,resume=resume)
            server = create_server(factory,port=0)
            thread = threading.Thread(target=server.serve_forever,daemon=True)
            thread.start()
            base = f'http://127.0.0.1:{server.server_address[1]}'
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True)
                    context = browser.new_context()
                    external = []
                    def route(request_route):
                        if request_route.request.url.startswith(base+'/'):
                            request_route.continue_()
                        else:
                            external.append(request_route.request.url)
                            request_route.abort()
                    context.route('**/*',route)
                    page = context.new_page()
                    page.goto(base)
                    page.locator('details > summary').first.click()
                    page.locator('textarea[name=text]').fill(jd)
                    # 先检查提交响应，避免服务端拒绝被掩盖为岗位卡片等待超时。
                    with page.expect_response(lambda response: response.url == base+'/import') as submitted:
                        page.get_by_role('button',name='离线分析并加入岗位池').click()
                    response = submitted.value
                    self.assertEqual(response.status, 200,
                                     f"Origin={response.request.headers.get('origin')}; {response.text()}")
                    page.wait_for_selector('#job-1')
                    self.assertIn('READY_FOR_REVIEW',page.locator('#job-1').inner_text())
                    # 保留两份旧页面，验证编辑和批量审批都不能跨决策版本复用。
                    stale_batch = context.new_page()
                    stale_batch.goto(base)
                    flow = factory()
                    try:
                        old = flow.rows()[0]
                        changed = flow.repo.upsert_job(old['job'], raw_jd=old['raw_jd'],
                            decision={**old['decision'], 'note': '浏览器测试新增条件'})
                    finally:
                        flow.close()
                    page.locator('textarea[name=message]').fill('旧页面不能覆盖新决策')
                    with page.expect_response(lambda r: r.url == base+'/edit') as rejected_edit:
                        page.get_by_role('button',name='保存修改（旧审批失效）').click()
                    self.assertEqual(rejected_edit.value.status, 400)
                    page.wait_for_selector('text=操作未完成')
                    flow = factory()
                    try:
                        self.assertEqual(flow.repo.latest_material(1)['id'], old['material']['id'])
                        fresh = flow.repo.save_material(1, old['material']['content'],
                                                       expected_revision=changed['revision'])
                        self.assertEqual(fresh['content_hash'], old['material']['content_hash'])
                    finally:
                        flow.close()
                    stale_batch.locator('input[name=selected]').check()
                    stale_batch.locator('input[name=acknowledge_review]').check()
                    with stale_batch.expect_response(lambda r: r.url == base+'/approve') as rejected_batch:
                        stale_batch.get_by_role('button',name='批准所选：仅人工联系准备').click()
                    self.assertEqual(rejected_batch.value.status, 200)
                    stale_batch.wait_for_selector('text=批准 0 条，未批准 1 条')
                    flow = factory()
                    try:
                        self.assertEqual(flow.repo.list_approvals(1), [])
                    finally:
                        flow.close()
                    stale_batch.close()
                    page.goto(base)
                    page.locator('input[name=selected]').check()
                    page.locator('input[name=acknowledge_review]').check()
                    page.get_by_role('button',name='批准所选：仅人工联系准备').click()
                    page.wait_for_selector('form[action="/manual-submit"]')
                    page.locator('textarea[name=message]').fill('您好，我想了解这个岗位，做过Python后端项目。')
                    page.get_by_role('button',name='保存修改（旧审批失效）').click()
                    page.wait_for_selector('text=材料已保存')
                    self.assertEqual(page.locator('form[action="/manual-submit"]').count(),0)
                    page.locator('input[name=selected]').check()
                    page.locator('input[name=acknowledge_review]').check()
                    page.get_by_role('button',name='批准所选：仅人工联系准备').click()
                    page.wait_for_selector('input[name=evidence]')
                    # 撤换成同内容的新审批，旧确认页面仍须拒绝，不能消耗新授权。
                    old_approval_id = page.locator('input[name=expected_approval_id]').input_value()
                    flow = factory()
                    try:
                        material = flow.repo.latest_material(1)
                        flow.repo.save_material(1, {**material['content'], 'message': '临时版本'})
                        flow.repo.save_material(1, material['content'])
                        replacement = flow.repo.approve(1, acknowledge_review=True)
                        self.assertNotEqual(str(replacement['id']), old_approval_id)
                    finally:
                        flow.close()
                    page.locator('input[name=evidence]').fill('旧页面模拟确认，不能登记')
                    with page.expect_response(lambda r: r.url == base+'/manual-submit') as rejected_manual:
                        page.get_by_role('button',name='我已人工发送并核实').click()
                    self.assertEqual(rejected_manual.value.status, 400)
                    page.wait_for_selector('text=操作未完成')
                    self.assertEqual(page.locator('input[name=expected_approval_id]').input_value(), str(replacement['id']))
                    flow = factory()
                    try:
                        self.assertEqual(flow.repo.list_executions(1), [])
                        self.assertIsNone(flow.repo.list_approvals(1)[-1]['consumed_at'])
                    finally:
                        flow.close()
                    page.locator('input[name=evidence]').fill('仅本地测试：模拟人工核实发送记录，没有真实投递')
                    page.get_by_role('button',name='我已人工发送并核实').click()
                    page.wait_for_selector('form[action="/followup"]')
                    page.locator('select[name=status]').select_option('REPLIED')
                    page.get_by_role('button',name='更新进度').click()
                    page.wait_for_selector('text=已保存人工跟进记录')
                    self.assertIn('REPLIED',page.locator('#job-1').inner_text())
                    self.assertEqual(external,[])
                    browser.close()
                flow = factory()
                try:
                    self.assertEqual(flow.rows()[0]['status'],'REPLIED')
                    self.assertEqual(len(flow.repo.list_executions(1)),1)
                    self.assertEqual(flow.repo.list_executions(1)[0]['evidence'],'仅本地测试：模拟人工核实发送记录，没有真实投递')
                finally:
                    flow.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)


if __name__ == '__main__': unittest.main()
