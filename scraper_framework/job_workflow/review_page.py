"""Escaped local review interface. No third-party scripts, trackers or CDNs."""
from html import escape
from urllib.parse import urlsplit


STYLE = '''
:root{color-scheme:light dark;font-family:system-ui,sans-serif}body{max-width:1120px;margin:24px auto;padding:0 18px;line-height:1.6}h1{margin-bottom:0}small,.muted{opacity:.75}section,article{border:1px solid #8886;border-radius:10px;padding:18px;margin:14px 0}textarea,input[type=text]{box-sizing:border-box;width:100%;padding:9px;border:1px solid #8888;border-radius:6px;font:inherit}textarea{min-height:100px}button{padding:8px 14px;border-radius:6px;border:1px solid #8888;cursor:pointer;margin:4px}button.primary{background:#205cbb;color:white}nav,.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.badge{padding:3px 9px;background:#8882;border-radius:12px}.warning{border-left:4px solid #c88516;padding-left:10px}.notice{white-space:pre-wrap;border:1px solid #588b;padding:12px}pre{white-space:pre-wrap;overflow-wrap:anywhere}summary{cursor:pointer}a{color:#438de3}.approvebar{position:sticky;bottom:0;background:Canvas;border:1px solid #8888;padding:12px;border-radius:8px}label{cursor:pointer}input[type=checkbox]{width:18px;height:18px} .actions{margin-top:10px}
'''
SCRIPT = '''
document.addEventListener('click',async event=>{
 const button=event.target.closest('[data-copy]');
 if(button){const input=document.getElementById(button.dataset.copy);try{await navigator.clipboard.writeText(input.value);button.textContent='已复制';}catch(e){input.focus();input.select();button.textContent='请按 Ctrl+C 复制';}}
 const all=event.target.closest('[data-select-all]');if(all){document.querySelectorAll('input[name=selected]').forEach(x=>{x.checked=true;});}
});
'''


def _e(value):
    return escape(str(value if value is not None else ''), quote=True)


def _hidden(name, value):
    return f'<input type="hidden" name="{_e(name)}" value="{_e(value)}">'


def _items(values):
    if not values:
        return '<li>未提供</li>'
    if isinstance(values, str):
        values = [values]
    return ''.join(f'<li>{_e(v)}</li>' for v in values)


def _link(url):
    try:
        p = urlsplit(str(url or ''))
        if p.scheme not in {'http', 'https'} or not p.hostname or p.username or p.password:
            return '<span class="muted">无可打开的岗位链接</span>'
    except ValueError:
        return '<span class="muted">岗位链接格式错误</span>'
    return f'<a target="_blank" rel="noopener noreferrer" href="{_e(url)}">打开岗位（人工发送）</a>'


def render_page(rows, *, token, notice='', summary=None):
    csrf = _hidden('csrf', token)
    cards = []
    for row in rows:
        job_id = int(row['id'])
        job = row.get('job') or {}
        decision = row.get('decision') or {}
        material = row.get('material') or {}
        content = material.get('content') or {}
        status = row.get('status', '')
        category = decision.get('category', 'review')
        category_label = {'priority': '优先考虑', 'review': '需要核实 / 可冲', 'reject': '明确不符合'}.get(category, '需要核实')
        revision = row.get('revision')
        snapshot_ready = (type(revision) is int and revision > 0
                          and material.get('revision') == revision
                          and bool(row.get('jd_hash')) and bool(material.get('content_hash')))
        snapshot = (_hidden(f'jd_{job_id}', row.get('jd_hash', ''))
                    + _hidden(f'material_{job_id}', material.get('content_hash', ''))
                    + _hidden(f'revision_{job_id}', revision))
        select = ''
        if category != 'reject' and snapshot_ready and status in {'READY_FOR_REVIEW', 'APPROVED'}:
            select = f'<label><input form="batch" type="checkbox" name="selected" value="{job_id}">选择</label>'
            snapshot = snapshot.replace('<input ', '<input form="batch" ')
        message = content.get('message', '')
        edit = f'''<form method="post" action="/edit">{csrf}{_hidden('job_id', job_id)}{_hidden('expected_material_hash', material.get('content_hash', ''))}{_hidden('expected_revision', revision)}
<label>实际准备发送的正文<textarea id="message-{job_id}" name="message">{_e(message)}</textarea></label>
<button type="button" data-copy="message-{job_id}">复制文案</button><button>保存修改（旧审批失效）</button></form>''' if snapshot_ready and status in {'READY_FOR_REVIEW', 'APPROVED'} else f'<textarea id="message-{job_id}" readonly>{_e(message)}</textarea><button type="button" data-copy="message-{job_id}">复制文案</button>'
        manual = ''
        approval_id = row.get('approval_id')
        if status == 'APPROVED' and snapshot_ready and type(approval_id) is int and approval_id > 0:
            manual = f'''<form method="post" action="/manual-submit">{csrf}{_hidden('job_id', job_id)}{_hidden('expected_material_hash', material.get('content_hash', ''))}{_hidden('expected_jd_hash', row.get('jd_hash', ''))}{_hidden('expected_revision', revision)}{_hidden('expected_approval_id', approval_id)}<p class="warning">系统没有发送。请在渠道中人工发送并核实后，再登记。</p><input type="text" name="evidence" placeholder="必填：你核实发送成功的依据（例如站内已发送记录）" required><button>我已人工发送并核实</button></form>'''
        followup = ''
        if status in {'SUBMITTED', 'REPLIED', 'INTERVIEW'}:
            followup = f'''<form method="post" action="/followup">{csrf}{_hidden('job_id', job_id)}<select name="status"><option value="REPLIED">已回复</option><option value="INTERVIEW">进入面试</option><option value="CLOSED">关闭申请</option></select><input type="text" name="note" placeholder="人工记录跟进信息"><button>更新进度</button></form>'''
        cards.append(f'''<article id="job-{job_id}"><div class="row">{select}<h2>#{job_id} {_e(job.get('job_title') or '职位待核实')}</h2><span class="badge">{_e(category_label)}</span><span class="badge">{_e(status)}</span></div>{snapshot}
<p>{_e(job.get('company') or '公司待核实')} · {_e(job.get('location') or '地点待核实')} · {_e(job.get('salary_range') or '薪资未披露')} · 分数 {_e(decision.get('score'))}（不是录用概率）</p>
{_link(job.get('source_url'))}<h3>匹配依据 / 缺口</h3><ul>{_items(decision.get('reasons'))}</ul><ul class="warning">{_items((decision.get('warnings') or []) + (content.get('warnings') or []))}</ul>
<p class="warning">{_e(row.get('availability_warning', ''))}</p><p>材料类型：{_e(content.get('channel', 'chat'))} · 简历版本：{_e(content.get('resume_version', 'not_selected'))}（本工作台不附加、不上传简历）</p>{edit}
<details><summary>文案事实依据</summary><ul>{_items(content.get('evidence'))}</ul></details><details><summary>查看原始 JD / 抽取信息</summary><pre>{_e(row.get('raw_jd') or job.get('jd_summary') or '仅有结构化导入数据，无原始 JD；请回来源核实。')}</pre></details>
<div class="actions">{manual}{followup}<form method="post" action="/skip">{csrf}{_hidden('job_id', job_id)}<button>跳过此岗位</button></form></div></article>''')
    stats = ' · '.join(f'{_e(k)}: {_e(v)}' for k, v in (summary or {}).items())
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>本地求职审核台</title><style nonce="{_e(token)}">{STYLE}</style></head><body>
<h1>本地求职审核台</h1><p class="muted">离线规则 + 事实模板 · 不调用 LLM · 审核后人工发送 · 仅本机访问</p><nav><a href="/">全部岗位</a><a href="/?category=priority">优先考虑</a><a href="/?category=review">待核实</a><a href="/?status=APPROVED">已批准</a><a href="/report">查看摘要</a></nav><p>{stats}</p>
{f'<div class="notice">{_e(notice)}</div>' if notice else ''}
<details><summary>加入岗位：可一次粘贴多条 JD（不会自动打开链接）</summary><section><form method="post" action="/import">{csrf}<input type="text" name="url" placeholder="可选：岗位原始链接"><textarea name="text" required placeholder="可粘贴多条招聘 App 复制的 JD，每条以职位标题和薪资开头"></textarea><button class="primary">离线分析并加入岗位池</button></form></section></details>
<form id="batch" method="post" action="/approve">{csrf}</form>{''.join(cards) or '<section>没有岗位。先粘贴 JD，或用 CLI 导入现有 JSON。</section>'}
<div class="approvebar"><button type="button" data-select-all>选择当前可审核项</button><label><input form="batch" type="checkbox" name="acknowledge_review" value="yes">我已逐项核实待确认条件和文案事实</label><button class="primary" form="batch">批准所选：仅人工联系准备</button><small>批准绑定当前 JD 与材料版本，24 小时有效；不是自动投递授权。</small></div>
<script nonce="{_e(token)}">{SCRIPT}</script></body></html>'''
