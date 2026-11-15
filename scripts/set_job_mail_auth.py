"""在本机安全录入邮箱 SMTP 授权码：不回显、不写日志、不经过聊天。"""
import getpass
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / 'output/job_workflow/smtp_auth.txt'


def main():
    print('163 邮箱授权码录入（输入内容不显示，文件写在 output/ 下，已被 git 忽略）')
    code = getpass.getpass('粘贴授权码后回车：').strip()
    if not code:
        print('未输入，已取消')
        return 1
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(code + '\n', encoding='utf-8')
    print(f'已保存：{TARGET}')
    print('下一步：在 sources.local.json 的 notification 里把 channel 设为 email 并填好 email 配置')
    return 0


if __name__ == '__main__':
    sys.exit(main())
