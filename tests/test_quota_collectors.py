import json
import os
import stat
import subprocess
import sys
import textwrap
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tools.quota import api, normalize as N, store
from tools.quota.collectors import _allow, claude_statusline as cs, codex_app_server as cx, cursor_cli
from tools.quota.models import QuotaError

NOW = datetime(2026, 10, 24, 7, 0, tzinfo=UTC)
EPOCH = int(NOW.timestamp())


def fake_codex(tmp_path, behaviour, result=None):
    """Executable named `codex` in a directory with spaces; behaviour: ok|autherr|malformed|hang|exit|stray."""
    d = tmp_path / "bin dir"
    d.mkdir(exist_ok=True)
    script = d / "codex"
    script.write_text(textwrap.dedent(f"""\
        #!{sys.executable}
        import json, sys, time
        behaviour = {behaviour!r}
        result = {result!r}
        if sys.argv[1:] != ["app-server"]:
            sys.exit(9)
        seen = []
        for line in sys.stdin:
            m = json.loads(line)
            seen.append(m["method"])
            if m["method"] == "initialize":
                if behaviour == "hang": time.sleep(60)
                if behaviour == "exit": sys.exit(1)
                if behaviour == "malformed": print("{{not json"); sys.stdout.flush(); print("[1]")
                print(json.dumps({{"id": m["id"], "result": {{"userAgent": "x"}}}})); sys.stdout.flush()
            elif m["method"] == "account/rateLimits/read":
                if behaviour == "autherr":
                    print(json.dumps({{"id": m["id"], "error": {{"code": -32000, "message": "not logged in: token user@example.com"}}}}))
                else:
                    print(json.dumps({{"id": m["id"], "result": result}}))
                sys.stdout.flush()
                break
        assert set(seen) <= {{"initialize", "initialized", "account/rateLimits/read"}}, seen
    """))
    script.chmod(0o755)
    return str(script)


def ok_result(**over):
    r = {"rateLimits": {"planType": "plus", "limitId": "codex",
                        "primary": {"usedPercent": 0, "windowDurationMins": 300, "resetsAt": EPOCH + 3600},
                        "secondary": {"usedPercent": 30, "windowDurationMins": 10080, "resetsAt": EPOCH + 86400}},
         "ordinaryUsageAllowed": True, "accountId": "acct-123", "credits": {"balance": "9"}}
    r.update(over)
    return r


def test_codex_success(tmp_path):
    r = cx.collect(fake_codex(tmp_path, "ok", ok_result()), now=NOW)
    assert r["outcome"] == "ok" and r["plan"] == "plus" and r["ordinary_usage_allowed"] is True
    assert [(w["type"], w["window_minutes"], w["used_pct"]) for w in r["windows"]] == [
        ("session", 300, 0), ("weekly", 10080, 30)]
    assert "acct-123" not in json.dumps(r) and "credits" not in json.dumps(r)
    store.write("codex", r, "live", tmp_path / "s")
    assert api.pools(NOW, tmp_path / "s")[4]["status"] == "VERIFIED"


def test_codex_auth_failure_has_no_leaks(tmp_path):
    r = cx.collect(fake_codex(tmp_path, "autherr"), now=NOW)
    assert r["outcome"] == "error" and "login" in r["reason"] and "example.com" not in json.dumps(r)
    store.write("codex", r, "live", tmp_path / "s")
    p = api.pools(NOW, tmp_path / "s")[4]
    assert p["status"] == "ERROR" and p["windows"] == []


def test_codex_missing_binary(tmp_path):
    r = cx.collect(str(tmp_path / "nope" / "codex"), now=NOW)
    assert r["outcome"] == "error" and "not found" in r["reason"]


def test_codex_malformed_lines_then_valid(tmp_path):
    r = cx.collect(fake_codex(tmp_path, "malformed", ok_result()), now=NOW)
    assert r["outcome"] == "ok"


def test_codex_malformed_result_shape(tmp_path):
    r = cx.collect(fake_codex(tmp_path, "ok", {"rateLimits": "bad"}), now=NOW)
    assert r["outcome"] == "error"


def test_codex_timeout_terminates_process(tmp_path):
    started = []
    real = subprocess.Popen

    def spy(*a, **k):
        p = real(*a, **k)
        started.append(p)
        return p
    r = cx.collect(fake_codex(tmp_path, "hang"), timeout=1.0, now=NOW, popen=spy)
    assert r["outcome"] == "error" and "within" in r["reason"]
    assert started and started[0].poll() is not None


def test_codex_early_exit(tmp_path):
    assert "exited" in cx.collect(fake_codex(tmp_path, "exit"), now=NOW)["reason"]


def test_codex_missing_windows_null_reset_and_null_allowed(tmp_path):
    res = ok_result(ordinaryUsageAllowed=None)
    res["rateLimits"]["primary"] = None
    res["rateLimits"]["secondary"]["resetsAt"] = None
    r = cx.collect(fake_codex(tmp_path, "ok", res), now=NOW)
    assert [w["type"] for w in r["windows"]] == ["weekly"] and r["windows"][0]["resets_at"] is None
    assert "ordinary_usage_allowed" not in r and r["reason"] is None
    none = cx.collect(fake_codex(tmp_path, "ok", {"rateLimits": {"planType": "plus"}}), now=NOW)
    assert none["windows"] == []
    store.write("codex", none, "live", tmp_path / "s")
    assert api.pools(NOW, tmp_path / "s")[4]["status"] == "UNKNOWN"


def test_codex_ordinary_usage_false_noted_not_inferred(tmp_path):
    r = cx.collect(fake_codex(tmp_path, "ok", ok_result(ordinaryUsageAllowed=False)), now=NOW)
    assert r["ordinary_usage_allowed"] is False and "not currently allowed" in r["reason"]
    assert r["windows"][0]["used_pct"] == 0  # percentages untouched


def test_codex_bad_values_dropped_or_refused():
    bad = ok_result()
    bad["rateLimits"]["primary"]["usedPercent"] = 250
    assert [w["type"] for w in cx.map_rate_limits(bad, NOW)["windows"]] == ["weekly"]
    dup = ok_result()
    dup["rateLimits"]["secondary"]["windowDurationMins"] = 300
    assert cx.map_rate_limits(dup, NOW)["outcome"] == "error"
    unk = ok_result()
    unk["rateLimits"]["primary"]["windowDurationMins"] = None
    r = cx.map_rate_limits(unk, NOW)
    assert r["windows"][0]["type"] == "other"  # duration unknown: never guessed as session


def test_allowlist_guard():
    for method in ("thread/start", "turn/start", "model/list", "account/read", "sendUserMessage"):
        with pytest.raises(QuotaError):
            _allow.check_method(method)
    for argv in (["codex", "exec", "hi"], ["codex", "app-server", "--x"], ["claude", "-p", "hi"],
                 ["cursor-agent", "chat"], ["cursor-agent", "about"], []):
        with pytest.raises(QuotaError):
            _allow.check_argv(argv)
    _allow.check_argv(["/p a/th/codex", "app-server"])
    _allow.check_argv(["cursor-agent", "about", "--format", "json"])
    assert _allow.ALLOWED_RPC_METHODS == {"initialize", "initialized", "account/rateLimits/read"}


def test_rpc_send_refuses_other_methods():
    rpc = cx._Rpc.__new__(cx._Rpc)
    with pytest.raises(QuotaError):
        rpc.send("turn/start", {})


def test_collectors_spawn_only_allowlisted_commands(tmp_path):
    spawned = []

    class P:
        stdin = stdout = None

        def __init__(self, argv, **k):
            spawned.append(argv)
            raise FileNotFoundError

    cx.collect("codex", popen=P)
    cursor_cli.collect("cursor-agent", run=lambda argv, **k: spawned.append(argv) or (_ for _ in ()).throw(FileNotFoundError()))
    assert spawned == [["codex", "app-server"], ["cursor-agent", "about", "--format", "json"]]
    assert cx.collect("claude", popen=P)["outcome"] == "error" and len(spawned) == 2  # refused before spawning


def test_cursor_parse_drops_email_and_is_unsupported():
    text = json.dumps({"subscriptionTier": "Premium", "userEmail": "me@example.com", "cliVersion": "1"})
    r = cursor_cli.parse_about(text, NOW)
    assert r["outcome"] == "unsupported" and r["plan"] == "premium" and "example.com" not in json.dumps(r)
    assert cursor_cli.parse_about("nope", NOW)["outcome"] == "error"
    assert cursor_cli.parse_about("[]", NOW)["outcome"] == "error"


def test_cursor_collect_failures(tmp_path):
    assert cursor_cli.collect(str(tmp_path / "x" / "cursor-agent"), now=NOW)["outcome"] == "error"
    d = tmp_path / "my bin"
    d.mkdir()
    s = d / "cursor-agent"
    s.write_text(f"#!{sys.executable}\nimport sys\nsys.exit(3)\n")
    s.chmod(0o755)
    assert "status 3" in cursor_cli.collect(str(s), now=NOW)["reason"]
    s.write_text(f'#!{sys.executable}\nimport sys\nassert sys.argv[1:]==["about","--format","json"]\nprint(\'{{"subscriptionTier":"Premium"}}\')\n')
    assert cursor_cli.collect(str(s), now=NOW)["plan"] == "premium"


# ---- Claude status line

def payload(five=None, seven=None, **extra):
    rl = {}
    if five is not None:
        rl["five_hour"] = five
    if seven is not None:
        rl["seven_day"] = seven
    return {"rate_limits": rl, "session_id": "s", "cwd": "/private/x", "cost": {"total_cost_usd": 1},
            "transcript_path": "/p", "prompt": "secret", **extra}


FIVE = {"used_percentage": 23.5, "resets_at": EPOCH + 3600}
SEVEN = {"used_percentage": 41.2, "resets_at": EPOCH + 86400}


def test_statusline_both_windows_strips_private_data(tmp_path):
    out = cs.run("claude-1", json.dumps(payload(FIVE, SEVEN)), state_dir=tmp_path, now=NOW, env={})
    assert out == "5h 24% · 7d 41%"
    text = (tmp_path / "claude-1.json").read_text()
    for secret in ("/private/x", "secret", "total_cost", "transcript", "session_id"):
        assert secret not in text
    p = api.pools(NOW, tmp_path)[0]
    assert p["status"] == "VERIFIED" and [w["type"] for w in p["windows"]] == ["session", "weekly"]


def test_statusline_one_or_no_window(tmp_path):
    assert cs.run("claude-1", json.dumps(payload(seven=SEVEN)), state_dir=tmp_path, now=NOW, env={}) == "7d 41%"
    assert [w["type"] for w in api.pools(NOW, tmp_path)[0]["windows"]] == ["weekly"]
    before = (tmp_path / "claude-1.json").read_text()
    assert cs.run("claude-1", json.dumps(payload()), state_dir=tmp_path, now=NOW, env={}) == "quota n/a"
    assert (tmp_path / "claude-1.json").read_text() == before  # absent windows never wipe a good reading


@pytest.mark.parametrize("text", ["", "{", "[]", "null", '{"rate_limits": 5}', '{"rate_limits": {"five_hour": {"used_percentage": "x"}}}',
                                  '{"rate_limits": {"five_hour": {"used_percentage": 500, "resets_at": 1}}}', "\x00\xff"])
def test_statusline_malformed_never_crashes(tmp_path, text):
    assert cs.run("claude-1", text, state_dir=tmp_path, now=NOW, env={}) == "quota n/a"
    assert not list(tmp_path.glob("*.json"))


def test_statusline_drops_passed_reset_and_bad_alias(tmp_path):
    stale = {"used_percentage": 50, "resets_at": EPOCH - 10}
    assert cs.run("claude-1", json.dumps(payload(stale, SEVEN)), state_dir=tmp_path, now=NOW, env={}) == "7d 41%"
    assert cs.run("claude-9", json.dumps(payload(FIVE)), state_dir=tmp_path, now=NOW, env={}) == "quota n/a"


def test_statusline_repeat_writes_replace_atomically(tmp_path):
    for pct in (10, 20, 30):
        cs.run("claude-1", json.dumps(payload({"used_percentage": pct, "resets_at": EPOCH + 600})),
               state_dir=tmp_path, now=NOW, env={})
    assert api.pools(NOW, tmp_path)[0]["windows"][0]["used_pct"] == 30
    assert [f.name for f in tmp_path.iterdir()] == ["claude-1.json"]
    assert stat.S_IMODE(os.stat(tmp_path / "claude-1.json").st_mode) == 0o600


def test_statusline_config_dir_guard_blocks_cross_account(tmp_path):
    a, b = tmp_path / "acct a", tmp_path / "acct b"
    a.mkdir(), b.mkdir()
    sd = tmp_path / "s"
    # claude-2's tap running inside account A's process must not write anything
    cs.run("claude-2", json.dumps(payload(FIVE)), state_dir=sd, now=NOW,
           env={"CLAUDE_CONFIG_DIR": str(a)}, expect_config_dir=str(b))
    assert not sd.exists()
    cs.run("claude-2", json.dumps(payload(FIVE)), state_dir=sd, now=NOW,
           env={"CLAUDE_CONFIG_DIR": str(b)}, expect_config_dir=str(b))
    assert (sd / "claude-2.json").exists()


def test_statusline_cli_subprocess(tmp_path):
    root = Path(__file__).resolve().parents[1]
    r = subprocess.run([sys.executable, "-m", "tools.quota", "--state-dir", str(tmp_path / "s p"), "claude-statusline",
                        "--alias", "claude-2"], input=json.dumps(payload(
                            {"used_percentage": 5, "resets_at": int(datetime.now(UTC).timestamp()) + 3600})),
                       capture_output=True, text=True, cwd=root)
    assert r.returncode == 0 and r.stdout.strip() == "5h 5%"
    bad = subprocess.run([sys.executable, "-m", "tools.quota", "--state-dir", str(tmp_path / "s p"),
                          "claude-statusline", "--alias", "claude-2"], input="garbage", capture_output=True,
                         text=True, cwd=root)
    assert bad.returncode == 0 and bad.stdout.strip() == "quota n/a"


def test_snippet_and_installer(tmp_path):
    cdir = tmp_path / "claude dir"
    cdir.mkdir()
    snip = cs.snippet("claude-1", str(cdir), repo_root=Path("/r p"), python="/py thon")
    cmd = snip["statusLine"]["command"]
    assert "'/r p'" in cmd and "'/py thon'" in cmd and "--alias claude-1" in cmd and "--expect-config-dir" in cmd
    code, msg = cs.install("claude-1", str(cdir), apply=False, approved=False)
    assert code == 0 and "DRY RUN" in msg and not (cdir / "settings.json").exists()
    code, msg = cs.install("claude-1", str(cdir), apply=True, approved=False)
    assert "DRY RUN" in msg and not (cdir / "settings.json").exists()
    (cdir / "settings.json").write_text(json.dumps({"theme": "dark"}))
    code, msg = cs.install("claude-1", str(cdir), apply=True, approved=True, now=NOW)
    data = json.loads((cdir / "settings.json").read_text())
    assert code == 0 and data["theme"] == "dark" and data["statusLine"]["type"] == "command"
    backup = cdir / "settings.json.bak-20261024T070000Z"
    assert json.loads(backup.read_text()) == {"theme": "dark"}
    assert cs.install("claude-1", str(cdir), apply=True, approved=True)[0] == 0  # idempotent
    assert cs.install("claude-2", str(cdir), apply=True, approved=True)[0] == 2   # other account's line: refuse


def test_installer_refuses_existing_statusline_and_bad_json(tmp_path):
    cdir = tmp_path / "c"
    cdir.mkdir()
    mine = {"statusLine": {"type": "command", "command": "echo hi"}}
    (cdir / "settings.json").write_text(json.dumps(mine))
    code, msg = cs.install("claude-1", str(cdir), apply=True, approved=True)
    assert code == 2 and "Chain" in msg and json.loads((cdir / "settings.json").read_text()) == mine
    (cdir / "settings.json").write_text("{oops")
    assert cs.install("claude-1", str(cdir), apply=True, approved=True)[0] == 2
    assert cs.install("claude-1", str(tmp_path / "missing"), apply=True, approved=True)[0] == 2


def test_cli_manual_and_show(tmp_path):
    root = Path(__file__).resolve().parents[1]
    base = [sys.executable, "-m", "tools.quota", "--state-dir", str(tmp_path / "q q")]
    future = (datetime.now(UTC) + timedelta(days=3)).isoformat()
    ok = subprocess.run([*base, "manual", "set", "--pool", "devin-free", "--window", "weekly", "--used-pct", "20",
                         "--resets-at", future, "--source", "Devin UI", "--observed-at",
                         datetime.now(UTC).isoformat()], capture_output=True, text=True, cwd=root)
    assert ok.returncode == 0, ok.stderr
    shown = json.loads(subprocess.run([*base, "show", "--json"], capture_output=True, text=True, cwd=root).stdout)
    assert [p["id"] for p in shown][3] == "devin-free" and shown[3]["status"] == "MANUAL"
    bad = subprocess.run([*base, "manual", "set", "--pool", "devin-free", "--window", "weekly", "--used-pct", "999",
                          "--source", "x", "--observed-at", datetime.now(UTC).isoformat()],
                         capture_output=True, text=True, cwd=root)
    assert bad.returncode == 2 and "Traceback" not in bad.stderr
    cleared = subprocess.run([*base, "manual", "clear", "--pool", "devin-free"], capture_output=True, text=True, cwd=root)
    assert cleared.stdout.strip() == "cleared"
