"""Build the Problem 9 run report from REAL data only.

Sources:
  - output/audit_trail.json  (every agent step, MCP call, delegation, human approval)
  - the running backend at http://localhost:8000 (which reads the DB via the MCP server)
  - output/screenshots/ticket_<id>.png (headless-Chrome captures of the React dashboard)

Writes:
  - output/resolved_tickets.json
  - output/desk_tickets.html   (fills the Actual sections + Cash tab; Expected sections untouched)
  - output/resolved_board.html (standalone page with the embedded screenshots)

Fails loudly if the cash does not reconcile.

    .venv/bin/python scripts/build_run_report.py
"""

from __future__ import annotations

import base64
import html
import json
import re
import sys
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"
API = "http://localhost:8000/api"
TICKETS = (101, 102, 103)

AGENT_LABEL = {"boss": "Boss", "inventory": "Inventory", "accounting": "Accounting",
               "facilities": "Facilities", "customer_service": "Customer Service"}
AGENT_ICON = {"boss": "👔", "inventory": "📦", "accounting": "🧮", "facilities": "🏬", "customer_service": "💬"}
AGENT_ROLE = {"boss": "Reviews tickets, assigns work, makes the final call",
              "inventory": "Stock by SKU and size, shortages, restock vendors",
              "accounting": "Cash, invoices, margins; prepares payments for approval",
              "facilities": "Shop space, lease, and rent",
              "customer_service": "Drafts customer messages for approval"}
KIND_LABEL = {"invoice_payment": "Invoice payment", "rent_payment": "Rent payment", "purchase_order": "Purchase order",
              "price_quote": "Price quote", "customer_message": "Customer message"}
MONEY_OUT = {"invoice_payment", "rent_payment", "purchase_order"}

# Plan-vs-actual analysis, written after reading the run records below (checked against them in main()).
COMPARISON = {
    101: [
        ("match", "First contact: the Boss's first hand-off went to <b>Inventory</b>, as planned, sent in the same turn as Accounting."),
        ("match", "Same three specialists as planned (Inventory, Accounting, Customer Service). <b>Facilities was not involved</b>, as planned."),
        ("match", "Customer Service went <b>last</b>, in its own turn, with confirmed facts (out of stock, earliest restock 2026-09-05)."),
        ("match", "Accounting tied invoice 501 to this exact tee and filed an <code>invoice_payment</code> for $840. <b>No new purchase order</b>, as planned."),
        ("diff", "Inventory and Accounting were sent <b>in parallel</b> (one Boss turn), not one after the other. Inventory also called <code>get_ticket</code>, and the Boss checked <code>get_cash_position</code> twice."),
    ],
    102: [
        ("match", "First contact: <b>Facilities</b> verified the notice against lease 1 (landlord, due date, $2,400) before anyone filed a payment."),
        ("match", "Inventory and Customer Service were <b>not involved</b>, as planned."),
        ("diff", "The planned <b>Facilities → Accounting</b> specialist hand-off did not happen. The Boss sent Facilities and Accounting together (telling Accounting <i>not</i> to file yet), then delegated to Accounting a second time once Facilities had verified. That's 3 hand-offs instead of 2, and why Accounting called <code>get_lease</code> and <code>get_cash_position</code> twice."),
        ("match", "The safety intent held: the $2,400 <code>rent_payment</code> was filed only <b>after</b> verification, with the $160-left warning."),
    ],
    103: [
        ("diff", "First contact: the Boss sent <b>Inventory and Accounting together</b> (Inventory listed first), not Accounting alone. Accounting was told to wait for the stock facts."),
        ("diff", "The planned <b>Accounting → Inventory</b> specialist hand-off did not happen. The Boss relayed Inventory's facts to Accounting in a second delegation instead."),
        ("match", "Accounting priced the quote exactly as planned: <b>$49.30 × 20 = $986</b> (15% off list, above the $22 floor). Facilities was not involved."),
        ("diff", "The plan said to <b>hold</b> the $264 purchase order. Accounting <b>filed</b> it, and the server attached the warning that pending money-out ($3,504) exceeded cash ($3,400). The human <b>rejected</b> it, so the end result is the same as the plan."),
        ("diff", "Customer Service was delegated in the <b>same turn</b> as Accounting's filing request, not strictly after. Its draft still kept the discount \"pending manager approval\"."),
    ],
}

OUTCOME = {
    101: "Size S is out of stock (0 on hand). Earliest restock is 2026-09-05 via Bulldog Print Co. The overdue rush-reprint invoice 501 ($840) was paid on human approval, and the honest update to Tauhid was approved.",
    102: "The rent notice was verified against lease 1 (Elm City Properties, $2,400 due 2026-09-02). Rent was paid on human approval, and the lease's next due date moved to 2026-10-02.",
    103: "8 of 20 hoodies are on hand (12 short, restock earliest 2026-09-05). The bulk quote of $49.30 × 20 = $986 was approved. The $264 restock purchase order was rejected by the human. With rent and the invoice approved, only $160 remained, less than the $264 it needed. The reply to Yale AI Club was approved.",
}


def get(path: str):
    with urllib.request.urlopen(f"{API}{path}") as r:
        return json.load(r)


def esc(s) -> str:
    return html.escape(str(s))


def money(n: float) -> str:
    return f"-${abs(n):,.2f}" if n < 0 else f"${n:,.2f}"


# ---------------------------------------------------------------- collect

def collect() -> dict:
    audit = json.loads((OUT / "audit_trail.json").read_text())
    reset = [r for r in audit if r["event"] == "database_reset"][-1]
    after = [r for r in audit if r["seq"] > reset["seq"]]

    tickets_api = {t["id"]: t for t in get("/tickets")["tickets"]}
    approvals = get("/approvals?status=")["requests"]
    payments = get("/payments")
    cash = get("/cash")

    human = [r for r in after if r["event"] in ("human_approved", "human_rejected")]
    approval_events = {r["request_id"]: r for r in human}

    tickets = {}
    for tid in TICKETS:
        starts = [r for r in after if r["event"] == "ticket_run_start" and r["ticket_id"] == tid]
        assert starts, f"no run for ticket {tid} after the reset"
        run_id = starts[-1]["run_id"]
        recs = [r for r in after if r.get("run_id") == run_id]
        end = next(r for r in recs if r["event"] == "ticket_run_end")

        order: list[str] = []
        tools: dict[str, Counter] = defaultdict(Counter)
        reports: dict[str, list[str]] = defaultdict(list)
        delegated_by: dict[str, list[str]] = defaultdict(list)
        delegated_to: dict[str, list[str]] = defaultdict(list)
        delegations, turns, writes = [], [], []
        for r in recs:
            a = r.get("agent")
            if r["event"] == "agent_step" and r["node"] == "user_prompt" and a not in order:
                order.append(a)
            if r["event"] == "agent_step" and r["node"] == "model_response":
                dels = [p["args"].get("to_agent") for p in r["parts"] if p.get("type") == "tool_call" and p.get("tool") == "delegate"]
                if dels:
                    turns.append({"agent": a, "to": dels})
            if r["event"] == "agent_step" and r["node"] == "end":
                reports[a].append(r["output"].get("summary", ""))
            if r["event"] == "mcp_tool_result":
                tools[a][r["tool"]] += 1
                if r["tool"] in ("request_approval", "update_ticket_status"):
                    res = r["result"]
                    writes.append({"agent": a, "tool": r["tool"], "request_id": res.get("request_id"),
                                   "kind": res.get("kind") or r["args"].get("kind"), "amount": res.get("amount"),
                                   "warnings": res.get("warnings") or [], "new_status": res.get("new_status")})
            if r["event"] == "delegation_start":
                delegations.append({"n": r["delegation_number"], "from": r["from_agent"], "to": r["to_agent"],
                                    "depth": r["depth"] + 1, "task": r["task"], "ts": r["ts"]})
                if r["to_agent"] not in delegated_to[r["from_agent"]]:
                    delegated_to[r["from_agent"]].append(r["to_agent"])
                if r["from_agent"] not in delegated_by[r["to_agent"]]:
                    delegated_by[r["to_agent"]].append(r["from_agent"])
            if r["event"] == "delegation_refused":
                delegations.append({"n": None, "from": r["from_agent"], "to": r["to_agent"], "refused": r["reason"]})

        t_approvals = []
        for a in [x for x in approvals if x["ticket_id"] == tid]:
            ev = approval_events.get(a["id"], {})
            res = ev.get("result") or {}
            t_approvals.append({
                "request_id": a["id"], "kind": a["kind"], "amount": a["amount"], "prepared_by": a["requested_by"],
                "summary": a["summary"], "message": a["message"], "status": a["status"],
                "decided_by": a["decided_by"], "decided_at": a["decided_at"],
                "payment_id": res.get("payment_id"),
                "cash_change": -res["amount"] if res.get("payment_id") else 0.0,
                "balance_before": res.get("old_balance"), "balance_after": res.get("new_balance"),
                "audit_seq": ev.get("seq"),
            })

        tickets[tid] = {
            "ticket": tickets_api[tid], "run_id": run_id, "start": starts[-1], "end": end,
            "order": order, "tools": tools, "reports": reports, "delegations": delegations, "turns": turns,
            "writes": writes, "delegated_by": delegated_by, "delegated_to": delegated_to, "approvals": t_approvals,
        }

    return {"reset": reset, "tickets": tickets, "payments": payments, "cash": cash, "human": human,
            "audit_count": len(audit), "audit_last_seq": audit[-1]["seq"]}


def reconcile(data: dict) -> dict:
    start = float(data["reset"]["result"]["checking_balance"])
    changes = {tid: round(sum(a["cash_change"] for a in t["approvals"]), 2) for tid, t in data["tickets"].items()}
    computed = round(start + sum(changes.values()), 2)
    ending = float(data["cash"]["balance"])
    payments_total = float(data["payments"]["total"])
    ok = abs(computed - ending) < 0.005 and abs(start - payments_total - ending) < 0.005
    if not ok:
        sys.exit(f"CASH DOES NOT RECONCILE: start {start} + changes {changes} = {computed}, "
                 f"cash_accounts {ending}, payments total {payments_total}")
    return {"starting_balance": start, "changes": changes, "computed_ending": computed,
            "cash_accounts_ending": ending, "payments_total": payments_total, "difference": round(computed - ending, 2),
            "reconciled": ok}


def check_comparison(data: dict) -> None:
    """Guard the hand-written plan-vs-actual notes against the actual records."""
    t = data["tickets"]
    assert t[101]["turns"][0]["to"] == ["inventory", "accounting"] and t[101]["turns"][1]["to"] == ["customer_service"]
    assert "facilities" not in t[101]["order"]
    assert t[102]["turns"][0]["to"] == ["facilities", "accounting"] and t[102]["turns"][1]["to"] == ["accounting"]
    assert set(t[102]["order"]) == {"boss", "facilities", "accounting"}
    assert t[103]["turns"][0]["to"] == ["inventory", "accounting"] and t[103]["turns"][1]["to"] == ["accounting", "customer_service"]
    assert all(d["from"] == "boss" for tid in TICKETS for d in t[tid]["delegations"])
    po = next(a for a in t[103]["approvals"] if a["kind"] == "purchase_order")
    assert po["status"] == "rejected" and po["amount"] == 264.0
    quote = next(a for a in t[103]["approvals"] if a["kind"] == "price_quote")
    assert quote["amount"] == 986.0 and quote["status"] == "approved"


# ---------------------------------------------------------------- resolved_tickets.json

def write_json(data: dict, rec: dict) -> None:
    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sources": ["output/audit_trail.json", "GET /api/tickets, /api/approvals, /api/payments, /api/cash (via MCP)"],
        "database_reset": {"audit_seq": data["reset"]["seq"], "ts": data["reset"]["ts"]},
        "cash": rec,
        "tickets": [],
    }
    for tid, t in data["tickets"].items():
        u = t["end"]["usage"]
        dur = (datetime.fromisoformat(t["end"]["ts"]) - datetime.fromisoformat(t["start"]["ts"])).total_seconds()
        agents = []
        for a in t["order"]:
            agents.append({
                "agent": a, "role": AGENT_ROLE[a],
                "delegated_by": t["delegated_by"].get(a, []), "delegated_to": t["delegated_to"].get(a, []),
                "invocations": len(t["reports"][a]),
                "mcp_tools_used": dict(t["tools"][a]),
                "approval_requests_filed": [w["request_id"] for w in t["writes"] if w["agent"] == a and w["tool"] == "request_approval"],
                "contribution": t["reports"][a][-1] if t["reports"][a] else "",
                "all_reports": t["reports"][a],
            })
        out["tickets"].append({
            "id": tid, "type": t["ticket"]["type"], "requester": t["ticket"]["requester"], "subject": t["ticket"]["subject"],
            "final_status": t["ticket"]["status"], "boss_decision": t["end"]["decision"]["decision"],
            "outcome": OUTCOME[tid], "boss_summary": t["end"]["decision"]["summary"],
            "run": {"run_id": t["run_id"], "started": t["start"]["ts"], "finished": t["end"]["ts"], "seconds": round(dur, 1),
                    "total_tokens": u["total_tokens"], "model_calls": u["requests"], "tool_calls": u["tool_calls"],
                    "delegations": t["end"]["delegations"]},
            "agents": agents,
            "agents_not_involved": [a for a in AGENT_LABEL if a not in t["order"]],
            "delegations": [{k: v for k, v in d.items() if k != "ts"} for d in t["delegations"]],
            "human_approvals": [{k: v for k, v in a.items() if k not in ("summary",)} for a in t["approvals"]],
            "cash_change": rec["changes"][tid],
        })
    (OUT / "resolved_tickets.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------- desk_tickets.html

def agent_tag(a: str) -> str:
    return f'<span class="ag ag-{a}">{AGENT_ICON[a]} {AGENT_LABEL[a]}</span>'


def actual_html(tid: int, t: dict) -> str:
    u = t["end"]["usage"]
    dur = (datetime.fromisoformat(t["end"]["ts"]) - datetime.fromisoformat(t["start"]["ts"])).total_seconds()
    not_inv = [a for a in AGENT_LABEL if a not in t["order"]]
    first = t["delegations"][0]["to"]

    steps = []
    for turn_i, turn in enumerate(t["turns"], 1):
        ds = [d for d in t["delegations"] if d.get("n")][sum(len(x["to"]) for x in t["turns"][:turn_i - 1]):][:len(turn["to"])]
        for d in ds:
            par = " <span class='par'>same turn</span>" if len(turn["to"]) > 1 else ""
            steps.append(
                f"<li class='step'><div class='route'>{agent_tag(d['from'])} <span class='arrow'>→</span> {agent_tag(d['to'])}"
                f" <span class='mono' style='font-weight:400;color:var(--muted)'>hand-off #{d['n']} · Boss turn {turn_i}</span>{par}</div>"
                f"<p><span class='lbl'>Task (verbatim)</span>{esc(d['task'])}</p>"
                f"<div class='result'><b>Reported back:</b> {esc(_report_for(t, d))}</div></li>")
    boss_final = t["reports"]["boss"][-1]
    steps.append(f"<li class='step'><div class='route'>{agent_tag('boss')} final decision: "
                 f"<code>{esc(t['end']['decision']['decision'])}</code></div><p>{esc(boss_final)}</p></li>")

    rows = []
    for a in t["order"]:
        for tool, n in t["tools"][a].items():
            rows.append(f"<tr><td><code>{esc(tool)}</code></td><td>{agent_tag(a)}</td><td>{n}</td></tr>")

    wrows = []
    for w in t["writes"]:
        if w["tool"] == "request_approval":
            warn = f"<br><span class='warntext'>⚠ {esc(w['warnings'][0])}</span>" if w["warnings"] else ""
            wrows.append(f"<li>{agent_tag(w['agent'])} filed request <b>#{w['request_id']}</b> "
                         f"({esc(KIND_LABEL.get(w['kind'], w['kind']))}{', ' + money(w['amount']) if w['amount'] else ''}){warn}</li>")
        else:
            wrows.append(f"<li>{agent_tag(w['agent'])} set ticket status → <code>{esc(w['new_status'])}</code></li>")

    arows = []
    for a in t["approvals"]:
        st = {"approved": "✓ Approved", "rejected": "✕ Rejected", "pending": "Pending"}[a["status"]]
        cash = money(a["cash_change"]) if a["cash_change"] else "$0.00"
        arows.append(f"<tr><td>#{a['request_id']}</td><td>{esc(KIND_LABEL[a['kind']])}</td><td>{money(a['amount']) if a['amount'] else '—'}</td>"
                     f"<td class='st-{a['status']}'>{st}</td><td>{esc(a['decided_by'] or '')}</td><td>{cash}</td></tr>")

    comp = "".join(f"<li class='cmp-{k}'><span class='cmp-badge'>{'Matched plan' if k == 'match' else 'Differed'}</span> {txt}</li>"
                   for k, txt in COMPARISON[tid])

    return f"""<!--ACTUAL-{tid}-START-->
  <div class="card actual-card">
    <div class="actual-head">
      <h3 style="margin:0">What actually happened</h3>
      <span class="tag tag-green">✓ {esc(t['ticket']['status'])}</span>
    </div>
    <p class="actual-outcome">{esc(OUTCOME[tid])}</p>
    <div class="facts">
      <div class="fact"><div class="k">Run</div><div class="v mono">{esc(t['run_id'])}</div><div class="src">{esc(t['start']['ts'][11:19])}–{esc(t['end']['ts'][11:19])} UTC · {dur:.0f}s</div></div>
      <div class="fact"><div class="k">Boss contacted first</div><div class="v">{AGENT_ICON[first]} {AGENT_LABEL[first]}</div><div class="src">delegation #1</div></div>
      <div class="fact"><div class="k">Agents involved</div><div class="v">{', '.join(AGENT_LABEL[a] for a in t['order'])}</div><div class="src">not involved: {', '.join(AGENT_LABEL[a] for a in not_inv) or 'none'}</div></div>
      <div class="fact"><div class="k">Usage</div><div class="v">{u['total_tokens']:,} tokens</div><div class="src">{u['requests']} model calls · {u['tool_calls']} tool calls · {t['end']['delegations']} hand-offs</div></div>
    </div>
  </div>

  <div class="card">
    <h3>Delegations (from the audit trail)</h3>
    <ol class="steps">{''.join(steps)}</ol>
  </div>

  <div class="card">
    <h3>MCP tools actually used</h3>
    <div class="table-scroll"><table><thead><tr><th>Tool</th><th>Called by</th><th>Calls</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
    <h3 style="margin-top:22px">What the agents wrote</h3>
    <ul class="tight">{''.join(wrows)}</ul>
  </div>

  <div class="card">
    <h3>Human approvals</h3>
    <div class="table-scroll"><table><thead><tr><th>Request</th><th>Kind</th><th>Amount</th><th>Decision</th><th>By</th><th>Cash change</th></tr></thead><tbody>{''.join(arows)}</tbody></table></div>
  </div>

  <div class="card">
    <h3>Plan vs. actual</h3>
    <ul class="cmp">{comp}</ul>
  </div>
<!--ACTUAL-{tid}-END-->"""


def _report_for(t: dict, d: dict) -> str:
    """The child's report for this delegation (nth report of that agent)."""
    nth = [x for x in t["delegations"] if x.get("n") and x["to"] == d["to"]].index(d)
    reps = t["reports"][d["to"]]
    return reps[nth] if nth < len(reps) else "(no report)"


def cash_html(data: dict, rec: dict) -> str:
    rows, running = [], rec["starting_balance"]
    # in the order the human approved them
    events = sorted([a for t in data["tickets"].values() for a in t["approvals"] if a["payment_id"]], key=lambda a: a["audit_seq"])
    for a in events:
        running = round(running + a["cash_change"], 2)
        assert abs(running - a["balance_after"]) < 0.005
        rows.append(f"<tr><td>{esc(a['decided_at'][11:19])} UTC</td><td>#{a['request_id']} · ticket {_ticket_of(data, a)}</td>"
                    f"<td>{esc(KIND_LABEL[a['kind']])}</td><td>{esc(a['decided_by'])}</td><td>payment #{a['payment_id']}</td>"
                    f"<td class='neg'>{money(a['cash_change'])}</td><td><b>{money(running)}</b></td></tr>")

    per = []
    responsible = {
        101: "Invoice 501 to Bulldog Print Co (rush reprint of CC-TEE-WHITE S), request #1",
        102: "September rent, lease 1, Elm City Properties, request #3",
        103: "None. Purchase order #5 ($264) was <b>rejected</b>, so no payment was made",
    }
    for tid in TICKETS:
        ch = rec["changes"][tid]
        per.append(f"<tr><td><b>{tid}</b></td><td>{esc(data['tickets'][tid]['ticket']['subject'])}</td><td>{responsible[tid]}</td>"
                   f"<td class='{'neg' if ch else ''}'>{money(ch) if ch else '$0.00'}</td></tr>")

    t103 = {a["kind"]: a for a in data["tickets"][103]["approvals"]}
    return f"""<!--CASH-START-->
  <div class="card">
    <div class="ticket-head"><h2>Cash: checking account</h2><span class="tag tag-green">✓ Reconciled</span></div>
    <div class="facts">
      <div class="fact"><div class="k">Starting balance</div><div class="v">{money(rec['starting_balance'])}</div><div class="src">after reset · audit #{data['reset']['seq']}</div></div>
      <div class="fact bad"><div class="k">Paid out (human-approved)</div><div class="v">{money(-rec['payments_total'])}</div><div class="src">payments table · {data['payments']['count']} rows</div></div>
      <div class="fact"><div class="k">Ending balance</div><div class="v">{money(rec['cash_accounts_ending'])}</div><div class="src">cash_accounts.balance</div></div>
    </div>
  </div>

  <div class="card">
    <h3>Cash change by ticket</h3>
    <div class="table-scroll"><table><thead><tr><th>Ticket</th><th>Subject</th><th>Payment or purchase responsible</th><th>Cash change</th></tr></thead><tbody>
      {''.join(per)}
      <tr><td></td><td></td><td style="text-align:right"><b>Total</b></td><td class="neg"><b>{money(sum(rec['changes'].values()))}</b></td></tr>
    </tbody></table></div>
  </div>

  <div class="card">
    <h3>Ledger: in the order the human approved</h3>
    <div class="table-scroll"><table><thead><tr><th>Approved</th><th>Request</th><th>Kind</th><th>By</th><th>Payment row</th><th>Change</th><th>Balance</th></tr></thead><tbody>
      <tr><td>—</td><td>Starting balance (after reset)</td><td></td><td></td><td></td><td></td><td><b>{money(rec['starting_balance'])}</b></td></tr>
      {''.join(rows)}
    </tbody></table></div>
  </div>

  <div class="card">
    <h3>Reconciliation</h3>
    <table><tbody>
      <tr><td>Starting checking balance</td><td style="text-align:right">{money(rec['starting_balance'])}</td></tr>
      <tr><td>Ticket 101 · invoice 501 payment</td><td style="text-align:right" class="neg">{money(rec['changes'][101])}</td></tr>
      <tr><td>Ticket 102 · rent payment</td><td style="text-align:right" class="neg">{money(rec['changes'][102])}</td></tr>
      <tr><td>Ticket 103 · no payment</td><td style="text-align:right">{money(rec['changes'][103])}</td></tr>
      <tr><td><b>Calculated ending balance</b></td><td style="text-align:right"><b>{money(rec['computed_ending'])}</b></td></tr>
      <tr><td><b><code>cash_accounts.balance</code> (checking) in the database</b></td><td style="text-align:right"><b>{money(rec['cash_accounts_ending'])}</b></td></tr>
      <tr><td>Difference</td><td style="text-align:right"><b>{money(rec['difference'])}</b> ✓</td></tr>
    </tbody></table>
    <p class="note">Cross-check: the <code>payments</code> table totals {money(rec['payments_total'])}, and {money(rec['starting_balance'])} − {money(rec['payments_total'])} = {money(rec['starting_balance'] - rec['payments_total'])}.</p>
  </div>

  <div class="card">
    <h3>Why ticket 103 had no cash change</h3>
    <ul class="tight">
      <li><b>Purchase order #5 ({money(t103['purchase_order']['amount'])}, 12 hoodies from Bulldog Print Co) was rejected</b> by {esc(t103['purchase_order']['decided_by'])}. Agents only prepare purchases, and only an approval moves money, so nothing was paid. When it was filed, the server warned that pending money-out ($2,400 rent + $840 invoice + $264 PO = $3,504) exceeded the $3,400 in checking. With rent and the invoice approved, only $160 was left, which is less than $264.</li>
      <li><b>Price quote #6 ({money(t103['price_quote']['amount'])}) was approved</b>, but a quote is a price offered to the customer. It's money <i>in</i>, and only when the club pays, so approving it doesn't change checking.</li>
      <li><b>Customer message #4 was approved</b>. Messages never touch cash.</li>
    </ul>
    <p class="note">Ticket 101 also had an approved customer message (#2) with no cash effect. Only the two payments (#1 and #3) wrote rows to <code>payments</code>.</p>
  </div>
<!--CASH-END-->"""


def _ticket_of(data: dict, a: dict) -> int:
    return next(tid for tid, t in data["tickets"].items() if a in t["approvals"])


EXTRA_CSS = """
  /* --- Actual / Cash (Problem 9) --- */
  .tag-green { background: var(--green-soft); color: var(--green); }
  .actual-card { border-left: 4px solid var(--green); }
  .actual-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
  .actual-outcome { font-size: 17px; margin: 0 0 4px; }
  .ag { display: inline-block; font-size: 13px; font-weight: 600; padding: 2px 9px; border-radius: 999px; white-space: nowrap; }
  .ag-boss { background: #eeedfc; color: #5146d9; } .ag-inventory { background: #fdf1e3; color: #b45309; }
  .ag-accounting { background: #e6f4ea; color: #1e7a3c; } .ag-facilities { background: #e5effa; color: #0062c4; }
  .ag-customer_service { background: #fbe7ef; color: #b8195a; }
  .par { font-size: 11px; font-weight: 600; background: var(--soft); color: var(--muted); padding: 2px 8px; border-radius: 999px; margin-left: 6px; }
  .warntext { color: var(--amber); font-size: 14px; }
  .st-approved { color: var(--green); font-weight: 600; } .st-rejected { color: var(--red); font-weight: 600; }
  .neg { color: var(--red); }
  .note { color: var(--muted); font-size: 14px; margin: 12px 0 0; }
  ul.cmp { list-style: none; margin: 0; padding: 0; }
  ul.cmp li { padding: 10px 0; border-bottom: 1px solid var(--line); }
  ul.cmp li:last-child { border-bottom: 0; }
  .cmp-badge { display: inline-block; font-size: 12px; font-weight: 600; padding: 2px 9px; border-radius: 999px; margin-right: 6px; }
  .cmp-match .cmp-badge { background: var(--green-soft); color: var(--green); }
  .cmp-diff .cmp-badge { background: var(--amber-soft); color: var(--amber); }
"""


def update_desk(data: dict, rec: dict) -> None:
    path = OUT / "desk_tickets.html"
    s = path.read_text(encoding="utf-8")
    expected_before = re.findall(r'<div class="section-title"><h2>Expected</h2>.*?<div class="section-title"><h2>Actual</h2>', s, re.S)

    if "/* --- Actual / Cash (Problem 9) --- */" not in s:
        s = s.replace("</style>", EXTRA_CSS + "</style>", 1)
    for tid, t in data["tickets"].items():
        block = actual_html(tid, t)
        pat = re.compile(rf'<!--ACTUAL-{tid}-START-->.*?<!--ACTUAL-{tid}-END-->|<div class="actual-empty" data-actual="{tid}">.*?</div>', re.S)
        assert pat.search(s), f"no Actual placeholder for {tid}"
        s = pat.sub(lambda _: block, s, count=1)
        s = s.replace(f'<span class="badge actual">To be recorded</span></div>\n  {block[:20]}', f'<span class="badge actual">Recorded</span></div>\n  {block[:20]}')
    s = s.replace('<span class="badge actual">To be recorded</span>', '<span class="badge expected" style="background:var(--accent-soft);color:var(--accent)">Recorded</span>')

    cash_block = cash_html(data, rec)
    pat = re.compile(r'<!--CASH-START-->.*?<!--CASH-END-->|<div class="card placeholder">\s*<div class="icon" aria-hidden="true">💵</div>.*?</p>\s*</div>', re.S)
    assert pat.search(s), "no Cash placeholder"
    s = pat.sub(lambda _: cash_block, s, count=1)
    s = s.replace("<span class=\"pill\">If both are paid <b>$160 left</b></span>",
                  f"<span class=\"pill\">Ending checking <b>{money(rec['cash_accounts_ending'])}</b></span>")
    s = re.sub(r"<footer>.*?</footer>",
               f"<footer>Plan written before the run. Actual and Cash filled from the real run "
               f"(audit records #{data['reset']['seq']}–#{data['audit_last_seq']}) by scripts/build_run_report.py. "
               f"Source: campus-customs MCP server → data/campus_customs_new.db.</footer>", s, flags=re.S)

    expected_after = re.findall(r'<div class="section-title"><h2>Expected</h2>.*?<div class="section-title"><h2>Actual</h2>', s, re.S)
    assert expected_before == expected_after, "Expected sections changed!"
    path.write_text(s, encoding="utf-8")


# ---------------------------------------------------------------- resolved_board.html

def write_board(data: dict, rec: dict) -> None:
    cards = []
    for tid, t in data["tickets"].items():
        png = OUT / "screenshots" / f"ticket_{tid}.png"
        b64 = base64.b64encode(png.read_bytes()).decode()
        shot_time = datetime.fromtimestamp(png.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        appr = "".join(
            f"<li><b>#{a['request_id']}</b> {esc(KIND_LABEL[a['kind']])}{' ' + money(a['amount']) if a['amount'] else ''}: "
            f"<span class='st-{a['status']}'>{esc(a['status'])}</span> by {esc(a['decided_by'])}"
            f"{' · cash ' + money(a['cash_change']) if a['cash_change'] else ''}</li>" for a in t["approvals"])
        agents = " ".join(f'<span class="ag ag-{a}">{AGENT_ICON[a]} {AGENT_LABEL[a]}</span>' for a in t["order"])
        cards.append(f"""
  <section class="ticket" id="t{tid}">
    <div class="head">
      <div><div class="eyebrow">Ticket #{tid} · {esc(t['ticket']['requester'])}</div><h2>{esc(t['ticket']['subject'])}</h2></div>
      <span class="resolved">✓ {esc(t['ticket']['status'].title())}</span>
    </div>
    <p class="outcome">{esc(OUTCOME[tid])}</p>
    <div class="meta">
      <div><div class="k">Agents</div>{agents}</div>
      <div><div class="k">Cash change</div><b class="{'neg' if rec['changes'][tid] else ''}">{money(rec['changes'][tid]) if rec['changes'][tid] else '$0.00'}</b></div>
      <div><div class="k">Run</div><span class="mono">{esc(t['run_id'])}</span> · {t['end']['usage']['total_tokens']:,} tokens</div>
    </div>
    <ul class="appr">{appr}</ul>
    <figure>
      <a href="data:image/png;base64,{b64}" target="_blank" title="Open full size"><img src="data:image/png;base64,{b64}" alt="Screenshot of the Campus Customs dashboard showing ticket {tid} resolved"></a>
      <figcaption>Actual screenshot of the React dashboard at <code>http://localhost:5173/?ticket={tid}</code>, captured {shot_time} with headless Chrome (1440 px wide) after all approvals.</figcaption>
    </figure>
  </section>""")

    page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Campus Customs: Resolved Board</title>
<style>
  :root {{ --bg:#f5f5f7; --card:#fff; --text:#1d1d1f; --muted:#6e6e73; --line:#e3e3e8; --green:#1e7a3c; --green-soft:#e6f4ea; --red:#c4281c; --navy:#0f2a4a; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--text); font:16px/1.5 -apple-system,BlinkMacSystemFont,"SF Pro Text","Helvetica Neue",Arial,sans-serif; -webkit-font-smoothing:antialiased; }}
  header {{ background:var(--navy); color:#fff; padding:36px 24px; }}
  .wrap {{ max-width:1180px; margin:0 auto; }}
  header h1 {{ margin:0 0 6px; font-size:34px; letter-spacing:-.02em; }}
  header p {{ margin:0; color:rgba(255,255,255,.75); }}
  .summary {{ display:flex; flex-wrap:wrap; gap:10px; margin-top:18px; }}
  .summary span {{ background:rgba(255,255,255,.1); border:1px solid rgba(255,255,255,.2); border-radius:999px; padding:6px 14px; font-size:14px; }}
  nav {{ display:flex; gap:8px; margin:24px auto 0; max-width:1180px; padding:0 24px; }}
  nav a {{ text-decoration:none; color:var(--text); background:#fff; border:1px solid var(--line); border-radius:10px; padding:8px 14px; font-weight:600; font-size:14px; }}
  main {{ max-width:1180px; margin:0 auto; padding:20px 24px 60px; }}
  .ticket {{ background:var(--card); border-radius:18px; padding:26px; margin-top:22px; box-shadow:0 1px 2px rgba(0,0,0,.04),0 6px 24px rgba(0,0,0,.05); border-left:5px solid var(--green); }}
  .head {{ display:flex; justify-content:space-between; align-items:flex-start; gap:12px; }}
  .eyebrow {{ font-size:12px; font-weight:600; text-transform:uppercase; letter-spacing:.05em; color:var(--muted); }}
  h2 {{ margin:2px 0 0; font-size:26px; letter-spacing:-.01em; }}
  .resolved {{ background:var(--green-soft); color:var(--green); font-weight:700; padding:5px 14px; border-radius:999px; white-space:nowrap; }}
  .outcome {{ font-size:17px; margin:12px 0; }}
  .meta {{ display:flex; flex-wrap:wrap; gap:26px; margin:8px 0 6px; }}
  .k {{ font-size:12px; color:var(--muted); text-transform:uppercase; letter-spacing:.05em; margin-bottom:3px; }}
  .ag {{ display:inline-block; font-size:13px; font-weight:600; padding:2px 9px; border-radius:999px; margin:0 4px 4px 0; }}
  .ag-boss {{ background:#eeedfc; color:#5146d9; }} .ag-inventory {{ background:#fdf1e3; color:#b45309; }}
  .ag-accounting {{ background:#e6f4ea; color:#1e7a3c; }} .ag-facilities {{ background:#e5effa; color:#0062c4; }}
  .ag-customer_service {{ background:#fbe7ef; color:#b8195a; }}
  .appr {{ margin:10px 0 0; padding-left:20px; }} .appr li {{ margin:3px 0; }}
  .st-approved {{ color:var(--green); font-weight:600; }} .st-rejected {{ color:var(--red); font-weight:600; }}
  .neg {{ color:var(--red); }} .mono, code {{ font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:14px; }}
  figure {{ margin:20px 0 0; }}
  figure img {{ width:100%; border-radius:12px; border:1px solid var(--line); display:block; }}
  figcaption {{ color:var(--muted); font-size:13px; margin-top:8px; }}
  footer {{ text-align:center; color:var(--muted); font-size:13px; }}
</style></head>
<body>
<header><div class="wrap">
  <h1>Resolved Board</h1>
  <p>Campus Customs Multi-Agent Operations: clean end-to-end run of tickets 101, 102, and 103 (shop date 2026-08-31).</p>
  <div class="summary">
    <span>3 / 3 tickets resolved</span>
    <span>Checking {money(rec['starting_balance'])} → <b>{money(rec['cash_accounts_ending'])}</b></span>
    <span>Paid out {money(rec['payments_total'])} (2 human-approved payments)</span>
    <span>Reconciled ✓ (difference {money(rec['difference'])})</span>
  </div>
</div></header>
<nav>{''.join(f'<a href="#t{tid}">Ticket {tid}</a>' for tid in TICKETS)}</nav>
<main>{''.join(cards)}</main>
<footer>Screenshots are real captures of the running dashboard. Figures come from output/audit_trail.json and the backend API (via MCP). Built by scripts/build_run_report.py.</footer>
</body></html>"""
    (OUT / "resolved_board.html").write_text(page, encoding="utf-8")


def main() -> None:
    data = collect()
    for tid, t in data["tickets"].items():
        assert t["ticket"]["status"] == "resolved", f"ticket {tid} is not resolved"
        assert not any(a["status"] == "pending" for a in t["approvals"]), f"ticket {tid} has pending approvals"
    check_comparison(data)
    rec = reconcile(data)
    write_json(data, rec)
    update_desk(data, rec)
    write_board(data, rec)
    print(json.dumps(rec, indent=2))
    print("wrote output/resolved_tickets.json, output/desk_tickets.html, output/resolved_board.html")


if __name__ == "__main__":
    main()
