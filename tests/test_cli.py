import json

from cc_context import cli
from cc_context import dump_source


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
