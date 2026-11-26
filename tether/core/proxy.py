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
from tether.core.policy import IRREVERSIBLE_TOOLS, evaluate_action, scan_text
from tether.core.snapshot import log_event, save_snapshot, state_hash, update_event
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
        # Taint: set once this session reads content that looks like an attack.
        self.tainted: bool = False

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
            auto_approve: Python-only test hook (NOT exposed over MCP, so an agent
                can never approve its own action). ``True``/``False`` decides
                immediately; ``None`` uses the operator's approver mode
                (``TETHER_APPROVER``: terminal, file, approve or deny).

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
        policy_status, policy_reason = evaluate_action(tool_name, args, tainted=self.tainted)

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
            log_event(
                {
                    "action_id": action_id,
                    "tool": tool_name,
                    "args": args,
                    "status": "PENDING",
                    "reason": policy_reason,
                }
            )
            auto_decision = None
            if auto_approve is not None:
                auto_decision = "yes" if auto_approve else "no"

            approved, approval_note = request_approval(
                summary, policy_reason, auto_decision=auto_decision, request_id=action_id
            )
            if not approved:
                update_event(
                    action_id,
                    status="BLOCKED",
                    reason="Rejected by family approver",
                    approval_detail=approval_note,
                )
                return {"status": "BLOCKED", "reason": "Rejected by family approver"}

        # 5. Execute and log the successful, approved action.
        try:
            result = handler(**args)
        except Exception as exc:  # noqa: BLE001 - surface backend failures to caller/audit
            error_reason = f"{type(exc).__name__}: {exc}"
            if policy_status == "NEEDS_HUMAN":
                update_event(action_id, status="ERROR", reason=error_reason)
            else:
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

        # Scan what the tool returned (e.g. an email body). A hit taints the session.
        warning = None
        signal = scan_text(json.dumps(result, ensure_ascii=False, default=str))
        if signal is not None and tool_name == "read_inbox":
            self.tainted = True
            warning = f"Suspicious content in tool result ({signal}); session is now tainted"
            final_reason = f"{final_reason}; {warning}"

        entry = {
            "action_id": action_id,
            "tool": tool_name,
            "args": args,
            "reason": final_reason,
            "result": result,
            "irreversible": tool_name in IRREVERSIBLE_TOOLS,
            "after_hash": state_hash(mock_apps.get_full_state()),
            "tainted": self.tainted,
        }
        if policy_status == "NEEDS_HUMAN":
            update_event(action_id, status="ALLOWED", **{k: v for k, v in entry.items() if k != "action_id"})
        else:
            log_event({"status": "ALLOWED", **entry})
        response: dict[str, Any] = {"status": "ALLOWED", "result": result}
        if warning:
            response["tether_warning"] = warning
        return response

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
def execute_tool(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Execute a family app tool through Tether's safety checkpoint.

    Args:
        tool_name: book_appointment, add_sheet_row, draft_email, send_email,
            read_inbox or pay_bill.
        args: Tool arguments as an object.

    There is deliberately no way for the caller to approve its own action: who
    decides is set by the operator (TETHER_APPROVER), not by tool arguments.
    """
    return _proxy.execute_tool(tool_name, args)


@mcp.tool()
def ask_human_helper(question: str) -> str:
    """Ask a family member to verify something the agent cannot safely judge.

    Use this for photo verification, medicine-label checks, or any question that
    should be answered by a trusted human rather than guessed by the model.
    Tries the primary contact, then the backup if there is no answer in time.
    """
    return ask_human(question, request_id="q-" + uuid.uuid4().hex[:8])


def main() -> None:
    """Run the MCP server over stdio. Defaults to the file approver (no terminal here)."""
    import os

    os.environ.setdefault("TETHER_APPROVER", "file")
    mcp.run()


if __name__ == "__main__":
    main()


__all__ = ["FastMCP", "TetherProxy", "ask_human_helper", "execute_tool", "mcp"]
