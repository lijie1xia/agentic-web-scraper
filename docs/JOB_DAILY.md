# 每日公开岗位发现

## 当前范围

- 港中大（深圳）职业站：公开 HTML，不登录、不申请、不调用 LLM。
- 每次读取最新两页列表，按 AI、Agent、大模型、Python、Java、后端、开发实习等标题关键词发现线索；最多读取八个岗位详情。
- `known_urls` 优先复查，与新发现共享详情上限。名单填满八个会挤占新发现名额，建议只保留少量重点岗位。
- 这是**局部监测**，不是全站或国内岗位的完整覆盖。不因岗位掉出最新列表而标记下架。
- 标题命中不代表适合。公司名中的 AI、综合校招公告也可能进入待核实；规则不能识别的学历、届次、到岗条件仍需看原文。
- 公开可读不代表已获批量转载授权，也不保证外校学生能使用校内申请入口。本机仅每天低频个人监测，遇到拒绝或页面变化直接报错，不绕过限制。

## 本机使用

```text
# 运行当前已启用的公开来源配置
.venv/Scripts/python.exe -S scripts/run_job_daily.py --config output/job_workflow/sources.local.json

# 打开这批真实岗位的本机审核台（与演示数据库分开）
.venv/Scripts/python.exe scripts/run_job_workflow.py --db output/job_workflow/public_jobs.sqlite3 serve
```

审核地址：`http://127.0.0.1:8765`，暂不支持手机访问。

文件位置：

| 文件 | 内容 |
| --- | --- |
| `config/job_sources.json` | 可提交的默认配置，`allow_network: false` |
| `output/job_workflow/sources.local.json` | 本机明确启用联网的配置，不提交 Git |
| `output/job_workflow/public_jobs.sqlite3` | 本次公开岗位池，不提交 Git |
| `output/job_workflow/public_daily.txt` | 岗位摘要，包含原始链接、版本和失效提示 |
| `output/job_workflow/public_last_notice.txt` | 最近一份变化摘要，附来源错误；恢复后也更新 |

同一岗位重复出现不会重复建档；JD 或决策改变产生新版本。版本、状态、截止日提示或来源异常变化时输出摘要；无变化时 stdout 为空。已发送、回复、面试仍须人工登记，脚本不审批、不联系企业。

## Windows 定时运行

本机任务名：`ScraperFramework-JobDaily`，每天本机时间 **09:00（当前 UTC+8）**。

- 使用项目 `.venv/Scripts/python.exe`，运行 `scripts/run_job_daily.py` 和本地配置。
- 使用当前用户交互登录身份，不保存密码、不提升权限。
- 设置错过时间后尽快运行、禁止实例重叠、最长六分钟；保留 Windows 默认电池限制。
- 电脑关机、休眠或用户未登录时不能保证按点运行；是否补跑以 Windows 计划任务状态为准。
- 日报保存在上述文件。**尚未配置桌面弹窗、聊天推送或手机通知**。

可在 Windows“任务计划程序”中查看、运行或禁用任务。命令行查询：

```powershell
Get-ScheduledTask -TaskName 'ScraperFramework-JobDaily'
Get-ScheduledTaskInfo -TaskName 'ScraperFramework-JobDaily'
```

Hermes 的 `no_agent` 调度可直接运行这种脚本，但本机验证时 gateway 未运行，当前会话无可用投递通道，因此本次采用 Windows 计划任务；试建的暂停 Hermes 任务已删除，避免将来重复运行。

## 来源核验记录

2026-10-23 本机公开 GET 核验：

- [岗位列表](https://career.cuhk.edu.cn/en/job/search)：两次返回 200，研究时列表内容一致；只验证了前两页，不能据此宣称全站稳定。
- [深圳锐圳 AI 工作流实习生](https://career.cuhk.edu.cn/en/job/view/id/468767)：真实详情返回 200，明确深圳、实习、截止 2026-12-31，正文包含 Python/Agent 等要求。
- 首次完整本机运行导入五条线索，包含上述实习、广州后端开发、综合校招和生物科技招聘信息；均为待核实，不是五条合格推荐。
- Dify 招聘子域本机返回 403、ASML 搜索线索返回 404，未纳入每日来源。

截止日期按本机日期判断，过期即暂停审批及人工交接。Greenhouse 的完整来源缺失规则见 [JOB_WORKFLOW.md](JOB_WORKFLOW.md)；不能套用到这里的局部列表。
