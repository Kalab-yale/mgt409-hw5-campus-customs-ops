"""Turn the raw audit trail into a simple activity feed for the dashboard.

Each feed item answers "who did what": an agent said something, used a tool,
handed off work, or a human approved something.
"""

from __future__ import annotations

import json
from typing import Any

from config import AUDIT_PATH

PREVIEW_CHARS = 400


def _short(value: Any, limit: int = PREVIEW_CHARS) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text if len(text) <= limit else text[:limit] + "…"


def load_audit() -> list[dict]:
    if not AUDIT_PATH.exists() or AUDIT_PATH.stat().st_size == 0:
        return []
    try:
        records = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return records if isinstance(records, list) else []


def to_feed_items(record: dict) -> list[dict]:
    """One audit record -> zero or more feed items."""
    event = record.get("event")
    base = {
        "seq": record.get("seq"),
        "ts": record.get("ts"),
        "run_id": record.get("run_id"),
        "ticket_id": record.get("ticket_id"),
        "agent": record.get("agent"),
    }

    if event == "agent_step" and record.get("node") == "model_response":
        return [{**base, "kind": "said", "text": p["content"]}
                for p in record.get("parts", []) if p.get("type") == "text" and p.get("content")]
    if event == "agent_step" and record.get("node") == "end":
        out = record.get("output") or {}
        return [{**base, "kind": "report", "text": out.get("summary", ""), "output": out}]
    if event == "mcp_tool_result":
        return [{**base, "kind": "tool", "tool": record.get("tool"), "args": record.get("args"),
                 "text": f"{record.get('tool')} → {_short(record.get('result'), 200)}",
                 "result_preview": _short(record.get("result"))}]
    if event == "delegation_start":
        return [{**base, "agent": record.get("from_agent"), "kind": "delegation",
                 "to_agent": record.get("to_agent"), "text": record.get("task", "")}]
    if event in ("delegation_refused", "guardrail_block"):
        return [{**base, "agent": record.get("from_agent") or record.get("agent"), "kind": "guardrail",
                 "text": record.get("reason", "")}]
    if event == "ticket_run_start":
        return [{**base, "agent": "boss", "kind": "run_started", "text": f"Team started on ticket {record.get('ticket_id')}"}]
    if event == "ticket_run_end":
        decision = record.get("decision") or {}
        usage = record.get("usage") or {}
        return [{**base, "agent": "boss", "kind": "decision", "text": decision.get("summary", ""),
                 "decision": decision, "usage": usage}]
    if event in ("ticket_run_aborted", "ticket_run_error", "agent_error", "mcp_tool_error", "delegation_error"):
        return [{**base, "kind": "error", "text": record.get("reason") or record.get("error", "")}]
    if event == "ticket_resolved":
        return [{**base, "agent": "human", "kind": "ticket_resolved", "text": record.get("summary", "")}]
    if event in ("human_approved", "human_rejected", "database_reset"):
        return [{**base, "agent": "human", "kind": event, "text": record.get("summary", ""),
                 "result": record.get("result")}]
    return []


def _last_reset_seq(records: list[dict]) -> int:
    return max((r.get("seq") or 0 for r in records if r.get("event") == "database_reset"), default=0)


def latest_run_id(ticket_id: int, records: list[dict] | None = None) -> str | None:
    """The most recent team run on this ticket since the last database reset."""
    records = load_audit() if records is None else records
    reset_seq = _last_reset_seq(records)
    runs = [r["run_id"] for r in records
            if r.get("event") == "ticket_run_start" and r.get("ticket_id") == ticket_id and (r.get("seq") or 0) > reset_seq]
    return runs[-1] if runs else None


def feed(since: int = 0, limit: int = 100, ticket_id: int | None = None, run_id: str | None = None,
         latest_run: bool = False) -> dict:
    """Feed items after `since`. With latest_run + ticket_id, only that ticket's newest run
    (plus human actions on the ticket since then)."""
    records = load_audit()
    items: list[dict] = []
    last_seq = since
    run_start_seq = 0
    if latest_run and ticket_id is not None:
        run_id = latest_run_id(ticket_id, records)
        if run_id is None:
            return {"items": [], "last_seq": max((r.get("seq") or 0 for r in records), default=since), "run_id": None}
        run_start_seq = next(r["seq"] for r in records if r.get("run_id") == run_id and r.get("event") == "ticket_run_start")
    for rec in records:
        seq = rec.get("seq") or 0
        last_seq = max(last_seq, seq)
        if seq <= since:
            continue
        if ticket_id is not None and rec.get("ticket_id") != ticket_id:
            continue
        if run_id is not None and rec.get("run_id") != run_id:
            # keep human actions on this ticket that happened after the run started
            if not (latest_run and seq > run_start_seq and rec.get("event") in ("human_approved", "human_rejected", "ticket_resolved")):
                continue
        items.extend(to_feed_items(rec))
    return {"items": items[-limit:], "last_seq": last_seq, "run_id": run_id}


def contributions(ticket_id: int) -> dict:
    """Per-agent summary of the newest run on a ticket: what each agent did and concluded."""
    records = load_audit()
    run_id = latest_run_id(ticket_id, records)
    if run_id is None:
        return {"ticket_id": ticket_id, "run_id": None, "finished": False, "agents": {}}

    agents: dict[str, dict] = {}
    started: dict[str, str] = {}  # agent_run_id -> agent
    ended: set[str] = set()
    finished = False
    decision = None

    def entry(name: str) -> dict:
        return agents.setdefault(name, {
            "agent": name, "status": "working", "summary": "", "facts": [], "tools": {},
            "delegated_to": [], "delegated_by": [], "approval_request_ids": [], "blockers": [],
            "needs_human": False, "invocations": 0,
        })

    for rec in records:
        if rec.get("run_id") != run_id:
            continue
        event, name = rec.get("event"), rec.get("agent")
        if event == "agent_step" and rec.get("node") == "user_prompt":
            entry(name)["invocations"] += 1
            started[rec["agent_run_id"]] = name
        elif event == "agent_step" and rec.get("node") == "end":
            ended.add(rec["agent_run_id"])
            out = rec.get("output") or {}
            a = entry(name)
            a["summary"] = out.get("summary", a["summary"])
            a["facts"] = out.get("facts", out.get("plan", a["facts"]))
            a["blockers"] = out.get("blockers", out.get("risks", a["blockers"]))
            a["needs_human"] = bool(out.get("needs_human", a["needs_human"]))
            for rid in out.get("approval_request_ids", []):
                if rid not in a["approval_request_ids"]:
                    a["approval_request_ids"].append(rid)
        elif event == "mcp_tool_result":
            tools = entry(name)["tools"]
            tools[rec.get("tool")] = tools.get(rec.get("tool"), 0) + 1
        elif event == "delegation_start":
            src, dst = rec.get("from_agent"), rec.get("to_agent")
            if dst not in entry(src)["delegated_to"]:
                entry(src)["delegated_to"].append(dst)
            if src not in entry(dst)["delegated_by"]:
                entry(dst)["delegated_by"].append(src)
        elif event == "ticket_run_end":
            finished, decision = True, rec.get("decision")
        elif event in ("ticket_run_aborted", "ticket_run_error"):
            finished = True

    for agent_run_id, name in started.items():
        if agent_run_id not in ended:
            agents[name]["status"] = "error" if finished else "working"
    for name, a in agents.items():
        if a["invocations"] and all(rid in ended for rid, n in started.items() if n == name):
            a["status"] = "done"
    return {"ticket_id": ticket_id, "run_id": run_id, "finished": finished, "decision": decision, "agents": agents}
