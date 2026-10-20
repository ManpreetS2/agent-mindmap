"""SEC-MM020c: shared tools.secret_scan denylist."""

from __future__ import annotations

from tools.secret_scan import find_secrets, looks_like_secret, secret_kinds


def test_public_api_and_kinds() -> None:
    kinds = secret_kinds()
    assert "sk" in kinds
    assert "github_token" in kinds
    assert "email" in kinds
    assert looks_like_secret("") is False
    assert find_secrets("") == []


def test_sec_mm020c1_sk_case_sensitive_and_benign_passes() -> None:
    """SEC-MM020c-1 / QA-MM020c-2: case-sensitive sk-; false-positive phrases pass."""
    for benign in (
        "task-runner",
        "risk-based",
        "ask-me",
        "desk-top",
        "desk-lamp",
        "Mask-RCNN",
    ):
        assert looks_like_secret(benign) is False, benign
        assert find_secrets(benign) == []
        assert looks_like_secret(f"please use the {benign} approach") is False

    # Uppercase SK- must not match (case-sensitive).
    upper = "SK-proj-abcdefghijklmnopqrstuvwxyz12"
    assert looks_like_secret(upper) is False
    assert "sk" not in find_secrets(upper)

    # Real-looking sk- key (≥20 chars after sk-) is refused.
    real = "sk-proj-abcdefghijklmnopqrstuvwxyz1234567890ABCDEF"
    assert looks_like_secret(real) is True
    assert find_secrets(real) == ["sk"]
    assert looks_like_secret(f"key={real}") is True

    # Too short after sk- → not a hit.
    short = "sk-proj-abcdefghij"  # fewer than 20 after sk-
    assert looks_like_secret(short) is False


def test_sec_mm0101_and_qa_patterns() -> None:
    samples = {
        "github_token": "token ghp_abcdefghijklmnopqrstuvwxyz1234567890AB",
        "github_pat": "token github_pat_abcdefghijklmnopqrstuvwxyz",
        "bearer": "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abc.def",
        "sk": "sk-proj-abcdefghijklmnopqrstuvwxyz1234567890ABCDEF",
        "akia": "AKIAIOSFODNN7EXAMPLE",
        "jwt": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0In0.signature",
        "private_key": (
            "-----BEGIN PRIVATE KEY----- MIIEvQIBADANBg -----END PRIVATE KEY-----"
        ),
        "email": "contact alice@example.com please",
    }
    for kind, sample in samples.items():
        assert looks_like_secret(sample), kind
        kinds = find_secrets(sample)
        assert kind in kinds, (kind, kinds)
        # Never return the secret material itself.
        assert sample not in kinds
