import json

import pytest

from cc_context import core
from cc_context import dump_source as d


def test_dump_to_contract(dump_file):
    raw = d.read_dump(dump_file)
    c = d.dump_to_contract(raw, now_ts=0)
    assert c["session_id_kind"] == "claude_code_cli"
    assert c["context_window_used"] == 57384
    assert c["usage_percentage"] == 5.74
    assert c["rate_limits"]["five_hour"]["used_percentage"] == 99


def test_incomplete_when_usage_null(tmp_path):
    p = tmp_path / "cc-context-x.json"
    p.write_text(
        json.dumps(
            {
                "session_id": "local_x",
                "model": {"display_name": "m"},
                "context_window": {"used_percentage": None, "current_usage": None},
            }
        ),
        encoding="utf-8",
    )
    c = d.dump_to_contract(d.read_dump(p), now_ts=0)
    assert c["status"] == "incomplete"


def test_schema_mismatch_raises(tmp_path):
    p = tmp_path / "cc-context-y.json"
    p.write_text(
        json.dumps({"session_id": "local_y", "totally": "different"}), encoding="utf-8"
    )
    with pytest.raises(core.ContractError):
        d.dump_to_contract(d.read_dump(p), now_ts=0)
