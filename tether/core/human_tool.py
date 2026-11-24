"""Human approval and "humans-as-tools" helpers.

Both functions are deliberately isolated from the proxy so the terminal prompts
can later be replaced by Telegram Bot API calls (send a message, wait for a
callback, update the audit log) without touching policy or tool execution.

For automated tests, pass ``auto_decision="yes"`` / ``"no"`` or
``auto_reply="..."`` to skip terminal I/O deterministically.
"""

from __future__ import annotations

import os
import sys
import time
from typing import Any

from tether.core.policy import load_config

_AFFIRMATIVE = {"y", "yes", "approve", "approved", "true", "1"}
_NEGATIVE = {"n", "no", "deny", "denied", "false", "0", ""}


def _parse_decision(value: str) -> bool | None:
    """Parse a free-form yes/no answer. Returns ``None`` for unrecognised input."""
    normalised = value.strip().lower()
    if normalised in _AFFIRMATIVE:
        return True
    if normalised in _NEGATIVE:
        return False
    return None


def _read_line_with_timeout(timeout_sec: float) -> str | None:
    """Read one line from the terminal, returning ``None`` on timeout.

    Windows uses ``msvcrt`` so the input thread does not linger and steal the
    next prompt after a timeout. Unix uses ``select``. Non-TTY stdin falls back
    to a normal blocking read (useful for piped demo scripts).
    """
    if timeout_sec <= 0:
        return None

    if os.name == "nt":  # pragma: no cover - exercised interactively on Windows
        try:
            import msvcrt
        except ImportError:
            try:
                return input()
            except EOFError:
                return None

        deadline = time.monotonic() + timeout_sec
        characters: list[str] = []
        try:
            while time.monotonic() < deadline:
                if not msvcrt.kbhit():
                    time.sleep(0.05)
                    continue
                character = msvcrt.getwch()
                if character in ("\r", "\n"):
                    print()
                    return "".join(characters)
                if character == "\x08":  # backspace
                    if characters:
                        characters.pop()
                        print("\b \b", end="", flush=True)
                    continue
                if character == "\x03":  # Ctrl+C
                    raise KeyboardInterrupt
                if character == "\x1a":  # Ctrl+Z / EOF
                    print()
                    return None
                characters.append(character)
                print(character, end="", flush=True)
        except OSError:
            # stdin is redirected; msvcrt cannot poll it.
            try:
                return input()
            except EOFError:
                return None
        print()
        return None

    # POSIX fallback.
    try:
        import select

        ready, _, _ = select.select([sys.stdin], [], [], timeout_sec)
        if not ready:
            print()
            return None
        return sys.stdin.readline().rstrip("\r\n")
    except (ImportError, OSError):  # pragma: no cover - unusual terminals
        try:
            return input()
        except EOFError:
            return None


def _approver_settings(config: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], float]:
    """Extract primary/backup approvers and a safe timeout value."""
    primary = dict(config.get("primary_approver") or {})
    backup = dict(config.get("backup_approver") or {})
    try:
        timeout = float(primary.get("timeout_sec", 10))
    except (TypeError, ValueError):
        timeout = 10.0
    if timeout <= 0:
        timeout = 10.0
    return primary, backup, timeout


def request_approval(
    action_summary: str,
    reason: str,
    auto_decision: str | None = None,
) -> tuple[bool, str]:
    """Ask a family member to approve a sensitive action.

    Args:
        action_summary: Human-readable description of the proposed tool call.
        reason: Why policy escalated the action.
        auto_decision: Test hook. ``"yes"``/``"no"`` returns immediately without
            terminal I/O. ``None`` prompts the primary approver in the terminal.

    Returns:
        ``(approved, explanation)``. Timeouts, skipped prompts, and
        unrecognised answers default to denial.
    """
    config = load_config()
    primary, backup, timeout_sec = _approver_settings(config)

    primary_name = str(primary.get("name", "Primary approver"))
    primary_contact = str(primary.get("contact", "unknown"))
    backup_name = str(backup.get("name", "Backup approver"))
    backup_contact = str(backup.get("contact", "unknown"))

    if auto_decision is not None:
        parsed = _parse_decision(auto_decision)
        if parsed is True:
            return True, f"Auto-approved for automated run (primary: {primary_name})"
        if parsed is False:
            return False, "Auto-denied for automated run"
        return False, f"Unrecognised auto decision '{auto_decision}'; denied by default"

    print("\n" + "=" * 64)
    print("TETHER HUMAN APPROVAL REQUIRED")
    print(f"Action : {action_summary}")
    print(f"Reason : {reason}")
    print(f"Primary: {primary_name} ({primary_contact})")
    print("=" * 64)

    print(f"Approve this action? [y/n] ({primary_name}): ", end="", flush=True)
    answer = _read_line_with_timeout(timeout_sec)
    if answer is None:
        print(
            f"No response from {primary_name} within {timeout_sec:.0f}s. "
            f"Contacting backup approver {backup_name} ({backup_contact})."
        )
        print("No backup response available in CLI mode; denying by default.")
        return (
            False,
            f"Timed out waiting for {primary_name}; backup {backup_name} notified "
            f"at {backup_contact}; denied by default",
        )

    answer = answer.strip()
    parsed = _parse_decision(answer)
    if parsed is True:
        print(f"Approved by {primary_name}.")
        return True, f"Approved by {primary_name} ({primary_contact})"
    if parsed is False and answer:
        print(f"Denied by {primary_name}.")
        return False, f"Denied by {primary_name} ({primary_contact})"

    print(
        f"Skipped or invalid response. Falling back to backup approver "
        f"{backup_name} ({backup_contact}); denying by default in CLI mode."
    )
    return (
        False,
        f"No valid response from {primary_name}; backup {backup_name} notified "
        f"at {backup_contact}; denied by default",
    )


def ask_human_helper(question: str, auto_reply: str | None = None) -> str:
    """Ask a family member a free-form question (the "humans-as-tools" pattern).

    Example uses: verify a medicine label from a photo, confirm whether a person
    at the door is expected, or read out an OTP that must never be exposed to the
    agent's own context.

    Args:
        question: The question to present to the human.
        auto_reply: Test/demo hook that returns immediately without terminal I/O.

    Returns:
        The human's answer, or an empty string on EOF.
    """
    if auto_reply is not None:
        return auto_reply

    print("\n" + "-" * 64)
    print("TETHER HUMAN HELPER")
    print(question)
    print("-" * 64)
    try:
        return input("Answer: ").strip()
    except (EOFError, KeyboardInterrupt):
        return ""


__all__ = ["ask_human_helper", "request_approval"]
