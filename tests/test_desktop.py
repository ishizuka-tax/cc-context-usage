import datetime
import json

from cc_context import audit_source, desktop


def test_get_current_usage_returns_contract(audit_session, monkeypatch):
    monkeypatch.setattr(audit_source, "resolve_session", lambda sid=None: audit_session)
    r = desktop.get_current_context_usage()
    assert r["session_id_kind"] == "cowork_local"
    assert r["context_window_used"] == 2 + 838 + 56544
    assert r["rate_limits"]["five_hour"]["used_percentage"] == 99.0
    assert "email_address" not in r  # PII 非混入


def test_staleness_flag_stale_for_old_audit(audit_session, monkeypatch):
    # fixture の assistant ts は 2026-06-27（古い）→ stale。ただし数値は返す。
    monkeypatch.setattr(audit_source, "resolve_session", lambda sid=None: audit_session)
    r = desktop.get_current_context_usage()
    assert r["status"] == "stale"
    assert r["last_event_age_seconds"] > 0
    assert r["context_window_used"] == 2 + 838 + 56544  # 数値は withhold しない


def test_staleness_flag_ok_for_fresh_audit(audit_session, monkeypatch):
    fresh = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    audit = audit_session / "audit.jsonl"
    objs = [json.loads(line) for line in audit.read_text().splitlines()]
    for o in objs:
        if o.get("type") == "assistant":
            o["_audit_timestamp"] = fresh
    audit.write_text("\n".join(json.dumps(o) for o in objs) + "\n", encoding="utf-8")
    monkeypatch.setattr(audit_source, "resolve_session", lambda sid=None: audit_session)
    r = desktop.get_current_context_usage()
    assert r["status"] == "ok"


def test_get_session_meta_excludes_pii(audit_session, monkeypatch):
    monkeypatch.setattr(audit_source, "resolve_session", lambda sid=None: audit_session)
    m = desktop.get_session_meta()
    assert m["model"] == "claude-opus-4-8"
    assert "cwd" not in m and "email_address" not in m


def test_docstring_defines_the_number():
    d = desktop.get_current_context_usage.__doc__ or ""
    assert "input" in d and "billing" in d and "/context" in d  # 定義が docstring に内蔵
