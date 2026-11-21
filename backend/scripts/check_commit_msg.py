"""commit-msg hook: one line in Conventional Commits form, as the repository rules require.

prek calls it with the path of the message file; it exits 1 and explains what is wrong.
"""

import re
import sys
from pathlib import Path

TYPES = ("feat", "fix", "docs", "refactor", "test", "chore", "build", "perf")
SUBJECT = re.compile(rf"(?:{'|'.join(TYPES)})\([a-z0-9][a-z0-9._-]*\): \S.*")
CODE_SPAN = re.compile(r"`[^`]*`")
PASS_THROUGH = ("Merge ", "Revert ", "fixup! ", "squash! ", "amend! ")
MAX_LENGTH = 100


def problems(message: str) -> list[str]:
    lines = [line.rstrip() for line in message.splitlines() if not line.startswith("#")]
    while lines and not lines[-1]:
        lines.pop()
    if not lines:
        return ["the message is empty"]
    subject = lines[0]
    if subject.startswith(PASS_THROUGH):
        return []

    found = []
    if len(lines) > 1:
        found.append("use a single line: no body, no trailers")
    if not SUBJECT.fullmatch(subject):
        found.append(f"use `type(scope): summary`, where type is one of: {', '.join(TYPES)}")
    plain = CODE_SPAN.sub("", subject)
    if plain != plain.lower():
        found.append("use lowercase (code in backticks may keep its case)")
    if subject.endswith("."):
        found.append("drop the trailing period")
    if len(subject) > MAX_LENGTH:
        found.append(f"keep it within {MAX_LENGTH} characters (now {len(subject)})")
    return found


def main() -> int:
    message = Path(sys.argv[1]).read_text(encoding="utf-8")
    found = problems(message)
    for problem in found:
        print(f"commit message: {problem}", file=sys.stderr)
    if found:
        print("example: feat(scraper): add price segmentation", file=sys.stderr)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
