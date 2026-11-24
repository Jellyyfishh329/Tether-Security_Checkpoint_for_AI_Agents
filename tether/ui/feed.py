"""Tether live audit feed.

Run with ``uvicorn tether.ui.feed:app --port 8000`` (or option 4 in
``run_demo.py``). The dashboard has no build step and no external assets.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from tether.core.snapshot import get_logs, undo_last

app = FastAPI(title="Tether Live Feed", version="0.1.0")


@app.get("/api/logs")
def api_logs() -> list[dict[str, Any]]:
    """Return the newest audit-log entries."""
    return get_logs()


@app.post("/api/undo")
def api_undo() -> dict[str, Any]:
    """Revert the most recent executed action."""
    return undo_last()


@app.get("/", response_class=HTMLResponse)
def dashboard() -> HTMLResponse:
    """Serve the single-file dashboard."""
    return HTMLResponse(content=INDEX_HTML)


INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tether · Family Safety Feed</title>
<style>
  :root {
    --bg: #f4f6f8;
    --panel: #ffffff;
    --ink: #18212b;
    --muted: #667382;
    --line: #e3e8ee;
    --green-bg: #e5f7ed;
    --green: #137a46;
    --red-bg: #fdeaea;
    --red: #b42323;
    --amber-bg: #fff4db;
    --amber: #9a6200;
    --gray-bg: #eef1f4;
    --gray: #5b6672;
    --accent: #1f6feb;
    --shadow: 0 12px 30px rgba(24, 33, 43, 0.08);
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    min-height: 100vh;
    background:
      radial-gradient(1000px 500px at 15% -10%, #dcecff 0%, transparent 60%),
      radial-gradient(700px 400px at 100% 0%, #e8f7ef 0%, transparent 55%),
      var(--bg);
    color: var(--ink);
    font-family: Inter, "Segoe UI", system-ui, -apple-system, sans-serif;
  }
  .wrap { max-width: 1080px; margin: 0 auto; padding: 40px 22px 70px; }
  header { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; flex-wrap: wrap; }
  .brand { display: flex; align-items: center; gap: 14px; }
  .mark {
    width: 48px; height: 48px; border-radius: 14px;
    background: linear-gradient(145deg, #1f6feb, #0e9f6e);
    color: #fff; display: grid; place-items: center;
    font-size: 24px; font-weight: 800; box-shadow: var(--shadow);
  }
  h1 { margin: 0; font-size: 28px; letter-spacing: -0.02em; }
  .sub { margin: 4px 0 0; color: var(--muted); font-size: 14px; }
  .live { display: inline-flex; align-items: center; gap: 8px; color: var(--muted); font-size: 13px; padding-top: 8px; }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: #0e9f6e; box-shadow: 0 0 0 5px rgba(14,159,110,.12); animation: pulse 2s infinite; }
  @keyframes pulse { 50% { opacity: .45; } }

  .stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 28px 0 18px; }
  .stat { background: var(--panel); border: 1px solid var(--line); border-radius: 14px; padding: 16px 18px; box-shadow: 0 3px 12px rgba(24,33,43,.03); }
  .stat .label { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .08em; }
  .stat .value { font-size: 28px; font-weight: 750; margin-top: 4px; }
  .stat.allowed .value { color: var(--green); }
  .stat.blocked .value { color: var(--red); }
  .stat.pending .value { color: var(--amber); }
  .stat.undone .value { color: var(--gray); }

  .toolbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin: 26px 0 10px; flex-wrap: wrap; }
  .toolbar h2 { margin: 0; font-size: 17px; }
  .actions { display: flex; align-items: center; gap: 10px; }
  .toast { color: var(--muted); font-size: 13px; min-height: 18px; }
  button.undo {
    background: var(--ink); color: #fff; border: 0; border-radius: 10px;
    padding: 10px 16px; font-size: 13px; font-weight: 650; cursor: pointer;
    transition: transform .12s ease, opacity .12s ease;
  }
  button.undo:hover { transform: translateY(-1px); }
  button.undo:disabled { opacity: .45; cursor: default; transform: none; }

  .panel { background: var(--panel); border: 1px solid var(--line); border-radius: 16px; box-shadow: var(--shadow); overflow: hidden; }
  table { width: 100%; border-collapse: collapse; }
  thead th {
    text-align: left; font-size: 11px; letter-spacing: .09em; text-transform: uppercase;
    color: var(--muted); font-weight: 650; padding: 14px 18px; background: #fbfcfd;
    border-bottom: 1px solid var(--line);
  }
  tbody td { padding: 15px 18px; border-bottom: 1px solid var(--line); font-size: 14px; vertical-align: top; }
  tbody tr:last-child td { border-bottom: 0; }
  tbody tr:hover { background: #fafcff; }
  .badge { display: inline-block; padding: 4px 9px; border-radius: 999px; font-size: 11px; font-weight: 750; letter-spacing: .04em; }
  .badge.ALLOWED { background: var(--green-bg); color: var(--green); }
  .badge.BLOCKED { background: var(--red-bg); color: var(--red); }
  .badge.PENDING { background: var(--amber-bg); color: var(--amber); }
  .badge.UNDONE { background: var(--gray-bg); color: var(--gray); }
  .badge.ERROR { background: var(--red-bg); color: var(--red); }
  .tool { font-family: "Cascadia Code", Consolas, monospace; font-size: 13px; font-weight: 650; }
  .reason { color: var(--muted); line-height: 1.45; }
  .time { color: var(--muted); white-space: nowrap; font-size: 12px; }
  .id { display: block; color: #9aa5b1; font-family: "Cascadia Code", Consolas, monospace; font-size: 10px; margin-top: 5px; }
  .empty { padding: 54px 20px; text-align: center; color: var(--muted); }
  .empty strong { display: block; color: var(--ink); margin-bottom: 6px; }
  @media (max-width: 760px) {
    .stats { grid-template-columns: repeat(2, 1fr); }
    thead { display: none; }
    tbody td { display: block; border-bottom: 0; padding: 6px 16px; }
    tbody tr { display: block; padding: 12px 0; border-bottom: 1px solid var(--line); }
    tbody tr:last-child { border-bottom: 0; }
  }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <div class="brand">
        <div class="mark">T</div>
        <div>
          <h1>Tether</h1>
          <p class="sub">A family-first safety checkpoint between AI agents and MCP tools.</p>
        </div>
      </div>
    </div>
    <div class="live"><span class="dot"></span><span id="refresh-label">Live · refreshing every 2s</span></div>
  </header>

  <section class="stats">
    <div class="stat allowed"><div class="label">Allowed</div><div class="value" id="count-allowed">0</div></div>
    <div class="stat blocked"><div class="label">Blocked</div><div class="value" id="count-blocked">0</div></div>
    <div class="stat pending"><div class="label">Pending</div><div class="value" id="count-pending">0</div></div>
    <div class="stat undone"><div class="label">Undone</div><div class="value" id="count-undone">0</div></div>
  </section>

  <div class="toolbar">
    <h2>Action feed</h2>
    <div class="actions">
      <span class="toast" id="toast"></span>
      <button class="undo" id="undo-btn" type="button">Undo Last Action</button>
    </div>
  </div>

  <section class="panel">
    <table>
      <thead>
        <tr><th style="width:110px">Status</th><th style="width:180px">Tool</th><th>Reason</th><th style="width:150px">Time</th></tr>
      </thead>
      <tbody id="log-body">
        <tr><td class="empty" colspan="4"><strong>No actions yet.</strong>Run the demo or benchmark to populate the feed.</td></tr>
      </tbody>
    </table>
  </section>
</div>

<script>
  const statuses = ["ALLOWED", "BLOCKED", "PENDING", "UNDONE"];
  const logBody = document.getElementById("log-body");
  const toast = document.getElementById("toast");
  const undoBtn = document.getElementById("undo-btn");

  function setCounts(logs) {
    for (const status of statuses) {
      const count = logs.filter((entry) => String(entry.status || "").toUpperCase() === status).length;
      document.getElementById("count-" + status.toLowerCase()).textContent = String(count);
    }
  }

  function formatTime(value) {
    if (!value) return "—";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleString(undefined, {
      month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit"
    });
  }

  function buildRow(entry) {
    const row = document.createElement("tr");

    const statusCell = document.createElement("td");
    const status = String(entry.status || "UNKNOWN").toUpperCase();
    const badge = document.createElement("span");
    badge.className = "badge " + status;
    badge.textContent = status;
    statusCell.appendChild(badge);
    row.appendChild(statusCell);

    const toolCell = document.createElement("td");
    const tool = document.createElement("span");
    tool.className = "tool";
    tool.textContent = entry.tool || "—";
    toolCell.appendChild(tool);
    const id = document.createElement("span");
    id.className = "id";
    id.textContent = entry.action_id ? "#" + String(entry.action_id).slice(0, 8) : "";
    toolCell.appendChild(id);
    row.appendChild(toolCell);

    const reasonCell = document.createElement("td");
    const reason = document.createElement("div");
    reason.className = "reason";
    reason.textContent = entry.reason || "—";
    reasonCell.appendChild(reason);
    row.appendChild(reasonCell);

    const timeCell = document.createElement("td");
    const time = document.createElement("span");
    time.className = "time";
    time.textContent = formatTime(entry.timestamp);
    timeCell.appendChild(time);
    row.appendChild(timeCell);

    return row;
  }

  function render(logs) {
    setCounts(logs);
    logBody.replaceChildren();
    if (!Array.isArray(logs) || logs.length === 0) {
      const row = document.createElement("tr");
      const cell = document.createElement("td");
      cell.colSpan = 4;
      cell.className = "empty";
      const strong = document.createElement("strong");
      strong.textContent = "No actions yet.";
      cell.appendChild(strong);
      cell.appendChild(document.createTextNode("Run the demo or benchmark to populate the feed."));
      row.appendChild(cell);
      logBody.appendChild(row);
      return;
    }
    const newestFirst = logs.slice().reverse();
    for (const entry of newestFirst) {
      logBody.appendChild(buildRow(entry));
    }
  }

  async function load() {
    try {
      const response = await fetch("/api/logs", { cache: "no-store" });
      if (!response.ok) throw new Error("HTTP " + response.status);
      render(await response.json());
      document.getElementById("refresh-label").textContent = "Live · refreshing every 2s";
    } catch (error) {
      document.getElementById("refresh-label").textContent = "Disconnected · retrying…";
    }
  }

  undoBtn.addEventListener("click", async () => {
    undoBtn.disabled = true;
    toast.textContent = "Restoring snapshot…";
    try {
      const response = await fetch("/api/undo", { method: "POST" });
      if (!response.ok) throw new Error("HTTP " + response.status);
      const data = await response.json();
      if (data.status === "UNDONE") {
        toast.textContent = "Undid " + (data.tool || "last action") + ".";
      } else {
        toast.textContent = data.reason || "Nothing to undo.";
      }
      await load();
    } catch (error) {
      toast.textContent = "Undo failed: " + error.message;
    } finally {
      undoBtn.disabled = false;
    }
  });

  load();
  setInterval(load, 2000);
</script>
</body>
</html>
"""


if __name__ == "__main__":  # pragma: no cover - manual launch convenience
    import uvicorn

    uvicorn.run("tether.ui.feed:app", host="127.0.0.1", port=8000, reload=False)


__all__ = ["app"]
