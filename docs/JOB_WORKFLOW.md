# 本地求职审核工作流

把多份 JD 整理成可批量审核的岗位池：离线提取、规则评分、事实模板文案、SQLite 存储、审批和人工进度登记。新入口不调用 LLM，旧的抽取和生成脚本保持独立。

## 快速试用

在项目根目录运行，先用独立的演示数据库：

```text
.venv/Scripts/python.exe scripts/run_job_workflow.py --db output/job_workflow/demo.sqlite3 import-json data/job_workflow_examples.json
.venv/Scripts/python.exe scripts/run_job_workflow.py --db output/job_workflow/demo.sqlite3 serve
```

浏览器打开 `http://127.0.0.1:8765`。演示文件包含虚构岗位，不可用于真实投递；使用自己的 JD 时换一个数据库路径。

1. 展开“加入岗位”，粘贴 JD；也可导入原项目的抽取或评分 JSON。
2. 查看“优先考虑 / 需要核实 / 明确不符合”、判断理由和实际文案。复杂或缺失条件需要人工核实，分数不是录用概率。
3. 修改文案，勾选已核实事实，选择岗位后批量批准。
4. 复制文案，在招聘渠道中人工发送；确认发送记录后填写依据并登记。
5. 收到回复或面试安排后，在工作台更新进度。

按 `Ctrl+C` 关闭服务。重启时使用同一数据库路径即可继续。

## 常用命令

省略 `--db` 时使用 `output/job_workflow/jobs.sqlite3`。通用参数写在子命令之前。

```text
# 导入原项目 JSON，重新评分，不信任旧的推荐结果
.venv/Scripts/python.exe scripts/run_job_workflow.py import-json path/to/jobs.json

# 从 UTF-8 文本导入 JD；链接只保存，不会自动打开
.venv/Scripts/python.exe scripts/run_job_workflow.py paste path/to/jd.txt --url https://example.com/jobs/123

# 查看进度摘要
.venv/Scripts/python.exe scripts/run_job_workflow.py report

# 重复导入并更新日报；某个来源失败不阻塞其他来源
.venv/Scripts/python.exe scripts/run_job_workflow.py cycle --input path/to/jobs.json --report output/job_workflow/daily.txt

# 预览岗位 1 已批准的材料，不执行发送
.venv/Scripts/python.exe scripts/run_job_workflow.py handoff 1
```

`cycle` 支持重复传入 `--input` 和 `--board`。内容不变时不会重复创建岗位，摘要不变时不重复写文件。只提供原文、没有链接或外部 ID 的岗位按原文去重；原文改写可能成为新岗位。

## 画像与材料

默认读取 `data/skill_profile.json` 和 `data/resume_highlights.json`；可用 `--profile`、`--resume` 指定其他 JSON 文件。默认生成短招呼语；`--channel email` 改为邮件开场白。

材料只选用已有简历事实中的匹配项目，不改写简历事实。页面的简历版本字段不代表已经选择、附加或上传了 PDF。

材料或岗位判断变化会使旧审批失效。旧页面保存、批准或登记时，如果版本已变化，会要求刷新后重新确认。审批默认 24 小时有效；重复批准仍有效的同一份材料不会顺延有效期。

## 公开岗位来源

已提供指定公司 Greenhouse 招聘板的公开 GET 适配器，必须显式允许联网：

```text
.venv/Scripts/python.exe scripts/run_job_workflow.py discover-greenhouse BOARD_TOKEN --allow-network
```

将 `BOARD_TOKEN` 替换为已核实的公司招聘板标识。适配器限制官方 API 主机、拒绝重定向，不包含申请提交接口。没有配置公司名单，也没有接入 BOSS 或牛客的登录态发现和沟通。

Greenhouse 完整快照只有在整批读取、导入均成功后，才将先前存在但本轮缺席的岗位标记为“来源缺失”，撤销旧审批并暂停新的审批。失败、不完整响应和本地导入不会触发缺失判定；缺失也不等于确认关闭。岗位重新出现后可重新审核，不恢复旧审批，不覆盖已投递或面试记录。

来源明确提供的 `deadline` 使用 ISO 日期（`YYYY-MM-DD`）；按本机日期判断，截止日当天仍可审核。过期后审核页和日报提示原因，审批及人工交接入口均拒绝，不把历史申请记录改成关闭。没有明确截止日期的岗位不会凭空推断过期。

`cycle` 仍是单次运行命令。港中大深圳局部公开来源、每日脚本及本机 Windows 计划任务见 [JOB_DAILY.md](JOB_DAILY.md)。手机访问和通知推送尚未接入。

## 状态与数据

- 审核后仍由用户发送；`SUBMITTED` 表示人工核实后登记，不是平台回执。
- 回复和面试由人工登记，日报依据本地记录，不读取招聘平台消息。
- 数据库保存岗位修订、材料、审批、执行和跟进记录；不要提交数据库、私人 JD 或简历内容到 Git。
- 工作台只监听 `127.0.0.1`，不能直接当作手机可访问的远程服务。

## 离线验证

```text
.venv/Scripts/python.exe -m unittest discover -s tests -p "test_job_*.py"
.venv/Scripts/python.exe tests/test_decision.py
.venv/Scripts/python.exe tests/test_generate.py
```

浏览器测试使用 Playwright Chromium、临时 SQLite 和本地模拟岗位。环境安装方式见 [ENVIRONMENT.md](ENVIRONMENT.md)。
