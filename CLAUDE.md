# saleVault: Claude Code

The project brief for every coding agent lives in `AGENTS.md`; it is imported here.

@AGENTS.md

## Claude Code specifics

- `.claude/settings.json`: shared permissions. Everyday checks run without prompts; anything that reaches the shops or leaves the machine asks first (scrapes, live tests, `git push`, merging PRs, `just gen-api`, `just shortcut`, `pnpm approve`); reading `data/browser/` (shop cookies) is denied. Personal overrides go to `.claude/settings.local.json` (gitignored).
- `.claude/hooks/guard.py` (PreToolUse, tested in `backend/tests/unit/test_guard.py`): blocks hand edits of generated files, bypassing git hooks (`--no-verify`, `-n`, `SKIP=`, `core.hooksPath`), and any forced `git add`; asks before live tests in any spelling.
- Skills: `.claude/skills/<name>` are symlinks to `.agents/skills/<name>` (project skills) or to `frontend/.claude/skills/<name>` (TanStack's skills, maintained by pnpm). Edit project skills in `.agents/skills/`; add a symlink for a new one (`ln -s ../../.agents/skills/<name> .claude/skills/<name>`) and check with `just links`.
- Browser checks use the Playwright MCP browser. It saves screenshots only inside the repo (`.playwright-mcp/`, gitignored); delete them afterwards.
