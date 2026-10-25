"""Instruction-system drift check: the committed files pass, and each guard fails when it should."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from tools import check_agent_docs as chk

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    for rel in chk.REQUIRED + ["project.md"]:
        dest = tmp_path / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / rel, dest)
    shutil.copytree(REPO / "docs/handoffs", tmp_path / "docs/handoffs")  # linked from the charter and workflow
    return tmp_path


def test_committed_instruction_system_passes():
    assert chk.check(REPO) == []


def test_missing_adapter_is_reported(tree: Path):
    (tree / "CLAUDE.md").unlink()
    assert any("CLAUDE.md" in e for e in chk.check(tree))


def test_claude_md_must_import_agents_md(tree: Path):
    (tree / "CLAUDE.md").write_text("# no import here\n")
    assert any("@AGENTS.md" in e for e in chk.check(tree))


def test_import_inside_code_fence_does_not_count(tree: Path):
    (tree / "CLAUDE.md").write_text("```\n@AGENTS.md\n```\n")
    assert any("@AGENTS.md" in e for e in chk.check(tree))


def test_oversized_agents_md_is_reported(tree: Path):
    path = tree / "AGENTS.md"
    path.write_text(path.read_text() + "\nx" * chk.AGENTS_MAX_BYTES)
    assert any("exceeds" in e for e in chk.check(tree))


def test_agents_md_must_link_charter(tree: Path):
    path = tree / "AGENTS.md"
    path.write_text(path.read_text().replace("docs/agents/charter.md", "docs/agents/other.md"))
    assert any("charter.md" in e for e in chk.check(tree))


def test_cursor_rule_must_always_apply(tree: Path):
    path = tree / ".cursor/rules/engineering-charter.mdc"
    path.write_text(path.read_text().replace("alwaysApply: true", "alwaysApply: false"))
    assert any("alwaysApply" in e for e in chk.check(tree))


def test_cursor_rule_reference_must_exist(tree: Path):
    (tree / "docs/agents/workflow.md").unlink()
    assert any("missing" in e for e in chk.check(tree))


def test_skill_name_must_match_directory(tree: Path):
    path = tree / ".claude/skills/recon/SKILL.md"
    path.write_text(path.read_text().replace("name: recon", "name: other"))
    assert any("recon/SKILL.md" in e for e in chk.check(tree))


def test_broken_relative_link_is_reported(tree: Path):
    path = tree / "docs/agents/workflow.md"
    path.write_text(path.read_text() + "\n[x](nope.md)\n")
    assert any("broken relative link" in e for e in chk.check(tree))


def test_machine_path_is_reported(tree: Path):
    path = tree / "docs/agents/charter.md"
    path.write_text(path.read_text() + "\nsee /" + "Users/someone/repo\n")
    assert any("machine-specific" in e for e in chk.check(tree))


def test_credential_shape_is_reported(tree: Path):
    path = tree / "docs/agents/charter.md"
    fake = "gh" + "p_" + "a" * 36  # assembled at runtime so no token-shaped literal is committed
    path.write_text(path.read_text() + f"\n{fake}\n")
    assert any("credential-shaped" in e for e in chk.check(tree))


def test_import_inside_html_comment_does_not_count(tree: Path):
    (tree / "CLAUDE.md").write_text("<!--\n@AGENTS.md\n-->\n")
    assert any("@AGENTS.md" in e for e in chk.check(tree))


def test_cursor_rule_must_reference_canonical_docs(tree: Path):
    path = tree / ".cursor/rules/engineering-charter.mdc"
    text = path.read_text()
    for ref in chk.CURSOR_MUST_REFERENCE:
        text = text.replace("@" + ref, ref)
    path.write_text(text)
    errors = chk.check(tree)
    assert all(any(f"@{ref}" in e for e in errors) for ref in chk.CURSOR_MUST_REFERENCE)


@pytest.mark.parametrize("leak", ["C:/Users/alice/repo", "/home/Alice/repo", "/tmp/alice/repo", "/var/folders/ab/cd"])
def test_more_machine_path_shapes_are_reported(tree: Path, leak: str):
    path = tree / "docs/agents/charter.md"
    path.write_text(path.read_text() + f"\nsee {leak}\n")
    assert any("machine-specific" in e for e in chk.check(tree))


def test_handoffs_are_scanned_for_hygiene(tree: Path):
    path = next((tree / "docs/handoffs").glob("*chatgpt-lead.md"))
    path.write_text(path.read_text() + "\nsee /" + "Users/someone/repo\n")
    assert any("chatgpt-lead.md" in e and "machine-specific" in e for e in chk.check(tree))


def test_main_exit_code(tree: Path, capsys):
    assert chk.main(["--root", str(tree)]) == 0
    (tree / "AGENTS.md").unlink()
    assert chk.main(["--root", str(tree)]) == 1
