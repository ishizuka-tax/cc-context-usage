import json
from pathlib import Path

import pytest

from cc_context import audit_source as a


def _write_results(tmp_path: Path, events: list[dict]) -> Path:
    """result event を渡された順 (= 古い順、末尾が最新) で audit.jsonl に書き、session dir を返す。"""
    base = tmp_path / "ws" / "acct" / "local_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    base.mkdir(parents=True)
    lines = [{"type": "result", **ev} for ev in events]
    (base / "audit.jsonl").write_text(
        "\n".join(json.dumps(o) for o in lines) + "\n", encoding="utf-8"
    )
    return base


def _iter_usage(cache_read: int) -> dict:
    return {"input_tokens": 2, "cache_creation_input_tokens": 100, "cache_read_input_tokens": cache_read, "output_tokens": 50}


def test_result_history_uses_iterations_last(tmp_path):
    sess = _write_results(tmp_path, [
        {"is_error": False, "_audit_timestamp": "2026-06-28T08:00:00Z",
         "usage": {"iterations": [_iter_usage(1000), _iter_usage(5000)]}},
    ])
    hist = a.result_history(sess, 10)
    assert len(hist) == 1
    assert hist[0]["source"] == "iterations[-1]"
    assert hist[0]["context_window_size"] == 2 + 100 + 5000  # iterations[-1] のみ


def test_result_history_falls_back_to_top_level_usage(tmp_path):
    sess = _write_results(tmp_path, [
        {"is_error": False, "_audit_timestamp": "2026-06-28T08:00:00Z", "usage": _iter_usage(6000)},
    ])
    hist = a.result_history(sess, 10)
    assert len(hist) == 1
    assert hist[0]["source"] == "usage (fallback)"
    assert hist[0]["context_window_size"] == 2 + 100 + 6000


def test_result_history_excludes_empty_measurement_rows(tmp_path):
    """iterations も top-level usage tokens も無い result event は計測値ではないので除外。"""
    sess = _write_results(tmp_path, [
        {"is_error": False, "_audit_timestamp": "2026-06-28T08:00:00Z", "usage": {}},
        {"is_error": False, "_audit_timestamp": "2026-06-28T08:01:00Z"},  # usage キーすら無い
    ])
    hist = a.result_history(sess, 10)
    assert hist == []


def test_result_history_excludes_error_rows(tmp_path):
    """is_error の result event は実測があっても spike 推移のノイズなので除外。"""
    sess = _write_results(tmp_path, [
        {"is_error": True, "_audit_timestamp": "2026-06-29T04:25:00Z", "usage": _iter_usage(7000)},
    ])
    hist = a.result_history(sess, 10)
    assert hist == []


def test_result_history_fills_n_with_valid_skipping_noise(tmp_path):
    """空・error 行を飛ばし、有効な計測値で n を満たす (newest-first)。"""
    sess = _write_results(tmp_path, [
        {"is_error": False, "_audit_timestamp": "t1", "usage": _iter_usage(1111)},  # 最古
        {"is_error": False, "_audit_timestamp": "t2", "usage": {}},                  # 空
        {"is_error": False, "_audit_timestamp": "t3", "usage": _iter_usage(3333)},
        {"is_error": True,  "_audit_timestamp": "t4", "usage": _iter_usage(4444)},   # error
        {"is_error": False, "_audit_timestamp": "t5", "usage": _iter_usage(5555)},   # 最新
    ])
    hist = a.result_history(sess, 2)
    assert [h["ts"] for h in hist] == ["t5", "t3"]  # 最新2件の有効値、空/error はスキップ
    assert all(h["context_window_size"] > 0 for h in hist)


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
