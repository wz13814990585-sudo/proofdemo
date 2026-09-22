"""Tests for deterministic diagnostic redaction."""

from proofdemo.security import sanitize_diagnostic_text


def test_diagnostic_redaction_removes_common_secret_shapes() -> None:
    raw = (
        "authorization=Bearer abc.def password=hunter2 "
        "api_key=sk-example https://alice:secret@example.test/path"
    )

    sanitized = sanitize_diagnostic_text(raw)

    assert "abc.def" not in sanitized
    assert "hunter2" not in sanitized
    assert "sk-example" not in sanitized
    assert "alice" not in sanitized
    assert "secret@example" not in sanitized
    assert sanitized.count("[REDACTED]") >= 4


def test_diagnostic_redaction_bounds_message_length() -> None:
    assert len(sanitize_diagnostic_text("x" * 10_000)) == 2_000
