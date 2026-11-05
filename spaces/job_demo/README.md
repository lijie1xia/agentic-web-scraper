---
title: Job Agent Demo
emoji: 📬
colorFrom: indigo
colorTo: blue
sdk: gradio
sdk_version: 4.44.1
app_file: app.py
pinned: false
license: mit
python_version: "3.11"
---

# 求职 Agent Demo

粘贴招聘 JD → 结构化抽取 → 匹配评分 → 三版求职邮件开场白。

本应用只处理粘贴文本，不打开招聘网站，也不代为发送邮件。

页面顶部有一份**静态样例结果**，打开即可看。下方粘贴任意 JD 会走本地规则抽取与评分，同样不消耗额度。

需要按自己粘贴的 JD 实时生成开场白时，展开页面底部的「高级选项」，填入**访客自己的** DeepSeek API Key。

![preview](preview.gif)

Demo 使用作者的公开求职画像（学校、实习、项目成果），不含手机号、邮箱或证件号。

## 密钥与费用

- **不需要**在 Space / 创空间 Secrets 里配置 `DEEPSEEK_API_KEY`：公开 Demo 默认零成本运行。
- 访客 Key 只在本次请求内透传给模型调用，不写入磁盘、不记录日志；留空时只返回预置示例文案。
- 免费路径（规则抽取 + 评分）不限流；实时生成的连续调用 5 次后冷却 60 秒。

## 部署

Hugging Face Spaces（需先 `hf auth login`）：

```bash
python spaces/job_demo/deploy.py

# 网络不可直连时用代理；也可以设置 HF_PROXY，不写死在代码里
python spaces/job_demo/deploy.py --proxy http://127.0.0.1:7890
```

ModelScope 创空间：在魔搭创建 Gradio 创空间后，导出产物再推进该仓库：

```bash
python spaces/job_demo/deploy.py --out ./space_build
```

本地：

```bash
python spaces/job_demo/app.py
```
