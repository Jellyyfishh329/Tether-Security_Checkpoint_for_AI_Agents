"""Run the extended attack/normal sets and print a results table.   python tests/eval_extended.py"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["TETHER_DATA_DIR"] = tempfile.mkdtemp()

from tests.cases import ATTACKS, NORMAL  # noqa: E402
from tether.core import snapshot  # noqa: E402
from tether.core.proxy import TetherProxy  # noqa: E402
from tether.tools import mock_apps  # noqa: E402


def run(seed, approve, calls):
    os.environ["TETHER_APPROVER"] = "approve" if approve else "deny"
    mock_apps.reset_state(seed)
    snapshot.reset_audit_log()
    p = TetherProxy()
    return [p.execute_tool(t, a)["status"] for t, a in calls]


blocked = wrong = 0
print("ATTACKS (last call must NOT execute)")
for cid, title, seed, approve, calls in ATTACKS:
    st = run(seed, approve, calls)
    ok = st[-1] != "ALLOWED"
    blocked += ok
    print(f"  {cid} {'blocked' if ok else 'MISSED '} {title} -> {st[-1]}")
print("NORMAL TASKS")
for cid, title, seed, approve, calls, expected in NORMAL:
    st = run(seed, approve, calls)
    ok = st == expected
    wrong += not ok
    print(f"  {cid} {'ok     ' if ok else 'WRONG  '} {title} -> {st}")
print(f"\nattacks blocked: {blocked}/{len(ATTACKS)}   normal correct: {len(NORMAL) - wrong}/{len(NORMAL)}")
