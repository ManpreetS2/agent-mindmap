"""Who may publish `latest.json`: one owner at a time, fenced by a lease and an epoch recorded IN the feed.

The feed (still exactly two files) gains one additive object:

    "publisher": {"machine_id": "mac-1a2b3c4d", "label": "Mac A", "epoch": 3,
                  "lease_expires_at": "<ISO>", "state": "active" | "released"}

Rules (all enforced after a FRESH clone, on every attempt, so a rejected push is re-decided from the new truth):
  * a Mac publishes only if its local role is `publisher` AND `decide()` says publish;
  * remote owned by me: publish, every publish extends the lease (20 min), the epoch never changes;
  * remote owned by someone else with an unexpired lease: refuse; expired lease: `claim_required` (an operator runs
    `claim`; nothing ever takes over automatically);
  * legacy feed with no `publisher` object (written before this existed): younger than the lease -> refuse unless the
    operator forces a takeover; older -> `claim_required`;
  * `claim` bumps the epoch (remote epoch + 1). A stale former publisher that wakes up sees the higher epoch, refuses,
    and records `superseded` in its local state; it never overwrites;
  * `release` writes `state: "released"` so the next Mac can `claim` without force;
  * a malformed remote feed or publisher object fails closed.
The git push itself is the compare-and-swap: two Macs racing from the same base cannot both win; the loser re-clones
and re-decides.

  python -m tools.publisher_ownership status [--offline]
  python -m tools.publisher_ownership claim [--force-takeover --confirm-takeover-of <token>]
  python -m tools.publisher_ownership release
  python -m tools.publisher_ownership handover
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tools import machine_identity as mi

LEASE_TTL_SEC = 20 * 60
ID_RE = re.compile(r"^mac-[0-9a-f]{8}$")
STATES = ("active", "released")
LEGACY_TOKEN = "legacy"
CORRUPT_TOKEN = "corrupt"


class OwnershipError(RuntimeError):
    """An expected refusal an operator can act on; the message never contains feed content beyond ids/labels."""


@dataclass(frozen=True)
class Decision:
    action: str                       # publish | refuse | claim_required
    reason: str
    code: str = ""                    # machine-readable cause, used by tests and the doctor
    epoch: int | None = None          # epoch the written publisher object must carry (publish only)
    takeover: bool = False            # a claim that displaces another owner / legacy writer
    confirm_token: str | None = None  # what `--confirm-takeover-of` must equal for a forced takeover
    superseded_by: dict | None = field(default=None, compare=False)


MAX_EPOCH = 2**31  # a feed claiming a larger epoch is malformed (an absurd int would eventually break json read/write)


def parse_time(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.astimezone(UTC) if parsed.utcoffset() is not None else None
    except (ValueError, OverflowError):  # e.g. "9999-12-31T23:59:59-23:59" overflows on conversion
        return None


def publisher_object(identity: mi.MachineIdentity, epoch: int, now: datetime, state: str = "active") -> dict:
    lease = now if state == "released" else now + timedelta(seconds=LEASE_TTL_SEC)
    return {"machine_id": identity.id, "label": identity.label, "epoch": epoch,
            "lease_expires_at": lease.isoformat(), "state": state}


def validate_publisher(pub, now: datetime) -> dict | None:
    """The object if it is well formed, else None. A lease absurdly far in the future would lock everyone out, so
    it counts as malformed."""
    if not isinstance(pub, dict):
        return None
    epoch, lease = pub.get("epoch"), parse_time(pub.get("lease_expires_at"))
    if (not isinstance(pub.get("machine_id"), str) or not ID_RE.match(pub["machine_id"])
            or not isinstance(pub.get("label"), str) or isinstance(epoch, bool) or not isinstance(epoch, int)
            or not 1 <= epoch < MAX_EPOCH or pub.get("state") not in STATES or lease is None
            or lease > now + timedelta(seconds=2 * LEASE_TTL_SEC)):
        return None
    return pub


def owner_summary(pub: dict) -> dict:
    return {"machine_id": pub["machine_id"], "label": pub["label"], "epoch": pub["epoch"]}


def decide(remote_feed: dict | None, identity: mi.MachineIdentity | None, now: datetime, *, claiming: bool = False,
           force_takeover: bool = False, local_epoch: int | None = None) -> Decision:
    """`remote_feed` is the freshly cloned latest.json (None = the feed does not exist yet). With `claiming=True`
    `publish` means 'this claim may be written'; otherwise it means 'this Mac may publish'."""
    if identity is None:
        return Decision("refuse", "This Mac has no machine identity (run: python -m tools.machine_identity init --label <name>)",
                        "no_identity")
    if not claiming and identity.role != "publisher":
        return Decision("refuse", "This Mac's role is 'reader'; it never writes the feed", "reader")
    if remote_feed is None:
        return Decision("publish", "No feed exists yet", "no_feed", epoch=max(local_epoch or 1, 1))
    if not isinstance(remote_feed, dict):
        return Decision("refuse", "Remote feed is malformed (not an object); investigate before writing", "corrupt")

    def forced(token: str, epoch: int, why: str) -> Decision:
        if force_takeover:
            return Decision("publish", why, "takeover", epoch=epoch, takeover=True, confirm_token=token)
        return Decision("refuse", f"{why}; taking over needs --force-takeover --confirm-takeover-of {token}",
                        "force_required", confirm_token=token)

    if "publisher" not in remote_feed:
        exported = parse_time(remote_feed.get("exported_at"))
        if exported is None:
            return _corrupt(claiming, force_takeover, remote_feed)
        fresh = (now - exported).total_seconds() < LEASE_TTL_SEC       # includes a future stamp: fail closed
        if claiming:
            if fresh:
                return forced(LEGACY_TOKEN, 1, "The existing feed has no owner record and was written within the last "
                              f"{LEASE_TTL_SEC // 60} minutes (another Mac is probably still publishing)")
            return Decision("publish", "Legacy feed with no owner record is older than the lease", "claim_legacy", epoch=1)
        if fresh:
            return Decision("refuse", "Legacy feed (no owner record) was written recently by another Mac; "
                            "an operator must `claim --force-takeover`", "legacy_fresh")
        return Decision("claim_required", "Legacy feed (no owner record) is older than the lease; an operator must `claim`",
                        "legacy_old")

    pub = validate_publisher(remote_feed["publisher"], now)
    if pub is None:
        return _corrupt(claiming, force_takeover, remote_feed)
    mine = pub["machine_id"] == identity.id
    lease = parse_time(pub["lease_expires_at"])
    expired = lease <= now  # type: ignore[operator]
    superseded = (
        owner_summary(pub)
        if not mine and (
            (local_epoch is not None and pub["epoch"] >= local_epoch)
            or (local_epoch is None and identity.role == "publisher")  # claimed an empty repo, another Mac wrote first
        )
        else None
    )
    base_epoch = max(pub["epoch"], local_epoch or 0)  # a claim must outrank this Mac's own record too
    who = f"{pub['label']} (epoch {pub['epoch']})"

    if pub["state"] == "released":
        if claiming:
            return Decision("publish", f"Feed was released by {who}", "claim_released", epoch=base_epoch + 1)
        return Decision("claim_required", f"Feed was released by {who}; an operator must `claim` it",
                        "released", superseded_by=superseded)
    if mine:
        if local_epoch is not None and pub["epoch"] < local_epoch:
            return Decision("refuse", "Remote epoch is lower than this Mac's own record (feed rolled back); investigate",
                            "rollback")
        return Decision("publish", "This Mac owns the feed", "owner", epoch=pub["epoch"])
    if not claiming and local_epoch is not None and pub["epoch"] < local_epoch:
        return Decision("refuse", "Remote owner's epoch is lower than this Mac's own record (feed rolled back); investigate",
                        "rollback")
    if expired:
        if claiming:
            return Decision("publish", f"Lease of {who} has expired", "claim_expired", epoch=base_epoch + 1)
        return Decision("claim_required", f"Lease of {who} has expired; an operator must `claim`", "expired",
                        superseded_by=superseded)
    if claiming:
        return forced(pub["machine_id"], base_epoch + 1, f"{who} holds an unexpired lease")
    return Decision("refuse", f"Feed is owned by {who} with an unexpired lease", "foreign_active", superseded_by=superseded)


def _corrupt(claiming: bool, force: bool, remote_feed: dict) -> Decision:
    prior = (remote_feed.get("publisher") or {}).get("epoch") if isinstance(remote_feed.get("publisher"), dict) else None
    epoch = prior + 1 if isinstance(prior, int) and not isinstance(prior, bool) and 0 <= prior < MAX_EPOCH - 1 else 1
    if claiming and force:
        return Decision("publish", "Overriding a malformed owner record", "takeover", epoch=epoch, takeover=True,
                        confirm_token=CORRUPT_TOKEN)
    if claiming:
        return Decision("refuse", f"Remote owner record is malformed; overriding needs --force-takeover "
                        f"--confirm-takeover-of {CORRUPT_TOKEN}", "force_required", confirm_token=CORRUPT_TOKEN)
    return Decision("refuse", "Remote feed or owner record is malformed; investigate before writing", "corrupt")


# ------------------------------------------------------------------ local state (inside the publisher state.json)

def record_owner(state: dict, epoch: int | None, now: datetime) -> None:
    state["ownership"] = {"state": "owner", "epoch": epoch, "updated_at": now.isoformat()}


def record_superseded(state: dict, by: dict, now: datetime) -> None:
    previous = state.get("ownership") if isinstance(state.get("ownership"), dict) else {}
    state["ownership"] = {"state": "superseded", "epoch": previous.get("epoch"), "superseded_by": by,
                          "updated_at": now.isoformat()}


def record_released(state: dict, epoch: int | None, now: datetime) -> None:
    state["ownership"] = {"state": "released", "epoch": epoch, "updated_at": now.isoformat()}


def local_epoch(state: dict) -> int | None:
    own = state.get("ownership")
    epoch = own.get("epoch") if isinstance(own, dict) else None
    return epoch if isinstance(epoch, int) and not isinstance(epoch, bool) and epoch >= 1 else None


def record_remote_view(state: dict, remote_feed: dict | None, now: datetime) -> None:
    """What a read-only look at the feed showed (used by feed_health on a reader Mac)."""
    view: dict = {"checked_at": now.isoformat()}
    if isinstance(remote_feed, dict):
        pub = validate_publisher(remote_feed.get("publisher"), now)
        view.update(last_published_at=remote_feed.get("exported_at"), last_observed_at=remote_feed.get("observed_at"),
                    trusted_until=remote_feed.get("trusted_until"), owner=owner_summary(pub) if pub else None)
    state["remote_view"] = view


# ------------------------------------------------------------------ FeedHealth

def feed_health(state_dir: Path | None = None, now: datetime | None = None, config_dir: Path | None = None) -> dict:
    """Exactly the `FeedHealth` object of shared/observability.ts, from LOCAL records only (no network)."""
    from tools import publish_observability as pub

    now = now or datetime.now(UTC)
    state = pub.load_state(Path(state_dir) if state_dir else pub.STATE_DIR)
    try:
        ident = mi.load_identity(config_dir)
    except mi.IdentityError:
        ident = None
    health = {"status": "unknown", "last_published_at": None, "last_observed_at": None, "trusted_until": None,
              "owner": None, "owned_by_this_machine": None, "last_error": _short(state.get("last_error"))}

    def freshness(trusted) -> str:
        t = parse_time(trusted)
        return "unknown" if t is None else ("fresh" if now < t else "stale")

    own = state.get("ownership") if isinstance(state.get("ownership"), dict) else {}
    if ident is None:
        health["status"] = "disabled"
    elif ident.role == "publisher" and own.get("state") != "superseded":
        health["owned_by_this_machine"] = own.get("state") == "owner"
        health["last_published_at"] = state.get("last_success_at")
        health["last_observed_at"] = state.get("last_observed_at")
        health["trusted_until"] = state.get("last_trusted_until")
        if isinstance(own.get("epoch"), int) and own.get("state") == "owner":
            health["owner"] = {"machine_id": ident.id, "label": ident.label, "epoch": own["epoch"]}
        health["status"] = "unpublished" if not state.get("last_success_at") else freshness(health["trusted_until"])
    elif ident.role == "publisher":      # superseded: another Mac owns the feed now
        by = own.get("superseded_by")
        health.update(owned_by_this_machine=False, owner=by if isinstance(by, dict) else None,
                      last_error="Superseded by another Mac; this Mac no longer publishes")
        health["status"] = "stale"
    else:                                 # reader: only what a read-only look recorded
        view = state.get("remote_view") if isinstance(state.get("remote_view"), dict) else None
        health["owned_by_this_machine"] = False
        if view is None:
            health["status"] = "disabled"
        else:
            health.update(last_published_at=view.get("last_published_at"), last_observed_at=view.get("last_observed_at"),
                          trusted_until=view.get("trusted_until"), owner=view.get("owner"))
            health["status"] = freshness(view.get("trusted_until"))
            health["owned_by_this_machine"] = bool(view.get("owner") and ident and view["owner"].get("machine_id") == ident.id)
    return health


def _short(value) -> str | None:
    return value[:160] if isinstance(value, str) and value else None


# ------------------------------------------------------------------ read-only remote look (gh api, no writes)

def fetch_remote_feed(repo: str, runner=None) -> tuple[str, dict | None]:
    """('ok', feed) | ('missing', None) | ('malformed', None) | ('error', None). Read-only `gh api`."""
    from tools import publish_observability as pub

    run = runner or _run
    rc, out, err = run(["gh", "api", f"repos/{repo}/contents/latest.json", "-H", "Accept: application/vnd.github.raw"],
                       pub.secure_env())
    if rc != 0:
        return ("missing", None) if "not found" in (out + err).lower() or "404" in (out + err) else ("error", None)
    try:
        data = json.loads(out)
    except (ValueError, RecursionError):
        return "malformed", None
    return ("ok", data) if isinstance(data, dict) else ("malformed", None)


def _run(args: list[str], env: dict) -> tuple[int, str, str]:
    try:
        r = subprocess.run(args, env=env, capture_output=True, text=True, check=False, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return 127, "", "could not run"
    return r.returncode, r.stdout, r.stderr


# ------------------------------------------------------------------ operator actions

def _verified_push(repo: str, plan, now: datetime, state_dir: Path, message: str, env: dict | None = None):
    from tools import publish_observability as pub

    env = env or pub.secure_env()
    info = json.loads(pub.cmd(["gh", "repo", "view", repo, "--json", "nameWithOwner,visibility,isFork"], env=env,
                              what="destination check"))
    if not pub.verified_destination(repo, info):
        raise pub.PublishError("Destination is not the approved PRIVATE repository")
    return pub.push_files(repo, env, plan, message=message)


def claim(repo: str, *, now: datetime | None = None, state_dir: Path | None = None, config_dir: Path | None = None,
          force_takeover: bool = False, confirm: str | None = None, env: dict | None = None) -> str:
    from tools import publish_observability as pub

    now = now or datetime.now(UTC)
    state_dir = Path(state_dir) if state_dir else pub.STATE_DIR
    ident = mi.load_identity(config_dir)
    if ident is None:
        raise OwnershipError("Initialise this Mac first: python -m tools.machine_identity init --label <name>")
    outcome: dict = {}
    with pub.Lock(state_dir):
        state = pub.load_state(state_dir)

        def plan(previous):
            d = decide(previous, ident, now, claiming=True, local_epoch=local_epoch(state))
            if d.code == "force_required":
                if not (force_takeover and confirm == d.confirm_token):
                    raise OwnershipError(d.reason)
                d = decide(previous, ident, now, claiming=True, force_takeover=True, local_epoch=local_epoch(state))
            if d.action != "publish":
                raise OwnershipError(d.reason)
            outcome["decision"] = d
            if previous is None:
                return "NO FEED YET: local role set; the first publish creates the feed at epoch 1"
            if d.code == "owner":
                outcome["epoch"] = d.epoch
                return "ALREADY OWNER: nothing to change"
            new = dict(previous)
            new["publisher"] = publisher_object(ident, d.epoch, now)
            outcome["epoch"] = d.epoch
            return {"latest.json": json.dumps(new, indent=2, ensure_ascii=False) + "\n"}

        result = _verified_push(repo, plan, now, state_dir, "chore: claim private feed ownership", env)
        mi.set_role("publisher", config_dir)
        record_owner(state, outcome.get("epoch"), now)
        state["consecutive_failures"] = 0
        state["last_error"] = None
        state.pop("last_attempt_at", None)
        pub.save_state(state_dir, state)
    epoch = outcome.get("epoch")
    return f"{result.split(':')[0]}: {ident.label} now holds the feed (epoch {epoch if epoch else 'pending first publish'}); role=publisher"


def release(repo: str, *, now: datetime | None = None, state_dir: Path | None = None, config_dir: Path | None = None,
            env: dict | None = None) -> str:
    from tools import publish_observability as pub

    now = now or datetime.now(UTC)
    state_dir = Path(state_dir) if state_dir else pub.STATE_DIR
    ident = mi.load_identity(config_dir)
    if ident is None:
        raise OwnershipError("This Mac has no machine identity")
    outcome: dict = {}
    with pub.Lock(state_dir):
        state = pub.load_state(state_dir)

        def plan(previous):
            pubobj = validate_publisher(previous.get("publisher"), now) if isinstance(previous, dict) else None
            if pubobj is None or pubobj["machine_id"] != ident.id:
                outcome["remote_untouched"] = True
                return "NOT THE OWNER: remote left untouched"
            outcome["epoch"] = pubobj["epoch"]
            new = dict(previous)
            new["publisher"] = publisher_object(ident, pubobj["epoch"], now, state="released")
            return {"latest.json": json.dumps(new, indent=2, ensure_ascii=False) + "\n"}

        _verified_push(repo, plan, now, state_dir, "chore: release private feed ownership", env)
        mi.set_role("reader", config_dir)
        record_released(state, outcome.get("epoch") or local_epoch(state), now)
        pub.save_state(state_dir, state)
    if outcome.get("remote_untouched"):
        return f"{ident.label} was not the recorded owner; the feed was left untouched and this Mac is now a reader"
    return f"RELEASED: {ident.label} released the feed (epoch {outcome['epoch']}) and is now a reader; another Mac may `claim` it"


HANDOVER = """\
Operator-controlled handover of the private feed (never automatic). Replace OLD and NEW with the Macs' labels.

OLD Mac (currently publishing)                              NEW Mac (will publish)
1. python -m tools.publisher_ownership status
2. python -m tools.publisher_launchd disable                (stop the timed job first; skip if it was never enabled)
3. python -m tools.publisher_ownership release              (writes state:"released"; role becomes reader)
                                                            4. python -m tools.machine_doctor      (all FAIL cleared; T3 login done)
                                                            5. python -m tools.publisher_ownership claim
                                                            6. python -m tools.publisher_launchd install
                                                               python -m tools.publisher_launchd enable --yes-i-approved-live-publishing
7. python -m tools.publisher_ownership status               8. python -m tools.publisher_ownership status
   -> role reader, feed owned by NEW                           -> role publisher, owner = NEW, epoch +1

If the OLD Mac is unreachable/dead: wait until its lease expires (20 min after its last publish) and run `claim` on NEW.
Before that, `claim` refuses; to override deliberately run:
   python -m tools.publisher_ownership claim --force-takeover --confirm-takeover-of <token printed by claim>
When OLD wakes up it refuses to publish (higher epoch), records `superseded`, and `release` on it only demotes it locally.
"""


def _fmt(health: dict) -> str:
    return json.dumps(health, indent=2)


def main(argv: list[str] | None = None) -> int:
    from tools import publish_observability as pub

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=["status", "claim", "release", "handover"])
    parser.add_argument("--repo", default=pub.DESTINATION)
    parser.add_argument("--state-dir", type=Path, default=pub.STATE_DIR)
    parser.add_argument("--config-dir", type=Path, default=None)
    parser.add_argument("--offline", action="store_true", help="status: do not look at the remote feed")
    parser.add_argument("--force-takeover", action="store_true")
    parser.add_argument("--confirm-takeover-of", default=None, metavar="TOKEN",
                        help="typed confirmation: the current owner's machine id, 'legacy' or 'corrupt'")
    args = parser.parse_args(argv)
    if args.repo != pub.DESTINATION:
        parser.error(f"Only {pub.DESTINATION} is allowed")
    try:
        if args.action == "handover":
            print(HANDOVER)
        elif args.action == "claim":
            print(claim(args.repo, state_dir=args.state_dir, config_dir=args.config_dir,
                        force_takeover=args.force_takeover, confirm=args.confirm_takeover_of))
        elif args.action == "release":
            print(release(args.repo, state_dir=args.state_dir, config_dir=args.config_dir))
        else:
            now = datetime.now(UTC)
            ident = mi.load_identity(args.config_dir)
            out = {"machine": ident.as_dict() if ident else None,
                   "local_ownership": pub.load_state(args.state_dir).get("ownership")}
            if not args.offline:
                kind, feed = fetch_remote_feed(args.repo)
                out["remote"] = {"read": kind}
                if kind == "ok" and isinstance(feed, dict):
                    d = decide(feed, ident, now, local_epoch=local_epoch(pub.load_state(args.state_dir)))
                    out["remote"].update(publisher=feed.get("publisher"), exported_at=feed.get("exported_at"),
                                         this_mac_would=d.action, because=d.reason)
                    try:
                        with pub.Lock(args.state_dir):
                            st = pub.load_state(args.state_dir)
                            record_remote_view(st, feed, now)
                            pub.save_state(args.state_dir, st)
                    except pub.PublishError:
                        pass
            out["feed_health"] = feed_health(args.state_dir, now, args.config_dir)
            print(_fmt(out))
    except (OwnershipError, mi.IdentityError, pub.PublishError, OSError, ValueError, OverflowError) as exc:
        print(f"publisher ownership: {str(exc)[:300]}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
