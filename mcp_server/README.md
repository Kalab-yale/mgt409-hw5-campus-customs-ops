# Campus Customs MCP Server

## What it's for

This is the shared toolbox for the Campus Customs multi-agent team. All five agents (Boss, Inventory, Accounting, Facilities, Customer Service) get every shop fact through these tools. None of them touch the database directly, and the backend has no other data layer. That way every agent sees the same numbers, and answers come from real data, not the model's guesses.

Built with [FastMCP](https://gofastmcp.com). Read tools open the database in SQLite `mode=ro`. Agents get two write tools, and neither moves money:
- `request_approval` files a **pending** request for a human to approve.
- `update_ticket_status` moves a ticket through the queue. It can never resolve one.

Four **human/backend-only** tools back the dashboard. No agent role is given them, and the backend refuses them if an agent tries:
- `approve_request` is the **only** code that moves money.
- `reject_request` declines a request.
- `resolve_ticket` marks a ticket resolved after a successful team run.
- `reset_database` restores the original data.

## Database

`data/campus_customs_new.db`: the working copy of the original `data/campus_customs.db`. The path is resolved relative to this folder, so the server works from any directory.

On startup the server adds one table if it's missing: **`approval_requests`**, the queue of things waiting for a human.

The shop's "today" comes from the `desk` table (`2026-08-31`), not the real calendar.

## Tools (17)

| Tool | Tables | What it returns / does |
|---|---|---|
| `list_open_tickets()` | `tickets`, `desk` | Every ticket that isn't resolved |
| `list_tickets()` | `tickets`, `approval_requests`, `desk` | All tickets with `status` open/resolved, raw `stage`, and approval counts (dashboard) |
| `get_ticket(ticket_id)` | `tickets`, `desk` | One ticket with its links (`sku`/`size`/`qty`, `lease_id`, `invoice_id`) |
| `update_ticket_status(ticket_id, status)` | `tickets` (write) | Boss only: `open` / `in_progress` / `awaiting_approval` / `blocked`. Never `resolved` |
| `check_stock(sku, size?, qty_needed?)` | `inventory` | Units on hand per SKU + size, aisle, can-fill, shortage |
| `list_vendors(specialty?)` | `vendors` | Restock vendors with lead days, filtered by specialty |
| `get_pricing(sku, qty?)` | `pricing` | Unit cost, list price, margin, totals for `qty` |
| `get_invoice(invoice_id)` | `invoices`, `vendors`, `desk` | Bill with vendor details and days overdue |
| `get_lease(lease_id)` | `leases`, `desk` | Landlord, monthly rent, next due, days until due |
| `get_cash_position()` | `cash_accounts`, `invoices`, `leases`, `approval_requests`, `desk` | Balance, open bills, rent due within 14 days, pending money-out, balance after each |
| `list_payments()` | `payments` | Money that actually left checking (only written by human approvals); used by the dashboard / Cash tab |
| `list_approval_requests(ticket_id?, status?)` | `approval_requests` | Requests waiting for, or already decided by, a human |
| `request_approval(ticket_id, kind, summary, …)` | `approval_requests` (write) + reads `tickets`, `invoices`, `leases`, `vendors`, `inventory`, `pricing`, `cash_accounts` | Files a **pending** `invoice_payment`, `rent_payment`, `purchase_order`, `price_quote`, or `customer_message` |
| `approve_request(request_id, approved_by)` **human only** | `approval_requests`, `cash_accounts`, `payments`, `invoices`, `leases`, `tickets`, `desk` | Approves and carries out a request. Payments and POs lower the checking balance, write `payments`, and mark the invoice paid or move rent forward a month. Resolves the ticket when nothing is left pending |
| `reject_request(request_id, decided_by, reason?)` **human only** | `approval_requests`, `tickets` | Declines a request; nothing is paid or sent |
| `resolve_ticket(ticket_id, resolved_by, note?)` **backend only** | `tickets`, `approval_requests` | Marks a ticket resolved when the team run finished successfully; pending requests stay pending |
| `reset_database(confirm="RESET")` **human only** | whole file | Copies `campus_customs.db` over `campus_customs_new.db` for a fresh run |

### Guardrails inside `request_approval`
- Amounts for payments and purchase orders are **calculated from the database**, never passed in.
- A price quote below unit cost or above list price is refused.
- A money-out request larger than cash on hand is refused. A warning is added when pending requests together exceed cash.
- Role permissions: only `accounting` can file money requests and only `customer_service` can file customer messages. The backend sets `requested_by` from the running agent.
- If the same request is already pending, it's returned instead of being filed twice.

If a ticket, SKU, lease, invoice, or vendor doesn't exist, a tool returns `found: false` (or `ok: false`) with a message instead of making something up.

## Run

```bash
cd <repo root>
source .venv/bin/activate
pip install -r requirements.txt
python mcp_server/server.py   # stdio transport
```

The agent backend and the FastAPI routes start this server themselves over stdio (`backend/mcp_client.py`). Claude Code connects through `.mcp.json`.
