import pytest

from cc_context import audit_source as a


def test_latest_assistant_usage(audit_session):
    usage, model, ts = a.latest_assistant_usage(audit_session)
    assert model == "claude-opus-4-8"
    assert usage["cache_read_input_tokens"] == 56544
    assert ts == "2026-06-27T06:00:00Z"


def test_age_seconds_parses_and_handles_garbage():
    assert a.age_seconds("2000-01-01T00:00:00Z") > 0  # 過去 → 正の経過秒
    assert a.age_seconds(None) is None
    assert a.age_seconds("not-a-timestamp") is None
    assert a.age_seconds(12345) is None  # 非 str (malformed audit) → None、crash しない


def test_resolve_session_error_has_no_absolute_path(tmp_path, monkeypatch):
    monkeypatch.setattr(a, "BASE_DIR", tmp_path / "nope")
    monkeypatch.delenv("COWORK_CONTEXT_SESSION_ID", raising=False)
    with pytest.raises(FileNotFoundError) as ei:
        a.resolve_session(None)
    assert str(tmp_path) not in str(ei.value)  # 絶対パス非露出


def test_session_meta_error_has_no_absolute_path(tmp_path):
    sess = tmp_path / "ws" / "acct" / "local_99999999-0000-0000-0000-000000000000"
    sess.mkdir(parents=True)
    (sess / "audit.jsonl").write_text("", encoding="utf-8")  # local_*.json 不在
    meta = a.session_meta(sess)
    assert "error" in meta
    assert str(tmp_path) not in meta["error"]  # 絶対パス非露出


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
