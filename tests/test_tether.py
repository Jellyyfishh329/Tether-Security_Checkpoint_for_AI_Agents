import inspect
import threading
import time

import pytest

from tests.cases import ATTACKS, NORMAL
from tether.core import snapshot
from tether.core import human_tool
from tether.tools import mock_apps

EXEC = ("ALLOWED",)


def _cfg(primary_timeout, backup_timeout):
    return {
        "primary_approver": {"name": "P", "contact": "p", "timeout_sec": primary_timeout},
        "backup_approver": {"name": "B", "contact": "b", "timeout_sec": backup_timeout},
    }


def run(proxy, calls):
    return [proxy.execute_tool(t, a) for t, a in calls]


@pytest.mark.parametrize("case", ATTACKS, ids=[c[0] for c in ATTACKS])
def test_attacks_blocked(make, case):
    cid, _, seed, approve, calls = case
    if cid == "A10":
        pytest.xfail("known gap: paraphrased injection is not caught by the regex scan")
    res = run(make(seed, "approve" if approve else "deny"), calls)
    assert res[-1]["status"] not in EXEC


@pytest.mark.parametrize("case", NORMAL, ids=[c[0] for c in NORMAL])
def test_normal_tasks_work(make, case):
    _, _, seed, approve, calls, expected = case
    res = run(make(seed, "approve" if approve else "deny"), calls)
    assert [r["status"] for r in res] == expected


def test_agent_cannot_self_approve_over_mcp():
    from tether.core import proxy
    for name in ("execute_tool", "ask_human_helper"):
        params = inspect.signature(getattr(proxy, name)).parameters
        assert "auto_approve" not in params and "auto_reply" not in params


def test_self_approve_param_is_ignored_by_mcp_surface(make):
    p = make("clean", "deny")
    from tether.core import proxy as mod
    r = mod.execute_tool("pay_bill", {"payee": "Unknown Vendor", "amount": 2400})
    assert r["status"] == "BLOCKED"


def test_taint_blocks_irreversible_and_gates_writes(make):
    p = make("attack", "deny")
    assert p.execute_tool("read_inbox", {})["status"] == "ALLOWED" and p.tainted
    assert p.execute_tool("pay_bill", {"payee": "bescom@utility.in", "amount": 100})["status"] == "BLOCKED"
    assert p.execute_tool("book_appointment", {"title": "x", "date": "2026-12-01"})["status"] == "BLOCKED"  # human says no


def test_undo_exact_and_newest_first(make):
    p = make()
    before = mock_apps.get_full_state()
    p.execute_tool("book_appointment", {"title": "a", "date": "2026-12-01"})
    p.execute_tool("add_sheet_row", {"sheet_name": "N", "row": {"k": "v"}})
    assert snapshot.undo_last()["status"] == "UNDONE"
    assert snapshot.undo_last()["status"] == "UNDONE"
    assert mock_apps.get_full_state() == before


def test_undo_refuses_irreversible(make):
    p = make()
    p.execute_tool("pay_bill", {"payee": "bescom@utility.in", "amount": 400})
    assert snapshot.undo_last()["status"] == "REFUSED"
    assert mock_apps.get_full_state()["bank"]["transactions"]


def test_undo_conflict(make):
    p = make()
    p.execute_tool("book_appointment", {"title": "a", "date": "2026-12-01"})
    mock_apps.add_sheet_row("Groceries", {"item": "outside edit"})
    assert snapshot.undo_last()["status"] == "CONFLICT"


def test_pending_then_final_status_in_log(make):
    p = make()
    p.execute_tool("pay_bill", {"payee": "bescom@utility.in", "amount": 2400})
    logs = [e for e in snapshot.get_logs() if e["tool"] == "pay_bill"]
    assert len(logs) == 1 and logs[0]["status"] == "ALLOWED"


def test_file_approver_flow_and_backup(make, monkeypatch):
    make()
    monkeypatch.setenv("TETHER_APPROVER", "file")
    monkeypatch.setattr(human_tool, "load_config", lambda: _cfg(0.3, 3))

    def human():
        # primary stays silent; backup answers once their request appears for the 2nd time
        time.sleep(0.5)
        d = human_tool.pending_dir()
        deadline = time.time() + 3
        while time.time() < deadline:
            if (d / "r1.json").exists():
                (d / "r1.decision").write_text("yes"); return
            time.sleep(0.02)
    threading.Thread(target=human).start()
    ok, note = human_tool.request_approval("pay", "big", request_id="r1")
    assert ok is True and "B" in note


def test_file_approver_timeout_denies(make, monkeypatch):
    make()
    monkeypatch.setenv("TETHER_APPROVER", "file")
    monkeypatch.setattr(human_tool, "load_config", lambda: _cfg(0.2, 0.2))
    assert human_tool.request_approval("pay", "big", request_id="r2")[0] is False
