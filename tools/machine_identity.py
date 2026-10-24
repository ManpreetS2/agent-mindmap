"""This Mac's anonymous identity: a random id, an owner-chosen label and a role (publisher | reader).

  python -m tools.machine_identity show
  python -m tools.machine_identity init --label "Mac A"        # role starts as reader; never publishes
  python -m tools.machine_identity set-role publisher           # prefer `python -m tools.publisher_ownership claim`

The id is `mac-` + 8 random hex digits. It is never derived from the hostname, username, MAC address or hardware,
and the file lives in `~/.config/agent-mindmap/machine.json` (override: env AGENT_MINDMAP_CONFIG_DIR), directory 0700,
file 0600. An existing identity is never regenerated: a corrupt file is an error, not a silent new id.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import secrets
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

ROLES = ("publisher", "reader")
LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,31}$")
ID_RE = re.compile(r"^mac-[0-9a-f]{8}$")
FILE_NAME = "machine.json"


class IdentityError(RuntimeError):
    pass


@dataclass(frozen=True)
class MachineIdentity:
    id: str
    label: str
    role: str
    platform: str

    def as_dict(self) -> dict:
        return asdict(self)


def config_dir(override: Path | str | None = None) -> Path:
    if override:
        return Path(override)
    env = os.environ.get("AGENT_MINDMAP_CONFIG_DIR")
    return Path(env) if env else Path.home() / ".config" / "agent-mindmap"


def platform_tag() -> str:
    system = {"darwin": "darwin", "linux": "linux", "win32": "windows"}.get(sys.platform, sys.platform)
    return f"{system}-{platform.machine() or 'unknown'}"


def validate_label(label: str) -> str:
    """Owner-chosen and published: keep it short and boring, never a path, hostname-like secret or token."""
    from tools.publish_observability import scan_for_sensitive  # lazy: avoids an import cycle at module load

    if not isinstance(label, str) or not LABEL_RE.match(label.strip()) or scan_for_sensitive(label):
        raise IdentityError("Label must be 1-32 characters: letters, digits, space, dot, dash or underscore (e.g. 'Mac A')")
    return label.strip()


def _write(directory: Path, data: dict) -> None:
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    fd, temp = tempfile.mkstemp(prefix=".machine-", dir=directory)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(temp, directory / FILE_NAME)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def load_identity(config_dir_: Path | str | None = None) -> MachineIdentity | None:
    """None until initialised. A present but unreadable/invalid file raises IdentityError (fail closed)."""
    path = config_dir(config_dir_) / FILE_NAME
    if not path.exists() and not path.is_symlink():
        return None
    if path.is_symlink() or not path.is_file():
        raise IdentityError("machine.json must be a regular file")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        ident = MachineIdentity(id=data["id"], label=data["label"], role=data["role"], platform=data["platform"])
    except (OSError, ValueError, KeyError, TypeError):
        raise IdentityError("machine.json is unreadable or incomplete; fix or remove it deliberately") from None
    if not ID_RE.match(str(ident.id)) or ident.role not in ROLES or not isinstance(ident.label, str):
        raise IdentityError("machine.json has an invalid id or role")
    return ident


def init_identity(label: str, role: str = "reader", config_dir_: Path | str | None = None) -> MachineIdentity:
    """Create the identity once. If one exists it is returned unchanged (id, label and role are never reset here)."""
    existing = load_identity(config_dir_)
    if existing is not None:
        return existing
    if role not in ROLES:
        raise IdentityError("role must be 'publisher' or 'reader'")
    ident = MachineIdentity(id="mac-" + secrets.token_hex(4), label=validate_label(label), role=role,
                            platform=platform_tag())
    data = ident.as_dict() | {"created_at": datetime.now(UTC).isoformat()}
    _write(config_dir(config_dir_), data)
    return ident


def _update(config_dir_: Path | str | None, **changes) -> MachineIdentity:
    current = load_identity(config_dir_)
    if current is None:
        raise IdentityError("This Mac has no identity yet: run `python -m tools.machine_identity init --label <name>`")
    path = config_dir(config_dir_) / FILE_NAME
    data = json.loads(path.read_text(encoding="utf-8")) | changes
    _write(config_dir(config_dir_), data)
    return load_identity(config_dir_)  # type: ignore[return-value]


def set_role(role: str, config_dir_: Path | str | None = None) -> MachineIdentity:
    if role not in ROLES:
        raise IdentityError("role must be 'publisher' or 'reader'")
    return _update(config_dir_, role=role)


def set_label(label: str, config_dir_: Path | str | None = None) -> MachineIdentity:
    return _update(config_dir_, label=validate_label(label))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("show")
    p = sub.add_parser("init")
    p.add_argument("--label", required=True)
    p.add_argument("--role", choices=ROLES, default="reader")
    r = sub.add_parser("set-role")
    r.add_argument("role", choices=ROLES)
    args = parser.parse_args(argv)
    try:
        if args.action == "show":
            ident = load_identity()
            print(json.dumps(ident.as_dict(), indent=2) if ident else "not initialised (run: init --label <name>)")
        elif args.action == "init":
            print(json.dumps(init_identity(args.label, args.role).as_dict(), indent=2))
        else:
            print(json.dumps(set_role(args.role).as_dict(), indent=2))
    except IdentityError as exc:
        print(f"machine identity: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
