"""Machine identity: random id, reader by default, 0700/0600, never derived from the host, never silently regenerated."""
import json
import os
import re
import socket
import stat
import getpass

import pytest

from tools import machine_identity as mi


def test_new_identity_is_a_random_reader_with_private_permissions(tmp_path):
    cfg = tmp_path / "cfg dir"                                   # a space in the path must work
    assert mi.load_identity(cfg) is None
    ident = mi.init_identity("Mac A", config_dir_=cfg)
    assert re.fullmatch(r"mac-[0-9a-f]{8}", ident.id) and ident.role == "reader" and ident.label == "Mac A"
    assert stat.S_IMODE(cfg.stat().st_mode) == 0o700
    assert stat.S_IMODE((cfg / "machine.json").stat().st_mode) == 0o600
    assert mi.load_identity(cfg) == ident


def test_id_is_not_derived_from_host_user_or_hardware(tmp_path):
    ids = {mi.init_identity("Mac", config_dir_=tmp_path / str(i)).id for i in range(20)}
    assert len(ids) == 20                                           # random each time
    blob = " ".join(ids) + json.dumps(json.loads((tmp_path / "0" / "machine.json").read_text()))
    for secret in (socket.gethostname(), getpass.getuser(), str(tmp_path)):
        assert secret.lower() not in blob.lower() or len(secret) < 4


def test_existing_identity_is_never_regenerated_or_demoted(tmp_path):
    first = mi.init_identity("Mac A", "publisher", tmp_path)
    again = mi.init_identity("Other", "reader", tmp_path)
    assert again == first
    assert mi.set_role("reader", tmp_path).id == first.id


def test_env_override_selects_the_config_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_MINDMAP_CONFIG_DIR", str(tmp_path / "from env"))
    ident = mi.init_identity("Mac A")
    assert (tmp_path / "from env" / "machine.json").is_file()
    assert mi.load_identity() == ident


@pytest.mark.parametrize("bad", ["", "x" * 40, "/Users/someone", "a\nb", "token=ghp_" + "a" * 30])
def test_labels_must_be_short_and_non_identifying(tmp_path, bad):
    with pytest.raises(mi.IdentityError):
        mi.init_identity(bad, config_dir_=tmp_path)
    assert mi.load_identity(tmp_path) is None


@pytest.mark.parametrize("content", ["not json", '{"id":"mac-zz","label":"x","role":"reader","platform":"p"}',
                                     '{"id":"mac-0123abcd","label":"x","role":"boss","platform":"p"}', "[]"])
def test_corrupt_identity_fails_closed_not_regenerated(tmp_path, content):
    (tmp_path).mkdir(exist_ok=True)
    (tmp_path / "machine.json").write_text(content)
    with pytest.raises(mi.IdentityError):
        mi.load_identity(tmp_path)
    with pytest.raises(mi.IdentityError):
        mi.init_identity("Mac A", config_dir_=tmp_path)


def test_symlinked_identity_file_is_refused(tmp_path):
    real = tmp_path / "real.json"
    real.write_text("{}")
    (tmp_path / "machine.json").symlink_to(real)
    with pytest.raises(mi.IdentityError):
        mi.load_identity(tmp_path)


def test_set_role_requires_an_identity_and_a_valid_role(tmp_path):
    with pytest.raises(mi.IdentityError):
        mi.set_role("publisher", tmp_path)
    mi.init_identity("Mac A", config_dir_=tmp_path)
    with pytest.raises(mi.IdentityError):
        mi.set_role("admin", tmp_path)
    assert mi.set_role("publisher", tmp_path).role == "publisher"
    assert stat.S_IMODE(os.stat(tmp_path / "machine.json").st_mode) == 0o600


def test_cli_show_and_init(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AGENT_MINDMAP_CONFIG_DIR", str(tmp_path))
    assert mi.main(["show"]) == 0 and "not initialised" in capsys.readouterr().out
    assert mi.main(["init", "--label", "Mac B"]) == 0
    assert json.loads(capsys.readouterr().out)["role"] == "reader"
    monkeypatch.setenv("AGENT_MINDMAP_CONFIG_DIR", str(tmp_path / "second"))
    assert mi.main(["init", "--label", "bad/label"]) == 1
