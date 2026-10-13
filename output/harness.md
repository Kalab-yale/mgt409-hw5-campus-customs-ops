# Campus Customs Multi-Agent Operations — Harness

The complete reference for the system built in Homework 5: the database, the MCP server, the five agents, the API, the dashboard, and the safety rules. It ends with the documented clean run of tickets 101–103.

> **Status (final run, Problem 9):** all three tickets **resolved**. Checking went **$3,400.00 → $160.00** through two human-approved payments ($3,240.00), and the reconciliation against `cash_accounts` **matches to the cent**. See §12.

---

## 1. System Overview

```
 React dashboard (frontend/, :5173)            human: runs tickets, reads results, approves / rejects
          │  fetch JSON
          ▼
 FastAPI backend (backend/main.py, :8000)      routes; starts team runs; human-only actions
          │                      │
          │ team.handle_ticket() │ direct MCP calls (approve, reset, lists …)
          ▼                      ▼
 PydanticAI agent team ──MCP (stdio)──▶ campus-customs MCP server (mcp_server/server.py)
 Boss · Inventory · Accounting ·                 │  the ONLY code that touches the database
 Facilities · Customer Service                   ▼
          │                             data/campus_customs_new.db  (working copy)
          ▼                             data/campus_customs.db      (original, never written)
 output/audit_trail.json  (append-only log of every agent step, MCP call, hand-off, approval)
```

**Run it locally**
```bash
# one-time (from Homework 5/)
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cd frontend && npm install && cd ..
# terminal 1: backend (reads PORTKEY_API_KEY from .env; copy .env.example first)
cd backend && ../.venv/bin/python -m uvicorn main:app --reload --port 8000
# terminal 2: dashboard
cd frontend && npm run dev          # open http://localhost:5173
```
CLI alternative without the dashboard: `.venv/bin/python backend/run_tickets.py 101 102 103`.

**Where things live**
| Path | What |
|---|---|
| `mcp_server/server.py`, `mcp_server/README.md` | FastMCP server (17 tools) |
| `.mcp.json` | Claude Code connection to the MCP server |
| `backend/config.py` | Paths, model, token / delegation limits |
| `backend/models.py` | All data types (agent outputs, role specs, run context, API bodies) |
| `backend/agents/*.py` | One `RoleSpec` per agent (prompt file, allowed MCP tools, output type) |
| `backend/prompts/*.md` | `_shared.md` team rules + one prompt per agent |
| `backend/mcp_client.py` | The agents' only path to data: MCP toolset, per-role filter, identity stamping, audit hook |
| `backend/team.py` | Builds the 5 agents, the `delegate` tool, the audited agent loop |
| `backend/audit.py`, `backend/events.py` | Append-only audit writer; audit → dashboard feed / contributions |
| `backend/main.py` | FastAPI routes |
| `frontend/` | React + Vite + TypeScript dashboard |
| `scripts/build_run_report.py` | Builds the Problem 9 reports from the audit trail + API (fails if cash doesn't reconcile) |
| `output/` | harness, plan/actual page, smoke test, audit trail, design, resolved tickets, resolved board, screenshots |

---

## 2. The Database

- **Original (read-only reference):** `data/campus_customs.db`
- **Working copy (all updates go here):** `data/campus_customs_new.db`

The original file is never written to. `POST /api/reset` (MCP `reset_database`) copies it over the working copy for a fresh run.

**"Today" for the agents is `2026-08-31`** (from `desk.date_today`). Due dates and "overdue" are judged against this date, not the real calendar.

The MCP server adds one table to the working copy: **`approval_requests`**, the queue of things agents prepared for a human (§3).

---

## 3. Tables and Fields

### `desk` — the shop's front desk / clock
| Field | Type | Meaning |
|---|---|---|
| `date_today` | TEXT | The shop's "today" (2026-08-31) |
| `notes` | TEXT | Free-form notes for the shift (empty) |

**Why it matters:** Gives every agent the same "today" so they agree on what is overdue or due soon.

### `inventory` — what is on the shelves
| Field | Type | Meaning |
|---|---|---|
| `sku` | TEXT (PK part) | Product code, e.g. `CC-TEE-WHITE` |
| `name` | TEXT | Product name |
| `size` | TEXT (PK part) | S / M / L / XL, or OS (one size) |
| `qty` | INTEGER | Units on hand |
| `location` | TEXT | Aisle in the shop |

**Why it matters:** The Inventory agent's main source of truth: can we fill an order by SKU and size, or is there a shortage? Stock is tracked per **SKU + size**, not per SKU.

### `pricing` — what an item costs us and what we sell it for
| Field | Type | Meaning |
|---|---|---|
| `sku` | TEXT (PK) | Product code (joins to `inventory.sku`) |
| `unit_cost` | REAL | What the shop pays per unit |
| `list_price` | REAL | Normal selling price |

**Why it matters:** Accounting uses it to check margins and set the lowest price we can accept on a discount request (we can't sell below `unit_cost`).

### `vendors` — who can restock us
| Field | Type | Meaning |
|---|---|---|
| `id` | INTEGER (PK) | Vendor ID (joins to `invoices.vendor_id`) |
| `name` | TEXT | Vendor name |
| `specialty` | TEXT | What they supply (apparel, mugs, courier) |
| `lead_days` | INTEGER | Days from order to delivery |

**Why it matters:** Inventory finds who can restock a shortage and how long it will take. There is no direct SKU→vendor link, so the agent matches by `specialty` (apparel → Bulldog Print Co, mugs → Elm City Gifts).

### `leases` — the shop space
| Field | Type | Meaning |
|---|---|---|
| `id` | INTEGER (PK) | Lease ID (joins to `tickets.lease_id`) |
| `space_name` | TEXT | Which space (Chapel Street shop) |
| `landlord` | TEXT | Who we pay |
| `monthly_rent` | REAL | Rent amount |
| `next_due` | TEXT | Next rent due date |
| `notes` | TEXT | Extra lease notes (empty) |

**Why it matters:** The Facilities agent checks rent notices against the real lease, so it doesn't trust an email's amount or date blindly.

### `cash_accounts` — money available
| Field | Type | Meaning |
|---|---|---|
| `name` | TEXT (PK) | Account name (`checking`) |
| `balance` | REAL | Current balance |
| `date` | TEXT | Date of that balance |

**Why it matters:** Accounting must confirm there is enough cash before proposing any payment. Several bills compete for the same $3,400.

### `payments` — money that has actually gone out (empty to start)
| Field | Type | Meaning |
|---|---|---|
| `id` | INTEGER (PK) | Payment ID |
| `kind` | TEXT | What was paid (e.g. rent, invoice) |
| `ref_id` | INTEGER | ID of the lease/invoice it pays |
| `amount` | REAL | Amount paid |
| `account` | TEXT | Which cash account it came from |
| `paid_at` | TEXT | When it was paid |
| `approved_by` | TEXT | **Human** who approved it |

**Why it matters:** This is the audit trail. A row should only be written **after a human approves**. Agents prepare payments; they never pay on their own.

### `invoices` — bills we owe vendors
| Field | Type | Meaning |
|---|---|---|
| `id` | INTEGER (PK) | Invoice ID (joins to `tickets.invoice_id`) |
| `vendor_id` | INTEGER (FK → vendors) | Who sent the bill |
| `amount` | REAL | Amount owed |
| `due_date` | TEXT | When it is due |
| `status` | TEXT | `open` / paid |
| `description` | TEXT | What the bill is for |

**Why it matters:** Accounting tracks unpaid and overdue bills. An unpaid vendor bill can hold up a restock that a customer is waiting for.

### `tickets` — the work queue
| Field | Type | Meaning |
|---|---|---|
| `id` | INTEGER (PK) | Ticket ID |
| `type` | TEXT | `customer_order`, `rent_notice`, `price_override` |
| `requester` | TEXT | Who asked |
| `subject` | TEXT | Short title |
| `sku`, `size`, `qty` | TEXT/TEXT/INTEGER | Product details (for orders/discounts) |
| `lease_id` | INTEGER (FK → leases) | Linked lease (for rent) |
| `invoice_id` | INTEGER (FK → invoices) | Linked bill |
| `status` | TEXT | `open` / in progress / closed |
| `notes` | TEXT | The request in plain words |
| `created_at` | TEXT | When it came in |

**Why it matters:** The Boss agent's inbox. Each ticket's `type` decides which specialist agents get pulled in, and the link fields tell them where to look.

### `approval_requests` — the human approval queue (added by the MCP server)
| Field | Type | Meaning |
|---|---|---|
| `id` | INTEGER (PK) | Request ID shown on the dashboard |
| `ticket_id` | INTEGER (FK → tickets) | Ticket it belongs to |
| `kind` | TEXT | `invoice_payment`, `rent_payment`, `purchase_order`, `price_quote`, `customer_message` |
| `ref_id` | INTEGER | Invoice id / lease id / vendor id, depending on `kind` |
| `sku`, `size`, `qty`, `unit_price` | | Order / quote details |
| `amount` | REAL | **Computed by the server from the database**, never typed by an agent |
| `summary`, `message` | TEXT | What the human reads; the full draft for customer messages |
| `requested_by` | TEXT | Agent that filed it (stamped by the backend, not the model) |
| `status` | TEXT | `pending` → `approved` / `rejected` |
| `created_at`, `decided_by`, `decided_at`, `decision_note` | TEXT | Audit fields; `decided_by` is the human |

**Why it matters:** this is the line between agents and money. Agents can only add `pending` rows here. Only a human approval turns a row into a `payments` row and a lower `cash_accounts.balance`.

### How the tables connect

```
tickets ──sku/size──▶ inventory ──sku──▶ pricing
   │
   ├──lease_id────▶ leases
   │
   └──invoice_id──▶ invoices ──vendor_id──▶ vendors

payments.ref_id ──▶ leases.id (rent) / invoices.id (invoice) / approval_requests.id (purchase_order)
cash_accounts.name ◀── payments.account
approval_requests.ticket_id ──▶ tickets.id
approval_requests (approved, money-out) ──▶ payments row + cash_accounts.balance − amount
```

---

## 4. The Three Tickets: What Each One Touches

Starting state: checking balance **$3,400** on 2026-08-31.

### Ticket 101: `customer_order`, Tauhid Zaman, 1 × Bulldog Tee size S
- **inventory:** `CC-TEE-WHITE / S` has **qty 0**, so we can't ship today.
- **invoices → 501:** Bulldog Print Co (vendor 1), **$840**, "Rush reprint CC-TEE-WHITE S", due **2026-08-28**, still **open**, so it's **3 days overdue**.
- **vendors → 1:** Bulldog Print Co, apparel reprint, 5-day lead time.
- **pricing:** cost $8.00, list $28.00.
- **The catch:** the restock the customer needs is tied to an overdue bill. The likely flow is Inventory sees the shortage, Accounting flags invoice 501 for payment approval, and Customer Service tells the customer the honest delay.
- **Agents:** Boss → Inventory, Accounting, Customer Service.

### Ticket 102: `rent_notice`, Elm City Properties, "shop rent due in 2 days"
- **leases → 1:** Chapel Street shop, **$2,400/month**, next due **2026-09-02**. That matches "2 days" from 2026-08-31.
- **The catch:** rent is $2,400 out of a $3,400 balance. Paying rent **and** invoice 501 = $3,240, which leaves only **$160**. Both fit, but just barely, so a human should approve each payment.
- **Agents:** Boss → Facilities, Accounting.

### Ticket 103: `price_override`, Yale AI Club, 20 × hoodie size M at a bulk discount
- **inventory:** `CC-HOOD-NAVY / M` has **qty 8**, so we're **12 short** of 20.
- **pricing:** cost $22.00, list $58.00 ($36 margin, 62%). At list, 20 hoodies = $1,160. Any discount must stay above $22/unit.
- **vendors:** restock from Bulldog Print Co (apparel, 5-day lead), and that vendor already has an overdue bill (invoice 501).
- **The catch:** this needs a margin decision plus a restock, so it's a human approval for the price and possibly a purchase order.
- **Agents:** Boss → Inventory, Accounting, Customer Service.

---

## 5. Other Things the Agents Should Notice

- **`CC-MUG-CREST / OS` is out of stock (qty 0)** but no ticket mentions it. Inventory could flag it (Elm City Gifts, 3-day lead).
- **Low stock:** `CC-TEE-WHITE / XL` (2), `CC-TEE-WHITE / L` (3), `CC-HOOD-NAVY / S` (4).
- **Only one cash account** (checking). Every payment draws from the same $3,400.
- **`payments` is empty**, so nothing has been paid yet. It's where human-approved payments will be recorded.

---

## 6. MCP Server: All 17 Tools

Server: `mcp_server/server.py` (FastMCP, name `campus-customs`, stdio). Database: `data/campus_customs_new.db`. Read tools open SQLite `mode=ro`. Every shop fact the agents, the API, or the dashboard see comes through these tools.

| # | Tool | Tables used | R/W | Who may call | Ticket(s) |
|---|---|---|---|---|---|
| 1 | `list_open_tickets()` | `tickets`, `desk` | read | Boss, backend | all |
| 2 | `list_tickets()` | `tickets`, `approval_requests`, `desk` | read | dashboard | all |
| 3 | `get_ticket(ticket_id)` | `tickets`, `desk` | read | all agents | 101, 102, 103 |
| 4 | `update_ticket_status(ticket_id, status)` | `tickets` | **write** | **Boss only**; never `resolved` | 101, 102, 103 |
| 5 | `check_stock(sku, size?, qty_needed?)` | `inventory` | read | Inventory, Customer Service | 101, 103 |
| 6 | `list_vendors(specialty?)` | `vendors` | read | Inventory, Accounting | 101, 103 |
| 7 | `get_pricing(sku, qty?)` | `pricing` | read | Accounting | 103 |
| 8 | `get_invoice(invoice_id)` | `invoices`, `vendors`, `desk` | read | Accounting | 101 |
| 9 | `get_lease(lease_id)` | `leases`, `desk` | read | Facilities, Accounting | 102 |
| 10 | `get_cash_position()` | `cash_accounts`, `invoices`, `leases`, `approval_requests`, `desk` | read | Boss, Accounting, dashboard | 101, 102, 103 |
| 11 | `list_payments()` | `payments` | read | dashboard | cash tab |
| 12 | `list_approval_requests(ticket_id?, status?)` | `approval_requests` | read | Boss, Accounting, Facilities, Customer Service, dashboard | 101, 102, 103 |
| 13 | `request_approval(ticket_id, kind, summary, …)` | writes `approval_requests`; reads `tickets`, `invoices`, `leases`, `vendors`, `inventory`, `pricing`, `cash_accounts` | **write** | **Accounting** (money kinds, quotes); **Customer Service** (messages) | 101, 102, 103 |
| 14 | `approve_request(request_id, approved_by)` | `approval_requests`, `cash_accounts`, `payments`, `invoices`, `leases`, `tickets`, `desk` | **write** | **human only** (dashboard Approve) | money moves here only |
| 15 | `reject_request(request_id, decided_by, reason?)` | `approval_requests`, `tickets` | **write** | **human only** | |
| 16 | `resolve_ticket(ticket_id, resolved_by, note?)` | `tickets`, `approval_requests` | **write** | **backend only**, after a successful run | |
| 17 | `reset_database(confirm="RESET")` | whole file (original → working copy) | **write** | **human only** | |

**Guardrails built into the write tools**
- `request_approval` computes every amount itself: invoice amount, lease rent, unit cost × qty. It refuses a quote below unit cost or above list price, and refuses a money-out request bigger than cash on hand. It **warns** when pending money-out would exceed cash (this fired on ticket 103's purchase order), returns an existing pending request instead of filing a duplicate, and enforces which role can file which kind.
- `approve_request` runs inside `BEGIN IMMEDIATE` (no double approvals). It re-checks that the invoice is still open and that cash covers the amount. Then it writes `payments`, lowers `cash_accounts.balance`, and marks the invoice `paid` or moves the lease's `next_due` forward a month.
- `approve_request`, `reject_request`, `resolve_ticket` and `reset_database` refuse an actor named after an agent. No agent role lists them, and the backend's MCP hook blocks them if an agent ever tries (`guardrail_block`).

### 6.1 The three core ticket tools (Problem 3)

#### Tool 1: `check_stock(sku, size=None, qty_needed=None)`
- **Reads:** `inventory` (`sku`, `name`, `size`, `qty`, `location`)
- **Unlocks ticket:** **101** (Tauhid Zaman, 1 × Classic Bulldog Tee, size S)
- **Why:** Ticket 101 asks for `CC-TEE-WHITE` in size **S**. Stock is stored per SKU **and** size, so `check_stock("CC-TEE-WHITE", "S", qty_needed=1)` returns `qty: 0, can_fill: false, shortage: 1`. That proves the order can't ship from the shelf today and starts the restock path (vendor Bulldog Print Co + overdue invoice 501), rather than letting Customer Service promise a tee we don't have.
- **Verified output:** `{'sku': 'CC-TEE-WHITE', 'size': 'S', 'qty': 0, 'location': 'Aisle B', 'in_stock': False, 'can_fill': False, 'shortage': 1}`
- **Also used by** ticket 103: `check_stock("CC-HOOD-NAVY", "M", 20)` → `qty: 8, shortage: 12`.

#### Tool 2: `get_lease(lease_id)`
- **Reads:** `leases` (`space_name`, `landlord`, `monthly_rent`, `next_due`, `notes`), plus `desk.date_today` for the shop's "today"
- **Unlocks ticket:** **102** (Elm City Properties, "Rent due", `lease_id = 1`)
- **Why:** Ticket 102 is just an email saying "shop rent due in 2 days." `get_lease(1)` checks it against the real lease. The landlord matches (Elm City Properties), rent is **$2,400**, and it's due **2026-09-02**, which is `days_until_due: 2` from the shop's 2026-08-31. So Facilities can confirm the notice is real and Accounting knows the exact amount to queue for approval. Nobody pays an amount just because an email said so.
- **Verified output:** `{'space_name': 'Chapel Street shop', 'landlord': 'Elm City Properties', 'monthly_rent': 2400.0, 'next_due': '2026-09-02', 'shop_today': '2026-08-31', 'days_until_due': 2, 'overdue': False}`

#### Tool 3: `get_pricing(sku, qty=1)`
- **Reads:** `pricing` (`unit_cost`, `list_price`)
- **Unlocks ticket:** **103** (Yale AI Club, 20 × Basic Hoodie Big Yale, size M, bulk discount)
- **Why:** Ticket 103 is a `price_override`: the club wants a discount on 20 hoodies. `get_pricing("CC-HOOD-NAVY", 20)` shows a **$22 unit cost** against a **$58 list price** ($36 / 62.1% margin, $1,160 at list vs. $440 cost). That gives Accounting and the Boss a hard price floor and room to offer a real bulk discount without selling at a loss. The final price still goes to a human for approval.
- **Verified output:** `{'unit_cost': 22.0, 'list_price': 58.0, 'margin_per_unit': 36.0, 'margin_pct': 62.1, 'qty': 20, 'total_at_list': 1160.0, 'total_cost': 440.0}`

---

## 7. The Agent Team

Five PydanticAI agents, all on **`gpt-6-luna`** via Portkey (`PORTKEY_API_KEY` from `.env`; `reasoning_effort="none"`, which this deployment requires for tool calls). Each role is a `RoleSpec` in `backend/agents/<role>.py` with its own prompt in `backend/prompts/<role>.md`, plus the shared rules in `_shared.md`.

| Agent | Job | MCP tools it may call | Can file | Returns |
|---|---|---|---|---|
| 👔 **Boss** | Reads the ticket, routes work, weighs cash across tickets, sets ticket status, makes the final call | `list_open_tickets`, `get_ticket`, `get_cash_position`, `list_approval_requests`, `update_ticket_status` | none | `TicketDecision` |
| 📦 **Inventory** | Stock by SKU + size, shortages, restock vendor + earliest restock date | `get_ticket`, `check_stock`, `list_vendors` | none | `AgentReport` |
| 🧮 **Accounting** | Invoices, rent amounts, cash, margins and the discount floor (≤15% off for 10+ units, never below cost) | `get_ticket`, `get_pricing`, `get_invoice`, `get_lease`, `get_cash_position`, `list_vendors`, `list_approval_requests`, `request_approval` | payments, purchase orders, price quotes | `AgentReport` |
| 🏬 **Facilities** | Verifies rent notices against the lease (landlord, amount, due date); flags mismatches as possible scams | `get_ticket`, `get_lease`, `list_approval_requests` | none | `AgentReport` |
| 💬 **Customer Service** | Drafts honest customer messages (no costs, margins, or unpaid bills; nothing promised before approval) | `get_ticket`, `check_stock`, `list_approval_requests`, `request_approval` | customer messages | `AgentReport` |

Each agent sees only its role's tools (`MCPToolset.filtered`).

**Full connectivity:** every agent has a `delegate(to_agent, task)` tool that can reach **any** other agent. The child runs its own loop and returns its structured report. Limits: no delegating to yourself, no calling an agent already waiting higher in the chain (no A→B→A loops), max depth 3, max 8 hand-offs per ticket. Refusals go back to the model and into the audit (`delegation_refused`). Specialist-to-specialist hand-offs are possible: Accounting → Inventory happened in a Problem 5 test run. In the final run the Boss chose to do all the routing itself (§12).

**The agent loop:** `Team.run_agent()` drives each agent with `agent.iter()`, node by node (user prompt → model request → model response with tool calls → … → end), and writes every node to the audit trail. One MCP stdio connection is shared by all agents, and all agents on a ticket share one `RunUsage`, so limits count the whole team.

---

## 8. Audit Trail

`output/audit_trail.json` is one JSON array, **append-only**. `backend/audit.py` loads it, adds a record, and writes it back atomically (temp file + `os.replace`); runs never clear it. Every record has `ts`, `seq`, `event`, and where relevant `run_id`, `agent_run_id`, `ticket_id`, `agent`, `parent_agent`, `depth`, `chain`.

| Event | Written when |
|---|---|
| `ticket_run_start` / `ticket_run_end` / `ticket_run_aborted` / `ticket_run_error` | A team run starts / ends (decision + total usage) / hits a limit / fails |
| `agent_step` | **Every node of every agent loop**: prompt, model request (tool returns), model response (text, tool calls with args, tokens), final output |
| `mcp_tool_result` / `mcp_tool_error` | Every MCP call: tool, args (with backend-stamped identity), result, ms |
| `delegation_start` / `delegation_end` / `delegation_refused` / `delegation_error` | Every hand-off: from → to, task text, report or reason |
| `guardrail_block` | An agent tried a human-only tool |
| `ticket_resolved` | Backend marked a ticket resolved after a successful run |
| `human_approved` / `human_rejected` | A person clicked Approve / Reject (with payment id and old → new balance) |
| `database_reset` | The working DB was restored from the original |

At the end of Problem 9 the file holds 553 records: earlier test runs plus the final clean run (#352 reset → #553 last approval).

---

## 9. API Routes

`backend/main.py` (FastAPI). Start from `backend/` with `uvicorn main:app --reload --port 8000`. Base URL **`http://localhost:8000`**, docs at `/docs`. CORS allows `http://localhost:5173` (plus Vite on any other localhost port). `main.py` never opens the database; every route calls an MCP tool.

- `GET  http://localhost:8000/api/health`: server is up; whether a team run is in progress.
- `GET  http://localhost:8000/api/tickets`: all tickets with `status` **open** / **resolved**, raw `stage`, approval counts (`list_tickets`).
- `GET  http://localhost:8000/api/tickets/{id}`: one ticket with its approval requests and the latest run's decision.
- `GET  http://localhost:8000/api/tickets/{id}/contributions`: per-agent summary of the ticket's newest run (status, summary, MCP tools used, hand-offs, requests filed).
- `POST http://localhost:8000/api/run` `{"ticket_id": 101}`: starts the team on a ticket in the background and returns a `run_id` (409 if busy or already resolved).
- `GET  http://localhost:8000/api/runs`: runs since the server started, with status and decision.
- `GET  http://localhost:8000/api/runs/{run_id}`: one run's status/decision (polled by the dashboard).
- `GET  http://localhost:8000/api/events?since=&ticket_id=&run_id=&latest_run=&limit=`: activity feed from the audit trail: what each agent said, tools used (args + result), hand-offs, decisions, human actions.
- `GET  http://localhost:8000/api/approvals?status=pending&ticket_id=`: requests the agents prepared (`list_approval_requests`).
- `POST http://localhost:8000/api/approvals/{id}/approve` `{"approved_by": "Kalab"}`: **the only route that moves money** (`approve_request`).
- `POST http://localhost:8000/api/approvals/{id}/reject` `{"decided_by": "Kalab", "reason": ""}`: declines a request; nothing paid or sent (`reject_request`).
- `GET  http://localhost:8000/api/cash`: current **checking balance** from `cash_accounts`, plus pending money-out (`get_cash_position`).
- `GET  http://localhost:8000/api/payments`: money that actually left checking (`list_payments`).
- `POST http://localhost:8000/api/reset` `{"confirm": "RESET"}`: restores the working DB from the original for a fresh run (`reset_database`). The audit trail is kept.

**Resolved rule:** when a run finishes and the Boss's decision isn't `blocked` / `in_progress`, the backend calls `resolve_ticket`. Prepared requests stay in the approval queue for the human.

---

## 10. Dashboard

`frontend/` (React + Vite + TypeScript), `npm run dev` → `http://localhost:5173` (`VITE_API_BASE` overrides the API URL; `?ticket=102` opens a ticket). Full design rationale: `output/design.md`.

- **Header (sticky):** shop date, "N awaiting approval" chip, the **Checking** tile (counts down with a red −$X chip when a payment is approved), "Approving as" name, Reset.
- **Left:** ticket queue (Open / ● Running / ✓ Resolved, "⏳ N waiting" per ticket) and **Needs your approval** ("Approve & pay $X" / Reject; customer drafts shown in full).
- **Center:** selected ticket, **Run agent team**, green **Resolved** banner, the Boss's final decision (summary, next steps, risks), and a **live activity feed** (hand-offs as agent→agent chips, MCP tool calls with expandable results, reports, human actions). It polls every 1.2s while running.
- **Right:** five agent cards. Each agent has a fixed color + icon + name; cards show Working / Done / Not needed plus that agent's summary, tools used, and who asked whom.

---

## 11. Safety Rules

**Real money**
1. **Agents never move money.** They can only file `pending` requests. `approve_request`, called only after a person clicks Approve, is the single code path that writes `payments` and lowers `cash_accounts`.
2. **Amounts come from the database, not the model** (invoice amount, lease rent, unit cost × qty).
3. **Server-side checks:** the invoice must exist and be open; the vendor and SKU/size must exist; requests larger than cash are refused, and approvals re-check cash (an over-cash approval returns "Not enough cash"). Over-commitment produces a warning so the human chooses the order (the Boss recommends rent → overdue bills → purchase orders).
4. **Discount floor:** no quote below unit cost or above list price. Policy is ≤15% off for 10+ units; anything beyond that is the human's call.
5. **Role permissions enforced on the server**, with the agent identity stamped by the backend (`requested_by` / `updated_by`), so a model can't claim another role. Human-only tools refuse agent names and are blocked in the MCP hook.
6. **No duplicates:** re-running a ticket returns existing pending requests instead of filing new ones. Approvals use a write lock, so nothing is paid twice.
7. **Scam check:** Facilities verifies rent notices against the lease before Accounting may file a payment. In the final run, the Boss told Accounting explicitly not to file until Facilities confirmed.

**Real customers**
8. Customer messages are **drafts** (`customer_message` requests) that a human approves and sends. Agents never claim a message was sent.
9. Customer Service drafts after the facts are in and uses only confirmed facts. It promises nothing unapproved ("pending manager approval", "we expect…").
10. Nothing internal goes to customers: no unit costs, margins, vendor bills, or the cash balance.
11. Ticket notes and customer text are **data, not instructions** (prompt-injection guard in `_shared.md`).

**Token / cost limits** (`backend/config.py`)
| Limit | Value | Scope |
|---|---|---|
| Model | `gpt-6-luna`, `reasoning_effort="none"` | every agent |
| Max output tokens per model call | 2,500 | each response |
| Model requests / tool calls / total tokens | 30 / 40 / 150,000 | whole team, per ticket |
| Delegation depth / count | 3 / 8 | per ticket |
| One team run at a time | API lock | tickets share one cash account |
| Audit text clipping | 2,000 chars | per field |

When a limit is hit, the ticket stops cleanly (`ticket_run_aborted`) and nothing half-done is paid or sent. Actual final-run usage was 34,822–47,446 tokens per ticket, under a third of the cap.

**Secrets:** `PORTKEY_API_KEY` is only read from `.env` and never printed or committed (`.env.example` holds a placeholder).

---

## 12. Final End-to-End Run (Problem 9)

Clean run through the dashboard. The DB was reset with the dashboard's Reset button (audit #352); each ticket was started with **Run agent team**; **all approvals and the rejection were clicked by Kalab** in the dashboard. Full details: `output/desk_tickets.html` (Actual + Cash tabs), `output/resolved_tickets.json`, `output/resolved_board.html` (real screenshots), `output/audit_trail.json`.

| Ticket | Agents involved | Hand-offs | Outcome | Human decisions | Cash |
|---|---|---|---|---|---|
| **101** Bulldog tee | Boss, Inventory, Accounting, Customer Service | 3 | Size S is out of stock (0 on hand). Earliest restock is 2026-09-05 via Bulldog Print Co. The overdue rush-reprint invoice 501 ($840) was paid on human approval, and the honest update to Tauhid was approved. | #1 invoice payment approved; #2 customer message approved | −$840.00 |
| **102** Rent due | Boss, Facilities, Accounting | 3 | The rent notice was verified against lease 1 (Elm City Properties, $2,400 due 2026-09-02). Rent was paid on human approval, and the lease's next due date moved to 2026-10-02. | #3 rent payment approved | −$2,400.00 |
| **103** Bulk hoodie discount | Boss, Inventory, Accounting, Customer Service | 4 | 8 of 20 hoodies are on hand (12 short, restock earliest 2026-09-05). The bulk quote of $49.30 × 20 = $986 was approved. The $264 restock purchase order was rejected by the human. With rent and the invoice approved, only $160 remained, less than the $264 it needed. The reply to Yale AI Club was approved. | #4 customer message approved; #5 purchase order rejected; #6 price quote approved | $0.00 |

**Cash reconciliation**
| | |
|---|---|
| Starting checking balance (after reset) | $3,400.00 |
| Ticket 101: invoice 501 payment (request #1, payment #2) | −$840.00 |
| Ticket 102: rent payment (request #3, payment #1) | −$2,400.00 |
| Ticket 103: no payment (purchase order #5 for $264 was **rejected**; the approved $986 quote is money in only when the club pays) | $0.00 |
| **Calculated ending balance** | **$160.00** |
| **`cash_accounts.balance` (checking)** | **$160.00** |
| Difference | **$0.00 ✓** (also: `payments` total $3,240.00) |

**Plan vs. actual, in short**
- **101 matched the plan:** Inventory first, then Accounting (invoice 501 tied to this tee, paid on approval, no new order), Customer Service last. Facilities was skipped.
- **102 met the plan's safety intent but not its routing:** Facilities verified the notice first and the rent payment was filed only afterwards. But the Boss relayed between the two specialists (3 hand-offs) instead of the planned Facilities → Accounting hand-off.
- **103 differed most:** the Boss sent Inventory and Accounting together rather than Accounting first, and relayed facts itself rather than Accounting → Inventory. Accounting **filed** the purchase order (with the server's over-cash warning) where the plan said hold. The human rejected it, so the cash outcome matched the plan.
- **Pattern:** with this model the Boss prefers to be the hub (every hand-off came from the Boss) and to send fact-finding tasks in parallel. Specialist-to-specialist delegation is available but wasn't chosen in the final run.
