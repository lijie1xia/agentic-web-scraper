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
| `config/job_sources.json` | 可提交的默认配置，`allow_network: false`、`notification.enabled: false` |
| `output/job_workflow/sources.local.json` | 本机明确启用联网的配置，不提交 Git |
| `output/job_workflow/public_jobs.sqlite3` | 本次公开岗位池，不提交 Git |
| `output/job_workflow/public_daily.txt` | 岗位摘要，包含原始链接、版本和失效提示 |
| `output/job_workflow/public_last_notice.txt` | 最近一份成功处理的变化摘要，附来源错误；是否要求通知确认取决于下述配置 |

同一岗位重复出现不会重复建档；JD 或决策改变产生新版本。版本、状态、截止日提示或来源异常变化时输出摘要；无变化时 stdout 为空。已发送、回复、面试仍须人工登记，脚本不审批、不联系企业。

## 可选个人微信通知（不调用 LLM）

默认不推送。省略 `notification` 或设置 `enabled: false` 时，只输出变化摘要并记录状态，不启动 Hermes。已有配置无需迁移。`allow_network` 只控制岗位来源抓取；微信推送由 `notification.enabled` 单独授权，启用后会通过 Hermes 联网发送给个人微信。

先在 Hermes 中完成个人微信配对与接收目标配置，再由用户明确启用本机 `output/job_workflow/sources.local.json` 的以下字段；不要将账号凭据、token 或 cookie 写进岗位配置：

```json
{
  "notification": {
    "enabled": true,
    "target": "weixin",
    "command": ["hermes"]
  }
}
```

这是合并进原配置的片段，不是完整来源配置。`command` 是非空字符串列表，可包含可执行文件及固定参数；不要填整条 shell 命令。上面的 `["hermes"]` 依赖 PATH。Windows 计划任务建议改成你本机已验证的 `hermes.exe` 绝对路径，写在不提交的 `output/job_workflow/sources.local.json` 里，不使用无扩展名的 shell 启动脚本。只接受布尔值 `enabled`，不是字符串 `"true"` 或数字 `1`；启用时 `target` 必须为 `weixin`。

发送和状态语义：

1. 摘要有变化时先输出到 stdout，并成功 flush；写入或 flush 失败则不发送、不更新 `notice_state`，返回非零。
2. 启用通知后，仅执行一次 `command + ["send", "--to", "weixin", "--json"]`。摘要通过 UTF-8 标准输入传递，捕获输出，`shell=False`，通知子进程超时为 30 秒；不启动聊天代理、不调用模型、不提交岗位申请或联系企业。
3. **stdout 输出成功不等于通知投递被接受。** 必须同时满足 CLI 退出码为 0、stdout 是 JSON 对象且 `success` 为布尔值 `true`，才更新 `notice_state`。这只是 CLI 确认投递被接受，不是手机已显示或用户已读的凭据；CLI JSON 不混入日报 stdout。
4. 命令失败、启动失败、超时、JSON 损坏或未确认成功都返回非零，保留旧状态。本次不立即重试；下一次计划运行会再次尝试尚未记录成功的变化摘要。超时属于结果未知，消息可能已经发出，因此下次运行可能重复；发送成功后本地状态写入失败也可能重复。**不承诺绝对 exactly-once。**
5. 摘要与 `notice_state` 相同则 stdout 为空且不发送。通知关闭时，状态只代表 stdout 已成功输出；从关闭切换到启用并不会自动补发相同摘要。如需把首次微信通知与历史 stdout 状态分开，可在本机配置选择新的 `notice_state` 路径，之后仍复用该路径。

离线回归测试（本地替身与子进程 mock，不会真实发送消息）：

```text
.venv/Scripts/python.exe -m unittest discover -s tests -p test_job_daily.py -v
```

## Windows 定时运行

本机任务名：`ScraperFramework-JobDaily`，每天本机时间 **09:00（当前 UTC+8）**。

- 使用项目 `.venv/Scripts/python.exe`，运行 `scripts/run_job_daily.py` 和本地配置。
- 使用当前用户交互登录身份，不保存密码、不提升权限。
- 设置错过时间后尽快运行、禁止实例重叠、最长六分钟；保留 Windows 默认电池限制。
- 电脑关机、休眠或用户未登录时不能保证按点运行；是否补跑以 Windows 计划任务状态为准。
- 日报保存在上述文件。个人微信推送须按上节显式启用；默认配置仍不推送，未配置桌面弹窗。

可在 Windows“任务计划程序”中查看、运行或禁用任务。命令行查询：

```powershell
Get-ScheduledTask -TaskName 'ScraperFramework-JobDaily'
Get-ScheduledTaskInfo -TaskName 'ScraperFramework-JobDaily'
```

Hermes 的 `no_agent` 调度也可直接运行这种脚本，但当前定时入口仍为 Windows 计划任务；无需再建第二个每日任务。个人微信配对已验证，用户已收到独立测试消息；是否推送每日摘要仍由本机 `notification.enabled` 决定。脚本通过 `hermes send` 直接发送，不依赖 LLM 调度。

## 来源核验记录

2026-10-23 本机公开 GET 核验：

- [岗位列表](https://career.cuhk.edu.cn/en/job/search)：两次返回 200，研究时列表内容一致；只验证了前两页，不能据此宣称全站稳定。
- [深圳锐圳 AI 工作流实习生](https://career.cuhk.edu.cn/en/job/view/id/468767)：真实详情返回 200，明确深圳、实习、截止 2026-12-31，正文包含 Python/Agent 等要求。
- 首次完整本机运行导入五条线索，包含上述实习、广州后端开发、综合校招和生物科技招聘信息；均为待核实，不是五条合格推荐。
- Dify 招聘子域本机返回 403、ASML 搜索线索返回 404，未纳入每日来源。

截止日期按本机日期判断，过期即暂停审批及人工交接。Greenhouse 的完整来源缺失规则见 [JOB_WORKFLOW.md](JOB_WORKFLOW.md)；不能套用到这里的局部列表。
