"""邮件正文排版：纯文本、岗位之间留空行。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scraper_framework.job_workflow.notify_text import to_plain

SAMPLE = """本地求职进度摘要
不调用 LLM；SUBMITTED 为人工确认记录，不是自动投递回执。
岗位总数: 2

需要核实
#9 广州一点灵犀正在招聘ai agent开发实习生 | READY_FOR_REVIEW | 版本1：画像未证明必需技能：C++
#5 后端开发工程师 | READY_FOR_REVIEW | 版本3：学历要求无法识别

明确不符合：0 条
"""


class NotifyTextTests(unittest.TestCase):
    def test_job_entries_become_indented_blocks_with_blank_lines(self):
        plain = to_plain(SAMPLE)
        self.assertIn('[9] 广州一点灵犀正在招聘ai agent开发实习生\n    状态：READY_FOR_REVIEW\n    说明：版本1：画像未证明必需技能：C++', plain)
        self.assertIn('\n\n[5] 后端开发工程师', plain)

    def test_no_pipe_separators_left_in_body(self):
        self.assertNotIn(' | ', to_plain(SAMPLE))

    def test_head_paragraph_stays_together_and_sections_separated(self):
        plain = to_plain(SAMPLE)
        self.assertTrue(plain.startswith('本地求职进度摘要\n不调用 LLM；SUBMITTED 为人工确认记录，不是自动投递回执。\n岗位总数: 2\n\n'))
        self.assertIn('\n\n需要核实\n\n[9]', plain)
        self.assertTrue(plain.endswith('明确不符合：0 条\n'))

    def test_markdown_markers_are_removed(self):
        # 原文没有空行时保持同一段，只去掉 markdown 记号，不擅自插入空行。
        plain = to_plain('## 需要核实\n**重点**：查看')
        self.assertEqual(plain, '需要核实\n重点：查看\n')

    def test_empty_input_returns_empty_string(self):
        self.assertEqual(to_plain(''), '')
        self.assertEqual(to_plain('\n\n'), '')


if __name__ == '__main__':
    unittest.main()
