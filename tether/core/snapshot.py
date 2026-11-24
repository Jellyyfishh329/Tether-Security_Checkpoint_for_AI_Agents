"""Snapshot, undo, and audit-log storage.

All persistence goes through :class:`StorageBackend`, so the JSON file used in
the MVP can be replaced with SQLite or a hosted audit store later:

    from tether.core.snapshot import configure_storage, SqliteStorageBackend
    configure_storage(SqliteStorageBackend("data/tether.db"))

The public functions in this module intentionally do not depend on the concrete
backend.
"""

from __future__ import annotations

import copy
import json
import os
import threading
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tether.tools import mock_apps

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
AUDIT_PATH = DATA_DIR / "audit_log.json"

_LOCK = threading.RLock()


def _now() -> str:
    """Return an ISO-8601 UTC timestamp."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _empty_audit() -> dict[str, Any]:
    return {"snapshots": {}, "logs": []}


def _normalise_audit(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Audit storage must contain a JSON object")
    audit = _empty_audit()
    audit.update(copy.deepcopy(value))
    if not isinstance(audit.get("snapshots"), dict):
        raise ValueError("Audit field 'snapshots' must be an object")
    if not isinstance(audit.get("logs"), list):
        raise ValueError("Audit field 'logs' must be a list")
    return audit


class StorageBackend(ABC):
    """Persistence contract for snapshots and audit logs."""

    @abstractmethod
    def load(self) -> dict[str, Any]:
        """Return the full audit document."""

    @abstractmethod
    def save(self, data: dict[str, Any]) -> None:
        """Persist the full audit document."""


class JsonStorageBackend(StorageBackend):
    """Single-file JSON storage suitable for the MVP and local demos."""

    def __init__(self, path: str | Path = AUDIT_PATH) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return _empty_audit()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Corrupt audit log at {self.path}: {exc}") from exc
        return _normalise_audit(raw)

    def save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(".json.tmp")
        payload = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
        tmp_path.write_text(payload + "\n", encoding="utf-8")
        os.replace(tmp_path, self.path)


_backend: StorageBackend = JsonStorageBackend(AUDIT_PATH)


def configure_storage(backend: StorageBackend) -> None:
    """Swap the audit storage backend (for example, SQLite in production)."""
    global _backend
    if not isinstance(backend, StorageBackend):
        raise TypeError("backend must implement StorageBackend")
    with _LOCK:
        _backend = backend


def save_snapshot(action_id: str, state_before: dict[str, Any]) -> None:
    """Persist the complete mock-app state before an action executes."""
    if not isinstance(action_id, str) or not action_id:
        raise ValueError("action_id must be a non-empty string")
    if not isinstance(state_before, dict):
        raise TypeError("state_before must be an object")

    with _LOCK:
        audit = _backend.load()
        audit["snapshots"][action_id] = {
            "action_id": action_id,
            "timestamp": _now(),
            "state": copy.deepcopy(state_before),
        }
        _backend.save(audit)


def log_event(entry: dict[str, Any]) -> None:
    """Append an audit-log entry and persist it immediately."""
    if not isinstance(entry, dict):
        raise TypeError("Audit entry must be an object")

    record = copy.deepcopy(entry)
    record.setdefault("timestamp", _now())
    record.setdefault("status", "UNKNOWN")
    with _LOCK:
        audit = _backend.load()
        audit["logs"].append(record)
        _backend.save(audit)


def get_logs() -> list[dict[str, Any]]:
    """Return all audit-log entries, oldest first."""
    with _LOCK:
        return copy.deepcopy(_backend.load()["logs"])


def undo_last() -> dict[str, Any]:
    """Revert state to before the most recent executed (ALLOWED) action.

    The matching log entry is marked ``UNDONE`` (its original status is retained
    in ``previous_status``) so repeated undo calls walk backwards through
    history instead of undoing the same action twice.
    """
    with _LOCK:
        audit = _backend.load()
        logs: list[dict[str, Any]] = audit["logs"]
        snapshots: dict[str, Any] = audit["snapshots"]

        target_index: int | None = None
        for index in range(len(logs) - 1, -1, -1):
            entry = logs[index]
            if (
                entry.get("status") == "ALLOWED"
                and entry.get("action_id") in snapshots
            ):
                target_index = index
                break

        if target_index is None:
            return {
                "status": "NOOP",
                "reason": "No executed action is available to undo",
            }

        entry = logs[target_index]
        action_id = str(entry["action_id"])
        snapshot = snapshots[action_id]
        state_before = snapshot.get("state")
        try:
            mock_apps.restore_full_state(state_before)
        except (TypeError, ValueError) as exc:
            return {
                "status": "ERROR",
                "reason": f"Snapshot could not be restored: {exc}",
                "action_id": action_id,
            }

        entry["previous_status"] = entry.get("status")
        entry["status"] = "UNDONE"
        entry["undone_at"] = _now()
        _backend.save(audit)

    return {
        "status": "UNDONE",
        "action_id": action_id,
        "tool": entry.get("tool"),
        "original_timestamp": entry.get("timestamp"),
        "undone_at": entry.get("undone_at"),
        "reason": "State restored to the snapshot before the last allowed action",
        "restored": True,
    }


def reset_audit_log() -> None:
    """Clear snapshots and logs (used by the benchmark suite)."""
    with _LOCK:
        _backend.save(_empty_audit())


__all__ = [
    "AUDIT_PATH",
    "JsonStorageBackend",
    "StorageBackend",
    "configure_storage",
    "get_logs",
    "log_event",
    "reset_audit_log",
    "save_snapshot",
    "undo_last",
]
