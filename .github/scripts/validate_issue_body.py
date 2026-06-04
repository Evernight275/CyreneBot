from __future__ import annotations

import json
import re
import sys
from pathlib import Path

MIN_BODY_LENGTH = 500
MIN_SECTION_LENGTH = 50

LOW_EFFORT_LINE_RE = re.compile(
    r"(?im)^\s*(-\s*)?(已测试|见代码|看代码|如题|同上|无|暂无|没有|N/A|n/a|none|null|no response)\s*[。.]?\s*$"
)
URL_RE = re.compile(r"https?://[^\s)]+")

COMMON_REQUIRED_SECTIONS = (
    "Problem",
    "Use case",
    "Design purpose",
    "Platform",
)

ISSUE_TYPE_REQUIRED_SECTIONS = {
    "bug": (
        "Problem",
        "Minimal reproduction",
        "Evidence",
        "Environment",
        "Expected behavior",
        "Scope and boundary check",
    ),
    "feature": (
        "Use case",
        "Proposal",
        "Project fit",
        "Boundaries and non-goals",
        "Architecture impact",
        "Acceptance evidence",
    ),
    "architecture": (
        "Design purpose",
        "Current call path",
        "Proposed boundary",
        "Function-level plan",
        "Rejected alternatives",
        "Boundary tests",
    ),
    "platform": (
        "Platform",
        "Agent capability",
        "Official API path",
        "Non-goals",
        "Architecture impact",
        "Evidence",
    ),
}


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: validate_issue_body.py <github-event-json> <comment-output>")
        return 2

    event = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    issue = event.get("issue") or {}
    title = issue.get("title") or ""
    body = issue.get("body") or ""

    errors = validate_issue(title=title, body=body)
    if errors:
        Path(sys.argv[2]).write_text(_comment(errors), encoding="utf-8")
        print("Issue gate failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("Issue gate passed.")
    return 0


def validate_issue(*, title: str, body: str) -> list[str]:
    errors: list[str] = []
    normalized_body = body.strip()
    if len(normalized_body) < MIN_BODY_LENGTH:
        errors.append("Issue body is too short to review.")

    if LOW_EFFORT_LINE_RE.search(body):
        errors.append("Issue contains low-effort placeholder answers.")

    sections = _sections(body)
    issue_type = _issue_type(title, sections)
    required_sections = ISSUE_TYPE_REQUIRED_SECTIONS.get(issue_type)
    if required_sections is None:
        if not any(section in sections for section in COMMON_REQUIRED_SECTIONS):
            errors.append("Issue does not appear to use an approved issue form.")
        required_sections = ()

    for section in required_sections:
        content = sections.get(section)
        if content is None:
            errors.append(f"Missing section: {section}")
            continue
        if len(_plain_content(content)) < MIN_SECTION_LENGTH:
            errors.append(f"Section is too short: {section}")

    if issue_type == "platform" and URL_RE.search(body) is None:
        errors.append("Platform issues must include at least one official API URL.")

    return errors


def _issue_type(title: str, sections: dict[str, str]) -> str | None:
    lowered = title.lower()
    for issue_type in ISSUE_TYPE_REQUIRED_SECTIONS:
        if lowered.startswith(f"[{issue_type}]"):
            return issue_type
    if "Minimal reproduction" in sections:
        return "bug"
    if "Project fit" in sections:
        return "feature"
    if "Current call path" in sections:
        return "architecture"
    if "Agent capability" in sections:
        return "platform"
    return None


def _sections(body: str) -> dict[str, str]:
    matches = list(re.finditer(r"(?m)^###\s+(.+?)\s*$", body))
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
        if not stripped or stripped == "_No response_":
            continue
        lines.append(stripped)
    return "\n".join(lines)


def _comment(errors: list[str]) -> str:
    items = "\n".join(f"- {error}" for error in errors)
    return (
        "This issue was closed by the Issue Gate because it does not provide enough "
        "reviewable material.\n\n"
        f"{items}\n\n"
        "Please open a new issue using the correct form and include concrete "
        "reproduction steps, evidence, architecture impact, and boundary details."
    )


if __name__ == "__main__":
    raise SystemExit(main())
