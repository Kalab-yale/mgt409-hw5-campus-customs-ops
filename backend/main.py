"""Campus Customs Multi-Agent Operations: FastAPI backend for the React dashboard.

Run from backend/:
    uvicorn main:app --reload --port 8000

Every shop read and write goes through the campus-customs MCP server (the
same connection the agents use). This file never opens the database.
The only route that changes cash is POST /api/approvals/{id}/approve, which
calls the human-only `approve_request` MCP tool after a person clicks Approve.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from events import contributions, feed
from models import ApproveBody, RejectBody, ResetBody, RunTicketRequest
from team import Team


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@asynccontextmanager
async def lifespan(app: FastAPI):
    team = Team()
    async with team:  # starts the MCP server once for the whole app
        app.state.team = team
        app.state.runs = {}  # run_id -> run info (kept in memory)
        app.state.run_lock = asyncio.Lock()  # one team run at a time: tickets share the same cash
        yield


app = FastAPI(title="Campus Customs Multi-Agent Operations", version="1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],  # the React dashboard (npm run dev)
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",  # ...or Vite on another local port
    allow_methods=["*"],
    allow_headers=["*"],
)


async def mcp(tool: str, args: dict[str, Any] | None = None) -> Any:
    """Call a campus-customs MCP tool directly (backend use, not an agent)."""
    return await app.state.team.mcp.direct_call_tool(tool, args or {})


def _fail(result: dict, status: int = 400) -> None:
    if not result.get("ok", result.get("found", True)):
        raise HTTPException(status_code=status, detail=result.get("message", "Request failed."))


# ---------------------------------------------------------------- health

@app.get("/api/health")
async def health() -> dict:
    return {"ok": True, "running": _running_run() is not None}


# ---------------------------------------------------------------- tickets

@app.get("/api/tickets")
async def list_tickets() -> dict:
    """Every ticket with status "open" or "resolved" (plus the raw stage and approval counts)."""
    data = await mcp("list_tickets")
    running = _running_run()
    for t in data["tickets"]:
        t["running"] = running is not None and running["ticket_id"] == t["id"]
    return data


@app.get("/api/tickets/{ticket_id}")
async def get_ticket(ticket_id: int) -> dict:
    """One ticket with its approval requests and the team's latest decision."""
    ticket = await mcp("get_ticket", {"ticket_id": ticket_id})
    _fail(ticket, 404)
    approvals = await mcp("list_approval_requests", {"ticket_id": ticket_id})
    last_run = next((r for r in reversed(app.state.runs.values()) if r["ticket_id"] == ticket_id), None)
    return {"ticket": ticket, "approvals": approvals["requests"], "last_run": last_run}


# ---------------------------------------------------------------- run the team

# A finished run resolves the ticket unless the Boss says it's blocked or still in progress.
RESOLVING_DECISIONS = {"awaiting_approval", "no_action_needed"}


def _running_run() -> dict | None:
    return next((r for r in app.state.runs.values() if r["status"] == "running"), None)


async def _run_team(run_id: str, ticket_id: int) -> None:
    run = app.state.runs[run_id]
    async with app.state.run_lock:
        try:
            decision = await app.state.team.handle_ticket(ticket_id, run_id=run_id)
            if decision is None:
                run.update(status="stopped", error="Hit the token/request limit; see the activity feed.")
            else:
                run.update(status="done", decision=decision.model_dump())
                if decision.decision in RESOLVING_DECISIONS:
                    result = await mcp("resolve_ticket", {"ticket_id": ticket_id, "resolved_by": "dashboard",
                                                          "note": decision.decision})
                    run["resolved"] = bool(result.get("ok"))
                    pending = result.get("pending_approvals", 0)
                    await app.state.team.audit.append(
                        "ticket_resolved", run_id=run_id, ticket_id=ticket_id,
                        summary=f"Ticket {ticket_id} resolved: the team finished"
                                + (f"; {pending} request(s) waiting for approval" if pending else ""),
                        result=result,
                    )
        except Exception as exc:  # surface errors to the dashboard instead of failing silently
            run.update(status="error", error=repr(exc))
        finally:
            run["finished_at"] = _now()


@app.post("/api/run", status_code=202)
async def run_ticket(body: RunTicketRequest) -> dict:
    """Start the agent team on a ticket. Returns at once; follow progress in /api/events."""
    if (busy := _running_run()) is not None:
        raise HTTPException(409, f"The team is already working on ticket {busy['ticket_id']} (run {busy['run_id']}).")
    ticket = await mcp("get_ticket", {"ticket_id": body.ticket_id})
    _fail(ticket, 404)
    if ticket["status"] in ("resolved", "closed"):
        raise HTTPException(409, f"Ticket {body.ticket_id} is already {ticket['status']}. Reset the database to run it again.")

    run_id = uuid.uuid4().hex[:12]
    app.state.runs[run_id] = {"run_id": run_id, "ticket_id": body.ticket_id, "status": "running",
                              "started_at": _now(), "finished_at": None, "decision": None, "error": None,
                              "resolved": False}
    asyncio.create_task(_run_team(run_id, body.ticket_id))
    return app.state.runs[run_id]


@app.get("/api/runs")
async def list_runs() -> dict:
    """Team runs since the server started (newest last)."""
    return {"runs": list(app.state.runs.values())}


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str) -> dict:
    run = app.state.runs.get(run_id)
    if run is None:
        raise HTTPException(404, f"No run {run_id}.")
    return run


# ---------------------------------------------------------------- activity feed

@app.get("/api/events")
async def events(
    since: int = Query(0, ge=0, description="Only events after this seq (use last_seq from the previous call)."),
    limit: int = Query(100, ge=1, le=500),
    ticket_id: int | None = None,
    run_id: str | None = None,
    latest_run: bool = Query(False, description="With ticket_id: only that ticket's newest run since the last reset."),
) -> dict:
    """Recent agent activity: what each agent said, tools used, hand-offs, decisions, human approvals."""
    return feed(since=since, limit=limit, ticket_id=ticket_id, run_id=run_id, latest_run=latest_run)


@app.get("/api/tickets/{ticket_id}/contributions")
async def ticket_contributions(ticket_id: int) -> dict:
    """What each agent did on the ticket's newest run: summary, tools used, hand-offs, requests filed."""
    return contributions(ticket_id)


# ---------------------------------------------------------------- human approvals

@app.get("/api/approvals")
async def list_approvals(status: str | None = "pending", ticket_id: int | None = None) -> dict:
    """Requests the agents prepared. Default: just the pending ones."""
    return await mcp("list_approval_requests", {"status": status or None, "ticket_id": ticket_id})


@app.post("/api/approvals/{request_id}/approve")
async def approve(request_id: int, body: ApproveBody) -> dict:
    """A human clicked Approve. For payments and purchases this is what actually moves the money."""
    result = await mcp("approve_request", {"request_id": request_id, "approved_by": body.approved_by})
    _fail(result)
    summary = f"{body.approved_by} approved request #{request_id} ({result['kind']})"
    if "amount" in result:
        summary += f": paid ${result['amount']:,.2f}, checking ${result['old_balance']:,.2f} → ${result['new_balance']:,.2f}"
    await app.state.team.audit.append("human_approved", ticket_id=result["ticket_id"], request_id=request_id,
                                      decided_by=body.approved_by, summary=summary, result=result)
    return result


@app.post("/api/approvals/{request_id}/reject")
async def reject(request_id: int, body: RejectBody) -> dict:
    """A human clicked Reject. Nothing is paid, ordered, or sent."""
    result = await mcp("reject_request", {"request_id": request_id, "decided_by": body.decided_by,
                                          "reason": body.reason})
    _fail(result)
    await app.state.team.audit.append("human_rejected", ticket_id=result["ticket_id"], request_id=request_id,
                                      decided_by=body.decided_by,
                                      summary=f"{body.decided_by} rejected request #{request_id}"
                                              + (f": {body.reason}" if body.reason else ""),
                                      result=result)
    return result


# ---------------------------------------------------------------- cash

@app.get("/api/cash")
async def cash() -> dict:
    """Current checking balance (cash_accounts) plus what's pending against it."""
    pos = await mcp("get_cash_position")
    checking = next((a for a in pos["accounts"] if a["name"] == "checking"), None)
    if checking is None:
        raise HTTPException(404, "No checking account found.")
    return {
        "account": "checking",
        "balance": checking["balance"],
        "as_of": checking["date"],
        "shop_today": pos["shop_today"],
        "pending_money_out_total": pos["pending_money_out_total"],
        "balance_if_pending_approved": pos["balance_if_pending_requests_approved"],
        "pending_money_out_requests": pos["pending_money_out_requests"],
    }


@app.get("/api/payments")
async def payments() -> dict:
    """Money that has actually left checking (the payments table): only written by human approvals."""
    return await mcp("list_payments")


# ---------------------------------------------------------------- reset

@app.post("/api/reset")
async def reset(body: ResetBody) -> dict:
    """Restore the working database from the original for a fresh run. The audit trail is kept."""
    if _running_run() is not None:
        raise HTTPException(409, "Wait for the current team run to finish before resetting.")
    result = await mcp("reset_database", {"confirm": body.confirm})
    _fail(result)
    app.state.runs.clear()
    await app.state.team.audit.append("database_reset", summary="Database reset to original values", result=result)
    return result
