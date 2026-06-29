import pytest

from cc_context import core


def test_normalize_model_strips_suffix():
    assert core.normalize_model("claude-opus-4-8[1m]") == "claude-opus-4-8"


def test_context_limit_known_and_fallback():
    assert core.context_limit_for("claude-opus-4-8") == 1000000
    assert core.context_limit_for("totally-unknown") == 1000000  # _fallback


def test_usage_to_contract_sums_input_only():
    c = core.usage_to_contract(
        {
            "input_tokens": 2,
            "cache_creation_input_tokens": 838,
            "cache_read_input_tokens": 56544,
            "output_tokens": 41,
        },
        "claude-opus-4-8",
    )
    assert c["context_window_used"] == 2 + 838 + 56544  # output 除外
    assert c["context_window_limit"] == 1000000
    assert c["usage_percentage"] == round((2 + 838 + 56544) / 1000000 * 100, 2)
    assert c["breakdown"]["output_tokens"] == 41
    assert c["model_normalized"] == "claude-opus-4-8"


def test_format_rate_window_human():
    w = core.format_rate_window(99, 1000 + 4228, "five_hour", 1000)
    assert w["resets_in_seconds"] == 4228
    assert w["resets_in_human"] == "1h10m"
    assert (
        core.format_rate_window(1, 500, "five_hour", 1000)["resets_in_human"]
        == "expired"
    )
    d = core.format_rate_window(50, 1000 + 100000, "seven_day", 1000)
    assert "d" in d["resets_in_human"] and d["resets_in_human"].endswith("h")


def test_validate_contract_raises_on_missing():
    with pytest.raises(core.ContractError):
        core.validate_contract({"usage_percentage": 5})  # 必須 key 欠落


# --- 第1層 共通化: attach_status (staleness/status の共有判定) -----------------

def _contract(age):
    """validate を通る最小 contract + 鮮度。"""
    return {
        "context_window_used": 100,
        "context_window_limit": 1000,
        "usage_percentage": 10.0,
        "model": "m",
        "breakdown": {},
        "last_event_age_seconds": age,
    }


def test_attach_status_ok_when_fresh():
    out = _contract(10)
    core.attach_status(out, auto_selected=True, threshold=600, stale_label="dump", precise_hint="HINT")
    assert out["status"] == "ok"
    assert "status_note" not in out  # ok は note なし


def test_attach_status_ok_at_boundary():
    out = _contract(600)  # age == threshold は ok ('>' 判定)
    core.attach_status(out, auto_selected=True, threshold=600, stale_label="dump", precise_hint="HINT")
    assert out["status"] == "ok"


def test_attach_status_stale_auto_uses_hint_and_label():
    out = _contract(99999)
    core.attach_status(out, auto_selected=True, threshold=600, stale_label="dump", precise_hint="HINT-X")
    assert out["status"] == "stale"
    assert "dump" in out["status_note"]  # source label が文言に反映
    assert "HINT-X" in out["status_note"]  # 自動選択時は precise_hint を案内
    assert "自動選択" in out["status_note"]


def test_attach_status_stale_explicit_omits_auto_hint():
    out = _contract(99999)
    core.attach_status(out, auto_selected=False, threshold=600, stale_label="audit", precise_hint="HINT-X")
    assert out["status"] == "stale"
    assert "自動選択" not in out["status_note"]  # 明示指定は auto note でない
    assert "HINT-X" not in out["status_note"]


def test_attach_status_unknown_when_age_none():
    out = _contract(None)
    core.attach_status(out, auto_selected=True, threshold=600, stale_label="dump", precise_hint="HINT")
    assert out["status"] == "unknown"


def test_attach_status_unknown_when_future():
    out = _contract(-50)  # 未来 ts / clock skew
    core.attach_status(out, auto_selected=True, threshold=600, stale_label="dump", precise_hint="HINT")
    assert out["status"] == "unknown"


# --- 共通オーケストレータ: build_current_usage (resolve→contract→status→validate) ---

class _FakeSource:
    """orchestrator の手続きを検証する最小 Source。"""
    session_id_kind = "fake"
    stale_label = "fake"
    precise_hint = "FAKE-HINT"

    def __init__(
        self,
        *,
        contract=None,
        raise_resolve=False,
        raise_contract=False,
        raise_fnf_in_contract=False,
        auto=True,
    ):
        self._contract = contract
        self._raise_resolve = raise_resolve
        self._raise_contract = raise_contract
        self._raise_fnf_in_contract = raise_fnf_in_contract
        self._auto = auto

    def resolve(self, session_id):
        if self._raise_resolve:
            raise FileNotFoundError("no source here")
        return "HANDLE", self._auto

    def source_file(self, handle):
        return "fake.json"

    def build_contract(self, handle, now_ts):
        if self._raise_contract:
            raise core.ContractError("bad shape")
        if self._raise_fnf_in_contract:
            # TOCTOU: resolve 後・読取時にファイルが消えた等。str(e) は絶対パスを含むので
            # message に載せない (privacy)。
            raise FileNotFoundError("/secret/abs/path/audit.jsonl")
        return dict(self._contract)


def test_build_current_usage_attaches_status_and_validates():
    src = _FakeSource(contract=_contract(10), auto=True)
    out = core.build_current_usage(src, None, now_ts=0)
    assert out["status"] == "ok"  # 手続き: status 付与済み


def test_build_current_usage_resolve_error_returns_error():
    src = _FakeSource(raise_resolve=True)
    out = core.build_current_usage(src, None, now_ts=0)
    assert out == {"error": "no source here"}  # FileNotFoundError → error dict


def test_build_current_usage_contract_error_includes_source_file():
    src = _FakeSource(raise_contract=True)
    out = core.build_current_usage(src, None, now_ts=0)
    assert "schema" in out["error"].lower()  # fail-loud
    assert out["source_file"] == "fake.json"


def test_build_current_usage_passes_through_terminal_incomplete():
    src = _FakeSource(contract={"status": "incomplete", "reason": "x"})
    out = core.build_current_usage(src, None, now_ts=0)
    assert out["status"] == "incomplete"  # terminal はそのまま返す (status 上書きしない)


def test_build_current_usage_passes_through_terminal_error():
    src = _FakeSource(contract={"error": "No assistant event", "session_id": "s"})
    out = core.build_current_usage(src, None, now_ts=0)
    assert out == {"error": "No assistant event", "session_id": "s"}


def test_build_current_usage_explicit_session_yields_explicit_note():
    src = _FakeSource(contract=_contract(99999), auto=False)
    out = core.build_current_usage(src, "local_x", now_ts=0)
    assert out["status"] == "stale"
    assert "自動選択" not in out["status_note"]  # auto=False が note に反映


def test_build_current_usage_catches_toctou_filenotfound():
    """resolve 後・build_contract 中にソースが消えても MCP 例外でなく error dict を返す。"""
    src = _FakeSource(raise_fnf_in_contract=True)
    out = core.build_current_usage(src, None, now_ts=0)
    assert "error" in out
    assert out["source_file"] == "fake.json"
    assert "/secret/abs/path" not in out["error"]  # 絶対パスを error に載せない (privacy)
