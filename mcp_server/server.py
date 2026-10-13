"""Campus Customs MCP server: the one place every agent gets shop facts from.

All agents (Boss, Inventory, Accounting, Facilities, Customer Service) call
these tools instead of touching the database directly. Every answer comes
straight from data/campus_customs_new.db; nothing is guessed or invented.

Read tools open the database read-only. Agent-facing writes are:
  - request_approval: files a *pending* request for a human to approve
    (payments, purchase orders, discounts, customer messages). Amounts are
    computed here from the database, never taken from the model.
  - update_ticket_status: moves a ticket through the work queue (never to resolved).

Human-only tools (called by the dashboard backend after a person clicks a
button; no agent role is ever given them):
  - approve_request: the ONLY code path that moves money. Pays the invoice /
    rent / purchase order, lowers the checking balance, writes `payments`.
  - reject_request: declines a pending request.
  - resolve_ticket: marks a ticket resolved once the team run finished successfully.
  - reset_database: restores the working copy from the original file.

Run (stdio):  python mcp_server/server.py
"""

from __future__ import annotations

import shutil
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal

from fastmcp import FastMCP

HERE = Path(__file__).resolve().parent
DB_PATH = HERE.parent / "data" / "campus_customs_new.db"
ORIGINAL_DB_PATH = HERE.parent / "data" / "campus_customs.db"

mcp = FastMCP("campus-customs")

ApprovalKind = Literal[
    "invoice_payment", "rent_payment", "purchase_order", "price_quote", "customer_message"
]
MONEY_OUT_KINDS = ("invoice_payment", "rent_payment", "purchase_order")

# Which agent may file which kind of approval request. The agent name is set by
# the backend from the running agent, not typed by the model.
ALLOWED_KINDS: dict[str, tuple[str, ...]] = {
    "accounting": ("invoice_payment", "rent_payment", "purchase_order", "price_quote"),
    "customer_service": ("customer_message",),
}
TICKET_STATUSES = ("open", "in_progress", "awaiting_approval", "blocked")  # agents can't set "resolved"
DONE_STATUSES = ("resolved", "closed")
AGENT_NAMES = ("boss", "inventory", "accounting", "facilities", "customer_service")
PAYMENT_KIND = {"invoice_payment": "invoice", "rent_payment": "rent", "purchase_order": "purchase_order"}


# ---------------------------------------------------------------- helpers

@contextmanager
def _connect(write: bool = False) -> Iterator[sqlite3.Connection]:
    """Open the working database. Read-only unless a write tool asks otherwise."""
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found: {DB_PATH}")
    mode = "rw" if write else "ro"
    conn = sqlite3.connect(f"file:{DB_PATH}?mode={mode}", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        if write:
            conn.commit()
    finally:
        conn.close()


def _ensure_schema() -> None:
    """Add the approval queue table if this copy of the database doesn't have it yet."""
    with _connect(write=True) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS approval_requests (
                id INTEGER PRIMARY KEY,
                ticket_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                ref_id INTEGER,
                sku TEXT,
                size TEXT,
                qty INTEGER,
                unit_price REAL,
                amount REAL,
                summary TEXT NOT NULL,
                message TEXT,
                requested_by TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                decided_by TEXT,
                decided_at TEXT,
                FOREIGN KEY (ticket_id) REFERENCES tickets(id)
            )
            """
        )
        columns = {r["name"] for r in conn.execute("PRAGMA table_info(approval_requests)")}
        if "decision_note" not in columns:
            conn.execute("ALTER TABLE approval_requests ADD COLUMN decision_note TEXT")


def _shop_today(conn: sqlite3.Connection) -> str:
    """The shop's own 'today' from the desk table (not the real calendar)."""
    return conn.execute("SELECT date_today FROM desk LIMIT 1").fetchone()["date_today"]


def _days_between(start: str, end: str) -> int:
    return (date.fromisoformat(end) - date.fromisoformat(start)).days


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _add_month(iso_day: str) -> str:
    """2026-09-02 -> 2026-10-02 (clamped to the month's last day)."""
    d = date.fromisoformat(iso_day)
    year, month = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    days_in_month = (date(year + (month == 12), month % 12 + 1, 1) - date(year, month, 1)).days
    return date(year, month, min(d.day, days_in_month)).isoformat()


def _require_human(name: str) -> str | None:
    """Return an error message unless `name` looks like a person, not an agent."""
    if not name.strip():
        return "A human name is required."
    if name.strip().lower() in AGENT_NAMES:
        return "Agents cannot approve, reject, or reset. This needs a human."
    return None


# ---------------------------------------------------------------- tickets

@mcp.tool
def list_open_tickets() -> dict:
    """List every ticket that is not closed: id, type, requester, subject, status."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, type, requester, subject, status, created_at FROM tickets "
            "WHERE status NOT IN ('resolved', 'closed') ORDER BY created_at"
        ).fetchall()
        today = _shop_today(conn)
    return {"shop_today": today, "count": len(rows), "tickets": [dict(r) for r in rows]}


@mcp.tool
def get_ticket(ticket_id: int) -> dict:
    """Get one ticket in full, including its linked sku/size/qty, lease_id, and invoice_id.

    Also returns the shop's 'today' (from the desk table) so due dates can be judged.

    Args:
        ticket_id: Ticket ID, e.g. 101.
    """
    with _connect() as conn:
        row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        today = _shop_today(conn)
    if row is None:
        return {"found": False, "ticket_id": ticket_id, "message": f"No ticket with id {ticket_id}."}
    return {"found": True, "shop_today": today, **dict(row)}


@mcp.tool
def list_tickets() -> dict:
    """List ALL tickets (any status) with a simple open/resolved flag and approval counts.

    `status` is "resolved" once the team run finished successfully (or a human
    decided every request on it); otherwise "open". `stage` is the raw status.
    """
    with _connect() as conn:
        today = _shop_today(conn)
        rows = conn.execute(
            """
            SELECT t.*,
                   (SELECT COUNT(*) FROM approval_requests a WHERE a.ticket_id = t.id AND a.status = 'pending') AS pending_approvals,
                   (SELECT COUNT(*) FROM approval_requests a WHERE a.ticket_id = t.id) AS total_approvals
            FROM tickets t ORDER BY t.id
            """
        ).fetchall()
    tickets = []
    for r in rows:
        t = dict(r)
        t["stage"] = t["status"]
        t["status"] = "resolved" if t["stage"] in DONE_STATUSES else "open"
        tickets.append(t)
    return {"shop_today": today, "count": len(tickets), "tickets": tickets}


@mcp.tool
def update_ticket_status(
    ticket_id: int,
    status: Literal["open", "in_progress", "awaiting_approval", "blocked"],
    updated_by: str = "",
) -> dict:
    """Move a ticket to open, in_progress, awaiting_approval, or blocked.

    Agents can never resolve a ticket; it resolves when a human has decided
    every request the team prepared for it.

    Args:
        ticket_id: Ticket ID.
        status: New status.
        updated_by: Set automatically by the backend to the calling agent.
    """
    if status not in TICKET_STATUSES:
        return {"ok": False, "message": f"Status must be one of {TICKET_STATUSES}; agents cannot close tickets."}
    if updated_by != "boss":
        return {"ok": False, "message": "Only the Boss agent can change a ticket's status."}
    with _connect(write=True) as conn:
        row = conn.execute("SELECT status FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if row is None:
            return {"ok": False, "message": f"No ticket with id {ticket_id}."}
        if row["status"] in DONE_STATUSES:
            return {"ok": False, "message": f"Ticket {ticket_id} is {row['status']}; only a human can reopen it."}
        conn.execute("UPDATE tickets SET status = ? WHERE id = ?", (status, ticket_id))
    return {"ok": True, "ticket_id": ticket_id, "old_status": row["status"], "new_status": status}


# ---------------------------------------------------------------- inventory & vendors

@mcp.tool
def check_stock(sku: str, size: str | None = None, qty_needed: int | None = None) -> dict:
    """Look up units on hand for a product by SKU and size.

    Args:
        sku: Product code, e.g. "CC-TEE-WHITE".
        size: S, M, L, XL, or OS. Leave empty to list every size of the SKU.
        qty_needed: Optional units the request needs; the reply then says
            whether stock covers it and how many units are short.
    """
    sku = sku.strip().upper()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT sku, name, size, qty, location FROM inventory WHERE sku = ? ORDER BY rowid",
            (sku,),
        ).fetchall()

    if not rows:
        return {"found": False, "sku": sku, "message": f"No inventory rows for SKU {sku}."}

    sizes = [dict(r) for r in rows]
    if size is None:
        return {"found": True, "sku": sku, "name": rows[0]["name"], "sizes": sizes}

    size = size.strip().upper()
    match = next((s for s in sizes if s["size"] == size), None)
    if match is None:
        return {
            "found": False,
            "sku": sku,
            "size": size,
            "message": f"{sku} is not stocked in size {size}.",
            "sizes_available": [s["size"] for s in sizes],
        }

    result = {"found": True, **match, "in_stock": match["qty"] > 0}
    if qty_needed is not None:
        result["qty_needed"] = qty_needed
        result["can_fill"] = match["qty"] >= qty_needed
        result["shortage"] = max(0, qty_needed - match["qty"])
    return result


@mcp.tool
def list_vendors(specialty: str | None = None) -> dict:
    """List restock vendors with their specialty and lead time in days.

    The database has no direct SKU-to-vendor link, so match on specialty
    (e.g. "apparel" for tees and hoodies, "mugs" for mugs).

    Args:
        specialty: Optional word to filter by, e.g. "apparel". Empty lists all vendors.
    """
    with _connect() as conn:
        if specialty:
            rows = conn.execute(
                "SELECT id, name, specialty, lead_days FROM vendors WHERE specialty LIKE ? ORDER BY id",
                (f"%{specialty.strip()}%",),
            ).fetchall()
        else:
            rows = conn.execute("SELECT id, name, specialty, lead_days FROM vendors ORDER BY id").fetchall()
    return {"count": len(rows), "vendors": [dict(r) for r in rows]}


# ---------------------------------------------------------------- money

@mcp.tool
def get_pricing(sku: str, qty: int = 1) -> dict:
    """Get unit cost, list price, and margin for a SKU, with totals for a quantity.

    Use this before answering any discount or price-override request: the
    unit cost is the floor the shop cannot sell below without losing money.

    Args:
        sku: Product code, e.g. "CC-HOOD-NAVY".
        qty: Number of units the request is for (default 1).
    """
    sku = sku.strip().upper()
    with _connect() as conn:
        row = conn.execute(
            "SELECT sku, unit_cost, list_price FROM pricing WHERE sku = ?", (sku,)
        ).fetchone()

    if row is None:
        return {"found": False, "sku": sku, "message": f"No pricing for SKU {sku}."}

    unit_cost, list_price = row["unit_cost"], row["list_price"]
    margin = list_price - unit_cost
    return {
        "found": True,
        "sku": sku,
        "unit_cost": unit_cost,
        "list_price": list_price,
        "margin_per_unit": round(margin, 2),
        "margin_pct": round(margin / list_price * 100, 1),
        "qty": qty,
        "total_at_list": round(list_price * qty, 2),
        "total_cost": round(unit_cost * qty, 2),
    }


@mcp.tool
def get_invoice(invoice_id: int) -> dict:
    """Get a vendor invoice with the vendor's name and lead time, and how overdue it is.

    Days overdue are measured from the shop's 'today' in the desk table.

    Args:
        invoice_id: Invoice ID, e.g. the invoice_id on a ticket.
    """
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT i.id, i.vendor_id, v.name AS vendor_name, v.specialty AS vendor_specialty,
                   v.lead_days AS vendor_lead_days, i.amount, i.due_date, i.status, i.description
            FROM invoices i JOIN vendors v ON v.id = i.vendor_id
            WHERE i.id = ?
            """,
            (invoice_id,),
        ).fetchone()
        today = _shop_today(conn)

    if row is None:
        return {"found": False, "invoice_id": invoice_id, "message": f"No invoice with id {invoice_id}."}

    days_past_due = _days_between(row["due_date"], today)
    return {
        "found": True,
        **dict(row),
        "shop_today": today,
        "days_overdue": max(0, days_past_due) if row["status"] == "open" else 0,
        "overdue": row["status"] == "open" and days_past_due > 0,
    }


@mcp.tool
def get_lease(lease_id: int) -> dict:
    """Get a shop lease: space, landlord, monthly rent, and next due date.

    Also reports how many days remain until rent is due, measured from the
    shop's 'today' in the desk table, so a rent notice can be checked against
    the real lease terms.

    Args:
        lease_id: Lease ID, e.g. the lease_id on a rent_notice ticket.
    """
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, space_name, landlord, monthly_rent, next_due, notes FROM leases WHERE id = ?",
            (lease_id,),
        ).fetchone()
        today = _shop_today(conn)

    if row is None:
        return {"found": False, "lease_id": lease_id, "message": f"No lease with id {lease_id}."}

    days_until_due = _days_between(today, row["next_due"])
    return {
        "found": True,
        **dict(row),
        "shop_today": today,
        "days_until_due": days_until_due,
        "overdue": days_until_due < 0,
    }


@mcp.tool
def get_cash_position() -> dict:
    """Get cash on hand and everything competing for it.

    Returns each cash account's balance, open vendor invoices, rent due in the
    next 14 days, and money-out approval requests still pending, plus what the
    balance would be if all of them were paid.
    """
    with _connect() as conn:
        today = _shop_today(conn)
        accounts = [dict(r) for r in conn.execute("SELECT name, balance, date FROM cash_accounts")]
        invoices = [
            dict(r)
            for r in conn.execute(
                "SELECT id, vendor_id, amount, due_date, description FROM invoices WHERE status = 'open' ORDER BY due_date"
            )
        ]
        leases = [
            dict(r)
            for r in conn.execute("SELECT id, space_name, landlord, monthly_rent, next_due FROM leases")
            if 0 <= _days_between(today, r["next_due"]) <= 14
        ]
        pending = [
            dict(r)
            for r in conn.execute(
                f"SELECT id, ticket_id, kind, ref_id, amount, summary FROM approval_requests "
                f"WHERE status = 'pending' AND kind IN ({','.join('?' * len(MONEY_OUT_KINDS))})",
                MONEY_OUT_KINDS,
            )
        ]

    balance = sum(a["balance"] for a in accounts)
    open_invoices_total = sum(i["amount"] for i in invoices)
    rent_due_total = sum(l["monthly_rent"] for l in leases)
    pending_total = sum(p["amount"] or 0 for p in pending)
    return {
        "shop_today": today,
        "accounts": accounts,
        "total_balance": balance,
        "open_invoices": invoices,
        "open_invoices_total": open_invoices_total,
        "rent_due_next_14_days": leases,
        "rent_due_total": rent_due_total,
        "pending_money_out_requests": pending,
        "pending_money_out_total": pending_total,
        "balance_if_bills_and_rent_paid": round(balance - open_invoices_total - rent_due_total, 2),
        "balance_if_pending_requests_approved": round(balance - pending_total, 2),
    }


@mcp.tool
def list_payments() -> dict:
    """List money that has actually gone out (the `payments` table), newest last.

    Rows only appear here after a human approves a payment or purchase.
    """
    with _connect() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT id, kind, ref_id, amount, account, paid_at, approved_by FROM payments ORDER BY id")]
    return {"count": len(rows), "total": round(sum(r["amount"] for r in rows), 2), "payments": rows}


# ---------------------------------------------------------------- human approval queue

@mcp.tool
def list_approval_requests(ticket_id: int | None = None, status: str | None = None) -> dict:
    """List approval requests waiting for (or decided by) a human.

    Check this before filing a new request so the same thing isn't requested twice.

    Args:
        ticket_id: Optional ticket to filter by.
        status: Optional status filter: pending, approved, or rejected.
    """
    query, params = "SELECT * FROM approval_requests WHERE 1=1", []
    if ticket_id is not None:
        query, params = query + " AND ticket_id = ?", params + [ticket_id]
    if status:
        query, params = query + " AND status = ?", params + [status]
    with _connect() as conn:
        rows = conn.execute(query + " ORDER BY id", params).fetchall()
    return {"count": len(rows), "requests": [dict(r) for r in rows]}


@mcp.tool
def request_approval(
    ticket_id: int,
    kind: ApprovalKind,
    summary: str,
    ref_id: int | None = None,
    sku: str | None = None,
    size: str | None = None,
    qty: int | None = None,
    unit_price: float | None = None,
    message: str | None = None,
    requested_by: str = "",
) -> dict:
    """File a PENDING request for a human to approve. Nothing is paid, ordered, or sent.

    The amount is always calculated here from the database, never supplied by the agent.

    What each kind needs:
      - invoice_payment:  ref_id = invoice id (amount = the invoice amount)
      - rent_payment:     ref_id = lease id (amount = the lease's monthly rent)
      - purchase_order:   ref_id = vendor id, sku, size, qty (amount = unit_cost x qty)
      - price_quote:      sku, qty, unit_price (must be >= unit cost and <= list price)
      - customer_message: message = the full draft to send to the ticket's requester

    Args:
        ticket_id: Ticket this request belongs to.
        kind: What is being requested.
        summary: One or two sentences a human can read to decide.
        ref_id: Invoice, lease, or vendor id (see above).
        sku: Product code (purchase_order, price_quote).
        size: Size (purchase_order).
        qty: Units (purchase_order, price_quote).
        unit_price: Proposed price per unit (price_quote).
        message: Draft text (customer_message).
        requested_by: Set automatically by the backend to the calling agent.
    """
    allowed = ALLOWED_KINDS.get(requested_by, ())
    if kind not in allowed:
        return {"ok": False, "message": f"Agent '{requested_by}' may not file '{kind}' requests. Allowed: {list(allowed) or 'none'}."}
    if not summary.strip():
        return {"ok": False, "message": "summary is required."}

    sku = sku.strip().upper() if sku else None
    size = size.strip().upper() if size else None
    warnings: list[str] = []

    with _connect(write=True) as conn:
        ticket = conn.execute("SELECT id, requester FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if ticket is None:
            return {"ok": False, "message": f"No ticket with id {ticket_id}."}

        amount: float | None = None
        if kind == "invoice_payment":
            inv = conn.execute("SELECT amount, status FROM invoices WHERE id = ?", (ref_id,)).fetchone()
            if inv is None:
                return {"ok": False, "message": f"No invoice with id {ref_id}."}
            if inv["status"] != "open":
                return {"ok": False, "message": f"Invoice {ref_id} is '{inv['status']}', not open."}
            amount = inv["amount"]
        elif kind == "rent_payment":
            lease = conn.execute("SELECT monthly_rent FROM leases WHERE id = ?", (ref_id,)).fetchone()
            if lease is None:
                return {"ok": False, "message": f"No lease with id {ref_id}."}
            amount = lease["monthly_rent"]
        elif kind == "purchase_order":
            if not (sku and size and qty and qty > 0):
                return {"ok": False, "message": "purchase_order needs sku, size, and a positive qty."}
            if conn.execute("SELECT 1 FROM vendors WHERE id = ?", (ref_id,)).fetchone() is None:
                return {"ok": False, "message": f"No vendor with id {ref_id}."}
            if conn.execute("SELECT 1 FROM inventory WHERE sku = ? AND size = ?", (sku, size)).fetchone() is None:
                return {"ok": False, "message": f"{sku} size {size} is not a stocked item."}
            price = conn.execute("SELECT unit_cost FROM pricing WHERE sku = ?", (sku,)).fetchone()
            if price is None:
                return {"ok": False, "message": f"No unit cost for {sku}, so the order can't be priced."}
            unit_price = price["unit_cost"]
            amount = round(unit_price * qty, 2)
        elif kind == "price_quote":
            if not (sku and qty and qty > 0 and unit_price is not None):
                return {"ok": False, "message": "price_quote needs sku, a positive qty, and unit_price."}
            price = conn.execute("SELECT unit_cost, list_price FROM pricing WHERE sku = ?", (sku,)).fetchone()
            if price is None:
                return {"ok": False, "message": f"No pricing for {sku}."}
            if unit_price < price["unit_cost"]:
                return {"ok": False, "message": f"Refused: ${unit_price:.2f} is below unit cost ${price['unit_cost']:.2f}; the shop would lose money."}
            if unit_price > price["list_price"]:
                return {"ok": False, "message": f"Refused: ${unit_price:.2f} is above list price ${price['list_price']:.2f}."}
            amount = round(unit_price * qty, 2)
        elif kind == "customer_message":
            if not (message and message.strip()):
                return {"ok": False, "message": "customer_message needs the draft text in `message`."}

        # Same request already waiting? Return it instead of filing a duplicate.
        dup = conn.execute(
            "SELECT id FROM approval_requests WHERE ticket_id = ? AND kind = ? AND status = 'pending' "
            "AND ref_id IS ? AND sku IS ? AND size IS ?",
            (ticket_id, kind, ref_id, sku, size),
        ).fetchone()
        if dup is not None:
            return {"ok": True, "duplicate": True, "request_id": dup["id"],
                    "message": f"A pending {kind} request already exists for ticket {ticket_id} (id {dup['id']})."}

        if kind in MONEY_OUT_KINDS:
            balance = conn.execute("SELECT COALESCE(SUM(balance), 0) AS b FROM cash_accounts").fetchone()["b"]
            if amount > balance:
                return {"ok": False, "message": f"Refused: ${amount:.2f} is more than the ${balance:.2f} cash on hand."}
            pending = conn.execute(
                f"SELECT COALESCE(SUM(amount), 0) AS p FROM approval_requests WHERE status = 'pending' "
                f"AND kind IN ({','.join('?' * len(MONEY_OUT_KINDS))})",
                MONEY_OUT_KINDS,
            ).fetchone()["p"]
            if pending + amount > balance:
                warnings.append(
                    f"With this request, pending money-out (${pending + amount:.2f}) exceeds cash on hand "
                    f"(${balance:.2f}). A human must choose what to approve first."
                )

        cur = conn.execute(
            """
            INSERT INTO approval_requests
                (ticket_id, kind, ref_id, sku, size, qty, unit_price, amount, summary, message,
                 requested_by, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
            """,
            (ticket_id, kind, ref_id, sku, size, qty, unit_price, amount, summary.strip(),
             message.strip() if message else None, requested_by, _now()),
        )

    return {
        "ok": True,
        "duplicate": False,
        "request_id": cur.lastrowid,
        "status": "pending",
        "kind": kind,
        "amount": amount,
        "recipient": ticket["requester"] if kind == "customer_message" else None,
        "warnings": warnings,
        "message": "Filed for human approval. Nothing has been paid, ordered, or sent.",
    }


# ---------------------------------------------------------------- human-only (dashboard)

@mcp.tool
def approve_request(request_id: int, approved_by: str) -> dict:
    """HUMAN ONLY. Approve a pending request and carry it out.

    Money-out kinds actually move money here, and nowhere else:
      - invoice_payment: pay the invoice (status -> paid)
      - rent_payment: pay rent (lease next_due moves forward one month)
      - purchase_order: pay the vendor for the order
    Each one lowers the checking balance and writes a row to `payments`.
    price_quote and customer_message are marked approved (no cash change).
    When no requests are left pending on the ticket, the ticket becomes resolved.

    Args:
        request_id: The approval request to approve.
        approved_by: Name of the person approving (not an agent).
    """
    if (err := _require_human(approved_by)) is not None:
        return {"ok": False, "message": err}

    with _connect(write=True) as conn:
        conn.execute("BEGIN IMMEDIATE")  # no double-approval races
        req = conn.execute("SELECT * FROM approval_requests WHERE id = ?", (request_id,)).fetchone()
        if req is None:
            return {"ok": False, "message": f"No approval request with id {request_id}."}
        if req["status"] != "pending":
            return {"ok": False, "message": f"Request {request_id} is already {req['status']}."}

        today = _shop_today(conn)
        result: dict = {"ok": True, "request_id": request_id, "kind": req["kind"], "ticket_id": req["ticket_id"]}

        if req["kind"] in MONEY_OUT_KINDS:
            account = conn.execute(
                "SELECT name, balance FROM cash_accounts WHERE name = 'checking'"
            ).fetchone() or conn.execute("SELECT name, balance FROM cash_accounts ORDER BY name LIMIT 1").fetchone()
            amount = req["amount"]
            if account is None or amount is None:
                return {"ok": False, "message": "No cash account or amount to pay from."}
            if amount > account["balance"]:
                return {"ok": False, "message": f"Not enough cash: ${amount:.2f} needed, ${account['balance']:.2f} in {account['name']}."}

            ref_id = req["ref_id"]
            if req["kind"] == "invoice_payment":
                inv = conn.execute("SELECT status FROM invoices WHERE id = ?", (ref_id,)).fetchone()
                if inv is None or inv["status"] != "open":
                    return {"ok": False, "message": f"Invoice {ref_id} is no longer open."}
                conn.execute("UPDATE invoices SET status = 'paid' WHERE id = ?", (ref_id,))
            elif req["kind"] == "rent_payment":
                lease = conn.execute("SELECT next_due FROM leases WHERE id = ?", (ref_id,)).fetchone()
                if lease is None:
                    return {"ok": False, "message": f"Lease {ref_id} not found."}
                result["lease_next_due"] = _add_month(lease["next_due"])
                conn.execute("UPDATE leases SET next_due = ? WHERE id = ?", (result["lease_next_due"], ref_id))
            else:  # purchase_order: no PO table, so the payment points at the request itself
                ref_id = request_id

            new_balance = round(account["balance"] - amount, 2)
            conn.execute("UPDATE cash_accounts SET balance = ?, date = ? WHERE name = ?", (new_balance, today, account["name"]))
            cur = conn.execute(
                "INSERT INTO payments (kind, ref_id, amount, account, paid_at, approved_by) VALUES (?, ?, ?, ?, ?, ?)",
                (PAYMENT_KIND[req["kind"]], ref_id, amount, account["name"], today, approved_by.strip()),
            )
            result.update(payment_id=cur.lastrowid, amount=amount, account=account["name"],
                          old_balance=account["balance"], new_balance=new_balance)
        elif req["kind"] == "customer_message":
            result["note"] = "Approved. A human sends the message; nothing is emailed automatically."
        else:
            result["note"] = "Price quote approved; no cash moves until the customer pays."

        conn.execute(
            "UPDATE approval_requests SET status = 'approved', decided_by = ?, decided_at = ? WHERE id = ?",
            (approved_by.strip(), _now(), request_id),
        )
        result["ticket_status"] = _resolve_ticket_if_done(conn, req["ticket_id"])
    return result


@mcp.tool
def reject_request(request_id: int, decided_by: str, reason: str = "") -> dict:
    """HUMAN ONLY. Decline a pending request. Nothing is paid, ordered, or sent.

    Args:
        request_id: The approval request to reject.
        decided_by: Name of the person rejecting (not an agent).
        reason: Optional note explaining why.
    """
    if (err := _require_human(decided_by)) is not None:
        return {"ok": False, "message": err}
    with _connect(write=True) as conn:
        conn.execute("BEGIN IMMEDIATE")
        req = conn.execute("SELECT ticket_id, status FROM approval_requests WHERE id = ?", (request_id,)).fetchone()
        if req is None:
            return {"ok": False, "message": f"No approval request with id {request_id}."}
        if req["status"] != "pending":
            return {"ok": False, "message": f"Request {request_id} is already {req['status']}."}
        conn.execute(
            "UPDATE approval_requests SET status = 'rejected', decided_by = ?, decided_at = ?, decision_note = ? WHERE id = ?",
            (decided_by.strip(), _now(), reason.strip() or None, request_id),
        )
        ticket_status = _resolve_ticket_if_done(conn, req["ticket_id"])
    return {"ok": True, "request_id": request_id, "ticket_id": req["ticket_id"], "status": "rejected",
            "ticket_status": ticket_status}


@mcp.tool
def resolve_ticket(ticket_id: int, resolved_by: str, note: str = "") -> dict:
    """HUMAN / BACKEND ONLY. Mark a ticket resolved after the team run finished successfully.

    The dashboard backend calls this when the Boss returns a final decision that
    isn't blocked. Prepared payments stay pending in the approval queue.

    Args:
        ticket_id: Ticket to resolve.
        resolved_by: Who resolved it (the dashboard backend or a person, never an agent).
        note: Optional short note (e.g. the Boss's decision).
    """
    if (err := _require_human(resolved_by)) is not None:
        return {"ok": False, "message": err}
    with _connect(write=True) as conn:
        row = conn.execute("SELECT status FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if row is None:
            return {"ok": False, "message": f"No ticket with id {ticket_id}."}
        conn.execute("UPDATE tickets SET status = 'resolved' WHERE id = ?", (ticket_id,))
        pending = conn.execute(
            "SELECT COUNT(*) AS n FROM approval_requests WHERE ticket_id = ? AND status = 'pending'", (ticket_id,)
        ).fetchone()["n"]
    return {"ok": True, "ticket_id": ticket_id, "old_status": row["status"], "new_status": "resolved",
            "pending_approvals": pending, "note": note}


def _resolve_ticket_if_done(conn: sqlite3.Connection, ticket_id: int) -> str:
    """Mark the ticket resolved once no request on it is still pending."""
    pending = conn.execute(
        "SELECT COUNT(*) AS n FROM approval_requests WHERE ticket_id = ? AND status = 'pending'", (ticket_id,)
    ).fetchone()["n"]
    if pending == 0:
        conn.execute("UPDATE tickets SET status = 'resolved' WHERE id = ?", (ticket_id,))
    return conn.execute("SELECT status FROM tickets WHERE id = ?", (ticket_id,)).fetchone()["status"]


@mcp.tool
def reset_database(confirm: str) -> dict:
    """HUMAN ONLY. Restore data/campus_customs_new.db from the original data/campus_customs.db.

    Wipes every approval request, payment, and status change made since the
    last reset. The audit trail is NOT touched.

    Args:
        confirm: Must be exactly "RESET".
    """
    if confirm != "RESET":
        return {"ok": False, "message": 'Pass confirm="RESET" to restore the original database.'}
    if not ORIGINAL_DB_PATH.exists():
        return {"ok": False, "message": f"Original database not found: {ORIGINAL_DB_PATH}"}
    shutil.copyfile(ORIGINAL_DB_PATH, DB_PATH)
    _ensure_schema()
    with _connect() as conn:
        balance = conn.execute("SELECT balance FROM cash_accounts WHERE name = 'checking'").fetchone()
        tickets = [dict(r) for r in conn.execute("SELECT id, status FROM tickets ORDER BY id")]
    return {"ok": True, "message": "Working database restored from the original.",
            "checking_balance": balance["balance"] if balance else None, "tickets": tickets}


_ensure_schema()

if __name__ == "__main__":
    mcp.run(show_banner=False)
