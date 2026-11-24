# Tether 🛡️

**A family-first safety checkpoint between AI agents and real-world apps.**

AI agents can now act across calendars, emails, spreadsheets, and bank accounts using the Model Context Protocol (MCP). While powerful, giving an AI direct keys to personal tools introduces three major risks: **prompt injection** (hidden instructions in emails or web pages tricking the agent), **irreversible mistakes**, and **excessive agency** (making high-stakes decisions alone).

Tether sits as a transparent MCP proxy between any AI agent and its tools. It blocks malicious actions, snapshots state for one-click undo, and turns **real people into callable tools** so family members can step in to approve risky requests or provide help from their phone.

---

## Key Features

* **Policy Rules & Injection Scanning:** Every tool call is checked against a deterministic YAML policy (spending limits, allowed recipients) and scanned for hidden prompt injections using pattern matching and a secondary LLM check.
* **State Snapshots & One-Click Undo:** Before modifying data, Tether saves a snapshot so mistakes can be rolled back cleanly. Actions that cannot be reversed (like sending emails or transferring money) use draft-and-approve workflows and strict limits.
* **Humans-as-Tools (Family Escalation):** Unlike developer-focused security gateways, Tether is built for elderly and digitally inexperienced users. When an action exceeds safety limits—or when the agent needs real-world help like a photo or verification—it calls a designated family member with timeout and backup-contact fallbacks.
* **Live Audit Feed:** A real-time web dashboard displays every intercepted action as **Allowed**, **Blocked**, **Pending**, or **Undone**, along with the exact reasoning.

---

## How It Works

```text
User Request ──▶ AI Agent (Claude / MCP Client)
                      │
                      ▼ (MCP Tool Call)
            ┌───────────────────┐
            │   Tether Proxy    │
            │ 1. Rules Check    │───▶ [Blocked] ──▶ Reason returned to agent
            │ 2. Injection Scan │
            │ 3. Save Snapshot  │───▶ [Pending] ──▶ Human Approval (Family)
            └─────────┬─────────┘                         │ (Approved)
                      │ (Allowed)                         ▼
                      └──────────────────────────▶ Mock App Tools
                                                   (Calendar, Sheet, Email, Bank)
