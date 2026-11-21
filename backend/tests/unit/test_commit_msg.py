import importlib.util
from pathlib import Path
from types import ModuleType

import pytest


def load() -> ModuleType:
    path = Path(__file__).parents[2] / "scripts" / "check_commit_msg.py"
    spec = importlib.util.spec_from_file_location("check_commit_msg", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


problems = load().problems


@pytest.mark.parametrize(
    "message",
    [
        "feat(scraper): add price segmentation\n",
        "perf(catalog): resolve new and price drop flags to ids before paging",
        "fix(ui): keep `HttpSession` open\n\n# Please enter the commit message\n",
        "Merge branch 'feature'\n\nsome body",
        "fixup! feat(ui): add logo",
    ],
)
def test_accepts(message: str) -> None:
    assert problems(message) == []


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("", "empty"),
        ("add stuff", "type(scope): summary"),
        ("feat: add stuff", "type(scope): summary"),
        ("style(ui): add stuff", "type(scope): summary"),
        ("feat(ui): Add stuff", "lowercase"),
        ("feat(ui): add stuff.", "trailing period"),
        ("feat(ui): add stuff\n\nCo-Authored-By: someone", "single line"),
        ("feat(ui): " + "a" * 100, "100 characters"),
    ],
)
def test_rejects(message: str, expected: str) -> None:
    assert any(expected in problem for problem in problems(message))
