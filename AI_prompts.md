# Homework 5 — AI Prompts Log

This file logs the prompts I gave the AI assistant (Claude Code) to solve Problems 2–11 of Homework 5.
When a problem needed a follow-up or revised prompt, a **"What was lacking"** note explains why.

---

## Context (Problem 1)

> Problem 1: context setting - Okay as always create the AI_prompts.md file for the following problems (problems 2 - 11) and keep updating it as I give you the promts.
> Additional context of what we will be doing (no action for you yet will give you actions and we will work on one problem at a time):
>
> We will build Campus Customs Multi-Agent Operations, an AI system that helps run a shop by handling tickets such as customer orders, rent, unpaid bills, and discount requests.
> The system will have three connected components: an MCP server, a FastAPI backend hosting the multi-agent team, and a React dashboard where a human can monitor the agents and approve requests.
> The team will consist of five agents:
>
> * Boss: Reviews each ticket, assigns work, and makes final decisions.
> * Inventory: Checks stock by SKU and size, identifies shortages, and finds vendors that can restock.
> * Accounting: Tracks cash and invoices, checks margins, and prepares payments or purchase orders for human approval.
> * Facilities: Handles shop-space matters, including leases and rent.
> * Customer Service: Drafts customer messages.
>
> All agents can communicate with and delegate tasks to any other agent. The goal is to coordinate shop operations while keeping a human involved in oversight and approvals.

---

## Problem 2 — Study the Campus Customs Database

### Prompt 1

> Problem 2: Study the campus customs database:
>
> Look through the database. Copy the original file into data/campus_customs_new.db so that later problems update this new copy version. Look at the 3 tickets to see how they link to other tables. Start output/harness.md , for each table list the fields and one short line why the table matters for agent (harness will continue to grow later).

---

## Problem 3 — Build the MCP Server

### Prompt 1

> Problem 3: Build the MCP Server
> Create an MCP server in `mcp_server/` using FastMCP. The server will use the database at `data/campus_customs_new.db`. You do not need to connect or run it for this problem.
> Every agent in this assignment will use the tools provided by this MCP server. More tools will be added later; for now, implement three tools needed to handle the tickets in the database. Give the tools clear names, and use only information contained in the database, never invent data.
> In `output/harness.md`, list each of the three MCP tools. For each tool, include:
>
> * Which database table it reads.
> * Which ticket it helps unlock: 101, 102, or 103.
> * One sentence explaining why that tool is appropriate for that specific ticket.
>
> Be specific about how each tool supports the ticket. Vague descriptions such as "reads inventory" will score poorly.
> Also create a short `mcp_server/README.md` explaining:
>
> * What the MCP server is for.
> * Which database file it uses.
> * The three tools it provides.

---

## Problem 4 — Add the MCP Server to the Vibe Coder

### Prompt 1

> Problem 4: Add the MCP Server to the Vibe Coder
> Add the MCP server to this project so that you can call its tools. Save the connection configuration in `.mcp.json` at the project root, or in the equivalent location where you use for local MCP server configurations.
> Once connected, test each of the three MCP tools through the coding assistant. Save the test evidence in `output/mcp_smoke.json`.
> For every tool, include:
>
> * The prompt i gave the coding assistant
> * The tool's name
> * The tool's output, which must match the values in `data/campus_customs_new.db`

---

## Problem 5 — Build the Agent Team and Expand the MCP Tools

### Prompt 1

> Problem 5: Build the Agent Team and Expand the MCP Tools
> Build the PydanticAI Campus Customs agent team with five agents: Boss, Inventory, Accounting, Facilities, and Customer Service.
> Include the prompts, models, and agent loops needed for full connectivity: every agent must be able to delegate work to any other agent.
> Organize the implementation as follows:
>
> * Store agent prompts in `backend/prompts/`, with one file per agent.
> * Store data types in `backend/models.py`.
> * Store agent implementation files under `backend/`. The layout may vary as long as the five roles are clear.
> * Use `PORTKEY_API_KEY` and only `gpt-6-luna` for every agent.
>
> Expand the MCP server with any additional tools the agents need to handle the open tickets. All shop facts must come through the MCP server using `data/campus_customs_new.db`. Do not create a separate shop-tools layer that bypasses MCP.
> Configure the agents to append records to `output/audit_trail.json` as they run. For every agent-loop step, record enough information to support a later audit. Preserve existing records and append new ones; do not clear the file on each run.
> Update `output/harness.md` to include:
>
> * Every agent.
> * Every MCP tool, including tools added in this problem, and the database table each tool uses.
> * A short safety section describing guardrails for interactions involving real customers and real money, plus limits to keep token usage under control.
>
> Finally, update `mcp_server/README.md` so its tool list matches the complete set of tools now available.

---

## Problem 6 — Plan the Three Tickets

### Prompt 1

> Problem 6: Plan the three tickets
>
> Before we wire the backend or run the agents, please create a plan for how our team should handle tickets 101, 102, and 103. Review the tickets and relevant shop facts through the MCP server so the plans reflect the actual database information.
> Create `output/desk_tickets.html` as a standalone page I can open by double-clicking it. Include separate tabs for tickets 101, 102, and 103, plus Cash and Reflection tabs with a "coming later" placeholder.
> For each ticket, complete an Expected section explaining:
>
> * Which specialist the Boss should contact first and why that agent is the best starting point.
> * The full sequence of anticipated delegations, specifying who delegates to whom, what they need help with, and why.
> * The MCP tools expected to be used and what information each tool contributes to resolving the ticket.
>
> Make each plan specific to the ticket. Involve specialists only when their responsibilities are relevant, rather than sending every ticket to every agent. Use clear wording and the actual tool names from our MCP server.
> Leave an empty Actual section on each ticket tab so we can later record what happened and compare it with the original plan. At this stage, document the expected workflow without running the team to resolve the tickets.

---

## Problem 7 — Backend Routes

### Prompt 1

> Problem 7: backend routes
> Please build the FastAPI backend in `backend/main.py` so our React dashboard can interact with the agent team and shop data.
> Add routes that let the dashboard:
>
> * Retrieve tickets 101, 102, and 103 with their current status: open or resolved.
> * Submit a ticket ID and run the agent team on that ticket.
> * Retrieve recent agent events, including what each agent said and which tools it used, so the dashboard can refresh its activity feed.
> * Approve a prepared payment or purchase after a human clicks Approve. Agents should only prepare these requests; the approval route must perform the action that changes cash.
> * Retrieve the current checking balance from the `cash_accounts` table.
> * Reset the database to its original values for a fresh run.
>
> Connect these routes to our existing agents and MCP tools, keeping shop-data access consistent with the MCP architecture.
> Make sure the server can start from the `backend/` folder using: uvicorn main:app --reload --port 8000
> The backend should be available at `http://localhost:8000` for the frontend to call.
> Update `output/harness.md` with one line per route showing its URL and what it does.

---

## Problem 8 — Agent Dashboard

### Prompt 1

> Problem 8: agent dashboard
>
> Please build our Campus Customs dashboard in `frontend/` using React, Vite, and TypeScript. Connect it to the existing FastAPI routes at `http://localhost:8000`.
> The dashboard should let me:
>
> * See all three tickets and their current status.
> * Select a ticket and start the agent team on it.
> * Watch each agent's messages, actions, and tool usage while the ticket runs.
> * See the ticket marked resolved when the run successfully finishes.
> * Read a brief summary of each agent's contribution to that ticket.
> * Review and approve prepared payments or purchases.
> * See the current checking balance and its decrease after an approved payment.
>
> Create a polished, thoughtful layout that feels like a shop operations desk. Make the five agents visually distinguishable, and make ticket status, pending approvals, and cash easy to find.
> Configure backend CORS to allow the frontend origin, normally `http://localhost:5173`. Ensure `npm run dev` starts the frontend.
> Document the design in `output/design.md`: explain the layout, how agents are distinguished, how resolved tickets and cash are displayed, and why you chose those visual details.
> Check that the frontend works with the actual backend responses, and give me any project-specific setup commands needed to run both servers locally.

---

## Problem 9 — Resolve the Tickets

### Prompt 1

> Problem 9: resolve the tickets:
>
> Please help me complete a clean end-to-end run of tickets 101, 102, and 103 through our React dashboard and document the actual results.
> Before starting, reset `data/campus_customs_new.db` to its original values and record the starting checking balance. Run all three tickets on the dashboard until each is resolved. Keep payment and purchase approvals as human actions: let me review and click Approve when needed.
> Use the actual run events, tool results, approvals, and database values to produce the following:
>
> 1. Update `output/desk_tickets.html`:
>    * Preserve the existing Expected sections.
>    * Fill each ticket's Actual section with the agents involved, their delegations, and the MCP tools used.
>    * Complete the Cash tab with the starting checking balance, each ticket's cash change, the payment or purchase responsible and its dollar amount, and the ending balance.
>    * Reconcile the cash calculation against the ending checking balance in `cash_accounts`. Explain any ticket with no cash change.
> 2. Save `output/resolved_tickets.json`, including each ticket's ID, final status, brief outcome, each agent's contribution, and any human approvals.
> 3. Create `output/resolved_board.html` as a page I can open by double-clicking it, containing an actual screenshot of the React dashboard for each resolved ticket.
> 4. Append the real run records to `output/audit_trail.json`, preserving existing entries.
> 5. Finish `output/harness.md` so it documents the database tables, MCP tools, all five agents, API routes, dashboard, and safety rules.
>
> Do not fabricate outcomes, screenshots, approvals, or cash figures. If a run fails or the cash does not reconcile, investigate and fix the issue before reporting completion. Tell me when I need to interact with the dashboard and where to save screenshots if you cannot capture them yourself.

---

## Problem 10 — Reflection

### Prompt 1

> Problem 10:
>
> Please help me complete the Reflection tab in `output/desk_tickets.html`. Read the Expected and Actual sections for tickets 101, 102, and 103, the Cash tab, and the recorded run evidence.
> Draft a detailed reflection grounded in our Campus Customs implementation, covering:
>
> 1. Evaluate the agents' performance on each ticket. Explain what worked well, what could improve, and why, using specific delegations, tool calls, outcomes, and cash effects.
> 2. Compare each ticket's actual workflow with its original expected plan. Explain the meaningful differences and whether they helped or hindered resolution.
> 3. Identify parts of this work that would have been simpler with one agent using tools. Explain the tradeoffs using examples from our runs.
> 4. Describe three new shop problems the current team could solve with the tools we actually built. Explain which agents and tools would handle each problem.
> 5. Describe three new shop problems the current implementation could not solve. Explain what capabilities are missing and which additional tools and agent roles would be needed.
>
> Tie every answer to our app and the three completed tickets. Use the ticket tabs and Cash tab as evidence, supported by the audit trail where useful. Clearly distinguish hypothetical future problems from observed results.
> Use clear, natural language. Do not invent run details or my personal views. Flag any missing evidence and ask for my perspective where needed. Preserve the existing ticket and Cash sections when adding the reflection.

---

### Prompt 2

**What was lacking:** the first draft of the reflection ended with six open questions that only I could answer (why I rejected the purchase order, whether the later approvals were intentional, message delivery, what "resolved" should mean, the discount policy, the cash floor). These are my answers so the reflection reflects my perspective.

> 1. because we couldn't serve it for now
> 2. yep, i thought it was fine
> 3. idk
> 4. no i guess
> 5. assume it fine
> 6. sure

---
