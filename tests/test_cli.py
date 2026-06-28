import json
import os

from cc_context import cli
from cc_context import dump_source


def _write_dump(d, session_id, pct):
    """指定 session_id / used_percentage の合成 dump を dir d に書き、Path を返す。"""
    p = d / f"cc-context-{session_id}.json"
    p.write_text(
        json.dumps(
            {
                "session_id": session_id,
                "model": {"display_name": "Opus 4.8 (1M)", "id": "claude-opus-4-8[1m]"},
                "context_window": {
                    "context_window_size": 1000000,
                    "used_percentage": pct,
                    "remaining_percentage": 100 - pct,
                    "total_input_tokens": 57384,
                    "current_usage": {
                        "input_tokens": 2,
                        "cache_creation_input_tokens": 838,
                        "cache_read_input_tokens": 56544,
                        "output_tokens": 41,
                    },
                },
                "rate_limits": {},
            }
        ),
        encoding="utf-8",
    )
    return p


def test_cli_honors_session_id_not_just_latest(tmp_path, monkeypatch):
    """明示 session_id を尊重: 別セッションの新しい dump があっても指定 dump を返す。"""
    monkeypatch.setenv("CLAUDE_CONTEXT_DUMP_DIR", str(tmp_path))
    target = _write_dump(tmp_path, "local_aaa", 11.0)
    newer = _write_dump(tmp_path, "local_bbb", 22.0)  # 後から書いた=mtime 新しい
    os.utime(newer, None)
    r = cli.get_current_context_usage(session_id="local_aaa")
    assert r["session_id"] == "local_aaa"
    assert r["usage_percentage"] == 11.0  # latest(bbb=22.0) でなく指定 aaa


def test_cli_happy_path_has_status_ok(tmp_path, monkeypatch):
    """成功時も Desktop と同形に status を持つ (fresh dump → ok)。"""
    monkeypatch.setenv("CLAUDE_CONTEXT_DUMP_DIR", str(tmp_path))
    _write_dump(tmp_path, "local_aaa", 5.74)
    r = cli.get_current_context_usage(session_id="local_aaa")
    assert r["status"] == "ok"
    assert "last_event_age_seconds" in r


def test_cli_stale_when_dump_old(tmp_path, monkeypatch):
    """古い dump (mtime 過去) は黙って返さず status=stale。"""
    monkeypatch.setenv("CLAUDE_CONTEXT_DUMP_DIR", str(tmp_path))
    monkeypatch.delenv("CC_CONTEXT_STALE_SECONDS", raising=False)
    p = _write_dump(tmp_path, "local_aaa", 5.74)
    import time as _t
    old = _t.time() - 99999
    os.utime(p, (old, old))
    r = cli.get_current_context_usage(session_id="local_aaa")
    assert r["status"] == "stale"
    assert r["last_event_age_seconds"] > 600


def test_cli_unknown_session_id_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONTEXT_DUMP_DIR", str(tmp_path))
    r = cli.get_current_context_usage(session_id="local_nope")
    assert "error" in r


def test_cli_current_usage(dump_file, monkeypatch):
    monkeypatch.setattr(dump_source, "find_latest_dump", lambda dump_dir=None: dump_file)
    r = cli.get_current_context_usage()
    assert r["session_id_kind"] == "claude_code_cli"
    assert r["usage_percentage"] == 5.74


def test_cli_schema_mismatch_is_hard_error(tmp_path, monkeypatch):
    p = tmp_path / "cc-context-z.json"
    p.write_text(json.dumps({"session_id": "local_z", "bogus": 1}), encoding="utf-8")
    monkeypatch.setattr(dump_source, "find_latest_dump", lambda dump_dir=None: p)
    r = cli.get_current_context_usage()
    assert "error" in r and "schema" in r["error"].lower()  # fail-loud (沈黙の誤値でない)


def test_cli_no_dump(monkeypatch):
    monkeypatch.setattr(dump_source, "find_latest_dump", lambda dump_dir=None: None)
    assert "error" in cli.get_current_context_usage()
