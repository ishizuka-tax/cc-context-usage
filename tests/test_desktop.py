from cc_context import audit_source, desktop


def test_get_current_usage_returns_contract(audit_session, monkeypatch):
    monkeypatch.setattr(audit_source, "resolve_session", lambda sid=None: audit_session)
    r = desktop.get_current_context_usage()
    assert r["session_id_kind"] == "cowork_local"
    assert r["context_window_used"] == 2 + 838 + 56544
    assert r["rate_limits"]["five_hour"]["used_percentage"] == 99.0
    assert "email_address" not in r  # PII 非混入


def test_get_session_meta_excludes_pii(audit_session, monkeypatch):
    monkeypatch.setattr(audit_source, "resolve_session", lambda sid=None: audit_session)
    m = desktop.get_session_meta()
    assert m["model"] == "claude-opus-4-8"
    assert "cwd" not in m and "email_address" not in m


def test_docstring_defines_the_number():
    d = desktop.get_current_context_usage.__doc__ or ""
    assert "input" in d and "billing" in d and "/context" in d  # 定義が docstring に内蔵
