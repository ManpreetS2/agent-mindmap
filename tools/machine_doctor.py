"""Read-only health report for THIS Mac: what works, what needs a human, what could make two Macs fight.

  python -m tools.machine_doctor [--json]

Statuses: PASS | WARN | FAIL | UNKNOWN. Exit code 1 only if something FAILs. It starts nothing, writes nothing, never
automates a login and never prints tokens, OAuth material, environment values, Keychain contents or e-mail addresses
(report only: logged in or not, plan name). All external commands go through an injectable runner.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from tools import machine_identity as mi
from tools import publisher_launchd as ld
from tools import publisher_ownership as own

PASS, WARN, FAIL, UNKNOWN = "PASS", "WARN", "FAIL", "UNKNOWN"
T3_MCP = "http://127.0.0.1:3773/mcp"
COLLECTOR_PORT, T3_PORT, LEGACY_PORT = 8799, 3773, 8787
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
TOKEN = re.compile(r"(?i)(gh[pousr]_[A-Za-z0-9]{10,}|github_pat_[A-Za-z0-9_]{10,}|sk-[A-Za-z0-9_-]{12,}|bearer\s+\S+)")


# More credential forms that can ride inside remote free text (owner labels, error output).
AUTH_HEADER = re.compile(r"(?i)authorization\s*[:=]\s*(?:basic|bearer|token)?\s*[^\s,;]+")
SECRET_KV = re.compile(r"(?i)\b(?:pass(?:word|wd)?|pwd|secret|token|api[_-]?key|access[_-]?key|credential|cookie)\w*\s*[:=]\s*[^\s,;]+")
SLACK = re.compile(r"(?i)xox[abprs]-[A-Za-z0-9-]{8,}")
LONG_B64 = re.compile(r"[A-Za-z0-9+/]{20,}={0,2}")


def redact(text: str) -> str:
    text = EMAIL.sub("<email>", text)
    text = AUTH_HEADER.sub("<redacted>", text)
    text = SECRET_KV.sub("<redacted>", text)
    text = SLACK.sub("<redacted>", text)
    text = TOKEN.sub("<redacted>", text)
    text = LONG_B64.sub(lambda m: "<redacted>" if any(c.isdigit() for c in m.group(0)) and any(c.isalpha() for c in m.group(0)) else m.group(0), text)
    home = str(Path.home())
    return text.replace(home, "~") if len(home) > 1 else text


@dataclass
class Check:
    id: str
    status: str
    summary: str
    hint: str | None = None

    def as_dict(self) -> dict:
        return {"id": self.id, "status": self.status, "summary": redact(self.summary),
                "hint": redact(self.hint) if self.hint else None}


Runner = Callable[[list[str], dict | None], tuple[int, str, str]]


def real_runner(args: list[str], env: dict | None = None) -> tuple[int, str, str]:
    try:
        r = subprocess.run(args, env=env, capture_output=True, text=True, check=False, timeout=30)
    except FileNotFoundError:
        return 127, "", "not installed"
    except (OSError, subprocess.TimeoutExpired):
        return 124, "", "did not answer"
    return r.returncode, r.stdout, r.stderr


def real_http(url: str) -> int | None:
    """HTTP status of an unauthenticated GET on a loopback URL, or None if nothing answers."""
    import urllib.error
    import urllib.request

    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(urllib.request.Request(url, headers={"Accept": "application/json"}), timeout=3) as r:
            return r.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except OSError:
        return None


def real_json(url: str) -> dict | None:
    import urllib.request

    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url, timeout=3) as r:
            data = json.loads(r.read(65536).decode())
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


@dataclass
class Context:
    runner: Runner = real_runner
    http_status: Callable[[str], int | None] = real_http
    http_json: Callable[[str], dict | None] = real_json
    home: Path = field(default_factory=Path.home)
    repo: Path = field(default_factory=lambda: Path(__file__).resolve().parents[1])
    config_dir: Path | None = None
    state_dir: Path | None = None
    runtime: Path | None = None
    now: datetime = field(default_factory=lambda: datetime.now(UTC))
    env: dict = field(default_factory=lambda: dict(os.environ))
    system: str = field(default_factory=platform.system)
    machine: str = field(default_factory=platform.machine)
    applications: tuple[Path, ...] = (Path("/Applications"),)
    offline: bool = False
    which_fn: Callable[[str], str | None] | None = None

    def which(self, name: str) -> str | None:
        return self.which_fn(name) if self.which_fn else ld.find_tool(name, self.env)


def _clean_env(ctx: Context, **extra: str) -> dict:
    env = {k: v for k, v in ctx.env.items() if k not in ("CLAUDE_CONFIG_DIR", "GH_TOKEN", "GITHUB_TOKEN")}
    env.update(extra)
    return env


# ------------------------------------------------------------------ checks

def check_platform(ctx: Context) -> Check:
    desc = f"{ctx.system} {ctx.machine}, Python {sys.version_info[0]}.{sys.version_info[1]}"
    if ctx.system != "Darwin":
        return Check("platform", WARN, f"{desc}: only macOS is supported by the LaunchAgent tooling")
    py = ld.discover_python(ctx.env, which=lambda n, path=None: ctx.which(n)) if not ctx.which_fn else sys.executable
    if not py:
        return Check("platform", FAIL, f"{desc}; no Python >= 3.12 found",
                     "Install one (brew install python@3.12) or set AGENT_MINDMAP_PYTHON")
    return Check("platform", PASS, f"{desc}; Python >= 3.12 available")


def check_t3_app(ctx: Context) -> Check:
    dirs = (*ctx.applications, ctx.home / "Applications")
    for d in dirs:
        try:
            if any(p.name.startswith("T3") and p.suffix == ".app" for p in d.iterdir()):
                return Check("t3_app", PASS, "T3 Code app is installed")
        except OSError:
            continue
    return Check("t3_app", WARN, "T3 Code app not found in /Applications or ~/Applications",
                 "Install T3 Code; the collector needs its MCP server")


def check_t3_mcp(ctx: Context) -> Check:
    code = ctx.http_status(T3_MCP)
    if code is None:
        return Check("t3_mcp", FAIL, f"Nothing answers on {T3_PORT}: T3 is not running", "Open T3 Code")
    if code == 401:
        return Check("t3_mcp", WARN, "T3 MCP is reachable but needs a one-time OAuth login",
                     "Copy the MCP URL from T3 Settings > Connections, then run: "
                     "python -m ingest.t3_mcp login --url <copied MCP URL> (approve READ-ONLY in the browser; never automated)")
    if code < 500:
        return Check("t3_mcp", PASS, f"T3 MCP is reachable (HTTP {code})")
    return Check("t3_mcp", WARN, f"T3 MCP answered HTTP {code}")


def _auth_json(out: str) -> dict | None:
    try:
        data = json.loads(out)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def check_claude(ctx: Context, key: str, label: str, config_dir: Path, default_dir: bool) -> Check:
    if not ctx.which("claude"):
        return Check(key, UNKNOWN, f"{label}: claude CLI not installed")
    if not config_dir.is_dir():
        return Check(key, WARN, f"{label}: config directory {redact(str(config_dir))} does not exist",
                     "Run `claude` with this config directory and log in")
    # The default directory is queried with the variable unset: setting it to the default path makes the CLI look in
    # a different file on some versions.
    env = _clean_env(ctx) if default_dir else _clean_env(ctx, CLAUDE_CONFIG_DIR=str(config_dir))
    rc, out, _ = ctx.runner(["claude", "auth", "status"], env)
    data = _auth_json(out)
    if data is None or "loggedIn" not in data:
        return Check(key, UNKNOWN, f"{label}: could not read auth status")
    if data["loggedIn"] is not True:
        return Check(key, WARN, f"{label}: not logged in", f"CLAUDE_CONFIG_DIR={config_dir} claude auth login")
    plan = data.get("subscriptionType")
    return Check(key, PASS, f"{label}: logged in" + (f" ({plan})" if isinstance(plan, str) and len(plan) < 24 else ""))


def check_claude_dirs(ctx: Context) -> Check:
    a, b = (ctx.home / ".claude").resolve(), (ctx.home / ".claude_second").resolve()
    if a == b:
        return Check("claude_dirs", FAIL, "Claude 1 and Claude 2 resolve to the same config directory")
    if not (a.is_dir() and b.is_dir()):
        return Check("claude_dirs", WARN, "Only one of the two Claude config directories exists (~/.claude, ~/.claude_second)")
    return Check("claude_dirs", PASS, "Claude 1 and Claude 2 use two distinct config directories")


def _logged_in(key: str, label: str, binary: str, args: list[str], ctx: Context, hint: str) -> Check:
    if not ctx.which(binary):
        return Check(key, UNKNOWN, f"{label}: {binary} not installed")
    rc, out, err = ctx.runner([binary, *args], _clean_env(ctx))
    text = (out + err).lower()
    if rc == 0 and "not logged in" not in text and "logged in" in text:
        return Check(key, PASS, f"{label}: logged in")
    if "not logged in" in text or "not authenticated" in text or "login" in text:
        return Check(key, WARN, f"{label}: not logged in", hint)
    return Check(key, UNKNOWN if rc == 0 else WARN, f"{label}: status could not be determined (exit {rc})", hint)


def check_gh(ctx: Context) -> Check:
    if not ctx.which("gh"):
        return Check("gh", FAIL, "gh (GitHub CLI) not installed", "brew install gh && gh auth login")
    rc, out, err = ctx.runner(["gh", "auth", "status"], _clean_env(ctx))
    if rc == 0:
        return Check("gh", PASS, "gh is logged in")
    return Check("gh", FAIL, "gh is not logged in", "gh auth login")


def _ps(ctx: Context) -> list[tuple[int, str]]:
    rc, out, _ = ctx.runner(["ps", "-axo", "pid=,args="], None)
    rows = []
    for line in out.splitlines():
        m = re.match(r"\s*(\d+)\s+(.*)", line)
        if m and int(m.group(1)) != os.getpid():
            rows.append((int(m.group(1)), m.group(2)))
    return rows


def check_processes(ctx: Context) -> Check:
    rows = _ps(ctx)
    collectors = [p for p, a in rows if re.search(r"-m tools\.run_collector|ingest\.live", a) and "doctor" not in a]
    publishers = [p for p, a in rows if "tools.publish_observability" in a and "--for-real" in a]
    desc = f"{len(collectors)} collector process(es), {len(publishers)} publisher process(es)"
    if len(collectors) > 1 or len(publishers) > 1:
        return Check("processes", FAIL, f"{desc}: duplicates", "Stop the extras; only one of each should run")
    return Check("processes", PASS, desc)


def _listeners(ctx: Context, port: int) -> int | None:
    rc, out, _ = ctx.runner(["lsof", "-nP", f"-tiTCP:{port}", "-sTCP:LISTEN"], None)
    if rc == 127:
        return None
    return len(out.split())


def check_ports(ctx: Context) -> list[Check]:
    checks = []
    n = _listeners(ctx, T3_PORT)
    checks.append(Check("port_3773", UNKNOWN if n is None else (PASS if n else WARN),
                        "T3 MCP port 3773: " + ("unknown" if n is None else ("listening" if n else "not listening"))))
    n = _listeners(ctx, COLLECTOR_PORT)
    health = ctx.http_json(f"http://127.0.0.1:{COLLECTOR_PORT}/healthz")
    if n is None:
        checks.append(Check("collector", UNKNOWN, "Collector port 8799: unknown"))
    elif not n:
        checks.append(Check("collector", WARN, "Collector is not running on 8799",
                            "Start it manually or via the runtime LaunchAgent (needs your approval)"))
    elif n > 1:
        checks.append(Check("collector", FAIL, "More than one listener on 8799"))
    elif health is None or "last_build" not in health:
        checks.append(Check("collector", FAIL, "Port 8799 is held by something that is not the collector"))
    else:
        polled = own.parse_time(health.get("last_t3_poll"))
        age = (ctx.now - polled).total_seconds() if polled else None
        if age is not None and age < 120:
            checks.append(Check("collector", PASS, f"Collector is polling T3 (last poll {int(age)}s ago)"))
        else:
            checks.append(Check("collector", WARN, "Collector is up but has no recent successful T3 poll",
                                "T3 closed, or OAuth login needed"))
    n = _listeners(ctx, LEGACY_PORT)
    checks.append(Check("port_8787", PASS, "Legacy port 8787 (report only, never touched): "
                        + ("unknown" if n is None else ("in use" if n else "free"))))
    return checks


def check_runtime(ctx: Context) -> Check:
    from tools import runtime_install as ri

    def loaded(label: str) -> bool:
        rc, _, _ = ctx.runner(["launchctl", "print", f"gui/{os.getuid()}/{label}"], None)
        return rc == 0

    try:
        data = ri.status_data(loaded_fn=loaded, pids_fn=lambda p: [], health_fn=lambda: ctx.http_json(
            f"http://127.0.0.1:{COLLECTOR_PORT}/healthz"), runtime=ctx.runtime, publisher_state=ctx.state_dir)
    except (OSError, ValueError):
        return Check("runtime", UNKNOWN, "Runtime status could not be read")
    if not data["release"] or not data["venv_ok"]:
        return Check("runtime", WARN, "Stable runtime is not built on this Mac",
                     "python -m tools.bootstrap_mac install --label <name>")
    sha = str(data["release"].get("commit", ""))[:12]
    loaded_desc = f"collector job {'loaded' if data['collector_loaded'] else 'not loaded'}, " \
                  f"publisher job {'loaded' if data['publisher_loaded'] else 'not loaded'}"
    return Check("runtime", PASS, f"Runtime release {sha} built; {loaded_desc}")


def _strip_credentials(url: str) -> str:
    parts = urlsplit(url)
    host = parts.hostname or ""
    return urlunsplit((parts.scheme, host + (f":{parts.port}" if parts.port else ""), parts.path, "", ""))


def check_git(ctx: Context) -> Check:
    def git(*a: str) -> str | None:
        rc, out, _ = ctx.runner(["git", "-C", str(ctx.repo), *a], _clean_env(ctx))
        return out.strip() if rc == 0 else None

    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    if branch is None:
        return Check("git", UNKNOWN, "Not a git checkout (or git missing)")
    dirty = git("status", "--porcelain", "--untracked-files=no")
    remote = git("remote", "get-url", "origin")
    where = _strip_credentials(remote).rsplit("github.com/", 1)[-1] if remote else "no origin"
    sha = git("rev-parse", "--short", "HEAD") or "?"
    desc = f"branch {branch} @ {sha}, origin {where}, " + ("uncommitted changes" if dirty else "clean")
    return Check("git", WARN if dirty else PASS, desc,
                 "Commit before building a release (runtime build requires a clean tree)" if dirty else None)


def check_identity(ctx: Context) -> tuple[Check, mi.MachineIdentity | None]:
    try:
        ident = mi.load_identity(ctx.config_dir)
    except mi.IdentityError:
        return Check("identity", FAIL, "machine.json is corrupt", "Fix or remove it deliberately; the id is not regenerated"), None
    if ident is None:
        return Check("identity", WARN, "This Mac has no machine identity yet",
                     "python -m tools.machine_identity init --label <name>   (starts as reader)"), None
    return Check("identity", PASS, f"{ident.id} \"{ident.label}\" role={ident.role}"), ident


def check_feed(ctx: Context, ident: mi.MachineIdentity | None) -> list[Check]:
    from tools import publish_observability as pub

    if ctx.offline:
        return [Check("feed", UNKNOWN, "Private feed not checked (offline)")]
    if not ctx.which("gh"):
        return [Check("feed", UNKNOWN, "Private feed not checked (gh missing)")]
    kind, feed = own.fetch_remote_feed(pub.DESTINATION, lambda a, e: ctx.runner(a, _clean_env(ctx)))
    if kind == "error":
        return [Check("feed", FAIL, "Private feed unreachable (GitHub outage, auth or permissions)", "gh auth status")]
    if kind == "missing":
        return [Check("feed", WARN, "Private feed has no latest.json yet")]
    if kind == "malformed" or feed is None:
        return [Check("feed", FAIL, "Private feed is malformed", "Investigate before anyone publishes")]
    trusted = own.parse_time(feed.get("trusted_until"))
    exported = own.parse_time(feed.get("exported_at"))
    age = f"{int((ctx.now - exported).total_seconds() // 60)} min ago" if exported else "unknown time"
    fresh = trusted is not None and ctx.now < trusted
    out = [Check("feed", PASS if fresh else WARN,
                 f"Private feed reachable; last write {age}; " + ("within its trust window" if fresh else "past its trust window (stale)"))]
    pubobj = own.validate_publisher(feed.get("publisher"), ctx.now) if "publisher" in feed else None
    if "publisher" not in feed:
        out.append(Check("ownership", WARN, "Feed has no owner record (written by an older publisher)",
                         "Run `python -m tools.publisher_ownership claim` on the Mac that should publish"))
    elif pubobj is None:
        out.append(Check("ownership", FAIL, "Feed owner record is malformed", "claim --force-takeover --confirm-takeover-of corrupt"))
    else:
        mine = ident is not None and pubobj["machine_id"] == ident.id
        lease_ok = own.parse_time(pubobj["lease_expires_at"]) > ctx.now  # type: ignore[operator]
        who = f"owner {pubobj['label']} epoch {pubobj['epoch']} ({pubobj['state']}, lease {'valid' if lease_ok else 'expired'})"
        if ident and ident.role == "publisher" and not mine and pubobj["state"] == "active":
            out.append(Check("ownership", FAIL, f"This Mac thinks it is the publisher but the feed says {who}",
                             "Two Macs may both believe they own it: run `python -m tools.publisher_ownership status`; "
                             "the loser must `release` (demotes locally) and stay a reader"))
        elif mine and ident and ident.role == "reader":
            out.append(Check("ownership", WARN, f"Feed records this Mac as {who} but its local role is reader",
                             "Run `claim` again to resume, or `release`"))
        else:
            out.append(Check("ownership", PASS, ("This Mac is the " if mine else "Another Mac is the ") + who))
    return out


def check_role_jobs(ctx: Context, ident: mi.MachineIdentity | None) -> Check:
    from tools import runtime_install as ri

    rc, _, _ = ctx.runner(["launchctl", "print", f"gui/{os.getuid()}/{ri.PUBLISHER_LABEL}"], None)
    loaded = rc == 0
    if ident is None:
        return Check("role_jobs", UNKNOWN, "Publisher job state not judged (no identity)")
    if loaded and ident.role != "publisher":
        return Check("role_jobs", WARN, "Publisher LaunchAgent is loaded but this Mac is a reader (it will skip every run)",
                     "python -m tools.publisher_launchd disable")
    if ident.role == "publisher" and not loaded:
        return Check("role_jobs", WARN, "This Mac is the publisher but the timed publisher job is not loaded",
                     "Only after approval: python -m tools.publisher_launchd enable --yes-i-approved-live-publishing")
    return Check("role_jobs", PASS, f"Publisher job {'loaded' if loaded else 'not loaded'} (role {ident.role})")


def run_checks(ctx: Context) -> list[Check]:
    checks: list[Check] = [check_platform(ctx), check_t3_app(ctx), check_t3_mcp(ctx)]
    checks.append(check_claude(ctx, "claude_1", "Claude 1", ctx.home / ".claude", True))
    checks.append(check_claude(ctx, "claude_2", "Claude 2", ctx.home / ".claude_second", False))
    checks.append(check_claude_dirs(ctx))
    checks.append(_logged_in("codex", "Codex", "codex", ["login", "status"], ctx, "codex login"))
    checks.append(_logged_in("cursor_agent", "Cursor Agent", "cursor-agent", ["status"], ctx, "cursor-agent login"))
    checks.append(check_gh(ctx))
    checks.append(check_processes(ctx))
    checks.extend(check_ports(ctx))
    checks.append(check_runtime(ctx))
    checks.append(check_git(ctx))
    ident_check, ident = check_identity(ctx)
    checks.append(ident_check)
    checks.extend(check_feed(ctx, ident))
    checks.append(check_role_jobs(ctx, ident))
    return checks


def render(checks: list[Check]) -> str:
    width = max(len(c.id) for c in checks)
    lines = ["Agent Mindmap machine doctor (read-only)"]
    for c in checks:
        d = c.as_dict()
        lines.append(f"[{c.status:7}] {c.id:<{width}}  {d['summary']}")
        if d["hint"]:
            lines.append(f"{'':11}{'':<{width}}  -> {d['hint']}")
    counts = {s: sum(1 for c in checks if c.status == s) for s in (PASS, WARN, FAIL, UNKNOWN)}
    lines.append("Summary: " + ", ".join(f"{n} {s}" for s, n in counts.items()))
    return "\n".join(lines)


def main(argv: list[str] | None = None, ctx: Context | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--offline", action="store_true", help="skip the private-feed lookup")
    args = parser.parse_args(argv)
    ctx = ctx or Context(offline=args.offline)
    checks = run_checks(ctx)
    if args.json:
        print(json.dumps({"checks": [c.as_dict() for c in checks]}, indent=2))
    else:
        print(render(checks))
    return 1 if any(c.status == FAIL for c in checks) else 0


if __name__ == "__main__":
    raise SystemExit(main())
