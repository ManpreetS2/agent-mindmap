"""Publish a T3 read-only snapshot to a dedicated *private* GitHub repository.

Ordinary code only: no model calls. Uses the user's own `gh` login (never Agent Control tokens), never writes
into the public dashboard repo, and publishes exactly two files: latest.json and summary.md.

  python -m tools.publish_observability --collector-url http://127.0.0.1:8799/activity.json   # local review only
  python -m tools.publish_observability --collector-url ... --for-real                       # upload
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import subprocess
import tempfile
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from tools import machine_identity as mi
from tools import publisher_ownership as own
from tools.export_observability import ROOT, make_feed, write_private

DESTINATION = "ManpreetS2/agent-observability-private"
ALLOWED_FILES = ("latest.json", "summary.md")
HEARTBEAT_SEC = 9 * 60        # an unchanged feed is re-stamped this often (must stay well under the 15 min trust window)
MIN_INTERVAL_SEC = 3 * 60     # never publish more often than this, whatever changed
BACKOFF_SEC = (60, 180, 600, 1800)
STATE_DIR = Path.home() / ".local" / "state" / "agent-mindmap-publisher"
MAX_SOURCE_BYTES = 2_000_000

# Anything that looks like a credential, key, or local path must never leave the machine.
SENSITIVE = re.compile(
    r"(?i)((?<![A-Za-z0-9])gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{16,}|(?<![A-Za-z0-9])AKIA[0-9A-Z]{16}"
    r"|xox[abprs]-[A-Za-z0-9-]{10,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|bearer\s+[A-Za-z0-9._~+/=-]{8,}"
    r"|authorization\s*[:=]|(?:api[_-]?key|secret|password|passwd|token)\s*[:=]\s*[A-Za-z0-9._~+/=-]{16,}"
    r"|/Users/[^/\s]+|/home/[^/\s]+|[A-Za-z]:\\Users\\|\.t3[\\/]|\.config[\\/]|\.ssh[\\/])"
)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


NO_REDIRECT = urllib.request.build_opener(_NoRedirect, urllib.request.ProxyHandler({}))


class PublishError(RuntimeError):
    """A condition we expected and can describe without leaking anything."""


class OwnershipRefusal(PublishError):
    """This Mac must not write the feed (reader role, someone else owns it, malformed owner record...)."""

    def __init__(self, decision: own.Decision):
        super().__init__(decision.reason)
        self.decision = decision


class CollectorUnavailable(PublishError):
    """The local T3 collector could not be read: the honest state to publish is 'unavailable'."""


def secure_env() -> dict[str, str]:
    """Use the owner's normal gh login, never a worker's overriding token/config."""
    env = dict(os.environ)
    for key in ("GH_TOKEN", "GITHUB_TOKEN", "GH_CONFIG_DIR", "GH_ENTERPRISE_TOKEN", "GIT_DIR", "GIT_WORK_TREE",
                "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_CONFIG_PARAMETERS", "GIT_SSH_COMMAND", "GIT_SSH",
                "GIT_ASKPASS", "SSH_ASKPASS", "GH_HOST", "GH_REPO"):
        env.pop(key, None)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    return env


def cmd(args: list[str], *, env: dict[str, str], cwd: Path | None = None, what: str = "GitHub operation") -> str:
    try:
        result = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, check=False, timeout=90)
    except subprocess.TimeoutExpired:
        raise PublishError(f"{what} timed out") from None
    except OSError:
        raise PublishError(f"{what} could not run ({args[0]} missing or not executable)") from None
    if result.returncode != 0:
        # Output can contain remote metadata; never echo it.
        raise PublishError(f"{what} failed (exit {result.returncode})")
    return result.stdout.strip()


GIT_SAFE = ["-c", "core.hooksPath=/dev/null", "-c", "credential.helper=",
            "-c", "credential.helper=!gh auth git-credential", "-c", "protocol.ext.allow=never",
            "-c", "core.fsmonitor=false", "-c", "commit.gpgsign=false"]


def verified_destination(repo: str, info: dict) -> bool:
    """Dedicated private feed only; the public mind-map and every other repository always fail."""
    return (
        repo == DESTINATION
        and info.get("nameWithOwner") == DESTINATION
        and info.get("visibility") == "PRIVATE"
        and info.get("isFork") is not True
    )


def comparable(feed: dict) -> dict:
    """What matters for 'did anything change': drop clocks, and the freshness derived from them."""
    c = json.loads(json.dumps(feed))
    for key in ("exported_at", "observed_at", "trusted_until", "freshness", "publisher"):  # lease churn is not a change
        c.pop(key, None)
    return c


def unchanged_except_export_time(previous: dict, current: dict) -> bool:
    return comparable(previous) == comparable(current)


def should_publish(previous: dict | None, current: dict, *, now: datetime) -> bool:
    if previous is None or not unchanged_except_export_time(previous, current):
        return True
    old = previous.get("exported_at")
    if not isinstance(old, str):
        return True
    try:
        prev = datetime.fromisoformat(old)
        if prev.utcoffset() is None:
            return True
        age = (now - prev).total_seconds()
        if age < -60:  # a stamp from the future (clock skew or a crafted feed) must never suppress the heartbeat
            return True
        return age >= HEARTBEAT_SEC
    except (ValueError, OverflowError):
        return True


def scan_for_sensitive(*texts: str) -> list[str]:
    """Names of categories found (never the matched text)."""
    found = []
    for text in texts:
        for m in SENSITIVE.finditer(text):
            found.append(m.group(0)[:3] + "…")
    return sorted(set(found))


def read_source(input_path: Path | None, collector_url: str | None) -> dict:
    """A regular local file, or the loopback collector's /activity.json. Nothing else."""
    if (input_path is None) == (collector_url is None):
        raise PublishError("Give exactly one of --input or --collector-url")
    if collector_url:
        u = urlparse(collector_url)
        if u.scheme != "http" or u.hostname not in {"127.0.0.1", "localhost", "::1"} or u.username or u.password:
            raise PublishError("The collector must be a loopback http URL")
        try:
            req = urllib.request.Request(collector_url, headers={"Accept": "application/json"})
            with NO_REDIRECT.open(req, timeout=10) as response:  # loopback only, checked above, never redirected
                raw = response.read(MAX_SOURCE_BYTES + 1)
        except OSError:
            raise CollectorUnavailable("Local collector is not reachable") from None
    else:
        if input_path.is_symlink() or not input_path.is_file():
            raise PublishError("Expected a regular local T3 activity snapshot file")
        raw = input_path.read_bytes()[: MAX_SOURCE_BYTES + 1]
    if len(raw) > MAX_SOURCE_BYTES:
        raise PublishError("Source snapshot is unexpectedly large")
    try:
        source = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError):
        raise PublishError("Source snapshot is not valid JSON") from None
    if collector_url and isinstance(source, dict):
        apply_last_poll(source, collector_url)
    return source


def apply_last_poll(source: dict, collector_url: str) -> None:
    """The collector rewrites activity.json only when content changes, so generated_at is the last CHANGE. Its
    /healthz reports the last poll in which T3 actually answered; that is the real observation time. Only ever
    moves the time forward, never into the future, and only while the snapshot says connected. Any problem
    leaves generated_at alone (which errs towards 'stale')."""
    try:
        u = urlparse(collector_url)
        with NO_REDIRECT.open(urllib.request.Request(f"{u.scheme}://{u.netloc}/healthz"), timeout=5) as r:
            polled = json.loads(r.read(65536).decode("utf-8")).get("last_t3_poll")
        t3 = (source.get("meta") or {}).get("t3") or {}
        if t3.get("connection") != "connected" or not isinstance(polled, str):
            return
        poll_dt = datetime.fromisoformat(polled)
        gen_dt = datetime.fromisoformat(source["generated_at"])
        if poll_dt.utcoffset() is None or gen_dt.utcoffset() is None:
            return
        if gen_dt < poll_dt <= datetime.now(UTC) + timedelta(seconds=60):
            source["generated_at"] = poll_dt.astimezone(UTC).isoformat()
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return


def unavailable_feed(now: datetime) -> tuple[dict, str, str]:
    """No sessions and no claims: readers must not infer that anything is idle or running."""
    feed = {
        "format": "agent-mindmap-private-feed/v1",
        "source": "T3 read-only metadata",
        "observed_at": None,
        "exported_at": now.isoformat(),
        "freshness": "stale",
        "connection": "unavailable",
        "trusted_until": now.isoformat(),
        "reader_guidance": "The Mac's T3 collector was unreachable (asleep, T3 closed, or collector stopped). "
                           "Agent status is UNKNOWN, not idle.",
        "quota": {"status": "unsupported", "pools": {}},
        "limitations": ["No session data is available in this snapshot"],
        "status_counts": {},
        "sessions": [],
        "delegations": [],
    }
    summary = ("# Agent Mindmap — PRIVATE read-only snapshot\n\n"
               f"Exported: {now.isoformat()}\n\n**Collector UNAVAILABLE.** Agent status is UNKNOWN, not idle. "
               "Do not rely on any earlier snapshot.\n")
    return feed, json.dumps(feed, indent=2) + "\n", summary


def build(source: dict, now: datetime) -> tuple[dict, str, str]:
    """Validate, allowlist, and secret-scan. Raises before anything could be written or sent."""
    try:
        feed, summary = make_feed(source, now=now)
    except ValueError as exc:
        raise PublishError(str(exc)[:160]) from None
    except Exception:  # noqa: BLE001 - jsonschema.ValidationError etc.: never echo the instance
        raise PublishError("Source snapshot failed schema validation") from None
    if feed["source"] != "T3 read-only metadata" or not feed["sessions"]:
        raise PublishError("No real T3 session metadata available; refusing to publish an empty feed")
    body = json.dumps(feed, indent=2, ensure_ascii=False) + "\n"
    hits = scan_for_sensitive(body, summary)
    if hits:
        raise PublishError(f"Sensitive-looking content in the export ({len(hits)} pattern(s)); nothing published")
    return feed, body, summary


class Lock:
    """One publisher at a time, across processes (launchd run + manual run)."""

    def __init__(self, state_dir: Path):
        state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(state_dir, 0o700)
        self.fd = os.open(state_dir / "publisher.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)

    def __enter__(self):
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(self.fd)
            raise PublishError("Another publisher is running; skipping this run") from None
        return self

    def __exit__(self, *exc):
        os.close(self.fd)


def load_state(state_dir: Path) -> dict:
    try:
        data = json.loads((state_dir / "state.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(state_dir: Path, state: dict) -> None:
    fd, temp = tempfile.mkstemp(prefix=".state-", dir=state_dir)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        os.replace(temp, state_dir / "state.json")
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def failure_count(state: dict) -> int:
    """A corrupt counter counts as zero, so one good run repairs it."""
    value = state.get("consecutive_failures")
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 1000 else 0


def due(state: dict, now: datetime) -> str | None:
    """Why a run must wait (rate limit, failure backoff), or None."""
    def age(key: str) -> float | None:
        try:
            return (now - datetime.fromisoformat(state[key])).total_seconds()
        except (KeyError, ValueError, TypeError, OverflowError):
            return None
    since_success = age("last_success_at")
    if since_success is not None and 0 <= since_success < MIN_INTERVAL_SEC:  # a future stamp is ignored, not obeyed
        return f"published {since_success:.0f}s ago; minimum interval is {MIN_INTERVAL_SEC}s"
    failures = failure_count(state)
    since_attempt = age("last_attempt_at")
    if failures and since_attempt is not None and since_attempt >= 0:
        wait = BACKOFF_SEC[min(failures - 1, len(BACKOFF_SEC) - 1)]
        if since_attempt < wait:
            return f"backing off after {failures} failure(s); next try in {wait - since_attempt:.0f}s"
    return None


def load_previous(checkout: Path) -> dict | None:
    existing = checkout / "latest.json"
    if existing.is_symlink():
        raise PublishError("Refusing a symlinked remote feed file")
    if not existing.exists():
        return None
    try:
        previous = json.loads(existing.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError, OSError):
        raise PublishError("Remote feed is malformed: investigate before writing") from None
    if not isinstance(previous, dict):
        raise PublishError("Remote feed is malformed: investigate before writing")
    return previous


def push_files(repo: str, env: dict, plan, *, attempts: int = 2,
               message: str = "chore: update private read-only T3 activity snapshot") -> str:
    """Fresh shallow clone each attempt. `plan(previous_feed_or_None)` runs on THAT clone and returns either the files to
    write ({name: text}, allowlisted) or a string meaning 'nothing to do'; it may raise to refuse. On a rejected push
    (someone else updated the feed) the next attempt re-clones and re-runs `plan`, so every decision is made against
    the newest remote state."""
    original_umask = os.umask(0o077)
    try:
        for attempt in range(1, attempts + 1):
            with tempfile.TemporaryDirectory(prefix="agent-observability-") as tmp:
                checkout = Path(tmp) / "feed"
                cmd(["git", *GIT_SAFE, "clone", "--quiet", "--depth", "1", "--template=",
                     f"https://github.com/{repo}.git", str(checkout)], env=env, what="clone")
                files = plan(load_previous(checkout))
                if isinstance(files, str):
                    return files
                if not files or not set(files) <= set(ALLOWED_FILES):
                    raise PublishError("Planned files are outside the two-file allowlist")
                for name, content in files.items():
                    target = checkout / name
                    if target.is_symlink():
                        raise PublishError("Refusing to overwrite a symlink")
                    target.write_text(content, encoding="utf-8")
                cmd(["git", *GIT_SAFE, "add", "--", *files], cwd=checkout, env=env, what="stage")
                staged = set(cmd(["git", *GIT_SAFE, "diff", "--cached", "--name-only"], cwd=checkout, env=env,
                                 what="inspect").splitlines())
                if not staged or not staged <= set(ALLOWED_FILES):
                    raise PublishError("Staged files are outside the two-file allowlist")
                cmd(["git", *GIT_SAFE, "-c", "user.name=Agent Mindmap",
                     "-c", "user.email=agent-mindmap@users.noreply.github.com", "commit", "--quiet", "--no-verify",
                     "-m", message], cwd=checkout, env=env, what="commit")
                try:
                    cmd(["git", *GIT_SAFE, "push", "--quiet", "origin", "HEAD:refs/heads/main"],
                        cwd=checkout, env=env, what="push")
                    return "PUBLISHED"
                except PublishError:
                    if attempt == attempts:
                        raise PublishError("push was rejected or failed after a retry (conflict or auth)") from None
        raise PublishError("push did not complete")
    finally:
        os.umask(original_umask)


def push_snapshot(repo: str, env: dict, feed: dict, body: str, summary: str, now: datetime, attempts: int = 2, *,
                  identity: mi.MachineIdentity | None = None, local_epoch: int | None = None,
                  outcome: dict | None = None) -> str:
    """Publish the snapshot only if, on the fresh clone, ownership says this Mac may (see tools.publisher_ownership)."""
    outcome = outcome if outcome is not None else {}

    def plan(previous: dict | None):
        decision = own.decide(previous, identity, now, local_epoch=local_epoch)
        outcome["decision"] = decision
        if decision.action != "publish":
            raise OwnershipRefusal(decision)
        outcome["epoch"] = decision.epoch
        if not should_publish(previous, feed, now=now):
            return "NO CHANGE: equivalent to the last upload and the heartbeat is not due; nothing pushed"
        signed = {**feed, "publisher": own.publisher_object(identity, decision.epoch, now)}
        text = json.dumps(signed, indent=2, ensure_ascii=False) + "\n"
        if scan_for_sensitive(text):
            raise PublishError("Sensitive-looking content in the owner record; nothing published")
        return {"latest.json": text, "summary.md": summary}

    return push_files(repo, env, plan, attempts=attempts)


def publish(input_path: Path | None, repo: str, *, for_real: bool, collector_url: str | None = None,
            state_dir: Path = STATE_DIR, now: datetime | None = None, review_dir: Path | None = None,
            config_dir: Path | None = None) -> str:
    now = now or datetime.now(UTC)
    try:
        source = read_source(input_path, collector_url)
        feed, body, summary = build(source, now)
    except CollectorUnavailable:
        # Say so on GitHub, but only once there is an earlier success to correct; never on a first/local run.
        if not for_real or not load_state(state_dir).get("last_success_at"):
            raise
        feed, body, summary = unavailable_feed(now)
    review = (f"{len(feed['sessions'])} sessions, {len(feed['delegations'])} delegations, "
              f"freshness={feed['freshness']}, connection={feed['connection']}")
    if not for_real:
        if review_dir is not None:  # the exact bytes that would be uploaded, for the owner to read first
            write_private(review_dir, "latest.json", body)
            write_private(review_dir, "summary.md", summary)
        return f"LOCAL CHECK OK: {review}; sensitive scan clean; nothing uploaded"

    try:
        identity = mi.load_identity(config_dir)
    except mi.IdentityError as exc:
        raise PublishError(str(exc)) from None
    if identity is None or identity.role != "publisher":
        return ("SKIPPED: this Mac is not a publisher (role "
                f"{identity.role if identity else 'unset'}); it never writes the feed")
    env = secure_env()
    with Lock(state_dir):
        state = load_state(state_dir)
        wait = due(state, now)
        if wait:
            return f"SKIPPED: {wait}"
        state["last_attempt_at"] = now.isoformat()
        outcome: dict = {}
        try:
            info = json.loads(cmd(["gh", "repo", "view", repo, "--json", "nameWithOwner,visibility,isFork"],
                                  env=env, what="destination check"))
            if not verified_destination(repo, info):
                raise PublishError("Destination is not the approved PRIVATE repository")
            result = push_snapshot(repo, env, feed, body, summary, now, identity=identity,
                                   local_epoch=own.local_epoch(state), outcome=outcome)
        except (PublishError, ValueError, OverflowError) as exc:
            if isinstance(exc, OwnershipRefusal) and exc.decision.superseded_by:
                own.record_superseded(state, exc.decision.superseded_by, now)
            state["consecutive_failures"] = failure_count(state) + 1
            state["last_error"] = str(exc)[:160]
            save_state(state_dir, state)
            raise
        state["consecutive_failures"] = 0
        state["last_error"] = None
        if outcome.get("epoch"):
            own.record_owner(state, outcome["epoch"], now)
        if result == "PUBLISHED":
            state["last_success_at"] = now.isoformat()
            state["last_observed_at"] = feed["observed_at"]
            state["last_trusted_until"] = feed["trusted_until"]
        save_state(state_dir, state)
        return f"{result}: {review}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", type=Path, help="Absolute local activity.json from the read-only T3 collector")
    source.add_argument("--collector-url", help="Loopback http URL of the collector's /activity.json")
    parser.add_argument("--repo", default=DESTINATION, help="Dedicated private repo; any other is refused")
    parser.add_argument("--for-real", action="store_true", help="Explicitly allow GitHub writes (default: local check)")
    parser.add_argument("--state-dir", type=Path, default=STATE_DIR)
    parser.add_argument("--review-dir", type=Path, help="With a local check: write the exact upload files here (0700)")
    args = parser.parse_args()
    if args.repo != DESTINATION:
        parser.error(f"Only {DESTINATION} is allowed")
    if args.input is not None:
        resolved = args.input.resolve()
        if ROOT == resolved or ROOT in resolved.parents:
            parser.error("Refusing an input file under the PUBLIC dashboard repository")
    try:
        print(publish(args.input, args.repo, for_real=args.for_real, collector_url=args.collector_url,
                      state_dir=args.state_dir, review_dir=args.review_dir))
        return 0
    except (PublishError, ValueError, OverflowError, OSError) as exc:
        print(f"Private publisher stopped: {str(exc)[:180]}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
