"""Tether proxy: the single checkpoint every tool call passes through.

The proxy is deliberately transport-agnostic. Import :class:`TetherProxy` for
direct Python/MCP use, or connect an MCP client to the module-level ``mcp``
server exposed at the bottom of this file.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Callable, Mapping

try:  # mcp < 2
    from mcp.server.fastmcp import FastMCP
except ModuleNotFoundError:  # mcp >= 2 renamed FastMCP to MCPServer
    from mcp.server.mcpserver import MCPServer as FastMCP  # type: ignore[assignment]

from tether.core.human_tool import ask_human_helper as ask_human
from tether.core.human_tool import request_approval
from tether.core.policy import evaluate_action
from tether.core.snapshot import log_event, save_snapshot
from tether.tools import mock_apps
from tether.tools.mock_apps import TOOL_REGISTRY

ToolFunction = Callable[..., dict[str, Any]]


class TetherProxy:
    """Policy-enforcing gateway around the family's tool backends."""

    def __init__(
        self,
        tool_registry: Mapping[str, ToolFunction] | None = None,
    ) -> None:
        self.tools: dict[str, ToolFunction] = dict(tool_registry or TOOL_REGISTRY)

    def execute_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        auto_approve: bool | None = None,
    ) -> dict[str, Any]:
        """Evaluate, approve (when needed), snapshot, execute, and audit a call.

        Args:
            tool_name: One of :data:`tether.tools.mock_apps.TOOL_REGISTRY`.
            args: Keyword arguments for the tool.
            auto_approve: Test/demo hook for ``NEEDS_HUMAN`` actions. ``True``
                approves immediately, ``False`` denies immediately, and ``None``
                prompts the family approver in the terminal.

        Returns:
            ``{"status": "ALLOWED", "result": ...}`` on success,
            ``{"status": "BLOCKED", "reason": ...}`` when policy or a human
            denies the call, or ``{"status": "ERROR", "reason": ...}`` when the
            backend raises unexpectedly.
        """
        if not isinstance(tool_name, str) or not tool_name:
            raise ValueError("tool_name must be a non-empty string")
        if not isinstance(args, dict):
            raise TypeError("args must be an object")

        action_id = uuid.uuid4().hex
        policy_status, policy_reason = evaluate_action(tool_name, args)

        # 1-2. Blocked calls are logged but never snapshotted or executed.
        if policy_status == "BLOCKED":
            log_event(
                {
                    "action_id": action_id,
                    "tool": tool_name,
                    "args": args,
                    "status": "BLOCKED",
                    "reason": policy_reason,
                }
            )
            return {"status": "BLOCKED", "reason": policy_reason}

        handler = self.tools.get(tool_name)
        if handler is None:
            reason = f"Unknown tool '{tool_name}'"
            log_event(
                {
                    "action_id": action_id,
                    "tool": tool_name,
                    "args": args,
                    "status": "BLOCKED",
                    "reason": reason,
                }
            )
            return {"status": "BLOCKED", "reason": reason}

        # 3. Capture the full pre-execution state for one-click undo.
        state_before = mock_apps.get_full_state()
        save_snapshot(action_id, state_before)

        # 4. Escalate risky-but-legitimate calls to a family member.
        approval_note = ""
        if policy_status == "NEEDS_HUMAN":
            summary = self._summarise(tool_name, args)
            auto_decision = None
            if auto_approve is not None:
                auto_decision = "yes" if auto_approve else "no"

            approved, approval_note = request_approval(
                summary, policy_reason, auto_decision=auto_decision
            )
            if not approved:
                log_event(
                    {
                        "action_id": action_id,
                        "tool": tool_name,
                        "args": args,
                        "status": "BLOCKED",
                        "reason": "Rejected by family approver",
                        "approval_detail": approval_note,
                    }
                )
                return {"status": "BLOCKED", "reason": "Rejected by family approver"}

        # 5. Execute and log the successful, approved action.
        try:
            result = handler(**args)
        except Exception as exc:  # noqa: BLE001 - surface backend failures to caller/audit
            error_reason = f"{type(exc).__name__}: {exc}"
            log_event(
                {
                    "action_id": action_id,
                    "tool": tool_name,
                    "args": args,
                    "status": "ERROR",
                    "reason": error_reason,
                }
            )
            return {"status": "ERROR", "reason": error_reason}

        final_reason = policy_reason
        if approval_note:
            final_reason = f"{policy_reason}; {approval_note}"

        log_event(
            {
                "action_id": action_id,
                "tool": tool_name,
                "args": args,
                "status": "ALLOWED",
                "reason": final_reason,
                "result": result,
            }
        )
        return {"status": "ALLOWED", "result": result}

    @staticmethod
    def _summarise(tool_name: str, args: dict[str, Any]) -> str:
        """Render a compact, human-readable action summary for approval prompts."""
        rendered = json.dumps(args, ensure_ascii=False, default=str, sort_keys=True)
        return f"{tool_name}({rendered})"


# ---------------------------------------------------------------------------
# MCP server
#
# This exposes Tether to any MCP client (Claude Desktop, Inspector, custom
# agents). Both calls still pass through the same policy, snapshot, and audit
# path as Python callers.
# ---------------------------------------------------------------------------

_proxy = TetherProxy()
mcp = FastMCP("Tether")


@mcp.tool()
def execute_tool(
    tool_name: str,
    args: dict[str, Any],
    auto_approve: bool | None = None,
) -> dict[str, Any]:
    """Execute a family app tool through Tether's safety checkpoint.

    Args:
        tool_name: book_appointment, add_sheet_row, draft_email, or pay_bill.
        args: Tool arguments as an object.
        auto_approve: Optional automation hook for high-value actions. Leave
            unset so the family approver is prompted for human decisions.
    """
    return _proxy.execute_tool(tool_name, args, auto_approve=auto_approve)


@mcp.tool()
def ask_human_helper(question: str, auto_reply: str | None = None) -> str:
    """Ask a family member to verify something the agent cannot safely judge.

    Use this for photo verification, medicine-label checks, or any question that
    should be answered by a trusted human rather than guessed by the model.
    """
    return ask_human(question, auto_reply=auto_reply)


__all__ = ["FastMCP", "TetherProxy", "ask_human_helper", "execute_tool", "mcp"]
