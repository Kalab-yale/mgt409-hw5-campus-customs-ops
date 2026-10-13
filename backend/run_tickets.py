"""Run the Campus Customs agent team on tickets from the command line.

    python backend/run_tickets.py            # every open ticket
    python backend/run_tickets.py 101 103    # just these tickets

Each ticket goes to the Boss, who delegates to the team. Approval requests land
in the database as *pending*; nothing is paid or sent. Every step is appended
to output/audit_trail.json.
"""

from __future__ import annotations

import asyncio
import json
import sys

from team import Team


async def open_ticket_ids(team: Team) -> list[int]:
    """Ask the MCP server (not the database) which tickets are open."""
    result = await team.mcp.direct_call_tool("list_open_tickets", {})
    return [t["id"] for t in result["tickets"]]


async def main(ticket_ids: list[int]) -> None:
    async with Team() as team:
        ids = ticket_ids or await open_ticket_ids(team)
        for ticket_id in ids:
            print(f"\n=== Ticket {ticket_id} ===", flush=True)
            decision = await team.handle_ticket(ticket_id)
            if decision is None:
                print("Stopped: hit the token/request limit. See output/audit_trail.json.")
            else:
                print(json.dumps(decision.model_dump(), indent=2))


if __name__ == "__main__":
    asyncio.run(main([int(a) for a in sys.argv[1:]]))
