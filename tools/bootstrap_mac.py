"""Prepare a new Mac for Agent Mindmap without starting anything.

  python -m tools.bootstrap_mac                       # --check (default): read-only report of what is missing
  python -m tools.bootstrap_mac --dry-run --label "Mac B"   # print what `install` would do; writes nothing
  python -m tools.bootstrap_mac install --label "Mac B"     # create the pieces below; idempotent

`install` creates: the config dir (0700), this Mac's anonymous identity (role READER), the state dirs, and the stable
runtime (venv + immutable release of the COMMITTED code, plists staged outside ~/Library/LaunchAgents). It starts no
process, loads no LaunchAgent, never copies another machine's credentials and makes no model call. Re-running it
changes nothing that is already in place.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from tools import machine_identity as mi
from tools import publisher_launchd as ld
from tools import runtime_install as ri


@dataclass
class Step:
    id: str
    done: bool
    action: str          # what install does when not done
    detail: str = ""


def head_sha(repo: Path) -> str | None:
    r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=False)
    return r.stdout.strip() if r.returncode == 0 else None


def runtime_built(runtime: Path, repo: Path) -> bool:
    try:
        built = json.loads((runtime / "current" / "RELEASE.json").read_text()).get("commit")
    except (OSError, ValueError):
        return False
    return bool(built) and built == head_sha(repo) and (runtime / "venv" / "bin" / "python").exists()


def plan(*, label: str | None, config_dir: Path, collector_state: Path, publisher_state: Path, runtime: Path,
         repo: Path, python: str | None) -> list[Step]:
    try:
        ident = mi.load_identity(config_dir)
        ident_note = f"{ident.id} role={ident.role}" if ident else ""
    except mi.IdentityError:
        ident, ident_note = None, "machine.json is corrupt (install will refuse to touch it)"
    return [
        Step("python", python is not None, "none (install needs Python >= 3.12: brew install python@3.12 or set AGENT_MINDMAP_PYTHON)",
             python or "no Python >= 3.12 found"),
        Step("config_dir", config_dir.is_dir(), f"create {config_dir} (0700)"),
        Step("identity", ident is not None, f"create a random machine id with label {label!r} and role reader", ident_note),
        Step("state_dirs", collector_state.is_dir() and publisher_state.is_dir(),
             f"create {collector_state} and {publisher_state} (0700)"),
        Step("runtime", runtime_built(runtime, repo), f"build venv + release of the committed code in {runtime}"),
    ]


def render(steps: list[Step], mode: str) -> str:
    lines = [f"bootstrap_mac ({mode}) — nothing is started, no LaunchAgent is loaded"]
    for s in steps:
        lines.append(f"  [{'ok' if s.done else 'todo'}] {s.id}: " + (s.detail or "in place") if s.done
                     else f"  [todo] {s.id}: {s.action}")
    return "\n".join(lines)


NEXT_STEPS = """\
Next steps (manual, in this order):
  1. Log in to T3 once: copy the MCP URL from T3 Settings > Connections, then
       python -m ingest.t3_mcp login --url <copied MCP URL>        (approve READ-ONLY in the browser)
  2. python -m tools.machine_doctor                                  (read-only health report)
  3. This Mac is a READER. To make it the one publisher later, ONLY after the other Mac released or you decided:
       python -m tools.publisher_ownership handover                  (prints the operator steps)
       python -m tools.publisher_ownership claim
  Credentials of other Macs are never copied: log in to claude/codex/cursor/gh here yourself."""


def install(*, label: str, config_dir: Path, collector_state: Path, publisher_state: Path, runtime: Path, repo: Path,
            python: str | None, build_fn: Callable[..., str] | None = None) -> list[str]:
    if python is None:
        raise ri.InstallError("No Python >= 3.12 found (brew install python@3.12, or set AGENT_MINDMAP_PYTHON)")
    done = []
    ident = mi.init_identity(label, "reader", config_dir)      # also creates the 0700 config dir; keeps an existing id
    done.append(f"identity {ident.id} (role {ident.role})")
    for d in (collector_state, publisher_state):
        d.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(d, 0o700)
    done.append("state directories")
    if runtime_built(runtime, repo):
        done.append("runtime already built for this commit; left alone")
    else:
        sha = (build_fn or ri.build)(repo, runtime, python)
        done.append(f"runtime release {sha[:12]} built; plists staged in {ri.staged_dir(runtime)}")
    return done


def main(argv: list[str] | None = None, *, python: str | None = ..., build_fn: Callable[..., str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", nargs="?", choices=["install"])
    parser.add_argument("--check", action="store_true", help="read-only report (default)")
    parser.add_argument("--dry-run", action="store_true", help="show what install would do; write nothing")
    parser.add_argument("--label", help="owner-chosen non-identifying name, e.g. 'Mac B'")
    parser.add_argument("--config-dir", type=Path, default=None)
    parser.add_argument("--runtime", type=Path, default=ri.RUNTIME)
    parser.add_argument("--repo", type=Path, default=ri.REPO)
    parser.add_argument("--collector-state", type=Path, default=ri.COLLECTOR_STATE)
    parser.add_argument("--publisher-state", type=Path, default=ri.PUBLISHER_STATE)
    args = parser.parse_args(argv)
    py = ld.discover_python() if python is ... else python
    config = mi.config_dir(args.config_dir)
    steps = plan(label=args.label, config_dir=config, collector_state=args.collector_state,
                 publisher_state=args.publisher_state, runtime=args.runtime, repo=args.repo, python=py)
    if args.action != "install" or args.dry_run:
        print(render(steps, "dry-run" if args.dry_run else "check"))
        return 0 if all(s.done for s in steps) or args.dry_run else 1 if args.check else 0
    if not args.label and mi.load_identity(config) is None:
        parser.error("install needs --label (a short name you choose, e.g. 'Mac B')")
    try:
        for line in install(label=args.label or "Mac", config_dir=config, collector_state=args.collector_state,
                            publisher_state=args.publisher_state, runtime=args.runtime, repo=args.repo, python=py,
                            build_fn=build_fn):
            print(f"done: {line}")
    except (ri.InstallError, mi.IdentityError, OSError, subprocess.SubprocessError) as exc:
        print(f"bootstrap stopped: {str(exc)[:300]}")
        return 1
    print(NEXT_STEPS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
