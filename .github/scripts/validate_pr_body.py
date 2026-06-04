from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REQUIRED_SECTIONS = (
    "设计目的",
    "架构审查",
    "import 审查",
    "函数审查",
    "验收证据",
    "风险与回滚",
)

PLACEHOLDER_MARKERS = (
    "[必须填写",
    "TODO",
    "todo",
    "待补",
    "后补",
)

ACTION_RUN_RE = re.compile(r"https://github\.com/[^/\s]+/[^/\s]+/actions/runs/\d+")
GITHUB_ATTACHMENT_RE = re.compile(
    r"https://github\.com/user-attachments/assets/[0-9a-fA-F-]+"
)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: validate_pr_body.py <github-event-json>")
        return 2

    event = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    body = (event.get("pull_request") or {}).get("body") or ""
    errors = validate_body(body)
    if errors:
        print("PR evidence gate failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("PR evidence gate passed.")
    return 0


def validate_body(body: str) -> list[str]:
    errors: list[str] = []
    if len(body.strip()) < 600:
        errors.append("PR 描述太短；需要设计说明、分层说明、证据和风险说明。")

    sections = _sections(body)
    for section in REQUIRED_SECTIONS:
        content = sections.get(section)
        if content is None:
            errors.append(f"缺少章节：## {section}")
            continue
        if len(_plain_content(content)) < 40:
            errors.append(f"章节内容过短：## {section}")

    for marker in PLACEHOLDER_MARKERS:
        if marker in body:
            errors.append(f"PR 描述仍包含占位内容：{marker}")

    has_action_run = ACTION_RUN_RE.search(body) is not None
    has_attachment = GITHUB_ATTACHMENT_RE.search(body) is not None
    if not has_action_run and not has_attachment:
        errors.append("验收证据必须包含 GitHub Actions run 链接或 GitHub 上传附件。")

    return errors


def _sections(body: str) -> dict[str, str]:
    matches = list(re.finditer(r"(?m)^##\s+(.+?)\s*$", body))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        title = match.group(1).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        sections[title] = body[start:end].strip()
    return sections


def _plain_content(value: str) -> str:
    lines = []
    for line in value.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("[必须填写"):
            continue
        lines.append(stripped)
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
