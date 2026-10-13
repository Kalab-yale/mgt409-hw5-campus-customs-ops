# Campus Customs Ops Desk: Dashboard Design

The dashboard (`frontend/`, React + Vite + TypeScript) is where a human manager watches the five agents work a ticket, reads what they concluded, and approves the money they've prepared. The design follows one idea: **it should feel like the shop's back-office desk.** That means a ticket queue on the left, the work in front of you, the team on the right, and the cash register always in view.

---

## 1. Layout

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│  CC Campus Customs        [Shop date 2026-08-31] [② awaiting approval]   ┌─────────┐ │
│     Ops Desk · Chapel St                                                 │CHECKING │ │  navy desk header
│                                                                          │$3,400.00│ │  (sticky)
│                                               Approving as [manager] ↺   └─────────┘ │
├──────────────────┬───────────────────────────────────────────┬───────────────────────┤
│ TICKET QUEUE     │  🛍️ CUSTOMER ORDER · #101           Open │ THE TEAM   4 of 5     │
│ ┌──────────────┐ │  Bulldog tee                              │ ┃👔 Boss       Done  │
│ │#101  ✓Resolved│ │  from Tauhid Zaman                       │ ┃📦 Inventory  Done  │
│ │🛍️ Bulldog tee │ │  "Needs a tee in size S."               │ ┃🧮 Accounting Done  │
│ │⏳ 1 waiting   │ │  [Item 1×CC-TEE-WHITE·S] [Invoice #501]  │ ┃🏬 Facilities  Not   │
│ └──────────────┘ │  [▶ Run agent team]  or  ✓ Resolved banner│ ┃   needed           │
│  #102 Open       │  Boss's final decision card               │ ┃💬 Customer Svc Done│
│  #103 Open       ├───────────────────────────────────────────┤ │  each: summary,     │
│                  │ LIVE ACTIVITY ●     3 hand-offs · 12 tools │ │  tools used,        │
│ NEEDS YOUR       │  👔 Boss  HAND-OFF  [Boss] → [Inventory]   │ │  who asked whom,    │
│ APPROVAL  ②      │  📦 Inventory TOOL ▸ check_stock(sku=…)    │ │  requests filed     │
│ 🧾 Invoice −$840 │  🧮 Accounting REPORT  "Invoice 501 is…"   │ │                     │
│ [Approve & pay]  │  👔 Boss  DECISION  "…"                    │ │                     │
│ ✉️ Customer msg  │  👤 You   RESOLVED                         │ │                     │
└──────────────────┴───────────────────────────────────────────┴───────────────────────┘
```

| Zone | What's there | Why it's there |
|---|---|---|
| **Header (sticky, navy)** | Brand, the **shop date** (the agents' "today", 2026-08-31), an **"N awaiting approval"** chip, the **cash tile**, who's approving, Reset | The three things a manager checks constantly (date, what needs me, how much cash) never scroll away. The approvals chip is a link that jumps to the queue. |
| **Left: the inbox** | **Ticket queue** (3 ticket stubs), then **Needs your approval** | This is the work coming *to* the human: tickets to run and decisions to make. Approvals sit right under the tickets because they're the human's other job. |
| **Center: the work** | Selected ticket (request, linked SKU/lease/invoice, Run button, resolved banner, the Boss's final decision), then the **Live activity** feed | The widest column holds what you're focused on, and reads top to bottom: what was asked, what the team did, what it decided. |
| **Right: the team** | Five agent cards with status and per-ticket contribution summaries | Shows *who* did the work. All five are always listed, so you can see who was **not needed** on a ticket (e.g. Facilities on 101). |

**Responsive:** under 1280px the team drops below as a card grid. Under 860px everything stacks into one column, with the cash tile staying at the top. I checked 1440px, 1024px, and 375px; there's no horizontal scrolling at any of them.

---

## 2. How the five agents are distinguished

Each agent has a fixed identity used **everywhere**: feed rows, hand-off chips, team cards, and "Prepared by" on approvals.

| Agent | Color | Icon | Why |
|---|---|---|---|
| **Boss** | Indigo `#5146D9` | 👔 | Authority/"final call" color, distinct from the green/red used for money |
| **Inventory** | Amber `#B45309` | 📦 | Warm, boxes on a shelf |
| **Accounting** | Green `#1E7A3C` | 🧮 | Money/ledger |
| **Facilities** | Blue `#0062C4` | 🏬 | Building, steady |
| **Customer Service** | Raspberry `#B8195A` | 💬 | Warm, people-facing |
| You (human) | Near-black `#1D1D1F` | 👤 | Neutral, so human actions stand apart from the agents |

- **Never color alone.** Every appearance pairs the color with an **icon and the name**, so it works for color-blind users and in grayscale.
- **Accessible contrast.** Each color passes WCAG AA as text on white. Each also has a pale tint (`soft`) for backgrounds, such as report bubbles and tool-name chips, so a feed row is tinted in its agent's color without becoming loud.
- **Status on the team cards:** *Idle* (gray), **Working** (agent-colored pill with a pulsing dot plus a soft glow around the card), **Done** (green), *Not needed* (card dimmed to 55%), *Stopped* (red).
- **Hand-offs** are shown as two agent chips with an arrow (`[👔 Boss] → [📦 Inventory]`) so delegation reads at a glance, including specialist-to-specialist hand-offs.

---

## 3. The activity feed (watching a run)

Each row is: **agent avatar · agent name (in its color) · KIND · time**, then the content.

| Kind | Shows |
|---|---|
| Hand-off | from → to chips + the task text the agent wrote |
| Tool | `check_stock(sku="CC-TEE-WHITE", size="S", qty_needed=1)`. Click to expand the MCP result as formatted JSON |
| Report | The agent's summary in a bubble tinted with its color |
| Decision | The Boss's final summary, plus tokens / model calls / tool calls for the run |
| Approved / Rejected / Resolved | Human and system actions, in green or red |
| Guardrail / Error | Amber / red, so a refusal is visible, not hidden |

While a ticket runs, the feed polls every 1.2s and appends only new events (using `since=last_seq`). It auto-scrolls unless you've scrolled up to read, and a pulsing red **live** dot plus "waiting for the next step…" show it's still working. Internal stamps (`requested_by`) are hidden from tool arguments to keep rows short.

---

## 4. Resolved tickets

- **Rule:** when a team run **finishes successfully** and the Boss's decision isn't *blocked* (or *in progress*), the backend marks the ticket **resolved** (MCP `resolve_ticket`). Prepared payments stay in the approval queue, because the team has done its part and the rest is the human's.
- **Ticket stub:** the gray **Open** pill becomes a green **✓ Resolved** pill, and the stub's left edge turns green. The queue header counts "1/3 resolved". While running, the pill is blue **● Running** with a pulse.
- **Ticket detail:** the Run button is replaced by a green **"✓ Resolved. The team finished this ticket."** banner. If requests are still waiting, it links to them ("1 request waiting for your approval →").
- **Feed:** ends with a **You · RESOLVED** row, and a toast says "Ticket 101 resolved ✓".
- **Why green check + text:** green means "done" for everyone, the checkmark repeats it for color-blind users, and the word "Resolved" removes any doubt. Running gets blue (in progress, not done), and Open stays neutral gray so it doesn't compete for attention.

---

## 5. Cash

- **Where:** a white tile in the navy header, the brightest thing on the screen, so it's always the first number you see.
- **What:** **Checking** balance in large tabular numerals (digits don't jiggle as they change), the "as of" date, and a thin **pending bar** showing how much of the balance pending payments would use. Below it: *Pending payments $840.00* and *After approval $2,560.00* (red if pending exceeds cash).
- **When a payment is approved:** the number **counts down** from the old to the new balance over about 0.9s and turns red while it drops. A red **"−$840.00"** chip pops in beside it for a few seconds, and a line under the tile records the change: *"Invoice payment approved by manager: $3,400.00 → $2,560.00"*. A toast confirms *"Paid $840.00 · checking now $2,560.00"*.
- **Why:** a manager approving money should *see* it leave. The animation and delta chip connect the click to the cash change, and the line under the tile keeps a record after the animation ends. Showing pending payments *before* approval helps the human spot the real trade-off on this desk: rent plus the overdue invoice leaves only $160.

---

## 6. Approvals

- Each card shows: kind icon + label, **amount** (money out in red with a minus sign, quotes in black), the agent's one-line summary, the full draft for customer messages, and **"Prepared by [🧮 Accounting]"**.
- The button says exactly what will happen: **"Approve & pay $840.00"** for money out, plain **Approve** for quotes and messages. **Reject** sits next to it as a quiet secondary button.
- The selected ticket's requests are sorted to the top and outlined in amber, so they're easy to connect to the ticket you're looking at.
- If a payment is bigger than current checking, the button is disabled with a note. The backend refuses it too.
- "Approving as" (stored in the browser) is sent as `approved_by`, so the audit trail and `payments.approved_by` record a person's name.

---

## 7. Visual language and why

- **Apple-style restraint:** light gray desk, white cards, system font (SF Pro on Mac), soft shadows, generous spacing. Surfaces stay quiet so that **color only ever means something**: an agent, a status, or money.
- **Shop details:** a Yale-navy header like a store sign, a "Shop date" chip like a desk calendar, ticket stubs with a punched notch like paper claim tickets, and monospace ticket numbers like printed receipts.
- **Money colors are reserved:** red is only for money leaving or errors, green only for done/approved, amber only for "waiting on a human". Agents' colors were picked so none of them reads as an alert.
- **Accessibility:** real buttons with focus rings, `aria-live` on the feed and cash, text labels on every status, `prefers-reduced-motion` turns off the animations.

---

## 8. Data flow (what the UI calls)

| UI | Route | Polling |
|---|---|---|
| Ticket queue, cash, approvals | `GET /api/tickets`, `/api/cash`, `/api/approvals` | every 4s; 1.5s while a run is active |
| Run button | `POST /api/run`, then `GET /api/runs/{id}` until done | 1.5s while running |
| Live activity | `GET /api/events?ticket_id=…&latest_run=true&since=…` | 1.2s while running, 4s otherwise |
| Team cards | `GET /api/tickets/{id}/contributions` | 1.5s while running, 5s otherwise |
| Approve / Reject | `POST /api/approvals/{id}/approve` · `/reject` | then refresh |
| Reset | `POST /api/reset` (after a confirm dialog) | then refresh |

The frontend reads shop data only through the backend, and the backend reads it only through the MCP server.
