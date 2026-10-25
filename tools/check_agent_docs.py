"""Drift check for the agent instruction system (AGENTS.md, CLAUDE.md, Cursor rule, skills, docs/agents).

Read-only. Verifies structure and hygiene only; it cannot prove a client actually loads the files
(see docs/agents/README.md for how loading was verified).

    python -m tools.check_agent_docs [--root PATH]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REQUIRED = [
    "AGENTS.md",
    "CLAUDE.md",
    ".cursor/rules/engineering-charter.mdc",
    ".claude/skills/recon/SKILL.md",
    ".claude/skills/handoff/SKILL.md",
    "docs/agents/charter.md",
    "docs/agents/workflow.md",
    "docs/agents/handoff-template.md",
    "docs/agents/README.md",
]
# Codex stops reading project docs at 32 KiB combined; keep the always-loaded digest far below that.
AGENTS_MAX_BYTES = 12_000
AGENTS_MUST_LINK = [
    "docs/agents/charter.md",
    "docs/agents/workflow.md",
    "docs/agents/handoff-template.md",
    "docs/agents/README.md",
    "project.md",
]
# Heuristic: catches common home/temp path shapes, not every possible machine-specific path.
MACHINE_PATH = re.compile(
    r"(?:/Users/|/home/[A-Za-z]|[A-Za-z]:[\\/]Users[\\/]|/private/tmp/|/var/folders/|/tmp/[A-Za-z])",
)
SECRET_SHAPES = [
    re.compile(p)
    for p in (
        r"gh[pousr]_[A-Za-z0-9]{30,}",
        r"github_pat_[A-Za-z0-9_]{30,}",
        r"sk-[A-Za-z0-9_-]{24,}",
        r"AKIA[0-9A-Z]{16}",
        r"xox[abprs]-[A-Za-z0-9-]{10,}",
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    )
]
MD_LINK = re.compile(r"\]\(([^)\s]+)\)")
AT_REF = re.compile(r"(?m)^\s*@([\w./-]+)\s*$")
CURSOR_AT_REF = re.compile(r"@([\w][\w./-]*\.[A-Za-z]+)")
CURSOR_MUST_REFERENCE = ["project.md", "docs/agents/charter.md", "docs/agents/workflow.md"]


def _strip_fences(text: str) -> str:
    """Drop fenced code and HTML comments: neither is an active import or link."""
    return re.sub(r"<!--.*?-->", "", re.sub(r"```.*?```", "", text, flags=re.S), flags=re.S)


def _frontmatter(text: str) -> dict[str, str] | None:
    match = re.match(r"---\n(.*?)\n---\n", text, flags=re.S)
    if not match:
        return None
    out: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            out[key.strip()] = value.strip()
    return out


def check(root: Path) -> list[str]:
    errors: list[str] = []
    texts: dict[str, str] = {}
    for rel in REQUIRED:
        path = root / rel
        if not path.is_file():
            errors.append(f"missing required file: {rel}")
        else:
            texts[rel] = path.read_text(encoding="utf-8")
    if errors:
        return errors

    agents = texts["AGENTS.md"]
    if len(agents.encode()) > AGENTS_MAX_BYTES:
        errors.append(f"AGENTS.md exceeds {AGENTS_MAX_BYTES} bytes (Codex truncates at 32 KiB combined)")
    for target in AGENTS_MUST_LINK:
        if target not in agents:
            errors.append(f"AGENTS.md does not reference {target}")

    if "AGENTS.md" not in AT_REF.findall(_strip_fences(texts["CLAUDE.md"])):
        errors.append("CLAUDE.md must import AGENTS.md with a standalone `@AGENTS.md` line")

    rule = texts[".cursor/rules/engineering-charter.mdc"]
    fm = _frontmatter(rule)
    if fm is None or fm.get("alwaysApply") != "true" or not fm.get("description"):
        errors.append("Cursor rule needs frontmatter with alwaysApply: true and a description")
    refs = CURSOR_AT_REF.findall(rule)
    for required in CURSOR_MUST_REFERENCE:
        if required not in refs:
            errors.append(f"Cursor rule must reference @{required}")
    for ref in refs:
        if not (root / ref).exists():
            errors.append(f"Cursor rule references missing file: @{ref}")

    for rel in (".claude/skills/recon/SKILL.md", ".claude/skills/handoff/SKILL.md"):
        fm = _frontmatter(texts[rel])
        expected = Path(rel).parent.name
        if fm is None or fm.get("name") != expected or not fm.get("description"):
            errors.append(f"{rel}: frontmatter must have name: {expected} and a description")

    for rel in ("CLAUDE.md", "AGENTS.md", *[r for r in REQUIRED if r.startswith("docs/agents/")]):
        base = (root / rel).parent
        body = _strip_fences(texts[rel])
        for link in MD_LINK.findall(body):
            if link.startswith(("http://", "https://", "mailto:", "#")):
                continue
            if not (base / link.split("#", 1)[0]).exists():
                errors.append(f"{rel}: broken relative link {link}")
        if rel == "CLAUDE.md":
            for ref in AT_REF.findall(body):
                if not (base / ref).exists():
                    errors.append(f"{rel}: broken @import {ref}")

    for handoff in sorted((root / "docs/handoffs").glob("*.md")):
        texts[handoff.relative_to(root).as_posix()] = handoff.read_text(encoding="utf-8")
    for rel, text in texts.items():
        if MACHINE_PATH.search(text):
            errors.append(f"{rel}: contains an absolute machine-specific path")
        if any(p.search(text) for p in SECRET_SHAPES):
            errors.append(f"{rel}: contains a credential-shaped string")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args(argv)
    errors = check(args.root)
    for err in errors:
        print(f"FAIL {err}")
    print("agent instruction check:", "FAILED" if errors else "ok")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
