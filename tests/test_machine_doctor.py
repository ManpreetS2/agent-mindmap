"""Doctor: every status, deterministic via an injected runner/http/which; never prints secrets; never runs real tools."""
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tools import machine_doctor as md
from tools import machine_identity as mi

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
TOOLS = {"claude", "codex", "cursor-agent", "gh", "git", "lsof"}


def auth(logged=True, plan="max"):
    return json.dumps({"loggedIn": logged, "subscriptionType": plan, "email": "someone@example.com", "orgId": "x"})


class Fake:
    def __init__(self, **over):
        self.calls = []
        self.over = over
        self.feed = over.get("feed")

    def __call__(self, args, env=None):
        self.calls.append((list(args), env))
        key = " ".join(args[:3])
        if args[0] == "claude":
            second = env and env.get("CLAUDE_CONFIG_DIR")
            return self.over.get("claude2" if second else "claude1", (0, auth(), ""))
        if args[:2] == ["codex", "login"]:
            return self.over.get("codex", (0, "Logged in using ChatGPT", ""))
        if args[0] == "cursor-agent":
            return self.over.get("cursor", (0, "✓ Logged in as someone@example.com", ""))
        if args[:2] == ["gh", "auth"]:
            return self.over.get("gh", (0, "Logged in to github.com account x (keyring)\nToken: gho_abcdefghijkl123456", ""))
        if args[:2] == ["gh", "api"]:
            return self.over.get("api", (0, json.dumps(self.feed) if self.feed is not None else "", "") if self.feed is not None else (1, "", "HTTP 404 Not Found"))
        if args[0] == "ps":
            return 0, self.over.get("ps", ""), ""
        if args[0] == "lsof":
            port = args[2].split(":")[1].split("-")[0] if ":" in args[2] else ""
            return 0, self.over.get("listen", {}).get(port, ""), ""
        if args[0] == "launchctl":
            return self.over.get("launchctl", (113, "", ""))
        if args[0] == "git":
            sub = args[3] if len(args) > 3 else ""
            table = {"rev-parse": "main", "status": self.over.get("dirty", ""), "remote": "https://user:tok@github.com/ManpreetS2/agent-mindmap.git"}
            return 0, table.get(sub, ""), ""
        return 127, "", ""


def ctx_for(tmp_path, fake=None, http=None, which=None, **kw):
    home = tmp_path / "home dir"
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    (home / ".claude_second").mkdir(exist_ok=True)
    apps = tmp_path / "Applications"
    apps.mkdir(exist_ok=True)
    (apps / "T3 Code (Beta).app").mkdir(exist_ok=True)
    fake = fake or Fake()
    return md.Context(runner=fake, http_status=(http or (lambda u: 200)), http_json=kw.pop("http_json", lambda u: None),
                      home=home, repo=tmp_path, config_dir=tmp_path / "cfg", state_dir=tmp_path / "state",
                      runtime=tmp_path / "rt", now=NOW, env={"PATH": "/x"}, system="Darwin", machine="arm64",
                      applications=(apps,), which_fn=which or (lambda n: f"/bin/{n}" if n in TOOLS else None), **kw)


def by_id(checks):
    return {c.id: c for c in checks}


def test_everything_healthy_is_pass(tmp_path):
    mi.init_identity("Mac A", "publisher", tmp_path / "cfg")
    feed = {"exported_at": (NOW - timedelta(minutes=2)).isoformat(), "trusted_until": (NOW + timedelta(minutes=10)).isoformat()}
    ident = mi.load_identity(tmp_path / "cfg")
    feed["publisher"] = {"machine_id": ident.id, "label": "Mac A", "epoch": 2,
                         "lease_expires_at": (NOW + timedelta(minutes=15)).isoformat(), "state": "active"}
    fake = Fake(feed=feed, listen={"3773": "1", "8799": "2", "8787": ""}, launchctl=(0, "", ""))
    rel = tmp_path / "rt" / "current"
    rel.mkdir(parents=True)
    (rel / "RELEASE.json").write_text(json.dumps({"commit": "a" * 40}))
    (tmp_path / "rt" / "venv" / "bin").mkdir(parents=True)
    (tmp_path / "rt" / "venv" / "bin" / "python").write_text("")
    health = {"last_build": "x", "errors": [], "last_t3_poll": (NOW - timedelta(seconds=20)).isoformat()}
    c = by_id(md.run_checks(ctx_for(tmp_path, fake, http_json=lambda u: health)))
    assert {k: v.status for k, v in c.items() if v.status != md.PASS} == {}, {k: v.summary for k, v in c.items()}


def test_t3_401_is_a_warn_with_the_exact_login_instruction_and_no_automation(tmp_path):
    fake = Fake()
    c = by_id(md.run_checks(ctx_for(tmp_path, fake, http=lambda u: 401)))
    assert c["t3_mcp"].status == md.WARN
    assert "python -m ingest.t3_mcp login --url <copied MCP URL>" in c["t3_mcp"].hint
    assert not any("t3_mcp" in " ".join(a) for a, _ in fake.calls)       # never runs the login


def test_t3_unreachable_fails_and_t3_app_missing_warns(tmp_path):
    ctx = ctx_for(tmp_path, http=lambda u: None)
    c = by_id(md.run_checks(ctx))
    assert c["t3_mcp"].status == md.FAIL
    ctx.applications = (tmp_path / "nowhere",)
    assert by_id(md.run_checks(ctx))["t3_app"].status == md.WARN


def test_claude_accounts_use_distinct_dirs_and_report_only_login_and_plan(tmp_path):
    fake = Fake(claude2=(0, auth(False), ""))
    ctx = ctx_for(tmp_path, fake)
    c = by_id(md.run_checks(ctx))
    assert c["claude_1"].status == md.PASS and "max" in c["claude_1"].summary
    assert c["claude_2"].status == md.WARN and "not logged in" in c["claude_2"].summary
    claude_envs = [env for a, env in fake.calls if a[0] == "claude"]
    assert any(e.get("CLAUDE_CONFIG_DIR") == str(ctx.home / ".claude_second") for e in claude_envs)
    assert c["claude_dirs"].status == md.PASS
    out = md.render(list(c.values()))
    assert "example.com" not in out and "orgId" not in out


def test_claude_unreadable_or_missing_is_unknown_or_warn(tmp_path):
    c = by_id(md.run_checks(ctx_for(tmp_path, Fake(claude1=(1, "garbage", "")))))
    assert c["claude_1"].status == md.UNKNOWN
    c = by_id(md.run_checks(ctx_for(tmp_path, which=lambda n: None)))
    assert c["claude_1"].status == md.UNKNOWN and c["gh"].status == md.FAIL and c["feed"].status == md.UNKNOWN
    ctx = ctx_for(tmp_path)
    (ctx.home / ".claude_second").rmdir()
    c = by_id(md.run_checks(ctx))
    assert c["claude_2"].status == md.WARN and c["claude_dirs"].status == md.WARN


def test_codex_cursor_gh_states(tmp_path):
    fake = Fake(codex=(1, "Not logged in", ""), cursor=(0, "Not logged in", ""), gh=(1, "", "You are not logged into any hosts"))
    c = by_id(md.run_checks(ctx_for(tmp_path, fake)))
    assert (c["codex"].status, c["cursor_agent"].status, c["gh"].status) == (md.WARN, md.WARN, md.FAIL)
    assert "gho_" not in md.render(list(c.values()))
    assert not any("--show-token" in a for args, _ in fake.calls for a in args)


def test_duplicate_collectors_and_publishers_fail(tmp_path):
    ps = "101 /v/python -m tools.run_collector\n102 /v/python -m tools.run_collector\n103 python -m tools.publish_observability --for-real"
    c = by_id(md.run_checks(ctx_for(tmp_path, Fake(ps=ps))))
    assert c["processes"].status == md.FAIL and "2 collector" in c["processes"].summary
    c = by_id(md.run_checks(ctx_for(tmp_path, Fake(ps="101 python -m tools.run_collector"))))
    assert c["processes"].status == md.PASS


def test_ports_8799_conflicts_and_legacy_8787_is_report_only(tmp_path):
    c = by_id(md.run_checks(ctx_for(tmp_path, Fake(listen={"8799": "5", "8787": "9"}), http_json=lambda u: None)))
    assert c["collector"].status == md.FAIL and "not the collector" in c["collector"].summary
    assert c["port_8787"].status == md.PASS and "in use" in c["port_8787"].summary
    c = by_id(md.run_checks(ctx_for(tmp_path, Fake(listen={"8799": "5 6"}))))
    assert c["collector"].status == md.FAIL
    c = by_id(md.run_checks(ctx_for(tmp_path, Fake(listen={"8799": "5"}),
                                    http_json=lambda u: {"last_build": 1, "errors": [], "last_t3_poll": (NOW - timedelta(hours=1)).isoformat()})))
    assert c["collector"].status == md.WARN


def test_doctor_never_touches_8787_or_kills_or_loads_anything(tmp_path):
    fake = Fake()
    md.run_checks(ctx_for(tmp_path, fake))
    flat = [" ".join(a) for a, _ in fake.calls]
    assert not any(w in " ".join(flat) for w in ("bootstrap", "bootout", "kill", "load ", "auth login", "--show-token"))
    assert not any(a[:2] == ["gh", "api"] and ("-X" in a or "--method" in a) for a, _ in fake.calls)


def test_runtime_and_git_states(tmp_path):
    c = by_id(md.run_checks(ctx_for(tmp_path, Fake(dirty=" M f"))))
    assert c["runtime"].status == md.WARN and c["git"].status == md.WARN
    assert "tok" not in c["git"].summary and "user:" not in c["git"].summary and "ManpreetS2/agent-mindmap" in c["git"].summary


def test_identity_states(tmp_path):
    ctx = ctx_for(tmp_path)
    assert by_id(md.run_checks(ctx))["identity"].status == md.WARN
    (tmp_path / "cfg").mkdir()
    (tmp_path / "cfg" / "machine.json").write_text("{bad")
    assert by_id(md.run_checks(ctx))["identity"].status == md.FAIL


def feed_with(owner, ident_epoch=3, state="active", lease_min=10, trusted_min=10):
    return {"exported_at": (NOW - timedelta(minutes=3)).isoformat(), "trusted_until": (NOW + timedelta(minutes=trusted_min)).isoformat(),
            "publisher": {"machine_id": owner, "label": "Mac Z", "epoch": ident_epoch,
                          "lease_expires_at": (NOW + timedelta(minutes=lease_min)).isoformat(), "state": state}}


def test_feed_states_and_the_two_publishers_conflict(tmp_path):
    mi.init_identity("Mac A", "publisher", tmp_path / "cfg")
    c = by_id(md.run_checks(ctx_for(tmp_path, Fake(feed=feed_with("mac-0000000b")))))
    assert c["feed"].status == md.PASS and c["ownership"].status == md.FAIL
    assert "release" in c["ownership"].hint
    c = by_id(md.run_checks(ctx_for(tmp_path, Fake(feed=feed_with("mac-0000000b", trusted_min=-30)))))
    assert c["feed"].status == md.WARN
    c = by_id(md.run_checks(ctx_for(tmp_path, Fake(feed={"exported_at": NOW.isoformat(), "publisher": {"x": 1}}))))
    assert c["ownership"].status == md.FAIL
    c = by_id(md.run_checks(ctx_for(tmp_path, Fake(api=(1, "", "connection refused")))))
    assert c["feed"].status == md.FAIL
    c = by_id(md.run_checks(ctx_for(tmp_path, Fake(api=(0, "not json", "")))))
    assert c["feed"].status == md.FAIL


def test_feed_missing_and_reader_view(tmp_path):
    mi.init_identity("Mac R", "reader", tmp_path / "cfg")
    c = by_id(md.run_checks(ctx_for(tmp_path, Fake())))
    assert c["feed"].status == md.WARN
    c = by_id(md.run_checks(ctx_for(tmp_path, Fake(feed=feed_with("mac-0000000b")))))
    assert c["ownership"].status == md.PASS and "Another Mac" in c["ownership"].summary
    assert c["role_jobs"].status == md.PASS


def test_role_and_job_mismatches_warn(tmp_path):
    mi.init_identity("Mac R", "reader", tmp_path / "cfg")
    c = by_id(md.run_checks(ctx_for(tmp_path, Fake(launchctl=(0, "", "")))))
    assert c["role_jobs"].status == md.WARN and "disable" in c["role_jobs"].hint
    mi.set_role("publisher", tmp_path / "cfg")
    c = by_id(md.run_checks(ctx_for(tmp_path, Fake())))
    assert c["role_jobs"].status == md.WARN and "enable" in c["role_jobs"].hint


def test_platform_states(tmp_path):
    ctx = ctx_for(tmp_path)
    ctx.system = "Linux"
    assert by_id(md.run_checks(ctx))["platform"].status == md.WARN


def test_all_four_statuses_are_reachable_and_json_is_clean(tmp_path, capsys):
    ctx = ctx_for(tmp_path, Fake(listen={"3773": "1"}))
    checks = md.run_checks(ctx)
    seen = {c.status for c in checks}
    assert {md.PASS, md.WARN, md.UNKNOWN} <= seen
    assert md.FAIL in {c.status for c in md.run_checks(ctx_for(tmp_path, http=lambda u: None))}
    assert md.main(["--json"], ctx) in (0, 1)
    data = json.loads(capsys.readouterr().out)
    assert {c["status"] for c in data["checks"]} <= {"PASS", "WARN", "FAIL", "UNKNOWN"}


def test_exit_code_is_one_only_for_fail(tmp_path, capsys):
    assert md.main([], ctx_for(tmp_path, http=lambda u: None)) == 1
    assert md.main([], ctx_for(tmp_path, Fake(listen={"3773": "1"}))) in (0, 1)


def test_redaction():
    out = md.redact("mail me at a.b@gmail.com token gho_abcdefghijklmnop and " + str(Path.home()) + "/x")
    assert "gmail" not in out and "gho_" not in out and str(Path.home()) not in out


def test_real_runner_handles_missing_binary():
    assert md.real_runner(["definitely-not-installed-xyz"])[0] == 127


def test_paths_with_spaces_in_home_and_repo(tmp_path):
    ctx = ctx_for(tmp_path / "a b" / "c d")
    assert "claude_1" in by_id(md.run_checks(ctx))
