from cc_context import audit_source, desktop


def _patch(monkeypatch, audit_session, age):
    """resolve_session を fixture に固定し、age_seconds を決定値に固定 (wall-clock 非依存)。"""
    monkeypatch.delenv("CC_CONTEXT_STALE_SECONDS", raising=False)
    monkeypatch.delenv("COWORK_CONTEXT_SESSION_ID", raising=False)
    monkeypatch.setattr(audit_source, "resolve_session", lambda sid=None: audit_session)
    monkeypatch.setattr(audit_source, "age_seconds", lambda ts: age)


def test_get_current_usage_returns_contract(audit_session, monkeypatch):
    _patch(monkeypatch, audit_session, age=10)
    r = desktop.get_current_context_usage()
    assert r["session_id_kind"] == "cowork_local"
    assert r["context_window_used"] == 2 + 838 + 56544
    assert r["rate_limits"]["five_hour"]["used_percentage"] == 99.0
    assert "email_address" not in r  # PII 非混入
    assert r["status"] == "ok"


def test_status_stale_when_old_and_auto(audit_session, monkeypatch):
    _patch(monkeypatch, audit_session, age=99999)  # 既定しきい値 600 超
    r = desktop.get_current_context_usage()
    assert r["status"] == "stale"
    assert r["last_event_age_seconds"] == 99999
    assert "session_id" in r["status_note"]  # 自動選択 → session_id 誘導
    assert r["context_window_used"] == 2 + 838 + 56544  # 数値は withhold しない


def test_stale_note_differs_when_explicit(audit_session, monkeypatch):
    _patch(monkeypatch, audit_session, age=99999)
    r = desktop.get_current_context_usage(session_id="local_11111111-2222-3333-4444-555555555555")
    assert r["status"] == "stale"
    assert "自動選択" not in r["status_note"]  # 明示指定 → auto note ではない


def test_status_unknown_when_age_none(audit_session, monkeypatch):
    _patch(monkeypatch, audit_session, age=None)  # parse 不能
    assert desktop.get_current_context_usage()["status"] == "unknown"


def test_status_unknown_when_future(audit_session, monkeypatch):
    _patch(monkeypatch, audit_session, age=-50)  # 未来 ts / clock skew
    assert desktop.get_current_context_usage()["status"] == "unknown"


def test_status_ok_at_threshold_boundary(audit_session, monkeypatch):
    _patch(monkeypatch, audit_session, age=600)  # age == 既定しきい値 → ok (> 判定)
    assert desktop.get_current_context_usage()["status"] == "ok"


def test_invalid_env_threshold_falls_back_to_default(audit_session, monkeypatch):
    monkeypatch.setattr(audit_source, "resolve_session", lambda sid=None: audit_session)
    monkeypatch.setattr(audit_source, "age_seconds", lambda ts: 700)
    monkeypatch.setenv("CC_CONTEXT_STALE_SECONDS", "not-an-int")  # 既定 600 に fallback → 700>600 stale
    assert desktop.get_current_context_usage()["status"] == "stale"


def test_get_session_meta_excludes_pii(audit_session, monkeypatch):
    monkeypatch.setattr(audit_source, "resolve_session", lambda sid=None: audit_session)
    m = desktop.get_session_meta()
    assert m["model"] == "claude-opus-4-8"
    assert "cwd" not in m and "email_address" not in m


def test_get_context_history_sanitizes_read_error(audit_session, monkeypatch):
    """resolve 後の read で audit が消えた等の OSError は握り潰し、絶対パスを leak しない。"""
    monkeypatch.setattr(audit_source, "resolve_session", lambda sid=None: audit_session)

    def _boom(sdir, n):
        raise FileNotFoundError(f"{sdir}/audit.jsonl gone")  # 絶対パス入りの例外

    monkeypatch.setattr(audit_source, "result_history", _boom)
    r = desktop.get_context_history()
    assert "history" not in r
    assert r["source_file"] == "audit.jsonl"  # basename only
    assert str(audit_session) not in r["error"]  # 絶対パス非露出


def test_get_context_history_rejects_nonpositive_n(audit_session, monkeypatch):
    monkeypatch.setattr(audit_source, "resolve_session", lambda sid=None: audit_session)
    assert "error" in desktop.get_context_history(n=0)


def test_docstring_defines_the_number():
    d = desktop.get_current_context_usage.__doc__ or ""
    assert "input" in d and "billing" in d and "/context" in d  # 定義が docstring に内蔵
