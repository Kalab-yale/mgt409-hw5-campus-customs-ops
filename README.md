# Campus Customs Multi-Agent Operations

MGT 409 (AI Foundations for Managers) · Homework 5

An AI back office for **Campus Customs**, a small Yale merch shop. Five PydanticAI agents work the shop's tickets together. A human manager watches them on a React dashboard and approves anything that touches real money or real customers.

| Agent | Job |
|---|---|
| 👔 **Boss** | Reviews each ticket, assigns work, makes the final decision |
| 📦 **Inventory** | Stock by SKU and size, shortages, restock vendors |
| 🧮 **Accounting** | Cash, invoices, margins; prepares payments / purchase orders / quotes for approval |
| 🏬 **Facilities** | The shop space: leases and rent |
| 💬 **Customer Service** | Drafts customer messages for approval |

Every agent can delegate to every other agent. Every shop fact comes through one **MCP server**, and only a human's **Approve** click moves money.

```
React dashboard (:5173) → FastAPI backend (:8000) → agent team ─MCP─▶ mcp_server ─▶ data/campus_customs_new.db
                                                       └──────▶ output/audit_trail.json (append-only)
```

**Final run (documented in `output/`):** tickets 101, 102, and 103 were all resolved. Checking went **$3,400 → $160** through two human-approved payments (rent $2,400, invoice $840), and the result reconciles with `cash_accounts` to the cent.

---

## Repository layout

```
.
├── AI_prompts.md              prompts given to the AI assistant (Problems 2–10)
├── README.md                  this file
├── requirements.txt           Python dependencies
├── .env.example               placeholder for PORTKEY_API_KEY (copy to .env)
├── .mcp.json                  connects Claude Code to the MCP server
├── data/
│   ├── campus_customs.db      ORIGINAL database (never written)
│   └── campus_customs_new.db  WORKING copy (agents + approvals write here); final state after the run
├── mcp_server/
│   ├── server.py              FastMCP server: 17 tools, the only code that touches the database
│   └── README.md
├── backend/                   FastAPI + PydanticAI agent team
│   ├── main.py                API routes
│   ├── models.py              data types
│   ├── team.py                5 agents, delegate tool, audited agent loop
│   ├── mcp_client.py          MCP connection, per-role tool filter, audit hook
│   ├── agents/                one RoleSpec per agent
│   ├── prompts/               _shared.md + boss / inventory / accounting / facilities / customer_service .md
│   ├── config.py, audit.py, events.py, run_tickets.py
├── frontend/                  React + Vite + TypeScript dashboard
├── scripts/build_run_report.py  rebuilds the Problem 9 reports from the audit trail + API
└── output/
    ├── harness.md             full system reference (tables, tools, agents, routes, dashboard, safety)
    ├── mcp_smoke.json         MCP smoke tests run through Claude Code
    ├── desk_tickets.html      plan (Expected) vs Actual per ticket, Cash, Reflection (double-click to open)
    ├── design.md              dashboard design rationale
    ├── resolved_tickets.json  final status, outcome, agent contributions, human approvals
    ├── resolved_board.html    screenshots of the dashboard for each resolved ticket (double-click to open)
    ├── screenshots/           the same screenshots as PNG files
    ├── audit_trail.json       every agent step, MCP call, hand-off, and approval
    └── github_url.txt         this repository's URL
```

---

## Setup (once)

Requirements: **Python 3.11+**, **Node 20+**, and a Portkey API key with access to `gpt-6-luna`.

```bash
git clone <this repo> campus-customs && cd campus-customs

# Python environment (MCP server + backend)
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# API key: copy the placeholder file and paste your own key into .env (never commit it)
cp .env.example .env

# Frontend
cd frontend && npm install && cd ..
```

---

## 1. Restore the working database from the original

`data/campus_customs_new.db` is committed in its **final state** after the documented run (checking $160, all three tickets resolved). To start over, restore it from the untouched original. Either:

```bash
cp data/campus_customs.db data/campus_customs_new.db
```

or, with the backend running, click **↺ Reset** in the dashboard (it calls `POST /api/reset`, which does the same copy through the MCP tool `reset_database`):

```bash
curl -X POST http://localhost:8000/api/reset -H "Content-Type: application/json" -d '{"confirm":"RESET"}'
```

The MCP server automatically adds its `approval_requests` table to the working copy when it starts. The audit trail is **never** cleared by a reset.

## 2. Start the MCP server

You normally don't start it by hand: **the backend starts it automatically** over stdio, and **Claude Code** starts it from `.mcp.json` when you open this folder (approve the `campus-customs` server when asked). To run it on its own:

```bash
.venv/bin/python mcp_server/server.py
```

It talks over stdio, so it waits silently for an MCP client. See `mcp_server/README.md` for the 17 tools.

## 3. Start the FastAPI backend

```bash
cd backend
../.venv/bin/python -m uvicorn main:app --reload --port 8000
```

The API is at **http://localhost:8000** (interactive docs at `/docs`). It reads `PORTKEY_API_KEY` from `.env`.

## 4. Start the React dashboard

In a second terminal:

```bash
cd frontend
npm run dev
```

Open **http://localhost:5173**.

## 5. Full three-ticket run

1. **Reset first**: click **↺ Reset** (or run the `cp` / `curl` command from step 1). Checking should read **$3,400.00**, with all tickets **Open** and nothing awaiting approval.
2. Type your name in **Approving as** (top right).
3. Select **#101 → ▶ Run agent team**. Watch the live activity feed until the ticket shows **✓ Resolved** (about 20–30 s). Repeat for **#102** and **#103**. The team runs one ticket at a time.
4. Review **Needs your approval** and click **Approve & pay** / **Approve** / **Reject**. The checking balance drops only when you approve a payment. Note: rent + invoice + the hoodie purchase order ($3,504) is more than the $3,400 in checking, so you can't approve all three. Approving rent and the invoice leaves $160.
5. Optional: rebuild the reports from your run (the backend must be running). The script refuses to write if the cash doesn't reconcile:
   ```bash
   .venv/bin/python scripts/build_run_report.py
   ```

Without the dashboard: `.venv/bin/python backend/run_tickets.py 101 102 103` runs the team from the command line. Approvals still require the API or dashboard.

---

## Safety in one paragraph

Agents can only **prepare** requests (`pending` rows in `approval_requests`). The MCP server computes every amount from the database, refuses quotes below cost and payments larger than cash, warns when pending payments exceed cash, and enforces which role may file what. Only the human-only `approve_request` tool, behind the dashboard's Approve button, writes `payments` and lowers the balance. Customer messages are drafts a human approves. Each ticket run is capped at 30 model calls, 40 tool calls, and 150k tokens, with delegation depth 3 and 8 hand-offs. Details: `output/harness.md` §11.

## Model and keys

All agents use `gpt-6-luna` through Portkey (`https://api.portkey.ai/v1`). The key is read from `.env` only, and `.env` is git-ignored.
