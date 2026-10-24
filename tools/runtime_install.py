"""Install the collector and publisher into a stable runtime directory, outside disposable PR worktrees.

  build        Create ~/.local/share/agent-mindmap-runtime: a pinned venv, an immutable release built from the
               COMMITTED code of this checkout (git archive + web build), and a `current` symlink. Starts nothing.
  stage        Write both LaunchAgent plists under <runtime>/staged. They are NOT in ~/Library/LaunchAgents, so
               nothing starts at login until `activate`.
  status       What is built, what is loaded, health of the collector and publisher.
  activate     (needs --yes-i-approved-persistent-collector) Replace the manual collector on 8799 with the
               LaunchAgent and move the publisher job onto the runtime. Rolls back on failure.
  deactivate   Unload both jobs and remove their plists (the runtime and the private feed are left alone).

Runs no model. Never touches port 8882, Agent Control, T3's own services, or credentials.
"""
from __future__ import annotations

import argparse
import json
import os
import plistlib
import re
import shutil
import signal
import subprocess
import tarfile
import tempfile
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from tools.publisher_launchd import LABEL as PUBLISHER_LABEL
from tools.publisher_launchd import plist_data as publisher_plist

REPO = Path(__file__).resolve().parents[1]
RUNTIME = Path(os.environ.get("AGENT_MINDMAP_RUNTIME") or Path.home() / ".local" / "share" / "agent-mindmap-runtime")
LAUNCH_AGENTS = Path(os.environ.get("AGENT_MINDMAP_LAUNCH_AGENTS") or Path.home() / "Library" / "LaunchAgents")
COLLECTOR_LABEL = "com.manpreets2.agent-mindmap-collector"
COLLECTOR_STATE = Path.home() / ".local" / "state" / "agent-mindmap-collector"
PUBLISHER_STATE = Path.home() / ".local" / "state" / "agent-mindmap-publisher"
PORT = 8799
SHIPPED = ("ingest", "tools", "schema", "shared", "config", "fixtures", "pyproject.toml", "web")
PYTHON = os.environ.get("AGENT_MINDMAP_PYTHON") or str(Path.home() / ".local" / "bin" / "python3.12")
PATH_ENV = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"


class InstallError(RuntimeError):
    pass


def sh(args: list[str], *, cwd: Path | None = None, check: bool = True, timeout: int = 900) -> subprocess.CompletedProcess:
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=False, timeout=timeout)
    if check and r.returncode != 0:
        raise InstallError(f"{' '.join(args[:3])} failed ({r.returncode}): {(r.stderr or r.stdout)[-300:]}")
    return r


def current() -> Path:
    return RUNTIME / "current"


def runtime_python() -> Path:
    return RUNTIME / "venv" / "bin" / "python"


# ---------------------------------------------------------------- plists

def collector_plist(runtime: Path = RUNTIME, state: Path = COLLECTOR_STATE) -> dict:
    cur = runtime / "current"
    return {
        "Label": COLLECTOR_LABEL,
        "ProgramArguments": [str(runtime / "venv" / "bin" / "python"), "-m", "tools.run_collector"],
        "WorkingDirectory": str(cur),
        "RunAtLoad": True,
        # Restart after a crash or a retryable failure; a clean exit (SIGTERM, duplicate instance) stays down.
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": 30,
        "ProcessType": "Background",
        "Nice": 5,
        "EnvironmentVariables": {"PATH": PATH_ENV, "PYTHONPATH": str(cur), "PYTHONDONTWRITEBYTECODE": "1"},
        "StandardOutPath": str(state / "collector.log"),
        "StandardErrorPath": str(state / "collector.log"),
    }


def publisher_plist_runtime(runtime: Path = RUNTIME) -> dict:
    data = publisher_plist(python=str(runtime / "venv" / "bin" / "python"), repo=runtime / "current",
                           state_dir=PUBLISHER_STATE)
    return data


def staged_dir(runtime: Path = RUNTIME) -> Path:
    return runtime / "staged"


def stage(runtime: Path = RUNTIME) -> list[Path]:
    out = staged_dir(runtime)
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for label, data in ((COLLECTOR_LABEL, collector_plist(runtime)), (PUBLISHER_LABEL, publisher_plist_runtime(runtime))):
        p = out / f"{label}.plist"
        p.write_bytes(plistlib.dumps(data))
        paths.append(p)
    return paths


# ---------------------------------------------------------------- build

def build(repo: Path = REPO, runtime: Path = RUNTIME, python: str = PYTHON) -> str:
    dirty = sh(["git", "status", "--porcelain", "--untracked-files=no"], cwd=repo).stdout.strip()
    if dirty:
        raise InstallError("Tracked files have uncommitted changes; commit them first so the release is reproducible")
    sha = sh(["git", "rev-parse", "HEAD"], cwd=repo).stdout.strip()
    runtime.mkdir(parents=True, exist_ok=True)
    venv = runtime / "venv"
    if not (venv / "bin" / "python").exists():
        sh([python, "-m", "venv", str(venv)])
    sh([str(venv / "bin" / "python"), "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
        "-r", str(repo / "ops" / "runtime-requirements.txt")])
    release = runtime / "releases" / sha[:12]
    if not (release / "RELEASE.json").exists():
        tmp = Path(tempfile.mkdtemp(prefix="release-", dir=runtime))
        try:
            archive = subprocess.run(["git", "archive", "--format=tar", sha, *SHIPPED], cwd=repo, capture_output=True,
                                     check=False, timeout=120)
            if archive.returncode != 0:
                raise InstallError("git archive failed")
            tar = tmp / "src.tar"
            tar.write_bytes(archive.stdout)
            with tarfile.open(tar) as t:
                t.extractall(tmp / "src", filter="data")
            tar.unlink()
            src = tmp / "src"
            sh(["npm", "ci", "--no-audit", "--no-fund", "--ignore-scripts"], cwd=src / "web", timeout=900)
            sh(["npm", "run", "build"], cwd=src / "web", timeout=900)
            shutil.rmtree(src / "web" / "node_modules")
            if not (src / "web" / "dist" / "index.html").is_file():
                raise InstallError("web build produced no dist/index.html")
            (src / "RELEASE.json").write_text(json.dumps(
                {"commit": sha, "built_at": datetime.now(UTC).isoformat()}, indent=2) + "\n")
            release.parent.mkdir(parents=True, exist_ok=True)
            os.replace(src, release)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    selftest(runtime, release)
    link = runtime / ".current.tmp"
    link.unlink(missing_ok=True)
    link.symlink_to(release)
    os.replace(link, runtime / "current")      # atomic switch; the previous release stays for rollback
    stage(runtime)
    return sha


def selftest(runtime: Path, release: Path) -> None:
    code = ("import ingest.live, ingest.t3_mcp, tools.publish_observability, tools.run_collector, jsonschema, mcp;"
            "print('ok')")
    r = sh([str(runtime / "venv" / "bin" / "python"), "-c", code], cwd=release, check=False)
    if r.returncode != 0 or r.stdout.strip() != "ok":
        raise InstallError("runtime self-test failed: imports do not resolve inside the release")
    env = {**os.environ, "PYTHONPATH": str(release)}
    r = subprocess.run([str(runtime / "venv" / "bin" / "python"), "-c",
                        "import ingest.live as live, sys;"
                        + "sys.exit(0 if str(live.ROOT).startswith(sys.argv[1]) else 1)", str(release.resolve())],
                       cwd=release, env=env, capture_output=True, check=False)
    if r.returncode != 0:
        raise InstallError("runtime self-test failed: code is not served from the release directory")


# ---------------------------------------------------------------- launchctl / processes

def launchctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True, check=False)


def domain() -> str:
    return f"gui/{os.getuid()}"


def loaded(label: str) -> bool:
    return launchctl("print", f"{domain()}/{label}").returncode == 0


def port_owner_pids(port: int) -> list[int]:
    r = subprocess.run(["lsof", f"-tiTCP:{port}", "-sTCP:LISTEN"], capture_output=True, text=True, check=False)
    return [int(x) for x in r.stdout.split()]


def is_manual_collector(pid: int, port: int = PORT) -> bool:
    args = subprocess.run(["ps", "-o", "args=", "-p", str(pid)], capture_output=True, text=True, check=False).stdout
    return "ingest.live" in args and f"--port {port}" in args and re.search(r"--source t3(\s|$)", args) is not None


def healthz(port: int = PORT) -> dict | None:
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"http://127.0.0.1:{port}/healthz", timeout=3) as r:
            return json.loads(r.read(65536).decode())
    except (OSError, ValueError):
        return None


def wait_connected(timeout: int = 60, port: int = PORT) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        doc = healthz(port)
        polled = doc and doc.get("last_t3_poll")
        if polled:
            try:
                if (datetime.now(UTC) - datetime.fromisoformat(polled)).total_seconds() < 45:
                    return True
            except ValueError:
                pass
        time.sleep(2)
    return False


def status() -> str:
    doc = healthz()
    cur = current()
    release = json.loads((cur / "RELEASE.json").read_text()) if (cur / "RELEASE.json").exists() else None
    pub = {}
    try:
        pub = json.loads((PUBLISHER_STATE / "state.json").read_text())
    except (OSError, ValueError):
        pass
    return json.dumps({
        "runtime": str(RUNTIME), "release": release, "venv_ok": runtime_python().exists(),
        "collector_loaded": loaded(COLLECTOR_LABEL), "publisher_loaded": loaded(PUBLISHER_LABEL),
        "port_8799_pids": port_owner_pids(PORT),
        "collector_health": {k: (doc or {}).get(k) for k in ("last_t3_poll", "last_build", "errors")} if doc else "unreachable",
        "publisher": {k: pub.get(k) for k in ("last_success_at", "last_error", "consecutive_failures")},
    }, indent=2)


def activate(runtime: Path = RUNTIME) -> list[str]:
    log = []
    if not (runtime / "current" / "RELEASE.json").exists():
        raise InstallError("run `build` first")
    selftest(runtime, (runtime / "current").resolve())
    staged = {label: staged_dir(runtime) / f"{label}.plist" for label in (COLLECTOR_LABEL, PUBLISHER_LABEL)}
    stage(runtime)
    COLLECTOR_STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    PUBLISHER_STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    LAUNCH_AGENTS.mkdir(parents=True, exist_ok=True)

    # 1. free port 8799 only if the occupant is our own manual collector; anything else aborts.
    for pid in port_owner_pids(PORT):
        if loaded(COLLECTOR_LABEL):
            continue
        if not is_manual_collector(pid):
            raise InstallError(f"port {PORT} is held by pid {pid}, which is not the manual collector; not touching it")
        os.kill(pid, signal.SIGTERM)
        for _ in range(20):
            time.sleep(0.5)
            if pid not in port_owner_pids(PORT):
                break
        else:
            raise InstallError(f"manual collector pid {pid} did not exit")
        log.append(f"stopped manual collector pid {pid}")

    # 2. collector
    target = LAUNCH_AGENTS / f"{COLLECTOR_LABEL}.plist"
    shutil.copyfile(staged[COLLECTOR_LABEL], target)
    target.chmod(0o644)
    if loaded(COLLECTOR_LABEL):
        launchctl("bootout", f"{domain()}/{COLLECTOR_LABEL}")
    r = launchctl("bootstrap", domain(), str(target))
    if r.returncode != 0 or not wait_connected():
        launchctl("bootout", f"{domain()}/{COLLECTOR_LABEL}")
        target.unlink(missing_ok=True)
        raise InstallError("collector did not become healthy; unloaded it (see collector.log). "
                           "The previous manual collector was stopped: start it again if you need it")
    log.append("collector loaded and polling T3")

    # 3. publisher: same label, same schedule, now on the runtime
    ptarget = LAUNCH_AGENTS / f"{PUBLISHER_LABEL}.plist"
    backup = ptarget.read_bytes() if ptarget.exists() else None
    if loaded(PUBLISHER_LABEL):
        launchctl("bootout", f"{domain()}/{PUBLISHER_LABEL}")
    shutil.copyfile(staged[PUBLISHER_LABEL], ptarget)
    ptarget.chmod(0o644)
    r = launchctl("bootstrap", domain(), str(ptarget))
    if r.returncode != 0:
        if backup is not None:
            ptarget.write_bytes(backup)
            launchctl("bootstrap", domain(), str(ptarget))
        raise InstallError("publisher could not be reloaded; restored the previous plist")
    log.append("publisher reloaded from the runtime")
    return log


def deactivate() -> list[str]:
    log = []
    for label in (COLLECTOR_LABEL, PUBLISHER_LABEL):
        if loaded(label):
            launchctl("bootout", f"{domain()}/{label}")
            log.append(f"unloaded {label}")
        (LAUNCH_AGENTS / f"{label}.plist").unlink(missing_ok=True)
    return log


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=["build", "stage", "status", "activate", "deactivate"])
    parser.add_argument("--yes-i-approved-persistent-collector", action="store_true")
    args = parser.parse_args()
    try:
        if args.action == "build":
            print(f"built release {build()[:12]} at {RUNTIME}; staged plists in {staged_dir()}; nothing started")
        elif args.action == "stage":
            print("\n".join(str(p) for p in stage()))
        elif args.action == "status":
            print(status())
        elif args.action == "activate":
            if not args.yes_i_approved_persistent_collector:
                parser.error("refusing to start persistent jobs without --yes-i-approved-persistent-collector")
            print("\n".join(activate()))
        else:
            print("\n".join(deactivate()) or "nothing was loaded")
    except (InstallError, OSError, subprocess.SubprocessError) as exc:
        print(f"runtime install stopped: {str(exc)[:300]}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
