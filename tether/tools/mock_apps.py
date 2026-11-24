"""JSON-backed mock family apps.

The state lives in ``data/app_state.json`` so it can be snapshotted and restored
by :mod:`tether.core.snapshot`. Every public function returns a JSON-safe dict
and raises ``ValueError`` for invalid input. This module is deliberately the
only place that knows how mock state is stored; a real backend (SQLite, Google
Calendar, Gmail, a bank API, or real MCP servers) can replace it behind the same
tool registry without changing the policy or proxy layers.
"""

from __future__ import annotations

import copy
import json
import math
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
STATE_PATH = DATA_DIR / "app_state.json"

_LOCK = threading.RLock()


def _now() -> str:
    """Return an ISO-8601 UTC timestamp."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _default_state() -> dict[str, Any]:
    """Create the seeded state used by the demo and benchmark."""
    return {
        "calendar": [
            {
                "title": "Dr. Sharma follow-up",
                "date": "2026-11-28",
                "created_at": "2026-11-20T09:00:00+00:00",
            },
            {
                "title": "Physiotherapy session",
                "date": "2026-11-30",
                "created_at": "2026-11-20T09:05:00+00:00",
            },
        ],
        "sheets": {
            "Groceries": [
                {"item": "Rice", "qty": 5, "status": "bought"},
                {"item": "Milk", "qty": 2, "status": "needed"},
            ],
            "Medicines": [
                {"item": "Metformin 500mg", "qty": 30, "status": "pending"},
            ],
        },
        "drafts": [
            {
                "to": "priya@family.com",
                "subject": "Sunday lunch",
                "body": "Please join us for lunch at 1pm. Grandmother is cooking.",
                "sent": False,
                "created_at": "2026-11-21T08:30:00+00:00",
            }
        ],
        "bank": {
            "balance": 5000.0,
            "currency": "INR",
            "transactions": [],
        },
    }


def _normalise_state(state: Any) -> dict[str, Any]:
    """Validate that a restored/snapshotted state has the expected top-level shape."""
    if not isinstance(state, dict):
        raise TypeError("State must be a JSON object")
    defaults = _default_state()
    merged = copy.deepcopy(defaults)
    merged.update(copy.deepcopy(state))
    if not isinstance(merged.get("calendar"), list):
        raise ValueError("State field 'calendar' must be a list")
    if not isinstance(merged.get("sheets"), dict):
        raise ValueError("State field 'sheets' must be an object")
    if not isinstance(merged.get("drafts"), list):
        raise ValueError("State field 'drafts' must be a list")
    if not isinstance(merged.get("bank"), dict):
        raise ValueError("State field 'bank' must be an object")
    return merged


def _read_state_unlocked() -> dict[str, Any]:
    """Read state while the caller holds ``_LOCK``, seeding it on first use."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not STATE_PATH.exists():
        state = _default_state()
        _write_state_unlocked(state)
        return state
    try:
        raw = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Corrupt mock state at {STATE_PATH}: {exc}") from exc
    return _normalise_state(raw)


def _write_state_unlocked(state: dict[str, Any]) -> None:
    """Atomically write state while the caller holds ``_LOCK``."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = STATE_PATH.with_suffix(".json.tmp")
    payload = json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True)
    tmp_path.write_text(payload + "\n", encoding="utf-8")
    os.replace(tmp_path, STATE_PATH)


def get_full_state() -> dict[str, Any]:
    """Return a deep copy of the complete mock-app state."""
    with _LOCK:
        return copy.deepcopy(_read_state_unlocked())


def restore_full_state(state: dict[str, Any]) -> dict[str, Any]:
    """Replace the mock-app state with a previously captured snapshot."""
    restored = _normalise_state(copy.deepcopy(state))
    with _LOCK:
        _write_state_unlocked(restored)
    return copy.deepcopy(restored)


def reset_state() -> dict[str, Any]:
    """Reset to the seeded demo state (used by the benchmark)."""
    state = _default_state()
    with _LOCK:
        _write_state_unlocked(state)
    return copy.deepcopy(state)


def book_appointment(title: str, date: str) -> dict[str, Any]:
    """Add an appointment to the family calendar."""
    if not isinstance(title, str) or not title.strip():
        raise ValueError("Appointment title must be a non-empty string")
    if not isinstance(date, str) or not date.strip():
        raise ValueError("Appointment date must be a non-empty string")

    appointment = {"title": title.strip(), "date": date.strip(), "created_at": _now()}
    with _LOCK:
        state = _read_state_unlocked()
        state["calendar"].append(appointment)
        _write_state_unlocked(state)
        calendar_size = len(state["calendar"])
    return {"appointment": appointment, "calendar_size": calendar_size}


def add_sheet_row(sheet_name: str, row: dict[str, Any]) -> dict[str, Any]:
    """Append a row to a named family spreadsheet."""
    if not isinstance(sheet_name, str) or not sheet_name.strip():
        raise ValueError("Sheet name must be a non-empty string")
    if not isinstance(row, dict):
        raise TypeError("Sheet row must be an object")

    stored_row = copy.deepcopy(row)
    stored_row.setdefault("added_at", _now())
    name = sheet_name.strip()
    with _LOCK:
        state = _read_state_unlocked()
        sheet = state["sheets"].setdefault(name, [])
        if not isinstance(sheet, list):
            raise ValueError(f"Sheet '{name}' is not a list")
        sheet.append(stored_row)
        row_count = len(sheet)
        _write_state_unlocked(state)
    return {"sheet": name, "row": stored_row, "row_count": row_count}


def draft_email(to: str, subject: str, body: str) -> dict[str, Any]:
    """Save an email draft. Drafts are never sent automatically."""
    if not isinstance(to, str) or not to.strip():
        raise ValueError("Recipient address must be a non-empty string")
    if not isinstance(subject, str) or not subject.strip():
        raise ValueError("Email subject must be a non-empty string")
    if not isinstance(body, str):
        raise TypeError("Email body must be a string")

    draft = {
        "to": to.strip(),
        "subject": subject.strip(),
        "body": body,
        "sent": False,
        "created_at": _now(),
    }
    with _LOCK:
        state = _read_state_unlocked()
        state["drafts"].append(draft)
        _write_state_unlocked(state)
        draft_count = len(state["drafts"])
    return {"draft": draft, "draft_count": draft_count, "sent": False}


def pay_bill(payee: str, amount: float) -> dict[str, Any]:
    """Pay a bill from the family bank account."""
    if not isinstance(payee, str) or not payee.strip():
        raise ValueError("Payee must be a non-empty string")
    if isinstance(amount, bool):
        raise TypeError("Bill amount must be a number")
    try:
        value = float(amount)
    except (TypeError, ValueError) as exc:
        raise ValueError("Bill amount must be a number") from exc
    if not math.isfinite(value) or value <= 0:
        raise ValueError("Bill amount must be a positive, finite number")

    with _LOCK:
        state = _read_state_unlocked()
        bank = state["bank"]
        balance = float(bank.get("balance", 0.0))
        if value > balance:
            raise ValueError(
                f"Insufficient balance: bill is {value:.2f}, balance is {balance:.2f}"
            )
        new_balance = round(balance - value, 2)
        transaction = {
            "payee": payee.strip(),
            "amount": value,
            "timestamp": _now(),
        }
        bank["balance"] = new_balance
        bank.setdefault("transactions", []).append(transaction)
        _write_state_unlocked(state)
    return {
        "payee": payee.strip(),
        "amount": value,
        "new_balance": new_balance,
        "currency": bank.get("currency", "INR"),
        "transaction": transaction,
    }


TOOL_REGISTRY: dict[str, Callable[..., dict[str, Any]]] = {
    "book_appointment": book_appointment,
    "add_sheet_row": add_sheet_row,
    "draft_email": draft_email,
    "pay_bill": pay_bill,
}


__all__ = [
    "TOOL_REGISTRY",
    "add_sheet_row",
    "book_appointment",
    "draft_email",
    "get_full_state",
    "pay_bill",
    "reset_state",
    "restore_full_state",
]
