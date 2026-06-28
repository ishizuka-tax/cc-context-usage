import pytest

from cc_context import audit_source as a


def test_latest_assistant_usage(audit_session):
    usage, model = a.latest_assistant_usage(audit_session)
    assert model == "claude-opus-4-8"
    assert usage["cache_read_input_tokens"] == 56544


def test_latest_rate_limits_cowork_schema(audit_session):
    rl = a.latest_rate_limits(audit_session)
    assert rl["five_hour"]["used_percentage"] == 99.0
    assert rl["five_hour"]["resets_in_human"]  # 整形済


def test_session_meta_excludes_pii(audit_session):
    meta = a.session_meta(audit_session)
    for pii in (
        "email_address",
        "account_name",
        "cwd",
        "process_name",
        "vm_process_name",
        "space_id",
        "emailAddress",
    ):
        assert pii not in meta
    assert meta["model"] == "claude-opus-4-8"


def test_resolve_session_rejects_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr(a, "BASE_DIR", tmp_path)
    with pytest.raises(FileNotFoundError):
        a.resolve_session("../etc/passwd")
