# Local development environment

The imported virtual environment referenced an interpreter on another device. It
was preserved outside the repository at
`D:\ProgramProject\scraper_framework-venv-imported-backup`.
The active environment is `.venv`, using Windows CPython 3.13.15.

## Rebuild on Windows

Run in the project directory (PowerShell or Git Bash):

```text
uv venv --python 3.13 .venv
uv pip install --python .venv/Scripts/python.exe -r requirements-hermes.lock --override requirements-overrides.txt
.venv/Scripts/python.exe -m playwright install chromium
```

Do not copy `.venv` between devices. Select `.venv/Scripts/python.exe` as the
interpreter in your editor. The lock captures the installed Windows environment,
not a guarantee of compatibility on other operating systems.

`requirements.txt` has not been rewritten. Direct dependency versions already
present in the imported environment were preserved where available; Gradio was
added from the manifest. The lock also pins resolved transitive dependencies.

## Known dependency metadata conflict

CAMEL-AI 0.2.90 declares `psutil>=5.9.8,<6`, while Crawl4AI 0.9.2 requires
`psutil>=6.1.1`. This conflict was already documented in the project's README.
The scoped override uses psutil 6.1.1; it does not falsify installed metadata.
`uv pip check --python .venv/Scripts/python.exe` therefore reports **one known
incompatibility**, not a clean dependency check. Do not downgrade psutil merely
to silence it; isolate these stacks or revisit upstream requirements separately.

## Verification baseline before workflow changes

- Real imports of CAMEL ChatAgent, MCP FastMCP, Gradio, DrissionPage and PyMuPDF.
- Playwright headless Chromium launched and read a local test page.
- Crawl4AI converted local HTML to Markdown.
- `tests/test_decision.py`: 13/13 passed.
- `tests/test_generate.py`: 7/7 passed (mocked LLM).
- `tests/test_doc_agent.py`: 10 passed, 1 pre-existing failure in
  `test_is_final_output`; the user's modified DocAgent file was not overwritten.

No live model request, recruitment login, or application submission is needed for
these checks. `.env`, credentials and browser sessions are not versioned.
