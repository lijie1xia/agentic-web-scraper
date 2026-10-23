# Agent working agreement

- Hermes changes belong on `feature/hermes`. Check the current branch before edits.
- Make small, purpose-specific commits after tests and review. Do not combine unrelated features in one commit or push without an explicit request.
- The repository contains pre-existing user modifications. Never discard, stage, or commit those as part of agent work. Inspect exact diffs; avoid `git add -A` and blanket stash/reset.
- Use `.venv/Scripts/python.exe` on this Windows workstation. See `docs/ENVIRONMENT.md` for reproducible installation and the known dependency/test baseline.
- Job workflow development is offline-first. Do not spend LLM credit, log into recruitment accounts, or send applications/messages during tests. Use local fixtures and temporary SQLite databases.
- All real contact requires a current approval tied to the exact job, material version, and action. A manual handoff is not a successful application. Ambiguous submissions must not auto-retry.
- If credentials, platform permission or user confirmation are missing, disable that operation and continue independent local work; never invent confirmation or fabricate execution results.
- Keep `.env`, API keys, cookies, private database contents and runtime logs out of commits.
