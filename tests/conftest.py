import json
from pathlib import Path

import pytest


@pytest.fixture
def audit_session(tmp_path: Path) -> Path:
    """合成 audit.jsonl を持つ session ディレクトリ (Desktop source 用)。"""
    base = tmp_path / "ws" / "acct" / "local_11111111-2222-3333-4444-555555555555"
    base.mkdir(parents=True)
    lines = [
        {
            "type": "assistant",
            "session_id": base.name,
            "_audit_timestamp": "2026-06-27T06:00:00Z",
            "message": {
                "model": "claude-opus-4-8",
                "usage": {
                    "input_tokens": 2,
                    "cache_creation_input_tokens": 838,
                    "cache_read_input_tokens": 56544,
                    "output_tokens": 41,
                },
            },
        },
        {
            "type": "rate_limit_event",
            "rate_limit_info": {
                "rateLimitType": "five_hour",
                "utilization": 0.99,
                "resetsAt": 9999999999,
                "status": "allowed_warning",
            },
        },
    ]
    (base / "audit.jsonl").write_text(
        "\n".join(json.dumps(o) for o in lines) + "\n", encoding="utf-8"
    )
    (base.parent / f"{base.name}.json").write_text(
        json.dumps(
            {
                "sessionId": base.name,
                "model": "claude-opus-4-8",
                "title": "t",
                "createdAt": 1750000000000,
                "emailAddress": "SECRET@example.com",
                "cwd": "/secret",
            }
        ),
        encoding="utf-8",
    )
    return base


@pytest.fixture
def dump_file(tmp_path: Path) -> Path:
    """合成 statusLine dump (CLI source 用)。"""
    p = tmp_path / "cc-context-local_abc.json"
    p.write_text(
        json.dumps(
            {
                "session_id": "local_abc",
                "model": {"display_name": "Opus 4.8 (1M)", "id": "claude-opus-4-8[1m]"},
                "context_window": {
                    "context_window_size": 1000000,
                    "used_percentage": 5.74,
                    "remaining_percentage": 94.26,
                    "total_input_tokens": 57384,
                    "current_usage": {
                        "input_tokens": 2,
                        "cache_creation_input_tokens": 838,
                        "cache_read_input_tokens": 56544,
                        "output_tokens": 41,
                    },
                },
                "rate_limits": {
                    "five_hour": {"used_percentage": 99, "resets_at": 9999999999}
                },
            }
        ),
        encoding="utf-8",
    )
    return p
