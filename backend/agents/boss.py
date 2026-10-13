"""Boss: reviews each ticket, assigns work, and makes the final decision."""

from models import RoleSpec, TicketDecision

ROLE = RoleSpec(
    name="boss",
    title="Boss",
    description="Reviews tickets, assigns work, weighs trade-offs across tickets, and makes the final decision.",
    prompt_file="boss.md",
    mcp_tools=frozenset({
        "list_open_tickets", "get_ticket", "get_cash_position",
        "list_approval_requests", "update_ticket_status",
    }),
    output_type=TicketDecision,
)
