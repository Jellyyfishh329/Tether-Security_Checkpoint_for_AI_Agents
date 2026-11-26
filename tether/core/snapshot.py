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
import hashlib
import json
import os
import threading
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tether.tools import mock_apps

from tether.paths import data_dir

AUDIT_PATH = None  # resolved lazily: <data dir>/audit_log.json

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

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path else None

    @property
    def path(self) -> Path:
        return self._path or data_dir() / "audit_log.json"

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


_backend: StorageBackend = JsonStorageBackend()


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


def state_hash(state: dict[str, Any]) -> str:
    """Stable fingerprint of the mock-app state (used to detect later changes)."""
    return hashlib.sha256(json.dumps(state, sort_keys=True, default=str).encode()).hexdigest()[:16]


def undo_last() -> dict[str, Any]:
    """Undo the most recent executed action, safely.

    Refuses (and changes nothing) when:
      * the action was irreversible (a payment or a sent email cannot be taken back), or
      * the state changed after the action (undoing would overwrite someone's later work).
    The log entry is marked UNDONE so repeated calls walk backwards, newest first.
    """
    with _LOCK:
        audit = _backend.load()
        logs: list[dict[str, Any]] = audit["logs"]
        snapshots: dict[str, Any] = audit["snapshots"]

        target_index: int | None = None
        for index in range(len(logs) - 1, -1, -1):
            entry = logs[index]
            if entry.get("status") == "ALLOWED" and entry.get("action_id") in snapshots:
                target_index = index
                break

        if target_index is None:
            return {"status": "NOOP", "reason": "No executed action is available to undo"}

        entry = logs[target_index]
        action_id = str(entry["action_id"])
        if entry.get("irreversible"):
            return {
                "status": "REFUSED",
                "action_id": action_id,
                "tool": entry.get("tool"),
                "reason": f"{entry.get('tool')} is irreversible and cannot be undone; contact the recipient or bank",
            }
        after_hash = entry.get("after_hash")
        if after_hash and state_hash(mock_apps.get_full_state()) != after_hash:
            return {
                "status": "CONFLICT",
                "action_id": action_id,
                "tool": entry.get("tool"),
                "reason": "State changed after this action; not overwriting later changes",
            }
        try:
            mock_apps.restore_full_state(snapshots[action_id].get("state"))
        except (TypeError, ValueError) as exc:
            return {"status": "ERROR", "reason": f"Snapshot could not be restored: {exc}", "action_id": action_id}

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


def update_event(action_id: str, **fields: Any) -> None:
    """Update the newest log entry with this action_id (e.g. PENDING -> final status)."""
    with _LOCK:
        audit = _backend.load()
        for entry in reversed(audit["logs"]):
            if entry.get("action_id") == action_id:
                entry.update(fields)
                break
        _backend.save(audit)


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
    "state_hash",
    "update_event",
    "save_snapshot",
    "undo_last",
]
