"""Family-side commands.   python -m tether.cli <command>

  pending              list requests waiting for a family member
  approve <id>         approve a waiting action
  reject <id>          reject it
  answer <id> "text"   answer a question the agent asked (ask_human_helper)
  log                  show the audit log
  undo                 undo the most recent action (refuses if unsafe)
  serve                run the MCP server over stdio
"""
from __future__ import annotations

import json
import sys

from tether.core import snapshot
from tether.core.human_tool import pending_dir


def _decide(request_id: str, text: str) -> int:
    if not (pending_dir() / f"{request_id}.json").exists():
        print(f"no pending request {request_id}", file=sys.stderr)
        return 1
    (pending_dir() / f"{request_id}.decision").write_text(text, encoding="utf-8")
    print(f"sent '{text}' for {request_id}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    cmd = args[0] if args else ""
    if cmd == "pending":
        items = sorted(pending_dir().glob("*.json"))
        if not items:
            print("nothing waiting")
        for item in items:
            print(json.dumps(json.loads(item.read_text()), indent=2))
        return 0
    if cmd in ("approve", "reject") and len(args) == 2:
        return _decide(args[1], "yes" if cmd == "approve" else "no")
    if cmd == "answer" and len(args) >= 3:
        return _decide(args[1], " ".join(args[2:]))
    if cmd == "log":
        for e in snapshot.get_logs():
            print(f"{str(e.get('action_id'))[:8]}  {e.get('tool', ''):<16} {e.get('status', ''):<8} {e.get('reason', '')}")
        return 0
    if cmd == "undo":
        print(json.dumps(snapshot.undo_last(), indent=2))
        return 0
    if cmd == "serve":
        from tether.core.proxy import main as serve

        serve()
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
