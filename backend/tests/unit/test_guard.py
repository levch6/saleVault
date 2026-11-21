"""The Claude Code guard in .claude/hooks/guard.py."""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest


def load() -> ModuleType:
    path = Path(__file__).parents[3] / ".claude" / "hooks" / "guard.py"
    spec = importlib.util.spec_from_file_location("guard", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = load()


@pytest.mark.parametrize(
    "command",
    [
        'git commit -m "x" --no-verify',
        'git commit -nm "x"',
        'git commit -anm "x"',
        'git commit --no-verif -m "x"',
        'cd repo && git -C /r commit -n -m "x" | tail -1',
        "git push --no-verify",
        "git -c core.hooksPath=/dev/null commit -m x",
        "git config --local core.hookspath /dev/null",
        "git -C /r config --get core.hooksPath; echo done",
        "SKIP=mypy git commit -m x",
        "git add -f .notes/plan.md",
        "git add -fA",
        "git add --force data/salevault.db",
        "cd .notes && git add -f plan.md",
    ],
)
def test_denies(command: str) -> None:
    verdict = guard.check_bash(command)
    assert verdict is not None
    assert verdict[0] == "deny"


@pytest.mark.parametrize(
    "command",
    [
        "uv run pytest -m live",
        "uv run pytest -q -m live",
        "uv run pytest tests/live -m live",
        "cd backend && uv run pytest tests/live",
    ],
)
def test_asks_before_live_tests(command: str) -> None:
    assert guard.check_bash(command) == ("ask", "Live tests send requests to the real shops.")


@pytest.mark.parametrize(
    "command",
    [
        'git commit -m "docs(repo): explain -n and --no-verify"',
        "git log --oneline -3; git status -sb",
        "git --no-pager log -n 3",
        "git add frontend/src/app.tsx",
        "git add zz.txt && git rm -q --cached -f zz.txt",
        "git add a.txt; echo -f done",
        "git commit -m x | grep -n done",
        "uv run pytest -q",
        "uv run pytest -m 'not live'",
        "just check",
        'echo "unterminated',
    ],
)
def test_allows(command: str) -> None:
    assert guard.check_bash(command) is None


def test_generated_files_are_read_only() -> None:
    assert guard.check_edit("/x/frontend/src/api/schema.d.ts") is not None
    assert guard.check_edit("/x/frontend/src/api/queries.ts") is None
